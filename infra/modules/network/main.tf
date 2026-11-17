# The network: one VPC split into public and private subnets.
#
#   public subnets  - have a route to the internet. The app server lives here.
#   private subnets - have NO route to the internet. The database lives here,
#                     reachable only from inside the VPC.
#
# There is deliberately no NAT gateway. A NAT gateway lets private machines
# reach the internet, and it bills every hour it exists plus every GB through
# it, which is the classic surprise on a learner's AWS bill. Nothing in a
# private subnet here needs the internet: RDS gets its updates from AWS itself.

variable "name" {
  type = string
}

variable "cidr_block" {
  description = "Address range of the whole VPC."
  type        = string
  default     = "10.20.0.0/16"
}

variable "az_count" {
  description = "How many availability zones (separate data centres) to spread subnets over. RDS requires at least 2."
  type        = number
  default     = 2

  validation {
    condition     = var.az_count >= 2
    error_message = "RDS needs subnets in at least two availability zones."
  }
}

data "aws_availability_zones" "available" {
  state = "available"
}

locals {
  azs = slice(data.aws_availability_zones.available.names, 0, var.az_count)
}

resource "aws_vpc" "main" {
  cidr_block           = var.cidr_block
  enable_dns_support   = true
  enable_dns_hostnames = true # RDS gives its address as a DNS name

  tags = { Name = var.name }
}

# Lock down the VPC's default security group: no rules means nothing in or out.
# Anything that forgets to choose a security group gets no access, not full access.
resource "aws_default_security_group" "default" {
  vpc_id  = aws_vpc.main.id
  ingress = []
  egress  = []
}

resource "aws_internet_gateway" "main" {
  vpc_id = aws_vpc.main.id
  tags   = { Name = var.name }
}

# 10.20.0.0/24, 10.20.1.0/24, ...
resource "aws_subnet" "public" {
  count = var.az_count

  vpc_id                  = aws_vpc.main.id
  availability_zone       = local.azs[count.index]
  cidr_block              = cidrsubnet(var.cidr_block, 8, count.index)
  map_public_ip_on_launch = false # each machine opts in explicitly

  tags = { Name = "${var.name}-public-${local.azs[count.index]}", tier = "public" }
}

# 10.20.10.0/24, 10.20.11.0/24, ...
resource "aws_subnet" "private" {
  count = var.az_count

  vpc_id            = aws_vpc.main.id
  availability_zone = local.azs[count.index]
  cidr_block        = cidrsubnet(var.cidr_block, 8, 10 + count.index)

  tags = { Name = "${var.name}-private-${local.azs[count.index]}", tier = "private" }
}

resource "aws_route_table" "public" {
  vpc_id = aws_vpc.main.id

  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.main.id
  }

  tags = { Name = "${var.name}-public" }
}

# Only the built-in "local" route: traffic stays inside the VPC.
resource "aws_route_table" "private" {
  vpc_id = aws_vpc.main.id
  route  = [] # explicitly none; Terraform removes any route someone adds by hand
  tags   = { Name = "${var.name}-private" }
}

resource "aws_route_table_association" "public" {
  count          = var.az_count
  subnet_id      = aws_subnet.public[count.index].id
  route_table_id = aws_route_table.public.id
}

resource "aws_route_table_association" "private" {
  count          = var.az_count
  subnet_id      = aws_subnet.private[count.index].id
  route_table_id = aws_route_table.private.id
}

output "vpc_id" {
  value = aws_vpc.main.id
}

output "public_subnet_ids" {
  value = aws_subnet.public[*].id
}

output "private_subnet_ids" {
  value = aws_subnet.private[*].id
}
