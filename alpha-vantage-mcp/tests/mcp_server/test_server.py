"""Exercise discovery, validation, and financial results through the MCP protocol."""

import json
from pathlib import Path
import sys

import anyio
from mcp import Client
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'mcp_server'))
import server
from alpha_vantage import AlphaVantage, AlphaVantageError


@pytest.fixture(autouse=True)
def fixture_api(monkeypatch):
    monkeypatch.setattr(server, 'api', AlphaVantage(mode='fixture'))


def call(name, arguments):
    async def run():
        async with Client(server.mcp) as client:
            return await client.call_tool(name, arguments)
    return anyio.run(run)


def test_tools_have_descriptions_and_schemas():
    async def run():
        async with Client(server.mcp) as client:
            return (await client.list_tools()).tools
    tools = {tool.name: tool for tool in anyio.run(run)}
    assert set(tools) == {'get_stock_quote', 'get_company_overview', 'get_income_statement',
                          'get_balance_sheet', 'get_cash_flow', 'get_company_snapshot'}
    for tool in tools.values():
        assert tool.description
        assert tool.input_schema['required'] == ['symbol']


def test_snapshot_is_labeled_and_contains_calculated_metrics():
    result = call('get_company_snapshot', {'symbol': ' ibm '})
    assert not result.is_error
    data = json.loads(result.content[0].text)
    assert data['mode'] == 'fixture'
    assert data['status'] == 'complete'
    assert data['metrics']['trailing_pe']['value'] == 20
    assert data['metrics']['revenue_growth_pct']['value'] == 10
    assert data['metrics']['net_margin_pct']['value'] == 15
    assert data['metrics']['free_cash_flow']['value'] == 15_000_000_000
    assert len(data['datasets']) == 5
    assert all('Synthetic' in d['notice'] for d in data['datasets'].values())


def test_quarterly_income_is_not_annual():
    result = call('get_income_statement', {'symbol': 'IBM', 'period': 'quarterly', 'limit': 1})
    data = json.loads(result.content[0].text)
    assert data['data']['reports'][0]['fiscalDateEnding'] == '2025-09-30'


@pytest.mark.parametrize('arguments', [{}, {'symbol': '../secret'}, {'symbol': 'AAPL'},
                                     {'symbol': 'IBM', 'period': 'monthly'},
                                     {'symbol': 'IBM', 'limit': 0}, {'symbol': 'IBM', 'limit': 6}])
def test_invalid_arguments_are_tool_errors(arguments):
    assert call('get_income_statement', arguments).is_error


def test_partial_snapshot_keeps_provider_failure_visible(monkeypatch):
    real_fetch = server.api.fetch
    async def fetch(function, symbol):
        if function == 'CASH_FLOW':
            raise AlphaVantageError('Alpha Vantage quota/rate limit reached')
        return await real_fetch(function, symbol)
    monkeypatch.setattr(server.api, 'fetch', fetch)
    result = call('get_company_snapshot', {'symbol': 'IBM'})
    data = json.loads(result.content[0].text)
    assert data['status'] == 'partial'
    assert 'CASH_FLOW' in data['errors']
    assert data['metrics']['free_cash_flow']['value'] is None


def test_missing_key_does_not_fall_back_to_fixture(monkeypatch):
    monkeypatch.setattr(server, 'api', AlphaVantage())
    result = call('get_company_snapshot', {'symbol': 'IBM'})
    assert result.is_error
    assert 'ALPHA_VANTAGE_API_KEY' in result.content[0].text
