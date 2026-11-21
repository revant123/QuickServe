# The deploy role is the most dangerous thing in this stack: whoever can
# assume it can change what runs on the live server. No AWS account needed.
mock_provider "aws" {
  override_data {
    target = data.aws_caller_identity.current
    values = { account_id = "123456789012" }
  }
  override_data {
    target = data.aws_partition.current
    values = { partition = "aws" }
  }
}

variables {
  name                 = "quickserve-test"
  github_repository    = "revant123/QuickServe"
  instance_arn         = "arn:aws:ec2:ap-south-1:123456789012:instance/i-0123456789abcdef0"
  deploy_document_arn  = "arn:aws:ssm:ap-south-1:123456789012:document/quickserve-test-deploy"
  target_parameter_arn = "arn:aws:ssm:ap-south-1:123456789012:parameter/quickserve/test/deploy_target"
  github_owner_id      = 149621150
  github_repository_id = 1461084605
}

run "only_the_production_environment_of_this_repo_may_deploy" {
  command = apply

  assert {
    condition     = local.trust_policy.Statement[0].Condition.StringEquals["token.actions.githubusercontent.com:sub"] == "repo:revant123@149621150/QuickServe@1461084605:environment:production"
    error_message = "The trust policy must name this repository (by its permanent IDs) AND the production environment exactly."
  }
  assert {
    condition     = !strcontains(jsonencode(local.trust_policy), "*") && !contains(keys(local.trust_policy.Statement[0].Condition), "StringLike")
    error_message = "No wildcards in the trust policy: repo:owner/*:* would let any repository deploy."
  }
  assert {
    condition     = local.trust_policy.Statement[0].Condition.StringEquals["token.actions.githubusercontent.com:aud"] == "sts.amazonaws.com"
    error_message = "The token must be meant for AWS STS."
  }
  assert {
    condition     = aws_iam_role.deploy.max_session_duration == 3600
    error_message = "Deploy credentials should expire within an hour."
  }
}

run "the_role_can_run_one_document_on_one_server" {
  command = apply

  assert {
    condition     = toset(local.deploy_policy.Statement[0].Resource) == toset([var.instance_arn, var.deploy_document_arn])
    error_message = "SendCommand only for this server and the deploy document (not AWS-RunShellScript)."
  }
  assert {
    condition     = !strcontains(jsonencode(local.deploy_policy), "AWS-RunShellScript") && alltrue(flatten([for st in local.deploy_policy.Statement : [for a in flatten([st.Action]) : startswith(a, "ssm:")]]))
    error_message = "SSM actions only (no IAM, no EC2), and never AWS-RunShellScript."
  }
  assert {
    condition     = alltrue([for st in local.deploy_policy.Statement : st.Resource != "*" || alltrue([for a in flatten([st.Action]) : startswith(a, "ssm:Get") || startswith(a, "ssm:List")])])
    error_message = "Only read-only actions may use Resource \"*\"."
  }
}

run "an_existing_oidc_provider_can_be_reused" {
  command = apply

  variables {
    create_oidc_provider = false
  }

  assert {
    condition     = length(aws_iam_openid_connect_provider.github) == 0
    error_message = "Don't create a second GitHub OIDC provider in the same account."
  }
  assert {
    condition     = local.provider_arn == "arn:aws:iam::123456789012:oidc-provider/token.actions.githubusercontent.com"
    error_message = "Reuse the account's existing provider."
  }
}

run "older_repositories_use_the_name_only_subject" {
  command = apply

  variables {
    github_owner_id      = null
    github_repository_id = null
  }

  assert {
    condition     = output.subject == "repo:revant123/QuickServe:environment:production"
    error_message = "Repositories created before July 15, 2026 send owner/name without IDs."
  }
}
