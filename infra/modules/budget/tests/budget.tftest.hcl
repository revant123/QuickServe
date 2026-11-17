mock_provider "aws" {}

variables {
  name              = "quickserve-test"
  monthly_limit_usd = 10
  alert_emails      = ["you@example.com"]
}

run "three_alerts" {
  command = plan

  assert {
    condition     = aws_budgets_budget.monthly.limit_amount == "10.00" && aws_budgets_budget.monthly.time_unit == "MONTHLY"
    error_message = "A USD 10 monthly budget."
  }
  assert {
    condition     = length(aws_budgets_budget.monthly.notification) == 3
    error_message = "Alerts at 50% and 80% actual, and 100% forecast."
  }
  assert {
    condition     = contains([for n in aws_budgets_budget.monthly.notification : "${n.notification_type}-${n.threshold}"], "FORECASTED-100")
    error_message = "The forecast alert is the early warning: it fires before the money is spent."
  }
}

run "no_email_is_rejected" {
  command = plan

  variables {
    alert_emails = []
  }

  expect_failures = [var.alert_emails]
}
