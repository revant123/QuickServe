mock_provider "aws" {}

variables {
  name               = "quickserve-test"
  subnet_ids         = ["subnet-a", "subnet-b"]
  security_group_ids = ["sg-db"]
  password           = "test-password-not-real-0123456789"
}

run "private_encrypted_and_cheap" {
  command = plan

  assert {
    condition     = aws_db_instance.main.publicly_accessible == false
    error_message = "The database must not have a public address."
  }
  assert {
    condition     = aws_db_instance.main.storage_encrypted
    error_message = "Storage must be encrypted."
  }
  assert {
    condition     = aws_db_instance.main.engine == "postgres" && aws_db_instance.main.engine_version == "16"
    error_message = "PostgreSQL 16, the same major version as Docker Compose and CI."
  }
  assert {
    condition     = aws_db_instance.main.multi_az == false && aws_db_instance.main.instance_class == "db.t4g.micro"
    error_message = "Dev uses one small Graviton instance."
  }
  assert {
    condition     = aws_db_instance.main.max_allocated_storage == null
    error_message = "Storage autoscaling stays off so the bill can't grow by itself."
  }
}

run "dev_destroys_without_a_snapshot" {
  command = plan

  assert {
    condition     = aws_db_instance.main.skip_final_snapshot && aws_db_instance.main.final_snapshot_identifier == null
    error_message = "Dev should destroy cleanly without leaving a billed snapshot."
  }
}

run "production_style_keeps_a_final_snapshot" {
  command = plan

  variables {
    skip_final_snapshot = false
    deletion_protection = true
  }

  assert {
    condition     = aws_db_instance.main.final_snapshot_identifier == "quickserve-test-db-final" && aws_db_instance.main.deletion_protection
    error_message = "With skip_final_snapshot = false, destroy must keep a named final snapshot."
  }
}
