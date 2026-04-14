# =============================================================================
# VPC — 2 AZs, Public + Private + Isolated Subnets
# =============================================================================
# Public:   ALB, NAT Gateway
# Private:  ECS Fargate tasks, ECS EC2 (Whisper GPU) — outbound via NAT
# Isolated: RDS PostgreSQL — no internet access
# =============================================================================

# -----------------------------------------------------------------------------
# Availability Zones
# -----------------------------------------------------------------------------

data "aws_availability_zones" "available" {
  state = "available"
}

locals {
  azs = slice(data.aws_availability_zones.available.names, 0, 2)

  # CIDR allocation: /16 VPC split into /24 subnets across 2 AZs
  # Public:   10.0.1.0/24, 10.0.2.0/24
  # Private:  10.0.11.0/24, 10.0.12.0/24
  # Isolated: 10.0.21.0/24, 10.0.22.0/24
  public_subnets   = ["10.0.1.0/24", "10.0.2.0/24"]
  private_subnets  = ["10.0.11.0/24", "10.0.12.0/24"]
  isolated_subnets = ["10.0.21.0/24", "10.0.22.0/24"]

  # Dev: 1 NAT gateway (cost savings). Prod: 1 per AZ (high availability).
  nat_gateway_count = var.multi_az ? 2 : 1
}

# -----------------------------------------------------------------------------
# VPC
# -----------------------------------------------------------------------------

resource "aws_vpc" "main" {
  cidr_block           = "10.0.0.0/16"
  enable_dns_support   = true
  enable_dns_hostnames = true

  tags = {
    Name = "aurion-vpc-${var.environment}"
  }
}

# -----------------------------------------------------------------------------
# Internet Gateway
# -----------------------------------------------------------------------------

resource "aws_internet_gateway" "main" {
  vpc_id = aws_vpc.main.id

  tags = {
    Name = "aurion-igw-${var.environment}"
  }
}

# -----------------------------------------------------------------------------
# Public Subnets — ALB, NAT Gateways
# -----------------------------------------------------------------------------

resource "aws_subnet" "public" {
  count = 2

  vpc_id                  = aws_vpc.main.id
  cidr_block              = local.public_subnets[count.index]
  availability_zone       = local.azs[count.index]
  map_public_ip_on_launch = true

  tags = {
    Name = "aurion-public-${local.azs[count.index]}-${var.environment}"
    Tier = "public"
  }
}

resource "aws_route_table" "public" {
  vpc_id = aws_vpc.main.id

  tags = {
    Name = "aurion-public-rt-${var.environment}"
  }
}

resource "aws_route" "public_internet" {
  route_table_id         = aws_route_table.public.id
  destination_cidr_block = "0.0.0.0/0"
  gateway_id             = aws_internet_gateway.main.id
}

resource "aws_route_table_association" "public" {
  count = 2

  subnet_id      = aws_subnet.public[count.index].id
  route_table_id = aws_route_table.public.id
}

# -----------------------------------------------------------------------------
# NAT Gateways — 1 for dev, 2 for prod
# -----------------------------------------------------------------------------

resource "aws_eip" "nat" {
  count  = local.nat_gateway_count
  domain = "vpc"

  tags = {
    Name = "aurion-nat-eip-${count.index}-${var.environment}"
  }
}

resource "aws_nat_gateway" "main" {
  count = local.nat_gateway_count

  allocation_id = aws_eip.nat[count.index].id
  subnet_id     = aws_subnet.public[count.index].id

  tags = {
    Name = "aurion-nat-${count.index}-${var.environment}"
  }

  depends_on = [aws_internet_gateway.main]
}

# -----------------------------------------------------------------------------
# Private Subnets — ECS Fargate, ECS EC2 (Whisper GPU)
# -----------------------------------------------------------------------------

resource "aws_subnet" "private" {
  count = 2

  vpc_id            = aws_vpc.main.id
  cidr_block        = local.private_subnets[count.index]
  availability_zone = local.azs[count.index]

  tags = {
    Name = "aurion-private-${local.azs[count.index]}-${var.environment}"
    Tier = "private"
  }
}

resource "aws_route_table" "private" {
  count = 2

  vpc_id = aws_vpc.main.id

  tags = {
    Name = "aurion-private-rt-${count.index}-${var.environment}"
  }
}

resource "aws_route" "private_nat" {
  count = 2

  route_table_id         = aws_route_table.private[count.index].id
  destination_cidr_block = "0.0.0.0/0"
  # In dev (1 NAT), both private subnets share the single NAT gateway.
  # In prod (2 NATs), each private subnet uses its own NAT for HA.
  nat_gateway_id = aws_nat_gateway.main[min(count.index, local.nat_gateway_count - 1)].id
}

resource "aws_route_table_association" "private" {
  count = 2

  subnet_id      = aws_subnet.private[count.index].id
  route_table_id = aws_route_table.private[count.index].id
}

# -----------------------------------------------------------------------------
# Isolated Subnets — RDS PostgreSQL (no internet access)
# -----------------------------------------------------------------------------

resource "aws_subnet" "isolated" {
  count = 2

  vpc_id            = aws_vpc.main.id
  cidr_block        = local.isolated_subnets[count.index]
  availability_zone = local.azs[count.index]

  tags = {
    Name = "aurion-isolated-${local.azs[count.index]}-${var.environment}"
    Tier = "isolated"
  }
}

resource "aws_route_table" "isolated" {
  vpc_id = aws_vpc.main.id

  tags = {
    Name = "aurion-isolated-rt-${var.environment}"
  }
}

# No routes — isolated subnets have no internet access by design

resource "aws_route_table_association" "isolated" {
  count = 2

  subnet_id      = aws_subnet.isolated[count.index].id
  route_table_id = aws_route_table.isolated.id
}
