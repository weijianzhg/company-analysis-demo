"""Request validation and the runtime's heartbeat/error/busy behavior."""

from pathlib import Path
import sys
from threading import Event

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'agents'))
import main
import analyst


@pytest.mark.parametrize('payload', [None, [], {}, {'prompt': ''}, {'prompt': 2}, {'prompt': 'a' * 10001}])
def test_invalid_requests(payload):
    assert 'error' in main.invoke(payload)


def test_results_and_tools_are_returned(monkeypatch):
    monkeypatch.setattr(main, 'analyze', lambda prompt: {'result': prompt, 'tools_used': ['get_company_snapshot']})
    events = list(main.invoke({'prompt': 'IBM P/E'}))
    assert events[0] == {'type': 'heartbeat'}
    assert events[-1]['result'] == 'IBM P/E'
    assert events[-1]['tools_used'] == ['get_company_snapshot']


def test_provider_exceptions_are_redacted_and_lock_is_released(monkeypatch):
    def fail(prompt):
        raise RuntimeError('secret-api-key')
    monkeypatch.setattr(main, 'analyze', fail)
    events = list(main.invoke({'prompt': 'IBM'}))
    assert 'RuntimeError' in events[-1]['error']
    assert 'secret-api-key' not in str(events)
    assert not main.invocation_lock.locked()


def test_busy_request_cannot_start_another_worker(monkeypatch):
    release = Event()
    monkeypatch.setattr(main, 'analyze', lambda prompt: (release.wait(5), {'result': 'done'})[1])
    events = main.invoke({'prompt': 'IBM'})
    try:
        assert next(events)['type'] == 'heartbeat'
        assert 'busy' in list(main.invoke({'prompt': 'AAPL'}))[0]['error']
    finally:
        release.set()
        list(events)


def test_bedrock_configuration(monkeypatch):
    monkeypatch.setenv('MODEL_PROVIDER', 'bedrock')
    monkeypatch.setenv('MODEL_ID', 'test-profile')
    monkeypatch.setenv('AWS_REGION', 'eu-west-1')
    monkeypatch.setattr(analyst, 'BedrockModel', lambda **kwargs: kwargs)
    assert analyst.create_model()['model_id'] == 'test-profile'


def test_unknown_model_provider_fails(monkeypatch):
    monkeypatch.setenv('MODEL_PROVIDER', 'guess')
    with pytest.raises(ValueError, match='MODEL_PROVIDER'):
        analyst.create_model()


def test_answer_without_mcp_tool_use_is_not_presented_as_analysis(monkeypatch):
    class Client:
        def __init__(self, *args):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def list_tools_sync(self):
            return []

    class UngroundedAgent:
        messages = []

        def __init__(self, **kwargs):
            pass

        def __call__(self, prompt):
            return 'An unsupported financial answer'

    monkeypatch.setattr(analyst, 'MCPClient', Client)
    monkeypatch.setattr(analyst, 'Agent', UngroundedAgent)
    result = analyst.analyze('Analyze IBM', model=object())
    assert 'did not fetch MCP data' in result['error']
    assert 'result' not in result
