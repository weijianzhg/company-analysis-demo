variable "aws_region" {
  type    = string
  default = "eu-west-1"
}

variable "container_tag" {
  type    = string
  default = "latest"
}

variable "knowledge_bucket" {
  description = "Existing S3 bucket containing UTF-8 Markdown; this stack does not create or modify it"
  type        = string
  validation {
    condition     = can(regex("^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$", var.knowledge_bucket))
    error_message = "knowledge_bucket must be an S3 bucket name, not an ARN or URL."
  }
}

variable "knowledge_prefix" {
  description = "Optional folder root within the bucket; tool paths are relative to this folder"
  type        = string
  default     = ""
  validation {
    condition = var.knowledge_prefix == "" || (
      !can(regex("[?*\\\\:]|^/|//|(^|/)\\.\\.?(/|$)", var.knowledge_prefix)) &&
      !can(regex("[[:cntrl:]]", var.knowledge_prefix))
    )
    error_message = "knowledge_prefix must be a relative folder path without wildcards or dot segments."
  }
}

variable "knowledge_kms_key_arn" {
  description = "Optional customer-managed KMS key for this bucket; its key policy must also allow the runtime role"
  type        = string
  default     = ""
}
