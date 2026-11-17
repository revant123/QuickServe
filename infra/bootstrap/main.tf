# Bootstrap: the two things that must exist BEFORE any real infrastructure.
#
#   1. A budget alert, so a forgotten resource emails you instead of surprising you.
#   2. An S3 bucket that stores Terraform's state for every other stack.
#
# This stack keeps its own state on your laptop (terraform.tfstate in this
# folder), because the bucket it creates can't store the state of the run that
# creates it. It's tiny and rarely changes. Run it once per AWS account.

terraform {
  required_version = ">= 1.11"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
  }
}

provider "aws" {
  region = var.region

  # Every resource gets these tags automatically. Cost Explorer can then split
  # the bill by project and stack (FinOps: you can't manage what you can't see).
  default_tags {
    tags = {
      project    = "quickserve"
      stack      = "bootstrap"
      managed_by = "terraform"
    }
  }
}

variable "region" {
  description = "AWS region. ap-south-1 is Mumbai, the closest region to India."
  type        = string
  default     = "ap-south-1"
}

variable "monthly_budget_usd" {
  description = "Monthly budget for the whole account, in US dollars."
  type        = number
  default     = 10
}

variable "alert_emails" {
  description = "Who gets the budget emails."
  type        = list(string)
}

data "aws_caller_identity" "current" {}

module "budget" {
  source = "../modules/budget"

  name              = "quickserve-monthly"
  monthly_limit_usd = var.monthly_budget_usd
  alert_emails      = var.alert_emails
}

# ---------- State bucket ----------

resource "aws_s3_bucket" "state" {
  # Bucket names are global across ALL AWS customers, so include the account ID.
  bucket = "quickserve-tfstate-${data.aws_caller_identity.current.account_id}-${var.region}"

  # Losing this bucket means Terraform forgets everything it built. This makes
  # `terraform destroy` refuse to delete it; remove the line on purpose if you
  # ever close the project down for good.
  lifecycle {
    prevent_destroy = true
  }
}

# Every write keeps the previous version, so a bad apply can be rolled back.
resource "aws_s3_bucket_versioning" "state" {
  bucket = aws_s3_bucket.state.id
  versioning_configuration {
    status = "Enabled"
  }
}

# State contains secrets (the database password), so encrypt it at rest.
resource "aws_s3_bucket_server_side_encryption_configuration" "state" {
  bucket = aws_s3_bucket.state.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

# No public access, ever, whatever someone clicks later.
resource "aws_s3_bucket_public_access_block" "state" {
  bucket                  = aws_s3_bucket.state.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_ownership_controls" "state" {
  bucket = aws_s3_bucket.state.id
  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

# FinOps: old state versions are only needed for a while. Delete them after 90
# days instead of paying to store every version forever.
resource "aws_s3_bucket_lifecycle_configuration" "state" {
  bucket = aws_s3_bucket.state.id

  rule {
    id     = "expire-old-state-versions"
    status = "Enabled"
    filter {}

    noncurrent_version_expiration {
      noncurrent_days = 90
    }
    abort_incomplete_multipart_upload {
      days_after_initiation = 7
    }
  }

  depends_on = [aws_s3_bucket_versioning.state]
}

# Refuse any request that isn't encrypted in transit (HTTPS).
resource "aws_s3_bucket_policy" "state" {
  bucket = aws_s3_bucket.state.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid       = "DenyInsecureTransport"
      Effect    = "Deny"
      Principal = "*"
      Action    = "s3:*"
      Resource  = [aws_s3_bucket.state.arn, "${aws_s3_bucket.state.arn}/*"]
      Condition = { Bool = { "aws:SecureTransport" = "false" } }
    }]
  })

  depends_on = [aws_s3_bucket_public_access_block.state]
}

output "state_bucket" {
  description = "Pass this to `terraform init` in infra/envs/dev."
  value       = aws_s3_bucket.state.bucket
}

output "region" {
  value = var.region
}
