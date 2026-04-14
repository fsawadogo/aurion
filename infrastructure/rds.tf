# =============================================================================
# RDS PostgreSQL — Aurion Session Metadata, Notes, Pilot Metrics
# =============================================================================

# -----------------------------------------------------------------------------
# Security Group — Only accessible from API tasks
# -----------------------------------------------------------------------------

resource "aws_security_group" "db" {
  name        = "aurion-db-sg-${var.environment}"
  description = "Security group for Aurion RDS - allows PostgreSQL from API tasks only"
  vpc_id      = aws_vpc.main.id

  ingress {
    description     = "PostgreSQL from FastAPI ECS tasks"
    from_port       = 5432
    to_port         = 5432
    protocol        = "tcp"
    security_groups = [aws_security_group.api.id]
  }

  # No egress — database does not need outbound internet access
  egress {
    description = "No outbound"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = []
  }

  tags = {
    Name = "aurion-db-sg-${var.environment}"
  }
}

# -----------------------------------------------------------------------------
# Subnet Group — Isolated subnets (no internet access)
# -----------------------------------------------------------------------------

resource "aws_db_subnet_group" "main" {
  name       = "aurion-db-subnet-${var.environment}"
  subnet_ids = aws_subnet.isolated[*].id

  tags = {
    Name = "aurion-db-subnet-${var.environment}"
  }
}

# -----------------------------------------------------------------------------
# RDS Instance
# -----------------------------------------------------------------------------

resource "aws_db_instance" "main" {
  identifier = "aurion-db-${var.environment}"

  # Engine
  engine         = "postgres"
  engine_version = "15"

  # Sizing
  instance_class        = var.db_instance_class
  allocated_storage     = 20
  max_allocated_storage = var.environment == "prod" ? 100 : 50

  # Database
  db_name                     = "aurion"
  username                    = "aurion"
  manage_master_user_password = true # Auto-generates credentials in Secrets Manager

  # Networking
  db_subnet_group_name   = aws_db_subnet_group.main.name
  vpc_security_group_ids = [aws_security_group.db.id]
  publicly_accessible    = false

  # Encryption — KMS customer-managed key
  storage_encrypted = true
  kms_key_id        = aws_kms_key.main.arn

  # High Availability
  multi_az = var.multi_az

  # Backup
  backup_retention_period = var.environment == "prod" ? 30 : 7
  backup_window           = "03:00-04:00"
  maintenance_window      = "sun:04:00-sun:05:00"

  # Protection
  deletion_protection       = var.environment == "prod"
  skip_final_snapshot       = var.environment == "dev"
  final_snapshot_identifier = var.environment == "prod" ? "aurion-db-final-${var.environment}" : null

  # Performance Insights (free tier for db.t3.medium)
  performance_insights_enabled = true

  tags = {
    Name = "aurion-db-${var.environment}"
  }
}
