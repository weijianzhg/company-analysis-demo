variable "alpha_vantage_mode" {
  description = "Use live Alpha Vantage data or explicitly labeled test fixtures"
  type        = string
  default     = "live"
  validation {
    condition     = contains(["live", "fixture"], var.alpha_vantage_mode)
    error_message = "alpha_vantage_mode must be live or fixture."
  }
}

resource "aws_secretsmanager_secret" "alpha_vantage" {
  count                   = local.is_agent ? 0 : 1
  name                    = "${local.name_prefix}/alpha-vantage-api-key"
  description             = "Alpha Vantage API key for the financial data MCP runtime"
  recovery_window_in_days = 7
}

resource "aws_iam_role_policy" "alpha_vantage_secret" {
  count = local.is_agent ? 0 : 1
  name  = "read-alpha-vantage-key"
  role  = aws_iam_role.agentcore_runtime.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = "secretsmanager:GetSecretValue"
      Resource = aws_secretsmanager_secret.alpha_vantage[0].arn
    }]
  })
}

output "alpha_vantage_secret_arn" {
  value       = one(aws_secretsmanager_secret.alpha_vantage[*].arn)
  description = "Populate this secret out of band; never put the key in Terraform variables"
}
