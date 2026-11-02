mock_provider "aws" {
  mock_resource "aws_iam_role" {
    defaults = { arn = "arn:aws:iam::123456789012:role/knowledge" }
  }
  mock_data "aws_caller_identity" {
    defaults = { account_id = "123456789012" }
  }
  mock_data "aws_partition" {
    defaults = { partition = "aws", dns_suffix = "amazonaws.com" }
  }
}

variables {
  knowledge_bucket = "internal-notes"
  knowledge_prefix = "knowledge/"
}

run "read_only_scoped_mcp" {
  command = apply
  assert {
    condition     = one(aws_bedrockagentcore_agent_runtime.this.protocol_configuration[*].server_protocol) == "MCP"
    error_message = "Knowledge must run as an MCP service."
  }
  assert {
    condition     = aws_bedrockagentcore_agent_runtime.this.environment_variables["KNOWLEDGE_PREFIX"] == "knowledge/"
    error_message = "The runtime must use the same prefix as IAM."
  }
  assert {
    condition     = length(aws_bedrockagentcore_agent_runtime.this.filesystem_configuration) == 0
    error_message = "Knowledge is stored in S3, not agent session storage."
  }
  assert {
    condition = alltrue([
      for s in jsondecode(aws_iam_role_policy.runtime.policy).Statement :
      s.Resource == "arn:aws:s3:::internal-notes/knowledge/*" && s.Action == "s3:GetObject"
      if try(s.Sid, "") == "ReadKnowledge"
    ])
    error_message = "Object access must be read-only and restricted to the configured prefix."
  }
  assert {
    condition = one([
      for s in jsondecode(aws_iam_role_policy.runtime.policy).Statement : s.Condition.StringLike["s3:prefix"]
      if try(s.Sid, "") == "ListKnowledge"
    ]) == ["knowledge/*"]
    error_message = "Listing must be restricted to the same prefix."
  }
}

run "normalize_folder_prefix" {
  command = plan
  variables { knowledge_prefix = "knowledge" }
  assert {
    condition     = local.prefix == "knowledge/"
    error_message = "Prefix must end at a folder boundary."
  }
}

run "root_prefix" {
  command = plan
  variables { knowledge_prefix = "" }
  assert {
    condition     = local.prefix == ""
    error_message = "Empty prefix must allow the bucket root."
  }
}

run "reject_wildcard_prefix" {
  command = plan
  variables { knowledge_prefix = "knowledge/*" }
  expect_failures = [var.knowledge_prefix]
}

run "reject_parent_prefix" {
  command = plan
  variables { knowledge_prefix = "knowledge/../private" }
  expect_failures = [var.knowledge_prefix]
}
