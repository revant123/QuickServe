# Lets GitHub Actions deploy to the app server WITHOUT any AWS keys stored in
# GitHub (Phase 16).
#
# How it works: for each run, GitHub signs a short-lived token (OIDC) that
# says "I am repo X, job running in environment Y". AWS checks the signature
# and the claims, then hands out credentials that expire within an hour.
# Nothing long-lived exists that could leak.
#
# What the role can do, and nothing more:
#   - read which server to deploy to (one Parameter Store value)
#   - run ONE SSM document (deploy.sh with a sha-... tag) on ONE server
#   - read that command's result

variable "name" {
  type = string
}

variable "github_repository" {
  description = "owner/name of the repository allowed to deploy, e.g. revant123/QuickServe."
  type        = string

  validation {
    condition     = can(regex("^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$", var.github_repository))
    error_message = "Use owner/name, e.g. revant123/QuickServe."
  }
}

# Since July 15, 2026, GitHub writes NEW repositories into the token as
# owner@owner-id/name@repo-id. The numbers never change, so a repository that
# is deleted and re-created under the same name by someone else can't deploy.
# Find them with: gh api repos/OWNER/NAME --jq '{owner_id: .owner.id, id}'
# Leave both null for a repository created before that date (name-only format).
variable "github_owner_id" {
  type    = number
  default = null
}

variable "github_repository_id" {
  type    = number
  default = null
}

variable "github_environment" {
  description = "Only jobs that run in this GitHub environment may assume the role. Pull requests can't."
  type        = string
  default     = "production"
}

variable "create_oidc_provider" {
  description = "An AWS account can trust GitHub's OIDC issuer only once. Set false if another stack already created it."
  type        = bool
  default     = true
}

variable "instance_arn" {
  type = string
}

variable "deploy_document_arn" {
  type = string
}

variable "target_parameter_arn" {
  description = "The Parameter Store value naming the server to deploy to."
  type        = string
}

locals {
  issuer = "token.actions.githubusercontent.com"
  owner  = split("/", var.github_repository)[0]
  repo   = split("/", var.github_repository)[1]
  # GitHub puts this in the token's "sub" claim for a job with `environment: production`.
  subject = (var.github_repository_id == null
    ? "repo:${var.github_repository}:environment:${var.github_environment}"
    : "repo:${local.owner}@${var.github_owner_id}/${local.repo}@${var.github_repository_id}:environment:${var.github_environment}"
  )
}

data "aws_caller_identity" "current" {}
data "aws_partition" "current" {}

resource "aws_iam_openid_connect_provider" "github" {
  count          = var.create_oidc_provider ? 1 : 0
  url            = "https://${local.issuer}"
  client_id_list = ["sts.amazonaws.com"]
}

locals {
  provider_arn = var.create_oidc_provider ? aws_iam_openid_connect_provider.github[0].arn : "arn:${data.aws_partition.current.partition}:iam::${data.aws_caller_identity.current.account_id}:oidc-provider/${local.issuer}"

  trust_policy = {
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Federated = local.provider_arn }
      Action    = "sts:AssumeRoleWithWebIdentity"
      Condition = {
        StringEquals = {
          "${local.issuer}:aud" = "sts.amazonaws.com"
          # Exact match, not a wildcard: other repositories, branches without
          # the environment, and pull requests all get "access denied".
          "${local.issuer}:sub" = local.subject
        }
      }
    }]
  }

  deploy_policy = {
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "RunTheDeployDocumentOnTheAppServer"
        Effect   = "Allow"
        Action   = "ssm:SendCommand"
        Resource = [var.instance_arn, var.deploy_document_arn]
      },
      {
        # These two can't be limited to one resource in IAM.
        Sid      = "ReadTheResult"
        Effect   = "Allow"
        Action   = ["ssm:GetCommandInvocation", "ssm:ListCommandInvocations"]
        Resource = "*"
      },
      {
        Sid      = "FindTheServer"
        Effect   = "Allow"
        Action   = "ssm:GetParameter"
        Resource = var.target_parameter_arn
      },
    ]
  }
}

resource "aws_iam_role" "deploy" {
  name                 = "${var.name}-github-deploy"
  description          = "Assumed by GitHub Actions (${local.subject}) to deploy QuickServe"
  assume_role_policy   = jsonencode(local.trust_policy)
  max_session_duration = 3600
}

resource "aws_iam_role_policy" "deploy" {
  name   = "deploy-quickserve"
  role   = aws_iam_role.deploy.id
  policy = jsonencode(local.deploy_policy)
}

output "role_arn" {
  value = aws_iam_role.deploy.arn
}

output "subject" {
  value = local.subject
}
