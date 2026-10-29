# Cloud deployment helpers

Start with the [quick deploy guide](../README.md#quick-deploy).

Detailed cloud instructions are consolidated in the [FAQ](../docs/faq.md), including [authentication](../docs/faq.md#how-are-the-endpoints-authorized), [API key rotation](../docs/faq.md#where-is-the-api-key-stored-and-how-do-i-rotate-it), [troubleshooting](../docs/faq.md#what-should-i-check-when-something-fails), and [cleanup](../docs/faq.md#how-do-i-remove-the-deployment).

- `build/`: Terraform for the image build resources.
- `build_images.py`: build both ARM64 images and check their status.
- `set_api_key.py`: store the Alpha Vantage key in Secrets Manager.
- `test_end_to_end.py`: verify the deployed agent and MCP.
