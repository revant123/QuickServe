# `terraform test`: checks the dev environment's security and cost rules
# WITHOUT an AWS account. The mock providers invent fake IDs instead of
# calling AWS, so this runs for free in CI on every pull request.
#
#   cd infra/envs/dev && terraform init -backend=false && terraform test

mock_provider "aws" {
  override_data {
    target = module.network.data.aws_availability_zones.available
    values = { names = ["ap-south-1a", "ap-south-1b", "ap-south-1c"] }
  }
  override_data {
    target = module.app_server.data.aws_ssm_parameter.al2023_arm64
    values = { value = "ami-0123456789abcdef0" }
  }
  override_data {
    target = module.app_server.data.aws_region.current
    values = { region = "ap-south-1" }
  }
  override_data {
    target = module.app_server.data.aws_caller_identity.current
    values = { account_id = "123456789012" }
  }
  override_data {
    target = module.app_server.data.aws_partition.current
    values = { partition = "aws" }
  }
  override_data {
    target = module.app_server.data.aws_iam_policy_document.assume_ec2
    values = { json = "{\"Version\":\"2012-10-17\",\"Statement\":[]}" }
  }
  override_data {
    target = module.app_server.data.aws_iam_policy_document.read_secrets
    values = { json = "{\"Version\":\"2012-10-17\",\"Statement\":[]}" }
  }
}

mock_provider "random" {}

variables {
  image_tag = "sha-3073e30"
}

run "database_is_private_and_encrypted" {
  command = apply

  assert {
    condition     = module.database.address != ""
    error_message = "The database should have an address."
  }
  assert {
    condition     = aws_vpc_security_group_ingress_rule.db_from_app.referenced_security_group_id == aws_security_group.app.id
    error_message = "Only the app server's security group may reach the database."
  }
  assert {
    condition     = aws_vpc_security_group_ingress_rule.db_from_app.from_port == 5432 && aws_vpc_security_group_ingress_rule.db_from_app.to_port == 5432
    error_message = "The database rule must open port 5432 and nothing else."
  }
  assert {
    condition     = endswith(aws_ssm_parameter.database_url.value, "?sslmode=require")
    error_message = "The app must connect to RDS over TLS."
  }
  assert {
    condition     = aws_ssm_parameter.database_url.type == "SecureString" && aws_ssm_parameter.jwt_secret_key.type == "SecureString"
    error_message = "Secrets must be stored encrypted."
  }
  assert {
    condition     = random_password.jwt.length >= 32
    error_message = "The app refuses JWT secrets shorter than 32 characters."
  }
}

run "app_server_only_opens_http_and_https" {
  command = apply

  assert {
    condition     = toset([for r in aws_vpc_security_group_ingress_rule.app_http : r.from_port]) == toset([80, 443]) && alltrue([for r in aws_vpc_security_group_ingress_rule.app_http : r.from_port == r.to_port && r.ip_protocol == "tcp"])
    error_message = "The app server should accept ports 80 and 443 only (no SSH: Session Manager is used instead)."
  }
}

run "live_site_secrets_and_deploys" {
  command = apply

  variables {
    domain        = "quickserve-test.duckdns.org"
    duckdns_token = "1a2b3c4d-1a2b-1a2b-1a2b-1a2b3c4d5e6f"
  }

  assert {
    condition     = alltrue([for p in [aws_ssm_parameter.demo_customer_password, aws_ssm_parameter.demo_staff_password, aws_ssm_parameter.duckdns_token[0]] : p.type == "SecureString"])
    error_message = "Demo passwords and the DuckDNS token are secrets."
  }
  assert {
    condition     = random_password.demo_customer.result != random_password.demo_staff.result && random_password.demo_customer.length >= 12 && random_password.demo_staff.length >= 12
    error_message = "Separate customer and staff passwords, long enough for scripts/seed.py."
  }
  assert {
    condition     = output.site_url == "https://quickserve-test.duckdns.org"
    error_message = "With a domain, the site is HTTPS on that domain."
  }
  assert {
    condition     = jsondecode(aws_ssm_parameter.deploy_target.value).document == "quickserve-dev-deploy"
    error_message = "GitHub Actions finds the server and the deploy document through deploy_target."
  }
  assert {
    condition     = module.github_deploy.subject == "repo:revant123@149621150/QuickServe@1461084605:environment:production"
    error_message = "Only this repository's production environment may deploy."
  }
}

run "no_token_no_token_parameter" {
  command = apply

  assert {
    condition     = length(aws_ssm_parameter.duckdns_token) == 0 && startswith(output.site_url, "http://")
    error_message = "Without a domain: no DuckDNS parameter, plain HTTP."
  }
}

run "http_can_be_limited_to_one_ip" {
  command = plan

  variables {
    allowed_http_cidrs = ["203.0.113.7/32"]
  }

  assert {
    condition     = toset(keys(aws_vpc_security_group_ingress_rule.app_http)) == toset(["203.0.113.7/32-80", "203.0.113.7/32-443"])
    error_message = "allowed_http_cidrs should replace the open-to-everyone rule."
  }
}

run "rejects_intel_instance_types" {
  command = plan

  variables {
    instance_type = "t3.small"
  }

  # The image deployed is ARM; an Intel server would pull the wrong one.
  expect_failures = [var.instance_type]
}

run "rejects_bad_cidr" {
  command = plan

  variables {
    allowed_http_cidrs = ["my-laptop"]
  }

  expect_failures = [var.allowed_http_cidrs]
}
