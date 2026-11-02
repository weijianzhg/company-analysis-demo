"""The agent's MCP endpoints. Add another entry here to connect another service."""

from dataclasses import dataclass
import os

from cloud_mcp import mcp_transport


@dataclass(frozen=True)
class MCPConnection:
    name: str
    url: str
    runtime_arn: str

    def transport(self):
        return mcp_transport(self.url, self.runtime_arn)


def configured_connections():
    # Keep the original names working for existing deployments.
    connections = [MCPConnection(
        "financials", os.environ.get("MCP_URL", "http://127.0.0.1:8000/mcp"),
        os.environ.get("MCP_RUNTIME_ARN", ""),
    )]
    knowledge = MCPConnection(
        "internal-knowledge", os.environ.get("INTERNAL_KNOWLEDGE_MCP_URL", ""),
        os.environ.get("INTERNAL_KNOWLEDGE_MCP_RUNTIME_ARN", ""),
    )
    if knowledge.url or knowledge.runtime_arn:
        connections.append(knowledge)
    return connections


def discover_tools(client):
    """Collect all discovery pages, including servers with more than one page."""
    tools = []
    page = client.list_tools_sync()
    while True:
        tools.extend(page)
        cursor = getattr(page, "pagination_token", None)
        if not cursor:
            return tools
        page = client.list_tools_sync(pagination_token=cursor)
