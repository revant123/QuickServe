locals {
  site_url = var.domain == "" ? "http://${module.app_server.public_dns}" : "https://${var.domain}"
}

output "site_url" {
  description = "The live app. Ready about 3-5 minutes after apply (Docker, images, migrations, certificate)."
  value       = local.site_url
}

output "api_url" {
  value = "${local.site_url}/docs"
}

output "ready_url" {
  value = "${local.site_url}/health/ready"
}

output "public_ip" {
  description = "Where the domain should point. With a DuckDNS token the server sets this itself."
  value       = module.app_server.public_ip
}

output "github_setup_commands" {
  description = "Run these once (in the repo folder) so GitHub Actions deploys after every merge."
  value       = <<-EOT
    gh variable set AWS_DEPLOY_ROLE_ARN --body "${module.github_deploy.role_arn}"
    gh variable set AWS_REGION --body "${var.region}"
    gh variable set LIVE_URL --body "${local.site_url}"
    gh variable set DEPLOY_TARGET_PARAMETER --body "${aws_ssm_parameter.deploy_target.name}"
  EOT
}

output "jaeger_tunnel_command" {
  description = "Jaeger's UI isn't on the internet. This opens it at http://localhost:16686 through Session Manager."
  value       = "aws ssm start-session --region ${var.region} --target ${module.app_server.instance_id} --document-name AWS-StartPortForwardingSession --parameters portNumber=16686,localPortNumber=16686"
}

output "demo_customer_password" {
  description = "customer@quickserve.dev on the live site: terraform output -raw demo_customer_password"
  value       = random_password.demo_customer.result
  sensitive   = true
}

output "demo_staff_password" {
  description = "owner@, rider@ and admin@quickserve.dev on the live site: keep this one to yourself"
  value       = random_password.demo_staff.result
  sensitive   = true
}

output "instance_id" {
  description = "For Session Manager: aws ssm start-session --target <this>"
  value       = module.app_server.instance_id
}

output "database_address" {
  description = "Private DNS name; reachable only from inside the VPC."
  value       = module.database.address
}

output "deploy_command" {
  description = "Deploy (or roll back) by hand, the same way GitHub Actions does."
  value       = "aws ssm send-command --region ${var.region} --instance-ids ${module.app_server.instance_id} --document-name ${module.app_server.deploy_document_name} --parameters tag=sha-XXXXXXX"
}
