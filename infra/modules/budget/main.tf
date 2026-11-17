# A monthly cost budget for the whole AWS account, with email alerts.
#
# This is an ALERT, not a spending cap: AWS keeps billing if you ignore it.
# Budgets that only send notifications are free.

variable "name" {
  description = "Name shown in the AWS Budgets console."
  type        = string
}

variable "monthly_limit_usd" {
  description = "Monthly budget in US dollars. Alerts fire at 50% and 80% of actual spend, and when the forecast passes 100%."
  type        = number

  validation {
    condition     = var.monthly_limit_usd > 0
    error_message = "monthly_limit_usd must be greater than zero."
  }
}

variable "alert_emails" {
  description = "Email addresses that receive budget alerts."
  type        = list(string)

  validation {
    condition     = length(var.alert_emails) > 0
    error_message = "Give at least one email address, or nobody hears the alarm."
  }
}

locals {
  # (threshold %, ACTUAL or FORECASTED)
  # ACTUAL fires when money has been spent; FORECASTED fires when AWS predicts
  # you WILL pass the limit by the end of the month, which is the early warning.
  alerts = [
    { threshold = 50, type = "ACTUAL" },
    { threshold = 80, type = "ACTUAL" },
    { threshold = 100, type = "FORECASTED" },
  ]
}

resource "aws_budgets_budget" "monthly" {
  name         = var.name
  budget_type  = "COST"
  limit_amount = format("%.2f", var.monthly_limit_usd)
  limit_unit   = "USD"
  time_unit    = "MONTHLY"

  dynamic "notification" {
    for_each = local.alerts
    content {
      comparison_operator        = "GREATER_THAN"
      threshold                  = notification.value.threshold
      threshold_type             = "PERCENTAGE"
      notification_type          = notification.value.type
      subscriber_email_addresses = var.alert_emails
    }
  }
}

output "budget_name" {
  value = aws_budgets_budget.monthly.name
}
