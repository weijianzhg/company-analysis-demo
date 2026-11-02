terraform {
  required_version = ">= 1.7.0"
  required_providers {
    aws = { source = "hashicorp/aws", version = ">= 6.46.0, < 7.0.0" }
  }
}

provider "aws" {
  region = var.aws_region
  default_tags { tags = { Project = "company-analysis-demo", ManagedBy = "terraform" } }
}

data "aws_caller_identity" "current" {}
data "aws_partition" "current" {}

locals {
  prefix     = var.knowledge_prefix == "" ? "" : "${trimsuffix(var.knowledge_prefix, "/")}/"
  bucket_arn = "arn:${data.aws_partition.current.partition}:s3:::${var.knowledge_bucket}"
}

resource "aws_ecr_repository" "agent" {
  name                 = "internal-knowledge-mcp-dev"
  image_tag_mutability = "MUTABLE"
  force_delete         = true # This fixed-name stack is a development demo.
  image_scanning_configuration { scan_on_push = true }
}

resource "aws_ecr_lifecycle_policy" "agent" {
  repository = aws_ecr_repository.agent.name
  policy = jsonencode({ rules = [{
    rulePriority = 1
    description  = "Expire untagged images after 10 days"
    selection    = { tagStatus = "untagged", countType = "sinceImagePushed", countUnit = "days", countNumber = 10 }
    action       = { type = "expire" }
  }] })
}

resource "aws_iam_role" "runtime" {
  name = "internal-knowledge-mcp-dev-runtime"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow", Action = "sts:AssumeRole",
      Principal = { Service = "bedrock-agentcore.amazonaws.com" }
    }]
  })
}

resource "aws_iam_role_policy" "runtime" {
  role = aws_iam_role.runtime.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = concat([
      { Effect = "Allow", Action = "ecr:GetAuthorizationToken", Resource = "*" },
      { Effect = "Allow", Action = ["ecr:BatchGetImage", "ecr:GetDownloadUrlForLayer"], Resource = aws_ecr_repository.agent.arn },
      {
        Effect   = "Allow"
        Action   = ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"]
        Resource = "arn:${data.aws_partition.current.partition}:logs:${var.aws_region}:${data.aws_caller_identity.current.account_id}:log-group:/aws/bedrock-agentcore/*"
      },
      {
        Sid       = "ListKnowledge", Effect = "Allow", Action = "s3:ListBucket", Resource = local.bucket_arn
        Condition = { StringLike = { "s3:prefix" = ["${local.prefix}*"] } }
      },
      {
        Sid      = "ReadKnowledge", Effect = "Allow", Action = "s3:GetObject"
        Resource = "${local.bucket_arn}/${local.prefix}*"
      }
      ], var.knowledge_kms_key_arn == "" ? [] : [{
        Effect    = "Allow", Action = "kms:Decrypt", Resource = var.knowledge_kms_key_arn
        Condition = { StringEquals = { "kms:ViaService" = "s3.${var.aws_region}.${data.aws_partition.current.dns_suffix}" } }
    }])
  })
}

resource "aws_bedrockagentcore_agent_runtime" "this" {
  agent_runtime_name = "internal_knowledge_mcp"
  description        = "Read-only company Markdown knowledge from S3"
  role_arn           = aws_iam_role.runtime.arn
  agent_runtime_artifact {
    container_configuration {
      container_uri = "${aws_ecr_repository.agent.repository_url}:${var.container_tag}"
    }
  }
  network_configuration { network_mode = "PUBLIC" }
  protocol_configuration { server_protocol = "MCP" }
  environment_variables = {
    KNOWLEDGE_BUCKET = var.knowledge_bucket
    KNOWLEDGE_PREFIX = local.prefix
    AWS_REGION       = var.aws_region
  }
  depends_on = [aws_iam_role_policy.runtime]
}

output "ecr_repository_url" { value = aws_ecr_repository.agent.repository_url }
output "agent_runtime_arn" { value = aws_bedrockagentcore_agent_runtime.this.agent_runtime_arn }
output "role_arn" { value = aws_iam_role.runtime.arn }
