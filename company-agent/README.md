# Company performance agent

A small Strands analyst served by Bedrock AgentCore. It retrieves financial data through the sibling Alpha Vantage MCP service and explains the returned figures, periods and limitations.

Start with the [AWS deployment guide](../README.md) or [local setup](../docs/local.md).

- [agents/analyst.py](agents/analyst.py) contains the model, prompt and tool loop.
- [agents/main.py](agents/main.py) serves `/invocations` on port 8080 with SSE heartbeats.
- [agents/cloud_mcp.py](agents/cloud_mcp.py) selects local HTTP or IAM-signed AgentCore MCP.
- [infra](infra/) deploys the runtime, scoped IAM permissions and model inference profile.

Each question starts a fresh analysis. The agent exposes no workspace or file tools, and has no Alpha Vantage API key. It reports the MCP tools used and withholds answers that did not call a data tool.

The blueprint's generic invocation/build helpers and optional infrastructure settings are retained. Use `scripts/invoke.py --prompt` for this analyst; the generic CLI's file-management actions are not supported by this runtime. This package contains only the agent implementation; the MCP implementation lives in `../alpha-vantage-mcp`.

Derived from [bedrock-agent-blueprint](https://github.com/weijianzhg/bedrock-agent-blueprint/tree/c65654ff433f8e9cbc8b916a3a579497a93537dc), under the MIT license.
