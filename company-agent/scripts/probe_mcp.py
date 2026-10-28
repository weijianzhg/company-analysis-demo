#!/usr/bin/env python3
"""Check the agent's real MCP connection without invoking a language model."""

import argparse
import json
import os
import sys

from mcp.client.streamable_http import streamablehttp_client
from strands.tools.mcp import MCPClient


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', default=os.environ.get('MCP_URL', 'http://127.0.0.1:8000/mcp'))
    parser.add_argument('--symbol', default='IBM')
    parser.add_argument('--list-tools', action='store_true')
    args = parser.parse_args()
    try:
        with MCPClient(lambda: streamablehttp_client(args.url)) as client:
            if args.list_tools:
                print(json.dumps([tool.tool_name for tool in client.list_tools_sync()], indent=2))
                return 0
            result = client.call_tool_sync('probe', 'get_company_snapshot', {'symbol': args.symbol})
        if result['status'] != 'success':
            print(json.dumps(result, indent=2), file=sys.stderr)
            return 1
        payload = next(json.loads(block['text']) for block in result['content'] if 'text' in block)
        print(json.dumps(payload, indent=2))
        return 0 if payload['status'] == 'complete' else 1
    except Exception as exc:
        print(f'MCP probe failed ({type(exc).__name__}); check MCP_URL and the server log', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
