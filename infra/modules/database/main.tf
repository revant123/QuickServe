# Managed PostgreSQL (Amazon RDS) in the private subnets.
#
# RDS does the database chores for us: backups, minor version patches, disk
# encryption, replacing failed hardware. We still choose the size, and the
# size is most of the bill.

variable "name" {
  type = string
}

variable "subnet_ids" {
  description = "Private subnets, in at least two availability zones."
  type        = list(string)
}

variable "security_group_ids" {
  description = "Security groups that decide who may connect on port 5432."
  type        = list(string)
}

variable "instance_class" {
  description = "Machine size. db.t4g.micro: 2 burstable ARM (Graviton) vCPUs and 1 GiB of RAM, the smallest PostgreSQL size."
  type        = string
  default     = "db.t4g.micro"
}

variable "engine_version" {
  description = "PostgreSQL major version; RDS picks and patches the minor version. Same major as Docker Compose and CI."
  type        = string
  default     = "16"
}

variable "allocated_storage_gb" {
  type    = number
  default = 20 # the RDS minimum for gp3
}

variable "db_name" {
  type    = string
  default = "quickserve"
}

variable "username" {
  type    = string
  default = "quickserve"
}

variable "password" {
  type      = string
  sensitive = true # never printed in plan output or logs
}

variable "backup_retention_days" {
  type    = number
  default = 1
}

variable "deletion_protection" {
  description = "true in production. false in dev so `terraform destroy` works in one step."
  type        = bool
  default     = false
}

variable "skip_final_snapshot" {
  description = "true in dev: destroy without keeping a snapshot (a snapshot you forget about is billed every month). false in production."
  type        = bool
  default     = true
}

resource "aws_db_subnet_group" "main" {
  name       = "${var.name}-db"
  subnet_ids = var.subnet_ids
}

resource "aws_db_instance" "main" {
  identifier     = "${var.name}-db"
  engine         = "postgres"
  engine_version = var.engine_version
  instance_class = var.instance_class

  allocated_storage = var.allocated_storage_gb
  storage_type      = "gp3"
  storage_encrypted = true
  # max_allocated_storage is left unset, so storage never grows (and bills) by itself.

  db_name  = var.db_name
  username = var.username
  password = var.password

  db_subnet_group_name   = aws_db_subnet_group.main.name
  vpc_security_group_ids = var.security_group_ids
  publicly_accessible    = false # no public address at all
  multi_az               = false # one copy: half the price, but no automatic failover (fine for dev)

  backup_retention_period    = var.backup_retention_days
  auto_minor_version_upgrade = true
  apply_immediately          = true # dev: apply changes now, not in the weekly maintenance window

  deletion_protection       = var.deletion_protection
  skip_final_snapshot       = var.skip_final_snapshot
  final_snapshot_identifier = var.skip_final_snapshot ? null : "${var.name}-db-final"
  copy_tags_to_snapshot     = true

  performance_insights_enabled = false
}

output "address" {
  description = "DNS name of the database, reachable only from inside the VPC."
  value       = aws_db_instance.main.address
}

output "port" {
  value = aws_db_instance.main.port
}

output "db_name" {
  value = aws_db_instance.main.db_name
}

output "username" {
  value = aws_db_instance.main.username
}
