# Cloud deployment helpers

Start with the [quick deploy guide](../README.md#quick-deploy).

Detailed cloud instructions are consolidated in the [FAQ](../docs/faq.md), including [authentication](../docs/faq.md#how-are-the-endpoints-authorized), [API key rotation](../docs/faq.md#where-is-the-api-key-stored-and-how-do-i-rotate-it), [troubleshooting](../docs/faq.md#what-should-i-check-when-something-fails), and [cleanup](../docs/faq.md#how-do-i-remove-the-deployment).

- `build/`: Terraform for the image build resources.
- `build_images.py`: build all three ARM64 service images and check their status.
- `set_api_key.py`: store the Alpha Vantage key in Secrets Manager.
- `test_end_to_end.py`: verify the deployed agent and financial MCP; add `--knowledge-path companies/IBM/research.md` to include the internal MCP.

To test an existing deployment without local Terraform state for every service, pass
`--agent-runtime-arn`, `--financial-mcp-runtime-arn` or `--knowledge-mcp-runtime-arn`
to `test_end_to_end.py`. Omitted ARNs are read from the corresponding Terraform root.

Pass `--require-tool-events` to verify that every tool call emits live start and
success events, without exposing tool arguments or results in the progress stream.
