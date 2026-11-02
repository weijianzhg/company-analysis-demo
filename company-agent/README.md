# Company performance agent

A small Strands analyst served by Bedrock AgentCore. It retrieves financial data through Alpha Vantage MCP and internal Markdown research through Internal Knowledge MCP, then explains the returned evidence and limitations.

Start with the [AWS deployment guide](../README.md) or [local setup](../docs/local.md).

- [agents/analyst.py](agents/analyst.py) contains the model, prompt and tool loop.
- [agents/main.py](agents/main.py) serves `/invocations` on port 8080 with SSE heartbeats.
- [agents/mcp_connections.py](agents/mcp_connections.py) lists the configured services and discovers their tools.
- [agents/cloud_mcp.py](agents/cloud_mcp.py) selects local HTTP or IAM-signed AgentCore MCP.
- [infra](infra/) deploys the runtime, scoped IAM permissions and model inference profile.

Each question starts a fresh analysis. The agent exposes no workspace or file tools, and has no Alpha Vantage API key or direct S3 access. It reports the MCP tools used and withholds answers that did not call a data tool.

The blueprint's generic invocation/build helpers and optional infrastructure settings are retained. Use `scripts/invoke.py --prompt` for this analyst; the generic CLI's file-management actions are not supported by this runtime. This package contains only the agent implementation; the MCP implementations live in `../alpha-vantage-mcp` and `../internal-knowledge-mcp`.

Derived from [bedrock-agent-blueprint](https://github.com/weijianzhg/bedrock-agent-blueprint/tree/c65654ff433f8e9cbc8b916a3a579497a93537dc), under the MIT license.

## Connections

| Service | Local URL | Deployed runtime ARN |
| --- | --- | --- |
| Financials | `MCP_URL` (defaults to localhost:8000/mcp) | `MCP_RUNTIME_ARN` |
| Internal knowledge | `INTERNAL_KNOWLEDGE_MCP_URL` | `INTERNAL_KNOWLEDGE_MCP_RUNTIME_ARN` |

A runtime ARN takes precedence over the URL for that service. Internal knowledge is
optional: leave both its settings unset for the original financial-only demo.
If a configured service cannot connect, the request fails with an error.

`analyst.py` opens each configured client with `ExitStack`, collects every page of
tools, rejects duplicate tool names and keeps all sessions alive until analysis
finishes. The prompt selects financial, internal or both sources based on the question.
To add another MCP, add its endpoint in `configured_connections`, add its deployment
ARN to `infra/mcp.tf`, and describe when to use its tools in the prompt.

## Live tool progress

The `/invocations` SSE stream sends a heartbeat, tool progress events as tools run,
and finally the usual `result`/`tools_used` response. A tool event looks like:

```json
{"type":"tool_call","id":"call-123","server":"internal-knowledge","tool":"search_internal_knowledge","status":"started"}
```

The same `id` is sent again with `status` set to `succeeded` or `failed`. A UI can
show a spinner at `started`, then update that row when the call finishes. Every
call gets its own ID, including repeated calls to the same tool. Events contain
metadata only: no tool arguments, raw results, document contents or exception bodies.
`succeeded` means the tool executed successfully; any partial data is still disclosed
in the final answer.
If the request ends with an error or the stream disconnects, mark any remaining
in-progress rows as interrupted; do not assume they succeeded.

Both `scripts/ask.py` and `scripts/invoke.py` show progress on stderr while keeping
the final answer on stdout. Python integrations can pass
`on_tool_event=callback` to `invoke_agent` to update their UI as each event arrives.
The [tool_progress.py](agents/tool_progress.py) hook translates actual Strands
execution events, so these statuses are not guessed by the model.
