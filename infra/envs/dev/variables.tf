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
  description = "Who may reach the API on port 80. Default: everyone. Put your own IP as \"x.x.x.x/32\" to keep the demo private."
  type        = list(string)
  default     = ["0.0.0.0/0"]

  validation {
    condition     = alltrue([for c in var.allowed_http_cidrs : can(cidrhost(c, 0))])
    error_message = "Each entry must be a CIDR block, e.g. 203.0.113.7/32."
  }
}
