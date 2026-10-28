variable "mcp_runtime_arn" {
  description = "The Alpha Vantage MCP runtime this agent may invoke"
  type        = string
  default     = ""
}

resource "aws_iam_role_policy" "mcp_invoke" {
  count = local.is_agent && var.mcp_runtime_arn != "" ? 1 : 0
  name  = "invoke-alpha-vantage-mcp"
  role  = aws_iam_role.agentcore_runtime.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = "bedrock-agentcore:InvokeAgentRuntime"
      Resource = [var.mcp_runtime_arn, "${var.mcp_runtime_arn}/runtime-endpoint/DEFAULT"]
    }]
  })
}
