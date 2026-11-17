# One small ARM (Graviton) server that runs the QuickServe image from ghcr.io:
# a migration job, then the API, the worker and a local Redis, all in Docker.
#
# It has no SSH key and no port 22 open. You get a shell through AWS Systems
# Manager Session Manager instead, which is logged and needs no open port.

variable "name" {
  type = string
}

variable "subnet_id" {
  description = "A public subnet."
  type        = string
}

variable "security_group_ids" {
  type = list(string)
}

variable "instance_type" {
  description = "t4g.small: 2 burstable Graviton vCPUs and 2 GiB of RAM."
  type        = string
  default     = "t4g.small"
}

variable "root_volume_gb" {
  type    = number
  default = 16
}

variable "image" {
  description = "Container image without a tag."
  type        = string
  default     = "ghcr.io/revant123/quickserve"
}

variable "image_tag" {
  description = "Tag deployed when the server first boots, e.g. sha-3073e30. Later deploys don't need Terraform (see README)."
  type        = string
}

variable "ssm_prefix" {
  description = "Parameter Store path holding this environment's secrets, e.g. /quickserve/dev."
  type        = string
}

variable "app_environment" {
  description = "Value of the app's ENVIRONMENT setting. Anything except local/test/ci makes the app refuse the dev JWT secret."
  type        = string
}

data "aws_region" "current" {}
data "aws_caller_identity" "current" {}
data "aws_partition" "current" {}

# The newest Amazon Linux 2023 image for ARM, looked up from AWS's public
# parameter, so we never hard-code an image ID that goes stale.
data "aws_ssm_parameter" "al2023_arm64" {
  name = "/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-arm64"
}

# ---------- Permissions: what the server itself may do ----------

data "aws_iam_policy_document" "assume_ec2" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ec2.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "app" {
  name               = "${var.name}-app-server"
  assume_role_policy = data.aws_iam_policy_document.assume_ec2.json
}

# Lets Session Manager open a shell and run deploy commands. No SSH needed.
resource "aws_iam_role_policy_attachment" "ssm_core" {
  role       = aws_iam_role.app.name
  policy_arn = "arn:${data.aws_partition.current.partition}:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

# Least privilege: read THIS environment's parameters, nothing else.
data "aws_iam_policy_document" "read_secrets" {
  statement {
    actions = ["ssm:GetParameter", "ssm:GetParameters"]
    resources = [
      "arn:${data.aws_partition.current.partition}:ssm:${data.aws_region.current.region}:${data.aws_caller_identity.current.account_id}:parameter${var.ssm_prefix}/*",
    ]
  }
}

resource "aws_iam_role_policy" "read_secrets" {
  name   = "read-${replace(trim(var.ssm_prefix, "/"), "/", "-")}-parameters"
  role   = aws_iam_role.app.id
  policy = data.aws_iam_policy_document.read_secrets.json
}

resource "aws_iam_instance_profile" "app" {
  name = "${var.name}-app-server"
  role = aws_iam_role.app.name
}

# ---------- The server ----------

resource "aws_instance" "app" {
  ami                         = data.aws_ssm_parameter.al2023_arm64.value
  instance_type               = var.instance_type
  subnet_id                   = var.subnet_id
  vpc_security_group_ids      = var.security_group_ids
  associate_public_ip_address = true
  iam_instance_profile        = aws_iam_instance_profile.app.name

  # FinOps: T-family instances default to "unlimited" bursting, which bills
  # extra when the CPU runs hot for long. "standard" slows down instead of billing.
  credit_specification {
    cpu_credits = "standard"
  }

  # IMDSv2 only, and hop limit 1, so containers can't reach the server's
  # credentials through the metadata service. Only the host's deploy script can.
  metadata_options {
    http_endpoint               = "enabled"
    http_tokens                 = "required"
    http_put_response_hop_limit = 1
  }

  root_block_device {
    volume_type           = "gp3"
    volume_size           = var.root_volume_gb
    encrypted             = true
    delete_on_termination = true
  }

  user_data = templatefile("${path.module}/templates/user_data.sh.tftpl", {
    image           = var.image
    image_tag       = var.image_tag
    region          = data.aws_region.current.region
    ssm_prefix      = var.ssm_prefix
    app_environment = var.app_environment
  })
  # Changing the boot script builds a fresh server instead of silently keeping
  # the old one. Routine deploys don't touch Terraform at all.
  user_data_replace_on_change = true

  tags = { Name = "${var.name}-app" }

  lifecycle {
    # A newer Amazon Linux image appearing must not replace a running server on
    # the next apply. Pick it up on purpose with `terraform apply -replace=...`.
    ignore_changes = [ami]
  }
}

output "instance_id" {
  value = aws_instance.app.id
}

output "public_ip" {
  value = aws_instance.app.public_ip
}

output "public_dns" {
  value = aws_instance.app.public_dns
}
