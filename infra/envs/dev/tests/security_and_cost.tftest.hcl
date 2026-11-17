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

run "app_server_only_opens_http" {
  command = apply

  assert {
    condition     = length(aws_vpc_security_group_ingress_rule.app_http) == 1 && alltrue([for r in aws_vpc_security_group_ingress_rule.app_http : r.from_port == 80 && r.to_port == 80])
    error_message = "The app server should accept port 80 only (no SSH: Session Manager is used instead)."
  }
}

run "http_can_be_limited_to_one_ip" {
  command = plan

  variables {
    allowed_http_cidrs = ["203.0.113.7/32"]
  }

  assert {
    condition     = keys(aws_vpc_security_group_ingress_rule.app_http) == ["203.0.113.7/32"]
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
