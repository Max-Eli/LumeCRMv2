# Network — VPC, subnets, IGW, NAT, route tables, VPC endpoints,
# security groups.
#
# Two-tier subnet layout per AZ:
#   - public  → ALB + NAT gateway only
#   - private → ECS tasks (backend + frontend) + RDS
#
# Egress from private subnets goes through the NAT, but we add VPC
# endpoints for ECR, S3, Secrets Manager, and CloudWatch Logs so the
# common high-traffic paths bypass the NAT (huge cost saver at scale,
# and a defense-in-depth posture: ECS tasks can pull images / read
# secrets / write logs without any internet route at all).

# ── VPC + subnets ──────────────────────────────────────────────────

resource "aws_vpc" "main" {
  cidr_block           = var.vpc_cidr
  enable_dns_support   = true
  enable_dns_hostnames = true

  tags = {
    Name = "${local.name_prefix}-vpc"
  }
}

resource "aws_subnet" "public" {
  count                   = var.az_count
  vpc_id                  = aws_vpc.main.id
  cidr_block              = local.public_subnet_cidrs[count.index]
  availability_zone       = local.azs[count.index]
  map_public_ip_on_launch = false

  tags = {
    Name = "${local.name_prefix}-public-${local.azs[count.index]}"
    Tier = "public"
  }
}

resource "aws_subnet" "private" {
  count             = var.az_count
  vpc_id            = aws_vpc.main.id
  cidr_block        = local.private_subnet_cidrs[count.index]
  availability_zone = local.azs[count.index]

  tags = {
    Name = "${local.name_prefix}-private-${local.azs[count.index]}"
    Tier = "private"
  }
}

# ── Internet + NAT ─────────────────────────────────────────────────

resource "aws_internet_gateway" "main" {
  vpc_id = aws_vpc.main.id

  tags = {
    Name = "${local.name_prefix}-igw"
  }
}

# Single NAT gateway (cheaper). For higher availability, switch to
# one-NAT-per-AZ — each costs ~$32/mo + data processing fees.
resource "aws_eip" "nat" {
  domain     = "vpc"
  depends_on = [aws_internet_gateway.main]

  tags = {
    Name = "${local.name_prefix}-nat-eip"
  }
}

resource "aws_nat_gateway" "main" {
  allocation_id = aws_eip.nat.id
  subnet_id     = aws_subnet.public[0].id

  tags = {
    Name = "${local.name_prefix}-nat"
  }

  depends_on = [aws_internet_gateway.main]
}

# ── Route tables ───────────────────────────────────────────────────

resource "aws_route_table" "public" {
  vpc_id = aws_vpc.main.id

  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.main.id
  }

  tags = {
    Name = "${local.name_prefix}-public-rt"
  }
}

resource "aws_route_table_association" "public" {
  count          = var.az_count
  subnet_id      = aws_subnet.public[count.index].id
  route_table_id = aws_route_table.public.id
}

resource "aws_route_table" "private" {
  vpc_id = aws_vpc.main.id

  route {
    cidr_block     = "0.0.0.0/0"
    nat_gateway_id = aws_nat_gateway.main.id
  }

  tags = {
    Name = "${local.name_prefix}-private-rt"
  }
}

resource "aws_route_table_association" "private" {
  count          = var.az_count
  subnet_id      = aws_subnet.private[count.index].id
  route_table_id = aws_route_table.private.id
}

# ── VPC endpoints (cost + security) ────────────────────────────────
#
# Gateway endpoints (S3, DynamoDB) are free and route via the
# private route table. Interface endpoints (ECR, Secrets Manager,
# CloudWatch Logs) cost ~$7/mo each but eliminate NAT data fees
# for those services. Worth it once we're past the smallest scale.

resource "aws_vpc_endpoint" "s3" {
  vpc_id            = aws_vpc.main.id
  service_name      = "com.amazonaws.${var.aws_region}.s3"
  vpc_endpoint_type = "Gateway"
  route_table_ids   = [aws_route_table.private.id]

  tags = {
    Name = "${local.name_prefix}-vpce-s3"
  }
}

resource "aws_security_group" "vpc_endpoints" {
  name        = "${local.name_prefix}-vpce"
  description = "Allow HTTPS to interface VPC endpoints from private subnets."
  vpc_id      = aws_vpc.main.id

  ingress {
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = local.private_subnet_cidrs
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name = "${local.name_prefix}-vpce-sg"
  }
}

# Interface endpoints kept minimal — every endpoint is +$7/mo so we
# only enable the ones that pull bytes (ECR + logs). Secrets Manager
# is hit once at task-start; the NAT fee for that is rounding error.
resource "aws_vpc_endpoint" "ecr_api" {
  vpc_id              = aws_vpc.main.id
  service_name        = "com.amazonaws.${var.aws_region}.ecr.api"
  vpc_endpoint_type   = "Interface"
  subnet_ids          = aws_subnet.private[*].id
  security_group_ids  = [aws_security_group.vpc_endpoints.id]
  private_dns_enabled = true

  tags = { Name = "${local.name_prefix}-vpce-ecr-api" }
}

resource "aws_vpc_endpoint" "ecr_dkr" {
  vpc_id              = aws_vpc.main.id
  service_name        = "com.amazonaws.${var.aws_region}.ecr.dkr"
  vpc_endpoint_type   = "Interface"
  subnet_ids          = aws_subnet.private[*].id
  security_group_ids  = [aws_security_group.vpc_endpoints.id]
  private_dns_enabled = true

  tags = { Name = "${local.name_prefix}-vpce-ecr-dkr" }
}

resource "aws_vpc_endpoint" "logs" {
  vpc_id              = aws_vpc.main.id
  service_name        = "com.amazonaws.${var.aws_region}.logs"
  vpc_endpoint_type   = "Interface"
  subnet_ids          = aws_subnet.private[*].id
  security_group_ids  = [aws_security_group.vpc_endpoints.id]
  private_dns_enabled = true

  tags = { Name = "${local.name_prefix}-vpce-logs" }
}

# ── Security groups for app traffic ────────────────────────────────

# ALB — internet-facing; accepts HTTPS only. HTTP redirects to HTTPS
# at the listener level (no need for an HTTP rule here).
resource "aws_security_group" "alb" {
  name        = "${local.name_prefix}-alb"
  description = "Public ALB. HTTPS in, traffic to backend + frontend tasks out."
  vpc_id      = aws_vpc.main.id

  ingress {
    description = "HTTPS from anywhere"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  ingress {
    description = "HTTP redirected to HTTPS by ALB"
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = { Name = "${local.name_prefix}-alb-sg" }
}

# Backend tasks — only the ALB can reach them on the gunicorn port.
resource "aws_security_group" "backend" {
  name        = "${local.name_prefix}-backend"
  description = "Backend Fargate tasks. Ingress from ALB only; egress unrestricted (RDS / SES / S3 / Secrets)."
  vpc_id      = aws_vpc.main.id

  ingress {
    description     = "ALB to backend gunicorn"
    from_port       = 8000
    to_port         = 8000
    protocol        = "tcp"
    security_groups = [aws_security_group.alb.id]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = { Name = "${local.name_prefix}-backend-sg" }
}

# Frontend tasks — Next standalone server on :3000.
resource "aws_security_group" "frontend" {
  name        = "${local.name_prefix}-frontend"
  description = "Frontend Fargate tasks. Ingress from ALB only."
  vpc_id      = aws_vpc.main.id

  ingress {
    description     = "ALB to frontend Next server"
    from_port       = 3000
    to_port         = 3000
    protocol        = "tcp"
    security_groups = [aws_security_group.alb.id]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = { Name = "${local.name_prefix}-frontend-sg" }
}

# RDS — only the backend tasks can reach Postgres. NO public access,
# NO bastion path. Local debugging goes through Session Manager into
# a Fargate task.
resource "aws_security_group" "rds" {
  name        = "${local.name_prefix}-rds"
  description = "RDS Postgres. Backend SG only."
  vpc_id      = aws_vpc.main.id

  ingress {
    description     = "Backend to Postgres"
    from_port       = 5432
    to_port         = 5432
    protocol        = "tcp"
    security_groups = [aws_security_group.backend.id]
  }

  egress {
    description = "Reply traffic only -- RDS does not initiate egress."
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = { Name = "${local.name_prefix}-rds-sg" }
}
