mock_provider "aws" {
  override_data {
    target = data.aws_availability_zones.available
    values = { names = ["ap-south-1a", "ap-south-1b", "ap-south-1c"] }
  }
}

variables {
  name = "quickserve-test"
}

run "private_subnets_have_no_internet_route" {
  command = plan

  assert {
    condition     = length(aws_route_table.private.route) == 0
    error_message = "Private subnets must not route to the internet (and no NAT gateway, which bills by the hour)."
  }
  assert {
    condition     = one(aws_route_table.public.route).cidr_block == "0.0.0.0/0"
    error_message = "Public subnets route to the internet gateway."
  }
}

run "subnets_span_two_zones" {
  command = plan

  assert {
    condition     = length(distinct([for s in aws_subnet.private : s.availability_zone])) == 2
    error_message = "RDS needs private subnets in two availability zones."
  }
  assert {
    condition     = [for s in aws_subnet.private : s.cidr_block] == ["10.20.10.0/24", "10.20.11.0/24"]
    error_message = "Private subnets should be 10.20.10.0/24 and 10.20.11.0/24."
  }
  assert {
    condition     = alltrue([for s in aws_subnet.public : s.map_public_ip_on_launch == false])
    error_message = "Machines must opt in to a public IP; it isn't handed out by default."
  }
}

run "default_security_group_allows_nothing" {
  command = plan

  assert {
    condition     = length(aws_default_security_group.default.ingress) == 0 && length(aws_default_security_group.default.egress) == 0
    error_message = "The VPC's default security group must have no rules."
  }
}

run "one_zone_is_rejected" {
  command = plan

  variables {
    az_count = 1
  }

  expect_failures = [var.az_count]
}
