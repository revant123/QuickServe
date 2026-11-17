# Security and cost settings of the app server. No AWS account needed.
mock_provider "aws" {
  override_data {
    target = data.aws_ssm_parameter.al2023_arm64
    values = { value = "ami-0123456789abcdef0" }
  }
  override_data {
    target = data.aws_region.current
    values = { region = "ap-south-1" }
  }
  override_data {
    target = data.aws_caller_identity.current
    values = { account_id = "123456789012" }
  }
  override_data {
    target = data.aws_partition.current
    values = { partition = "aws" }
  }
  override_data {
    target = data.aws_iam_policy_document.assume_ec2
    values = { json = "{\"Version\":\"2012-10-17\",\"Statement\":[]}" }
  }
  override_data {
    target = data.aws_iam_policy_document.read_secrets
    values = { json = "{\"Version\":\"2012-10-17\",\"Statement\":[]}" }
  }
}

variables {
  name               = "quickserve-test"
  subnet_id          = "subnet-123"
  security_group_ids = ["sg-123"]
  image_tag          = "sha-abc1234"
  ssm_prefix         = "/quickserve/test"
  app_environment    = "test"
}

run "server_is_hardened" {
  command = plan

  assert {
    condition     = aws_instance.app.metadata_options[0].http_tokens == "required"
    error_message = "IMDSv2 must be required (blocks the classic credential-theft trick)."
  }
  assert {
    condition     = aws_instance.app.metadata_options[0].http_put_response_hop_limit == 1
    error_message = "Hop limit 1 keeps containers away from the server's AWS credentials."
  }
  assert {
    condition     = aws_instance.app.root_block_device[0].encrypted
    error_message = "The disk must be encrypted."
  }
  assert {
    condition     = aws_iam_role_policy_attachment.ssm_core.policy_arn == "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
    error_message = "Session Manager needs the SSM core policy."
  }
}

run "server_reads_only_its_own_secrets" {
  command = plan

  assert {
    condition     = data.aws_iam_policy_document.read_secrets.statement[0].resources == toset(["arn:aws:ssm:ap-south-1:123456789012:parameter/quickserve/test/*"])
    error_message = "The server may read its own environment's parameters and nothing else."
  }
  assert {
    condition     = toset(data.aws_iam_policy_document.read_secrets.statement[0].actions) == toset(["ssm:GetParameter", "ssm:GetParameters"])
    error_message = "Read-only access only: no Put, no Delete."
  }
}

run "cost_settings" {
  command = plan

  assert {
    condition     = aws_instance.app.credit_specification[0].cpu_credits == "standard"
    error_message = "Standard CPU credits: the server slows down instead of running up a bill."
  }
  assert {
    condition     = aws_instance.app.root_block_device[0].volume_type == "gp3"
    error_message = "gp3 is cheaper than gp2 for the same size."
  }
}

run "boot_script_deploys_the_requested_tag_and_holds_no_secrets" {
  command = plan

  assert {
    condition     = strcontains(aws_instance.app.user_data, "/opt/quickserve/deploy.sh \"sha-abc1234\"")
    error_message = "The first boot should deploy the requested image tag."
  }
  assert {
    condition     = strcontains(aws_instance.app.user_data, "--name \"$PREFIX/$1\"") && strcontains(aws_instance.app.user_data, "PREFIX=\"/quickserve/test\"")
    error_message = "Secrets must be fetched from Parameter Store at deploy time."
  }
  assert {
    condition     = !strcontains(aws_instance.app.user_data, "postgresql+psycopg://")
    error_message = "No database URL (with its password) may be baked into the boot script."
  }
}
