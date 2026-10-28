terraform {
  required_version = ">= 1.5.0"
  required_providers {
    aws = { source = "hashicorp/aws", version = ">= 6.46.0, < 7.0.0" }
  }
}
variable "aws_region" {
  type    = string
  default = "eu-west-1"
}
provider "aws" {
  region = var.aws_region
  default_tags { tags = { Project = "company-analysis-demo", ManagedBy = "terraform" } }
}
data "aws_caller_identity" "current" {}
locals {
  projects = { mcp = "alpha-vantage-mcp-dev", agent = "company-agent-dev" }
}
data "aws_ecr_repository" "images" {
  for_each = local.projects
  name     = each.value
}
resource "aws_s3_bucket" "source" {
  bucket        = "company-analysis-build-${data.aws_caller_identity.current.account_id}-${var.aws_region}"
  force_destroy = true
}
resource "aws_s3_bucket_public_access_block" "source" {
  bucket                  = aws_s3_bucket.source.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}
resource "aws_s3_bucket_server_side_encryption_configuration" "source" {
  bucket = aws_s3_bucket.source.id
  rule {
    apply_server_side_encryption_by_default { sse_algorithm = "AES256" }
  }
}
resource "aws_s3_bucket_lifecycle_configuration" "source" {
  bucket = aws_s3_bucket.source.id
  rule {
    id     = "expire-build-sources"
    status = "Enabled"
    filter { prefix = "sources/" }
    expiration { days = 7 }
  }
}
resource "aws_cloudwatch_log_group" "build" {
  name              = "/aws/codebuild/company-analysis-demo"
  retention_in_days = 7
}
resource "aws_iam_role" "build" {
  name = "company-analysis-demo-build"
  assume_role_policy = jsonencode({
    Version   = "2012-10-17"
    Statement = [{ Effect = "Allow", Action = "sts:AssumeRole", Principal = { Service = "codebuild.amazonaws.com" } }]
  })
}
resource "aws_iam_role_policy" "build" {
  role = aws_iam_role.build.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      { Effect = "Allow", Action = ["s3:GetObject", "s3:GetObjectVersion"], Resource = "${aws_s3_bucket.source.arn}/sources/*" },
      { Effect = "Allow", Action = ["s3:GetBucketLocation"], Resource = aws_s3_bucket.source.arn },
      { Effect = "Allow", Action = ["logs:CreateLogStream", "logs:PutLogEvents"], Resource = "${aws_cloudwatch_log_group.build.arn}:*" },
      { Effect = "Allow", Action = "ecr:GetAuthorizationToken", Resource = "*" },
      { Effect = "Allow", Action = ["ecr:BatchCheckLayerAvailability", "ecr:InitiateLayerUpload", "ecr:UploadLayerPart", "ecr:CompleteLayerUpload", "ecr:PutImage", "ecr:BatchGetImage", "ecr:GetDownloadUrlForLayer"], Resource = [for repo in data.aws_ecr_repository.images : repo.arn] }
    ]
  })
}
resource "aws_codebuild_project" "image" {
  for_each       = local.projects
  name           = "company-analysis-${each.key}-build"
  service_role   = aws_iam_role.build.arn
  build_timeout  = 15
  queued_timeout = 15
  artifacts { type = "NO_ARTIFACTS" }
  environment {
    compute_type    = "BUILD_GENERAL1_SMALL"
    image           = "aws/codebuild/amazonlinux-aarch64-standard:4.0"
    type            = "ARM_CONTAINER"
    privileged_mode = true
    environment_variable {
      name  = "REPOSITORY_URL"
      value = data.aws_ecr_repository.images[each.key].repository_url
    }
    environment_variable {
      name  = "IMAGE_TAG"
      value = "unset"
    }
  }
  source {
    type     = "S3"
    location = "${aws_s3_bucket.source.id}/sources/${each.key}.zip"
    buildspec = jsonencode({
      version = "0.2"
      phases = {
        pre_build = { commands = [
          "test \"$IMAGE_TAG\" != unset",
          "export IMAGE_URI=\"$REPOSITORY_URL:$IMAGE_TAG\"",
          "aws ecr get-login-password --region ${var.aws_region} | docker login --username AWS --password-stdin \"$${REPOSITORY_URL%%/*}\""
        ] }
        build      = { commands = ["docker build --platform linux/arm64 -t \"$IMAGE_URI\" ."] }
        post_build = { commands = ["test \"$CODEBUILD_BUILD_SUCCEEDING\" = 1", "docker push \"$IMAGE_URI\""] }
      }
    })
  }
  logs_config {
    cloudwatch_logs {
      group_name  = aws_cloudwatch_log_group.build.name
      stream_name = each.key
    }
  }
  depends_on = [aws_iam_role_policy.build]
}
output "bucket" { value = aws_s3_bucket.source.id }
output "projects" { value = { for key, project in aws_codebuild_project.image : key => project.name } }
output "region" { value = var.aws_region }
