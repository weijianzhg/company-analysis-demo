#!/usr/bin/env bash
set -euo pipefail
DEMO_DIR="$(cd "$(dirname "$0")" && pwd)"
uv sync --project "$DEMO_DIR/alpha-vantage-mcp/mcp_server" --dev --frozen
uv sync --project "$DEMO_DIR/company-agent/agents" --dev --frozen
(
  cd "$DEMO_DIR/alpha-vantage-mcp"
  uv run --project mcp_server --frozen pytest tests/mcp_server -q
)
(
  cd "$DEMO_DIR/company-agent"
  EVIDENCE_DIR="$DEMO_DIR/evidence" uv run --project agents --frozen pytest tests -q
)
