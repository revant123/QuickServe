output "api_url" {
  description = "Open this in a browser once the server has finished booting (about 3 minutes after apply)."
  value       = "http://${module.app_server.public_dns}/docs"
}

output "ready_url" {
  value = "http://${module.app_server.public_dns}/health/ready"
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
  description = "Deploy another image tag without Terraform."
  value       = "aws ssm send-command --region ${var.region} --instance-ids ${module.app_server.instance_id} --document-name AWS-RunShellScript --parameters 'commands=[\"/opt/quickserve/deploy.sh sha-XXXXXXX\"]'"
}
