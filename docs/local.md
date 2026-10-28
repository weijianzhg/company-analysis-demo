# Run both services locally

Run `./test-local.sh` from the repository root for the automated test. It uses a scripted model and synthetic data and does not need credentials. For an interactive demo with a real language model, follow the steps below.

## 1. Set up the two environments

From the repository root:

```bash
uv sync --project alpha-vantage-mcp/mcp_server --dev --frozen
uv sync --project company-agent/agents --dev --frozen
cp alpha-vantage-mcp/.env.example alpha-vantage-mcp/.env
cp company-agent/.env.example company-agent/.env
```

Set `ALPHA_VANTAGE_MODE=fixture` in `alpha-vantage-mcp/.env` for synthetic IBM data. To use live data, set `ALPHA_VANTAGE_MODE=live` and your own `ALPHA_VANTAGE_API_KEY`. Local dotenv files are ignored by Git and are not uploaded to AWS builds.

The server and agent use separate locked environments: the MCP server uses SDK 2, while the Strands MCP client uses SDK 1.

## 2. Choose a model

For **Bedrock**, edit `company-agent/.env`:

```dotenv
MCP_URL=http://127.0.0.1:8000/mcp
MODEL_PROVIDER=bedrock
MODEL_ID=eu.anthropic.claude-sonnet-4-6
AWS_PROFILE=your-profile
AWS_REGION=eu-west-1
```

Authenticate your profile and verify model access as described in the [main guide](../README.md). Only model inference runs on AWS; these instructions run both services locally.

For a **local model**, use a tool-capable [llama.cpp](https://github.com/ggml-org/llama.cpp) server. The experiment used Qwen3.5-4B Q4_K_M:

```bash
llama-server -hf unsloth/Qwen3.5-4B-GGUF:Q4_K_M --no-mmproj \
  --host 127.0.0.1 --port 8081 --ctx-size 16384 --parallel 1 \
  --n-gpu-layers 99 --reasoning off
```

The first launch downloads the model; adjust GPU settings for your machine. Set `MODEL_PROVIDER=llamacpp`, `LLAMA_CPP_URL=http://127.0.0.1:8081`, and `MODEL_ID=default` in the agent's `.env`. This small model was used for a demonstration, not a quality benchmark.

## 3. Start MCP and the agent

In one terminal, from the repository root:

```bash
cd alpha-vantage-mcp
uv run --project mcp_server --env-file .env --frozen python mcp_server/server.py
```

In a second terminal, from the repository root:

```bash
cd company-agent
uv run --project agents --env-file .env --frozen python agents/main.py
```

Both services bind to localhost. Stop them with Ctrl+C.

## 4. Ask a question

In a third terminal, from the repository root:

```bash
uv run --project company-agent/agents --frozen python company-agent/scripts/ask.py \
  "Analyze IBM's P&L, P/E and cash flow."

uv run --project company-agent/agents --frozen python company-agent/scripts/probe_mcp.py --list-tools
```

The local endpoints are `http://127.0.0.1:8080/invocations` and `http://127.0.0.1:8000/mcp`. The agent returns SSE heartbeats followed by a result or error. The result includes the MCP tool names used. Each question starts a new analysis; include the ticker in each question. Fixture mode supports IBM only and labels every answer as synthetic.
