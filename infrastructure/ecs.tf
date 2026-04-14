# =============================================================================
# ECS — Cluster, FastAPI Fargate Service, Whisper GPU Service
# =============================================================================

# -----------------------------------------------------------------------------
# ECR Repository — Backend Docker Image
# -----------------------------------------------------------------------------

resource "aws_ecr_repository" "backend" {
  name                 = "aurion-backend-${var.environment}"
  image_tag_mutability = "MUTABLE"
  force_delete         = var.environment == "dev"

  image_scanning_configuration {
    scan_on_push = true
  }

  encryption_configuration {
    encryption_type = "KMS"
    kms_key         = aws_kms_key.main.arn
  }

  tags = {
    Name = "aurion-backend-${var.environment}"
  }
}

# -----------------------------------------------------------------------------
# ECS Cluster
# -----------------------------------------------------------------------------

resource "aws_ecs_cluster" "main" {
  name = "aurion-${var.environment}"

  setting {
    name  = "containerInsights"
    value = "enabled"
  }

  tags = {
    Name = "aurion-ecs-${var.environment}"
  }
}

# -----------------------------------------------------------------------------
# CloudWatch Log Groups
# -----------------------------------------------------------------------------

resource "aws_cloudwatch_log_group" "api" {
  name              = "/aurion/${var.environment}/api"
  retention_in_days = var.environment == "prod" ? 365 : 7

  tags = {
    Name    = "aurion-api-logs-${var.environment}"
    Service = "api"
  }
}

resource "aws_cloudwatch_log_group" "whisper" {
  name              = "/aurion/${var.environment}/whisper"
  retention_in_days = var.environment == "prod" ? 365 : 7

  tags = {
    Name    = "aurion-whisper-logs-${var.environment}"
    Service = "whisper"
  }
}

# =============================================================================
# FastAPI Fargate Service
# =============================================================================

# -----------------------------------------------------------------------------
# IAM — ECS Task Execution Role (pulls images, writes logs)
# -----------------------------------------------------------------------------

resource "aws_iam_role" "ecs_task_execution" {
  name = "aurion-ecs-exec-${var.environment}"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "ecs-tasks.amazonaws.com"
        }
      }
    ]
  })

  tags = {
    Name = "aurion-ecs-exec-${var.environment}"
  }
}

resource "aws_iam_role_policy_attachment" "ecs_task_execution" {
  role       = aws_iam_role.ecs_task_execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

# Allow execution role to read secrets for container env injection
resource "aws_iam_role_policy" "ecs_exec_secrets" {
  name = "aurion-ecs-exec-secrets-${var.environment}"
  role = aws_iam_role.ecs_task_execution.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "secretsmanager:GetSecretValue"
        ]
        Resource = [
          "arn:aws:secretsmanager:${var.region}:${data.aws_caller_identity.current.account_id}:secret:aurion/*"
        ]
      },
      {
        Effect = "Allow"
        Action = [
          "kms:Decrypt"
        ]
        Resource = [aws_kms_key.main.arn]
      }
    ]
  })
}

# -----------------------------------------------------------------------------
# IAM — FastAPI Task Role (application-level AWS access)
# -----------------------------------------------------------------------------

resource "aws_iam_role" "api_task" {
  name = "aurion-api-task-${var.environment}"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "ecs-tasks.amazonaws.com"
        }
      }
    ]
  })

  tags = {
    Name = "aurion-api-task-${var.environment}"
  }
}

resource "aws_iam_role_policy" "api_task_policy" {
  name = "aurion-api-task-policy-${var.environment}"
  role = aws_iam_role.api_task.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      # S3 — read/write audio, frames, eval buckets
      {
        Effect = "Allow"
        Action = [
          "s3:GetObject",
          "s3:PutObject",
          "s3:DeleteObject",
          "s3:ListBucket"
        ]
        Resource = [
          aws_s3_bucket.audio.arn,
          "${aws_s3_bucket.audio.arn}/*",
          aws_s3_bucket.frames.arn,
          "${aws_s3_bucket.frames.arn}/*",
          aws_s3_bucket.eval.arn,
          "${aws_s3_bucket.eval.arn}/*"
        ]
      },
      # DynamoDB — read/write audit log (append-only at application layer)
      {
        Effect = "Allow"
        Action = [
          "dynamodb:PutItem",
          "dynamodb:GetItem",
          "dynamodb:Query",
          "dynamodb:BatchWriteItem"
        ]
        Resource = [
          aws_dynamodb_table.audit_log.arn
        ]
      },
      # KMS — encrypt/decrypt for S3 and DynamoDB
      {
        Effect = "Allow"
        Action = [
          "kms:Encrypt",
          "kms:Decrypt",
          "kms:GenerateDataKey"
        ]
        Resource = [aws_kms_key.main.arn]
      },
      # AppConfig — read runtime configuration
      {
        Effect = "Allow"
        Action = [
          "appconfig:GetLatestConfiguration",
          "appconfig:StartConfigurationSession"
        ]
        Resource = ["*"]
      },
      # Secrets Manager — read AI provider API keys
      {
        Effect = "Allow"
        Action = [
          "secretsmanager:GetSecretValue"
        ]
        Resource = [
          "arn:aws:secretsmanager:${var.region}:${data.aws_caller_identity.current.account_id}:secret:aurion/*"
        ]
      },
      # Comprehend Medical — PHI detection on transcripts
      {
        Effect = "Allow"
        Action = [
          "comprehendmedical:DetectEntitiesV2",
          "comprehendmedical:DetectPHI"
        ]
        Resource = ["*"]
      },
      # Textract — screen capture OCR
      {
        Effect = "Allow"
        Action = [
          "textract:AnalyzeDocument",
          "textract:DetectDocumentText"
        ]
        Resource = ["*"]
      }
    ]
  })
}

# -----------------------------------------------------------------------------
# Security Groups
# -----------------------------------------------------------------------------

resource "aws_security_group" "alb" {
  name        = "aurion-alb-sg-${var.environment}"
  description = "Security group for Aurion ALB - allows inbound HTTP"
  vpc_id      = aws_vpc.main.id

  ingress {
    description = "HTTP from anywhere"
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  ingress {
    description = "HTTPS from anywhere"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    description = "All outbound"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name = "aurion-alb-sg-${var.environment}"
  }
}

resource "aws_security_group" "api" {
  name        = "aurion-api-sg-${var.environment}"
  description = "Security group for Aurion FastAPI ECS tasks"
  vpc_id      = aws_vpc.main.id

  ingress {
    description     = "Allow traffic from ALB on port 8000"
    from_port       = 8000
    to_port         = 8000
    protocol        = "tcp"
    security_groups = [aws_security_group.alb.id]
  }

  egress {
    description = "All outbound - needed for NAT, AWS APIs, AI providers"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name = "aurion-api-sg-${var.environment}"
  }
}

resource "aws_security_group" "whisper" {
  name        = "aurion-whisper-sg-${var.environment}"
  description = "Security group for Aurion Whisper GPU ECS tasks"
  vpc_id      = aws_vpc.main.id

  ingress {
    description     = "Allow traffic from API tasks on port 9000"
    from_port       = 9000
    to_port         = 9000
    protocol        = "tcp"
    security_groups = [aws_security_group.api.id]
  }

  egress {
    description = "All outbound"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name = "aurion-whisper-sg-${var.environment}"
  }
}

# -----------------------------------------------------------------------------
# ALB — Application Load Balancer for FastAPI
# -----------------------------------------------------------------------------

resource "aws_lb" "api" {
  name               = "aurion-api-${var.environment}"
  internal           = false
  load_balancer_type = "application"
  security_groups    = [aws_security_group.alb.id]
  subnets            = aws_subnet.public[*].id

  tags = {
    Name = "aurion-api-alb-${var.environment}"
  }
}

resource "aws_lb_target_group" "api" {
  name        = "aurion-api-tg-${var.environment}"
  port        = 8000
  protocol    = "HTTP"
  vpc_id      = aws_vpc.main.id
  target_type = "ip"

  health_check {
    enabled             = true
    path                = "/health"
    port                = "traffic-port"
    protocol            = "HTTP"
    healthy_threshold   = 3
    unhealthy_threshold = 3
    timeout             = 10
    interval            = 30
    matcher             = "200"
  }

  tags = {
    Name = "aurion-api-tg-${var.environment}"
  }
}

resource "aws_lb_listener" "api" {
  load_balancer_arn = aws_lb.api.arn
  port              = 80
  protocol          = "HTTP"

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.api.arn
  }

  tags = {
    Name = "aurion-api-listener-${var.environment}"
  }
}

# -----------------------------------------------------------------------------
# FastAPI Fargate Task Definition
# -----------------------------------------------------------------------------

resource "aws_ecs_task_definition" "api" {
  family                   = "aurion-api-${var.environment}"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = var.ecs_cpu
  memory                   = var.ecs_memory
  execution_role_arn       = aws_iam_role.ecs_task_execution.arn
  task_role_arn            = aws_iam_role.api_task.arn

  container_definitions = jsonencode([
    {
      name      = "aurion-api"
      image     = "${aws_ecr_repository.backend.repository_url}:latest"
      essential = true

      portMappings = [
        {
          containerPort = 8000
          protocol      = "tcp"
        }
      ]

      environment = [
        { name = "APP_ENV", value = var.environment },
        { name = "LOG_LEVEL", value = var.environment == "prod" ? "INFO" : "DEBUG" },
        { name = "AWS_DEFAULT_REGION", value = var.region },
        { name = "COGNITO_USER_POOL_ID", value = aws_cognito_user_pool.main.id },
        { name = "COGNITO_CLIENT_ID", value = aws_cognito_user_pool_client.main.id },
        { name = "DYNAMODB_AUDIT_TABLE", value = aws_dynamodb_table.audit_log.name },
        { name = "S3_AUDIO_BUCKET", value = aws_s3_bucket.audio.id },
        { name = "S3_FRAMES_BUCKET", value = aws_s3_bucket.frames.id },
        { name = "S3_EVAL_BUCKET", value = aws_s3_bucket.eval.id },
        { name = "APPCONFIG_APP_ID", value = aws_appconfig_application.main.id },
        { name = "APPCONFIG_ENV_ID", value = aws_appconfig_environment.main.environment_id },
        { name = "APPCONFIG_PROFILE_ID", value = aws_appconfig_configuration_profile.main.configuration_profile_id },
      ]

      secrets = [
        {
          name      = "DATABASE_URL"
          valueFrom = aws_db_instance.main.master_user_secret[0].secret_arn
        }
      ]

      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = aws_cloudwatch_log_group.api.name
          "awslogs-region"        = var.region
          "awslogs-stream-prefix" = "api"
        }
      }

      healthCheck = {
        command     = ["CMD-SHELL", "curl -f http://localhost:8000/health || exit 1"]
        interval    = 30
        timeout     = 10
        retries     = 3
        startPeriod = 60
      }
    }
  ])

  tags = {
    Name = "aurion-api-task-${var.environment}"
  }
}

# -----------------------------------------------------------------------------
# FastAPI Fargate Service
# -----------------------------------------------------------------------------

resource "aws_ecs_service" "api" {
  name            = "aurion-api-${var.environment}"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.api.arn
  desired_count   = var.environment == "prod" ? 2 : 1
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = aws_subnet.private[*].id
    security_groups  = [aws_security_group.api.id]
    assign_public_ip = false
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.api.arn
    container_name   = "aurion-api"
    container_port   = 8000
  }

  depends_on = [aws_lb_listener.api]

  tags = {
    Name = "aurion-api-service-${var.environment}"
  }
}

# -----------------------------------------------------------------------------
# FastAPI Auto-Scaling — 1 to 4 tasks
# -----------------------------------------------------------------------------

resource "aws_appautoscaling_target" "api" {
  max_capacity       = 4
  min_capacity       = 1
  resource_id        = "service/${aws_ecs_cluster.main.name}/${aws_ecs_service.api.name}"
  scalable_dimension = "ecs:service:DesiredCount"
  service_namespace  = "ecs"
}

resource "aws_appautoscaling_policy" "api_cpu" {
  name               = "aurion-api-cpu-scaling-${var.environment}"
  policy_type        = "TargetTrackingScaling"
  resource_id        = aws_appautoscaling_target.api.resource_id
  scalable_dimension = aws_appautoscaling_target.api.scalable_dimension
  service_namespace  = aws_appautoscaling_target.api.service_namespace

  target_tracking_scaling_policy_configuration {
    predefined_metric_specification {
      predefined_metric_type = "ECSServiceAverageCPUUtilization"
    }
    target_value       = 70.0
    scale_in_cooldown  = 60
    scale_out_cooldown = 60
  }
}

resource "aws_appautoscaling_policy" "api_memory" {
  name               = "aurion-api-memory-scaling-${var.environment}"
  policy_type        = "TargetTrackingScaling"
  resource_id        = aws_appautoscaling_target.api.resource_id
  scalable_dimension = aws_appautoscaling_target.api.scalable_dimension
  service_namespace  = aws_appautoscaling_target.api.service_namespace

  target_tracking_scaling_policy_configuration {
    predefined_metric_specification {
      predefined_metric_type = "ECSServiceAverageMemoryUtilization"
    }
    target_value       = 80.0
    scale_in_cooldown  = 60
    scale_out_cooldown = 60
  }
}

# =============================================================================
# Whisper GPU Service — EC2 Capacity Provider
# =============================================================================

# -----------------------------------------------------------------------------
# IAM — Whisper Task Role (read-only S3 access for audio)
# -----------------------------------------------------------------------------

resource "aws_iam_role" "whisper_task" {
  name = "aurion-whisper-task-${var.environment}"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "ecs-tasks.amazonaws.com"
        }
      }
    ]
  })

  tags = {
    Name = "aurion-whisper-task-${var.environment}"
  }
}

resource "aws_iam_role_policy" "whisper_task_policy" {
  name = "aurion-whisper-task-policy-${var.environment}"
  role = aws_iam_role.whisper_task.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      # S3 — read audio bucket for direct Whisper reads
      {
        Effect = "Allow"
        Action = [
          "s3:GetObject",
          "s3:ListBucket"
        ]
        Resource = [
          aws_s3_bucket.audio.arn,
          "${aws_s3_bucket.audio.arn}/*"
        ]
      },
      # KMS — decrypt audio objects
      {
        Effect = "Allow"
        Action = [
          "kms:Decrypt"
        ]
        Resource = [aws_kms_key.main.arn]
      }
    ]
  })
}

# -----------------------------------------------------------------------------
# EC2 Launch Template — GPU-optimized AMI
# -----------------------------------------------------------------------------

data "aws_ssm_parameter" "ecs_gpu_ami" {
  name = "/aws/service/ecs/optimized-ami/amazon-linux-2/gpu/recommended/image_id"
}

resource "aws_iam_role" "whisper_ec2" {
  name = "aurion-whisper-ec2-${var.environment}"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "ec2.amazonaws.com"
        }
      }
    ]
  })

  tags = {
    Name = "aurion-whisper-ec2-${var.environment}"
  }
}

resource "aws_iam_role_policy_attachment" "whisper_ec2_ecs" {
  role       = aws_iam_role.whisper_ec2.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonEC2ContainerServiceforEC2Role"
}

resource "aws_iam_role_policy_attachment" "whisper_ec2_ssm" {
  role       = aws_iam_role.whisper_ec2.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

resource "aws_iam_instance_profile" "whisper" {
  name = "aurion-whisper-profile-${var.environment}"
  role = aws_iam_role.whisper_ec2.name
}

resource "aws_launch_template" "whisper" {
  name_prefix   = "aurion-whisper-${var.environment}-"
  image_id      = data.aws_ssm_parameter.ecs_gpu_ami.value
  instance_type = var.whisper_instance_type

  iam_instance_profile {
    arn = aws_iam_instance_profile.whisper.arn
  }

  # Register instance with ECS cluster on boot
  user_data = base64encode(<<-EOF
    #!/bin/bash
    echo "ECS_CLUSTER=${aws_ecs_cluster.main.name}" >> /etc/ecs/ecs.config
    echo "ECS_ENABLE_GPU_SUPPORT=true" >> /etc/ecs/ecs.config
  EOF
  )

  network_interfaces {
    associate_public_ip_address = false
    security_groups             = [aws_security_group.whisper.id]
  }

  tag_specifications {
    resource_type = "instance"
    tags = {
      Name = "aurion-whisper-${var.environment}"
    }
  }

  tags = {
    Name = "aurion-whisper-lt-${var.environment}"
  }
}

# -----------------------------------------------------------------------------
# Auto Scaling Group — Whisper GPU instances
# -----------------------------------------------------------------------------

resource "aws_autoscaling_group" "whisper" {
  name                = "aurion-whisper-asg-${var.environment}"
  min_size            = var.environment == "prod" ? 1 : 0
  max_size            = var.environment == "prod" ? 2 : 1
  desired_capacity    = var.environment == "prod" ? 1 : 0
  vpc_zone_identifier = aws_subnet.private[*].id

  launch_template {
    id      = aws_launch_template.whisper.id
    version = "$Latest"
  }

  tag {
    key                 = "Name"
    value               = "aurion-whisper-${var.environment}"
    propagate_at_launch = true
  }

  tag {
    key                 = "AmazonECSManaged"
    value               = "true"
    propagate_at_launch = true
  }
}

# -----------------------------------------------------------------------------
# ECS Capacity Provider — Whisper ASG
# -----------------------------------------------------------------------------

resource "aws_ecs_capacity_provider" "whisper" {
  name = "aurion-whisper-cp-${var.environment}"

  auto_scaling_group_provider {
    auto_scaling_group_arn         = aws_autoscaling_group.whisper.arn
    managed_termination_protection = var.environment == "prod" ? "ENABLED" : "DISABLED"

    managed_scaling {
      status                    = "ENABLED"
      target_capacity           = 100
      minimum_scaling_step_size = 1
      maximum_scaling_step_size = 1
    }
  }

  tags = {
    Name = "aurion-whisper-cp-${var.environment}"
  }
}

resource "aws_ecs_cluster_capacity_providers" "main" {
  cluster_name       = aws_ecs_cluster.main.name
  capacity_providers = [aws_ecs_capacity_provider.whisper.name, "FARGATE"]

  default_capacity_provider_strategy {
    capacity_provider = "FARGATE"
    weight            = 1
  }
}

# -----------------------------------------------------------------------------
# Whisper EC2 Task Definition
# -----------------------------------------------------------------------------

resource "aws_ecs_task_definition" "whisper" {
  family                   = "aurion-whisper-${var.environment}"
  requires_compatibilities = ["EC2"]
  network_mode             = "awsvpc"
  execution_role_arn       = aws_iam_role.ecs_task_execution.arn
  task_role_arn            = aws_iam_role.whisper_task.arn

  container_definitions = jsonencode([
    {
      name      = "aurion-whisper"
      image     = "onerahmet/openai-whisper-asr-webservice:latest"
      essential = true
      memory    = 14336 # ~14GB — leave headroom on g4dn.xlarge (16GB)

      resourceRequirements = [
        {
          type  = "GPU"
          value = "1"
        }
      ]

      portMappings = [
        {
          containerPort = 9000
          protocol      = "tcp"
        }
      ]

      environment = [
        { name = "ASR_MODEL", value = "large-v3" },
        { name = "ASR_ENGINE", value = "openai_whisper" }
      ]

      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = aws_cloudwatch_log_group.whisper.name
          "awslogs-region"        = var.region
          "awslogs-stream-prefix" = "whisper"
        }
      }

      healthCheck = {
        command     = ["CMD-SHELL", "curl -f http://localhost:9000/health || exit 1"]
        interval    = 30
        timeout     = 10
        retries     = 3
        startPeriod = 120
      }
    }
  ])

  tags = {
    Name = "aurion-whisper-task-${var.environment}"
  }
}

# -----------------------------------------------------------------------------
# Whisper ECS Service
# -----------------------------------------------------------------------------

resource "aws_ecs_service" "whisper" {
  name            = "aurion-whisper-${var.environment}"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.whisper.arn
  desired_count   = var.environment == "prod" ? 1 : 0

  capacity_provider_strategy {
    capacity_provider = aws_ecs_capacity_provider.whisper.name
    weight            = 1
  }

  network_configuration {
    subnets          = aws_subnet.private[*].id
    security_groups  = [aws_security_group.whisper.id]
    assign_public_ip = false
  }

  depends_on = [aws_ecs_cluster_capacity_providers.main]

  tags = {
    Name = "aurion-whisper-service-${var.environment}"
  }
}
