#!/usr/bin/env python3
"""Ask the local agent and consume the blueprint's heartbeat/SSE response."""

import argparse
import json
import sys

import httpx


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("prompt")
    parser.add_argument("--url", default="http://127.0.0.1:8080/invocations")
    args = parser.parse_args()
    try:
        with httpx.stream("POST", args.url, json={"prompt": args.prompt}, timeout=600) as response:
            response.raise_for_status()
            if "text/event-stream" not in response.headers.get("content-type", ""):
                response.read()
                raise RuntimeError(response.json().get("error", "Unexpected response"))
            for line in response.iter_lines():
                if not line.startswith("data:"):
                    continue
                event = json.loads(line[5:])
                if event.get("type") == "heartbeat":
                    continue
                if "error" in event:
                    raise RuntimeError(event["error"])
                if "result" in event:
                    print(event["result"])
                    print("\nMCP tools used: " + ", ".join(event["tools_used"]), file=sys.stderr)
                    return 0
        raise RuntimeError("Agent stream ended without a result")
    except (httpx.HTTPError, RuntimeError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
