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
  domain             = "quickserve-test.duckdns.org"
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
    condition     = strcontains(local.user_data, "/opt/quickserve/deploy.sh \"sha-abc1234\"")
    error_message = "The first boot should deploy the requested image tag."
  }
  assert {
    condition     = strcontains(local.user_data, "--name \"$PREFIX/$1\"") && strcontains(local.user_data, "PREFIX=\"/quickserve/test\"")
    error_message = "Secrets must be fetched from Parameter Store at deploy time."
  }
  assert {
    condition     = !strcontains(local.user_data, "postgresql+psycopg://")
    error_message = "No database URL (with its password) may be baked into the boot script."
  }
}

run "live_site_https_and_blue_green" {
  command = plan

  assert {
    condition     = length(base64gzip(local.user_data)) * 3 / 4 < 16384 && aws_instance.app.user_data_base64 == base64gzip(local.user_data)
    error_message = "EC2 refuses user data over 16 KB: even compressed, the boot script has grown too big."
  }
  assert {
    condition     = strcontains(local.user_data, "SITE_ADDRESS=\"$${DOMAIN:-:80}\"") && strcontains(local.user_data, "DOMAIN=\"quickserve-test.duckdns.org\"")
    error_message = "Caddy must serve the configured domain (and get its certificate)."
  }
  assert {
    condition     = strcontains(local.user_data, "{$SITE_ADDRESS} {") && strcontains(local.user_data, "sampling_percentage: $${env:TRACE_SAMPLE_PERCENT:-100}")
    error_message = "The Caddyfile and Jaeger config must reach the server unchanged (their own placeholders untouched by Terraform)."
  }
  assert {
    condition     = strcontains(local.user_data, "-p 80:80 -p 443:443") && !strcontains(local.user_data, "-p 80:8000")
    error_message = "Only Caddy has public ports; the API is reached through it."
  }
  assert {
    condition     = strcontains(local.user_data, "-p 127.0.0.1:16686:16686")
    error_message = "Jaeger's UI must stay off the internet (localhost only, reached through Session Manager)."
  }
  assert {
    condition     = strcontains(local.user_data, "TRUSTED_PROXY_CIDRS=$CADDY_IP/32")
    error_message = "The API may trust X-Forwarded-For from Caddy only, or the login limits could be dodged."
  }
}

run "deploy_document_accepts_only_image_tags" {
  command = plan

  assert {
    condition     = jsondecode(aws_ssm_document.deploy.content).parameters.tag.allowedPattern == "^(sha-[0-9a-f]{7,40}|rollback)$"
    error_message = "The tag must be sha-<hex> or rollback, so it can't carry a shell command."
  }
  assert {
    condition     = jsondecode(aws_ssm_document.deploy.content).mainSteps[0].inputs.runCommand == ["/opt/quickserve/deploy.sh {{ tag }}"]
    error_message = "The document runs deploy.sh and nothing else."
  }
  assert {
    condition     = alltrue([for t in ["sha-0519a88", "sha-0519a88f3c2d1e0b9a8f7e6d5c4b3a2f1e0d9c8b", "rollback"] : can(regex(local.deploy_tag_pattern, t))])
    error_message = "Real tags must pass."
  }
  assert {
    condition     = !anytrue([for t in ["sha-0519a88; rm -rf /", "main", "sha-$(id)", "sha-0519a8", "rollback\nreboot"] : can(regex(local.deploy_tag_pattern, t))])
    error_message = "Anything else must be refused."
  }
}

run "domain_must_be_a_bare_host_name" {
  command = plan

  variables {
    domain = "https://quickserve-test.duckdns.org/"
  }

  expect_failures = [var.domain]
}
