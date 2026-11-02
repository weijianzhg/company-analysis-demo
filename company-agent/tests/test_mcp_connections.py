"""Multi-MCP configuration, tool discovery and session lifetime."""
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'agents'))
import analyst
import mcp_connections


@pytest.fixture(autouse=True)
def clean_mcp_environment(monkeypatch):
    for name in ('MCP_URL', 'MCP_RUNTIME_ARN', 'INTERNAL_KNOWLEDGE_MCP_URL',
                 'INTERNAL_KNOWLEDGE_MCP_RUNTIME_ARN'):
        monkeypatch.delenv(name, raising=False)


def test_financial_only_defaults_still_work():
    connections = mcp_connections.configured_connections()
    assert len(connections) == 1
    assert connections[0].url == 'http://127.0.0.1:8000/mcp'


def test_each_connection_keeps_its_own_transport_settings(monkeypatch):
    monkeypatch.setenv('MCP_URL', 'http://localhost:8000/mcp')
    monkeypatch.setenv('INTERNAL_KNOWLEDGE_MCP_URL', 'http://localhost:8001/mcp')
    monkeypatch.setenv('INTERNAL_KNOWLEDGE_MCP_RUNTIME_ARN', 'knowledge-arn')
    monkeypatch.setattr(mcp_connections, 'mcp_transport', lambda *args: args)
    financial, internal = mcp_connections.configured_connections()
    assert financial.transport() == ('http://localhost:8000/mcp', '')
    assert internal.transport() == ('http://localhost:8001/mcp', 'knowledge-arn')


def test_tools_from_all_discovery_pages():
    class Page(list):
        pagination_token = None
    first, second = Page(['first']), Page(['second'])
    first.pagination_token = 'next'
    client = SimpleNamespace(list_tools_sync=lambda pagination_token=None: second if pagination_token else first)
    assert mcp_connections.discover_tools(client) == ['first', 'second']


@pytest.mark.parametrize('failure', [None, 'connect', 'duplicate', 'model'])
def test_all_sessions_stay_open_and_close_on_failure(monkeypatch, failure):
    active, closed = set(), []
    monkeypatch.setenv('INTERNAL_KNOWLEDGE_MCP_URL', 'http://localhost:8001/mcp')

    class Client:
        def __init__(self, transport):
            self.name = transport.__self__.name
        def __enter__(self):
            if self.name == 'internal-knowledge' and failure == 'connect':
                raise RuntimeError('connect')
            active.add(self.name)
            return self
        def __exit__(self, *args):
            active.remove(self.name)
            closed.append(self.name)
        def list_tools_sync(self):
            return [SimpleNamespace(tool_name='duplicate' if failure == 'duplicate' else self.name)]

    class Agent:
        messages = [{'content': [{'toolUse': {'name': 'financials'}},
                                  {'toolUse': {'name': 'internal-knowledge'}}]}]
        def __init__(self, **kwargs):
            assert {t.tool_name for t in kwargs['tools']} == active
        def __call__(self, prompt):
            assert active == {'financials', 'internal-knowledge'}
            if failure == 'model':
                raise RuntimeError('model')
            return 'Analysis with internal context'

    monkeypatch.setattr(analyst, 'MCPClient', Client)
    monkeypatch.setattr(analyst, 'Agent', Agent)
    if failure:
        with pytest.raises((RuntimeError, ValueError)):
            analyst.analyze('IBM', model=object())
    else:
        assert analyst.analyze('IBM', model=object())['tools_used'] == ['financials', 'internal-knowledge']
    assert not active
    assert closed == (['financials'] if failure == 'connect' else ['internal-knowledge', 'financials'])
