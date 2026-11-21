# The dev environment: network, database, secrets and the app server.
#
#   terraform init -backend-config=backend.hcl
#   terraform plan
#   terraform apply
#   terraform destroy      <- at the end of every study session
#
# Step-by-step instructions are in infra/README.md.

terraform {
  required_version = ">= 1.11"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.7"
    }
  }

  # State lives in the S3 bucket made by infra/bootstrap. The bucket name and
  # region come from backend.hcl (copy backend.hcl.example), because a backend
  # block can't use variables.
  backend "s3" {
    key          = "quickserve/dev/terraform.tfstate"
    encrypt      = true
    use_lockfile = true # S3-native locking: two applies can't run at once
  }
}

provider "aws" {
  region = var.region

  default_tags {
    tags = {
      project     = "quickserve"
      environment = local.env
      managed_by  = "terraform"
    }
  }
}

locals {
  env  = "dev"
  name = "quickserve-${local.env}"

  # Parameter Store path for this environment's secrets.
  ssm_prefix = "/quickserve/${local.env}"
}

module "network" {
  source = "../../modules/network"
  name   = local.name
}

# ---------- Firewalls (security groups) ----------
# Defined here, not inside the modules, because each one refers to the other.

resource "aws_security_group" "app" {
  name        = "${local.name}-app"
  description = "QuickServe app server: HTTP and HTTPS in, anything out"
  vpc_id      = module.network.vpc_id
}

# Phase 16: 443 for HTTPS, and 80 because Let's Encrypt checks the domain over
# plain HTTP (the "HTTP-01 challenge") and Caddy redirects everyone else to 443.
locals {
  web_ingress = { for pair in setproduct(var.allowed_http_cidrs, [80, 443]) : "${pair[0]}-${pair[1]}" => { cidr = pair[0], port = pair[1] } }
}

resource "aws_vpc_security_group_ingress_rule" "app_http" {
  for_each = local.web_ingress

  security_group_id = aws_security_group.app.id
  description       = each.value.port == 443 ? "HTTPS to Caddy" : "HTTP to Caddy (Let's Encrypt checks, then a redirect to HTTPS)"
  cidr_ipv4         = each.value.cidr
  from_port         = each.value.port
  to_port           = each.value.port
  ip_protocol       = "tcp"
}

# Outbound: pull the image from ghcr.io, talk to Parameter Store and to RDS.
resource "aws_vpc_security_group_egress_rule" "app_all" {
  security_group_id = aws_security_group.app.id
  cidr_ipv4         = "0.0.0.0/0"
  ip_protocol       = "-1"
}

resource "aws_security_group" "db" {
  name        = "${local.name}-db"
  description = "PostgreSQL, reachable only from the app server"
  vpc_id      = module.network.vpc_id
}

# The ONLY way into the database: port 5432, from machines in the app group.
# Not from the internet, not from your laptop.
resource "aws_vpc_security_group_ingress_rule" "db_from_app" {
  security_group_id            = aws_security_group.db.id
  description                  = "PostgreSQL from the app server"
  referenced_security_group_id = aws_security_group.app.id
  from_port                    = 5432
  to_port                      = 5432
  ip_protocol                  = "tcp"
}

# ---------- Secrets ----------
# Letters and digits only, so they can sit inside a URL without escaping.
# 32 random letters and digits is about 190 bits: far beyond guessing.

resource "random_password" "db" {
  length  = 32
  special = false
}

resource "random_password" "jwt" {
  length  = 64
  special = false
}

# Phase 16: the demo accounts on a public site. The passwords in
# scripts/seed.py are in the README for everyone to read, so the live server
# uses these instead. The customer one is fine to share with someone trying
# the app; the staff one (owner, rider, admin) is for you only.
resource "random_password" "demo_customer" {
  length  = 16
  special = false
}

resource "random_password" "demo_staff" {
  length  = 20
  special = false
}

module "database" {
  source = "../../modules/database"

  name               = local.name
  subnet_ids         = module.network.private_subnet_ids
  security_group_ids = [aws_security_group.db.id]
  password           = random_password.db.result
}

# SecureString = encrypted with AWS KMS. Standard parameters are free.
resource "aws_ssm_parameter" "database_url" {
  name        = "${local.ssm_prefix}/database_url"
  description = "SQLAlchemy URL for the QuickServe database"
  type        = "SecureString"
  # sslmode=require: the connection to RDS is encrypted even inside the VPC.
  value = format(
    "postgresql+psycopg://%s:%s@%s:%d/%s?sslmode=require",
    module.database.username,
    random_password.db.result,
    module.database.address,
    module.database.port,
    module.database.db_name,
  )
}

resource "aws_ssm_parameter" "jwt_secret_key" {
  name        = "${local.ssm_prefix}/jwt_secret_key"
  description = "Key that signs QuickServe login tokens"
  type        = "SecureString"
  value       = random_password.jwt.result
}

resource "aws_ssm_parameter" "demo_customer_password" {
  name        = "${local.ssm_prefix}/demo_customer_password"
  description = "Password of customer@quickserve.dev on the live site"
  type        = "SecureString"
  value       = random_password.demo_customer.result
}

resource "aws_ssm_parameter" "demo_staff_password" {
  name        = "${local.ssm_prefix}/demo_staff_password"
  description = "Password of the demo owner, rider and admin on the live site"
  type        = "SecureString"
  value       = random_password.demo_staff.result
}

# The DuckDNS token can change the site's DNS, so it's a secret too.
resource "aws_ssm_parameter" "duckdns_token" {
  count       = var.duckdns_token == "" ? 0 : 1
  name        = "${local.ssm_prefix}/duckdns_token"
  description = "Lets the server point ${var.domain} at its own IP on boot"
  type        = "SecureString"
  value       = var.duckdns_token
}

module "app_server" {
  source = "../../modules/app_server"

  name               = local.name
  subnet_id          = module.network.public_subnet_ids[0]
  security_group_ids = [aws_security_group.app.id]
  instance_type      = var.instance_type
  image_tag          = var.image_tag
  ssm_prefix         = local.ssm_prefix
  app_environment    = local.env
  domain             = var.domain

  # The server reads these on its first boot, so they must exist first.
  depends_on = [
    aws_ssm_parameter.database_url,
    aws_ssm_parameter.jwt_secret_key,
    aws_ssm_parameter.duckdns_token,
    aws_ssm_parameter.demo_customer_password,
    aws_ssm_parameter.demo_staff_password,
  ]
}

# ---------- Continuous delivery from GitHub Actions (Phase 16) ----------

# Which server to deploy to. The deploy job reads this, so a server replaced
# by Terraform is picked up without changing anything in GitHub.
resource "aws_ssm_parameter" "deploy_target" {
  name        = "${local.ssm_prefix}/deploy_target"
  description = "Instance ID and SSM document that GitHub Actions deploys with"
  type        = "String"
  value = jsonencode({
    instance_id = module.app_server.instance_id
    document    = module.app_server.deploy_document_name
  })
}

module "github_deploy" {
  source = "../../modules/github_deploy"

  name                 = local.name
  github_repository    = var.github_repository
  github_owner_id      = var.github_owner_id
  github_repository_id = var.github_repository_id
  create_oidc_provider = var.create_github_oidc_provider
  instance_arn         = module.app_server.instance_arn
  deploy_document_arn  = module.app_server.deploy_document_arn
  target_parameter_arn = aws_ssm_parameter.deploy_target.arn
}
