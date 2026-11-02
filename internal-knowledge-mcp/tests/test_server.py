"""Discovery and tool execution through the MCP protocol with mocked AWS S3."""

import json

import anyio
from mcp import Client
import pytest

import server


@pytest.fixture(autouse=True)
def configured_store(monkeypatch, store):
    monkeypatch.setattr(server, 'get_store', lambda: store)


def call(name, arguments):
    async def run():
        async with Client(server.mcp) as client:
            return await client.call_tool(name, arguments)
    return anyio.run(run)


def test_discovery():
    async def run():
        async with Client(server.mcp) as client:
            return (await client.list_tools()).tools
    tools = anyio.run(run)
    assert {t.name for t in tools} == {'list_internal_documents', 'read_internal_document',
                                      'search_internal_knowledge'}
    assert all(t.description for t in tools)


def test_search_then_read():
    result = call('search_internal_knowledge', {'query': 'IBM hybrid'})
    assert not result.is_error
    match = json.loads(result.content[0].text)['matches'][0]
    result = call('read_internal_document', {'path': match['path']})
    assert not result.is_error
    assert 'Hybrid cloud' in json.loads(result.content[0].text)['content']


def test_browse_root():
    result = call('list_internal_documents', {})
    assert not result.is_error
    assert json.loads(result.content[0].text)['folders'] == ['companies/']


@pytest.mark.parametrize('name,args', [
    ('read_internal_document', {'path': '../secret.md'}),
    ('read_internal_document', {'path': 'missing.md'}),
    ('search_internal_knowledge', {'query': '  '}),
    ('list_internal_documents', {'page_size': 0}),
])
def test_invalid_requests_are_tool_errors(name, args):
    assert call(name, args).is_error
