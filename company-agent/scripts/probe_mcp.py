#!/usr/bin/env python3
"""Check either MCP connection without invoking a language model."""

import argparse
import json
from pathlib import Path
import sys

from strands.tools.mcp import MCPClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'agents'))
from cloud_mcp import mcp_transport
from mcp_connections import configured_connections, discover_tools


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--service', choices=['financials', 'internal-knowledge'], default='financials')
    parser.add_argument('--url', help='Use a local HTTP endpoint instead of the configured connection')
    parser.add_argument('--symbol', default='IBM')
    parser.add_argument('--path', help='Internal Markdown path to read; omit to browse the root')
    parser.add_argument('--list-tools', action='store_true')
    args = parser.parse_args()
    try:
        if args.url:
            transport = lambda: mcp_transport(url=args.url)
        else:
            connections = {connection.name: connection for connection in configured_connections()}
            if args.service not in connections:
                parser.error(f'{args.service} is not configured; set its MCP URL/runtime ARN or pass --url')
            transport = connections[args.service].transport
        with MCPClient(transport) as client:
            if args.list_tools:
                print(json.dumps([tool.tool_name for tool in discover_tools(client)], indent=2))
                return 0
            if args.service == 'financials':
                name, arguments = 'get_company_snapshot', {'symbol': args.symbol}
            elif args.path:
                name, arguments = 'read_internal_document', {'path': args.path}
            else:
                name, arguments = 'list_internal_documents', {}
            result = client.call_tool_sync('probe', name, arguments)
        if result['status'] != 'success':
            print(json.dumps(result, indent=2), file=sys.stderr)
            return 1
        payload = next(json.loads(block['text']) for block in result['content'] if 'text' in block)
        print(json.dumps(payload, indent=2))
        return 0 if payload.get('status', 'complete') == 'complete' else 1
    except Exception as exc:
        print(f'MCP probe failed ({type(exc).__name__}); check endpoint settings and the server log', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
