variable "region" {
  description = "AWS region. ap-south-1 is Mumbai."
  type        = string
  default     = "ap-south-1"
}

variable "image_tag" {
  description = "Image tag to deploy on first boot. Use an immutable sha-<commit> tag from ghcr.io/revant123/quickserve."
  type        = string
  default     = "main"

  validation {
    condition     = can(regex("^[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}$", var.image_tag))
    error_message = "image_tag must be a valid Docker tag, e.g. sha-3073e30."
  }
}

variable "instance_type" {
  description = "App server size. Must be an ARM (Graviton, the 'g' in t4g) type: the deploy uses the arm64 image."
  type        = string
  default     = "t4g.small"

  validation {
    condition     = can(regex("^[a-z][0-9]+g[a-z]*\\.", var.instance_type))
    error_message = "Use a Graviton (ARM) instance type such as t4g.small."
  }
}

variable "allowed_http_cidrs" {
  description = "Who may reach the site on ports 80 and 443. Default: everyone. With your own IP as \"x.x.x.x/32\" the demo stays private, but Let's Encrypt can't reach port 80 either, so there's no certificate."
  type        = list(string)
  default     = ["0.0.0.0/0"]

  validation {
    condition     = alltrue([for c in var.allowed_http_cidrs : can(cidrhost(c, 0))])
    error_message = "Each entry must be a CIDR block, e.g. 203.0.113.7/32."
  }
}

# ---------- Phase 16: live on the internet ----------

variable "domain" {
  description = "The site's name, e.g. quickserve-you.duckdns.org. Empty: plain HTTP on the server's AWS address, no certificate."
  type        = string
  default     = ""
}

variable "duckdns_token" {
  description = "Your DuckDNS token (duckdns.org, top of the page after signing in). Lets the server update its own DNS on every boot."
  type        = string
  default     = ""
  sensitive   = true

  validation {
    condition     = var.duckdns_token == "" || can(regex("^[0-9a-f-]{36}$", var.duckdns_token))
    error_message = "A DuckDNS token looks like 1a2b3c4d-1a2b-1a2b-1a2b-1a2b3c4d5e6f."
  }
}

variable "github_repository" {
  description = "The repository whose GitHub Actions may deploy (production environment only)."
  type        = string
  default     = "revant123/QuickServe"
}

# The repository's permanent IDs (public, not secrets). QuickServe was created
# after July 15, 2026, so GitHub's token names it by these. For a fork, put
# yours: gh api repos/OWNER/NAME --jq '{owner_id: .owner.id, id}'
variable "github_owner_id" {
  type    = number
  default = 149621150
}

variable "github_repository_id" {
  type    = number
  default = 1461084605
}

variable "create_github_oidc_provider" {
  description = "false if your AWS account already trusts token.actions.githubusercontent.com (only one is allowed per account)."
  type        = bool
  default     = true
}
