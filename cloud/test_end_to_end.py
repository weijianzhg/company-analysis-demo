#!/usr/bin/env python3
"""Verify deployed AgentCore endpoints, the MCP protocol and Bedrock tool use."""

import argparse
from datetime import datetime, timezone
from functools import partial
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from uuid import uuid4

import httpx
from strands.tools.mcp import MCPClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'company-agent/agents'))
sys.path.insert(0, str(ROOT / 'company-agent/scripts'))
from cloud_mcp import mcp_transport, runtime_endpoint
from invoke import invoke_agent


def output(repo, name):
    return subprocess.check_output(['terraform', f'-chdir={ROOT / repo / "infra"}',
                                    'output', '-raw', name], text=True).strip()


def validate_snapshot(snapshot, mode, allow_missing_overview=False):
    """The optional valuation limitation must never hide missing statements."""
    assert snapshot['mode'] == mode
    required = {'GLOBAL_QUOTE', 'OVERVIEW', 'INCOME_STATEMENT', 'BALANCE_SHEET', 'CASH_FLOW'}
    missing = required - set(snapshot['datasets'])
    errors = set(snapshot['errors'])
    if allow_missing_overview and mode == 'live' and missing == {'OVERVIEW'}:
        assert errors == {'OVERVIEW'}, f'Unexpected provider failures: {snapshot["errors"]}'
        assert snapshot['status'] == 'partial'
        for name in ('trailing_pe', 'forward_pe', 'price_to_eps'):
            assert snapshot['metrics'][name]['value'] is None, f'{name} must be unavailable without overview'
    else:
        assert not missing and not errors and snapshot['status'] == 'complete', (
            f'Required financial data unavailable: {snapshot["errors"]}; missing: {sorted(missing)}')
    for name in ('price', 'revenue', 'net_income', 'revenue_growth_pct', 'net_margin_pct',
                 'free_cash_flow', 'free_cash_flow_growth_pct', 'current_ratio'):
        assert snapshot['metrics'][name]['value'] is not None, f'Required demo metric unavailable: {name}'


def validate_agent_response(response, missing_overview=False):
    assert response.get('result'), response
    assert len(response['result'].split()) <= 300, 'Agent answer exceeded the 300-word limit'
    assert 'get_company_snapshot' in response.get('tools_used', []), response
    if missing_overview:
        assert re.search(r'\bp/e[\s:*_–—-]+unavailable\b', response['result'], re.IGNORECASE), (
            'Agent must explicitly report P/E unavailable')


def validate_tool_events(events, tools_used):
    pending, completed = {}, []
    for event in events:
        assert set(event) == {'type', 'id', 'tool', 'server', 'status'}, 'Unexpected tool progress payload'
        assert event['type'] == 'tool_call'
        if event['status'] == 'started':
            assert event['id'] not in pending
            pending[event['id']] = (event['tool'], event['server'])
        else:
            assert event['status'] == 'succeeded', event
            assert pending.pop(event['id']) == (event['tool'], event['server'])
            completed.append(event['tool'])
    assert not pending, 'Some tool calls never completed'
    assert completed == tools_used, 'Progress must cover every executed tool call'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--profile', help='AWS profile (otherwise use the standard AWS credential chain)')
    parser.add_argument('--agent-runtime-arn', help='Use an existing agent instead of Terraform output')
    parser.add_argument('--financial-mcp-runtime-arn', help='Use an existing financial MCP instead of Terraform output')
    parser.add_argument('--knowledge-mcp-runtime-arn', help='Use an existing knowledge MCP instead of Terraform output')
    parser.add_argument('--mode', required=True, choices=['fixture', 'live'])
    parser.add_argument('--allow-missing-overview', action='store_true',
                        help='Accept unavailable P/E in live mode; quote and all three statements are still required')
    parser.add_argument('--knowledge-path', help='Also verify internal MCP and agent retrieval of this relative Markdown path')
    parser.add_argument('--require-tool-events', action='store_true', help='Require live start/success events for every tool call')
    args = parser.parse_args()
    if args.allow_missing_overview and args.mode != 'live':
        parser.error('--allow-missing-overview is only for live data')
    if args.profile:
        os.environ['AWS_PROFILE'] = args.profile
    os.environ['MCP_RUNTIME_ARN'] = args.financial_mcp_runtime_arn or output('alpha-vantage-mcp', 'agent_runtime_arn')
    agent_arn = args.agent_runtime_arn or output('company-agent', 'agent_runtime_arn')
    evidence = {'tested_at':datetime.now(timezone.utc).isoformat(), 'mode':args.mode,
                'mcp_runtime_arn':os.environ['MCP_RUNTIME_ARN'], 'agent_runtime_arn':agent_arn}
    endpoints = [('agent', agent_arn), ('mcp', os.environ['MCP_RUNTIME_ARN'])]
    if args.knowledge_path:
        knowledge_arn = args.knowledge_mcp_runtime_arn or output('internal-knowledge-mcp', 'agent_runtime_arn')
        endpoints.append(('knowledge', knowledge_arn))
        with MCPClient(partial(mcp_transport, arn=knowledge_arn)) as client:
            result = client.call_tool_sync('knowledge-check', 'read_internal_document', {'path': args.knowledge_path})
            assert result['status'] == 'success', result
            document = next(json.loads(block['text']) for block in result['content'] if 'text' in block)
            evidence['knowledge_source'] = document['source']
    for label, arn in endpoints:
        url, _ = runtime_endpoint(arn)
        response = httpx.post(url, json={'prompt':'Unauthorized access test'}, timeout=30)
        assert response.status_code in (401,403), f'{label}: anonymous request returned {response.status_code}'
        evidence[f'{label}_unsigned_status'] = response.status_code
    with MCPClient(mcp_transport) as client:
        evidence['tools'] = sorted(tool.tool_name for tool in client.list_tools_sync())
        assert len(evidence['tools']) == 6
        result = client.call_tool_sync('snapshot-check', 'get_company_snapshot', {'symbol':'IBM'})
        assert result['status'] == 'success', result
        snapshot = next(json.loads(block['text']) for block in result['content'] if 'text' in block)
        assert snapshot['mode'] == args.mode
        evidence['snapshot'] = snapshot
        invalid = client.call_tool_sync('invalid-input-check','get_stock_quote',{'symbol':'../invalid'})
        assert invalid['status'] == 'error'
        evidence['invalid_input_rejected'] = True
        if args.mode == 'fixture':
            assert snapshot['status'] == 'complete'
            expected = {'revenue_growth_pct':10, 'net_margin_pct':15, 'trailing_pe':20,
                        'free_cash_flow':15_000_000_000, 'current_ratio':1.5}
            for key,value in expected.items():
                assert snapshot['metrics'][key]['value'] == value
            quarter = client.call_tool_sync('quarter-check','get_income_statement',
                                            {'symbol':'IBM','period':'quarterly','limit':1})
            assert quarter['status'] == 'success'
            evidence['quarterly_tool_checked'] = True
    prompt = ("Use get_company_snapshot to analyze IBM's annual P&L, revenue growth, net margin, "
              "trailing P/E, free cash flow and its supplied growth metric, and current ratio. "
              "Include actual figures, dates, source and data mode. If overview is unavailable, "
              "write 'P/E unavailable' and its reason; continue analyzing the statements. Keep it under 300 words.")
    if args.knowledge_path:
        prompt += (f" Also call read_internal_document for {args.knowledge_path}, summarize the internal context "
                   "and cite its S3 source. Distinguish synthetic notes from real company facts.")
    evidence['prompt'] = prompt
    evidence['tool_events'] = []

    def on_tool_event(event):
        evidence['tool_events'].append(event)
        print(f"[{event['server']}] {event['tool']}: {event['status']}", flush=True)

    evidence['agent_response'] = invoke_agent(agent_arn, {'prompt':prompt}, str(uuid4()),
                                             region=agent_arn.split(':')[3], profile=args.profile,
                                             on_tool_event=on_tool_event)
    path = ROOT / 'evidence/cloud' / f'{args.mode}-end-to-end.json'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(evidence,indent=2)+'\n')
    validate_snapshot(snapshot, args.mode, args.allow_missing_overview)
    validate_agent_response(evidence['agent_response'], 'OVERVIEW' not in snapshot['datasets'])
    if args.require_tool_events:
        validate_tool_events(evidence['tool_events'], evidence['agent_response']['tools_used'])
    if args.knowledge_path:
        assert 'read_internal_document' in evidence['agent_response']['tools_used']
        assert evidence['knowledge_source'] in evidence['agent_response']['result']
    if args.mode == 'fixture':
        assert 'synthetic' in evidence['agent_response']['result'].lower()
    print(json.dumps({'mode':args.mode,'snapshot_status':snapshot['status'],
                      'valuation':'unavailable' if 'OVERVIEW' not in snapshot['datasets'] else 'overview available',
                      'tools_used':evidence['agent_response']['tools_used'],'evidence':str(path)}))


if __name__ == '__main__':
    main()
