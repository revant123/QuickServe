# One small ARM (Graviton) server that runs QuickServe from ghcr.io, all in
# Docker: Caddy (HTTPS) in front, the API (blue/green), the React app, the
# worker, the notifier, Redis and Jaeger. A migration job runs on each deploy.
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

variable "web_image" {
  description = "The React app's image (nginx), without a tag. Published with the same tags as the API."
  type        = string
  default     = "ghcr.io/revant123/quickserve-app"
}

variable "domain" {
  description = "The site's name, e.g. quickserve-you.duckdns.org. Caddy gets a Let's Encrypt certificate for it. Empty: plain HTTP on the server's IP."
  type        = string
  default     = ""

  validation {
    condition     = var.domain == "" || can(regex("^([a-z0-9]([a-z0-9-]*[a-z0-9])?\\.)+[a-z]{2,}$", var.domain))
    error_message = "domain must be a lowercase host name such as quickserve-you.duckdns.org (no https://, no slash)."
  }
}

variable "trace_sample_percent" {
  description = "Share of ordinary traces Jaeger keeps. Errors, slow requests and suspected N+1 are always kept."
  type        = number
  default     = 10
}

# Pinned versions: a deploy must never pick up a new Caddy or Jaeger by surprise.
variable "caddy_image" {
  type    = string
  default = "caddy:2.11.9-alpine"
}

variable "jaeger_image" {
  type    = string
  default = "jaegertracing/jaeger:2.21.0"
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

locals {
  user_data = templatefile("${path.module}/templates/user_data.sh.tftpl", {
    image                = var.image
    web_image            = var.web_image
    image_tag            = var.image_tag
    region               = data.aws_region.current.region
    ssm_prefix           = var.ssm_prefix
    app_environment      = var.app_environment
    domain               = var.domain
    trace_sample_percent = var.trace_sample_percent
    caddy_image          = var.caddy_image
    jaeger_image         = var.jaeger_image
    # Inserted as they are: their own {$...} and ${env:...} are for Caddy and
    # Jaeger, not for Terraform.
    caddyfile     = trimspace(file("${path.module}/templates/Caddyfile"))
    jaeger_config = trimspace(file("${path.module}/../../k8s/tracing/jaeger-config.yaml"))
  })
}

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

  # gzip, then base64: EC2 accepts at most 16 KB of user data, and this script
  # (with the Caddy and Jaeger configs inside) is close to that. cloud-init
  # unzips it before running it. Compressed it's about a third of the size.
  user_data_base64 = base64gzip(local.user_data)
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

# ---------- Deploys from GitHub Actions (Phase 16) ----------
# The deploy job may run THIS document and nothing else, so "may deploy" never
# means "may run any command as root". The tag must look like sha-<commit>
# (or "rollback"): SSM rejects anything else before it reaches the shell, so
# a tag can't smuggle in a command.
resource "aws_ssm_document" "deploy" {
  name            = "${var.name}-deploy"
  document_type   = "Command"
  document_format = "JSON"
  content = jsonencode({
    schemaVersion = "2.2"
    description   = "Deploy one QuickServe image tag (or roll back to the previous one)"
    parameters = {
      tag = {
        type           = "String"
        description    = "sha-<commit>, or rollback"
        allowedPattern = local.deploy_tag_pattern
      }
    }
    mainSteps = [{
      action = "aws:runShellScript"
      name   = "deploy"
      inputs = {
        timeoutSeconds = "600"
        runCommand     = ["/opt/quickserve/deploy.sh {{ tag }}"]
      }
    }]
  })
}

locals {
  deploy_tag_pattern = "^(sha-[0-9a-f]{7,40}|rollback)$"
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

output "instance_arn" {
  value = aws_instance.app.arn
}

output "deploy_document_name" {
  value = aws_ssm_document.deploy.name
}

output "deploy_document_arn" {
  value = aws_ssm_document.deploy.arn
}

output "user_data_bytes" {
  description = "EC2 accepts at most 16 KB of user data: the compressed script, before base64."
  value       = { script = length(local.user_data), compressed = floor(length(base64gzip(local.user_data)) * 3 / 4) }
}
