variable "mcp_runtime_arn" {
  description = "Alpha Vantage MCP runtime ARN (retained for existing deployments)"
  type        = string
  default     = ""
}

variable "internal_knowledge_mcp_runtime_arn" {
  description = "Optional internal knowledge MCP runtime ARN"
  type        = string
  default     = ""
}

locals {
  mcp_runtimes = {
    MCP_RUNTIME_ARN                    = var.mcp_runtime_arn
    INTERNAL_KNOWLEDGE_MCP_RUNTIME_ARN = var.internal_knowledge_mcp_runtime_arn
  }
  mcp_environment = { for name, arn in local.mcp_runtimes : name => arn if arn != "" }
}

resource "aws_iam_role_policy" "mcp_invoke" {
  count = local.is_agent && length(local.mcp_environment) > 0 ? 1 : 0
  name  = "invoke-company-mcps"
  role  = aws_iam_role.agentcore_runtime.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = "bedrock-agentcore:InvokeAgentRuntime"
      Resource = flatten([
        for arn in values(local.mcp_environment) : [arn, "${arn}/runtime-endpoint/DEFAULT"]
      ])
    }]
  })
}
