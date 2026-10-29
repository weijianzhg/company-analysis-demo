"""Upstream HTTP failures, body-level errors, redaction, and cache semantics."""

import json
import logging
from pathlib import Path
import sys

import anyio
import httpx2
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'mcp_server'))
from alpha_vantage import AlphaVantage, AlphaVantageError


def test_request_parameters_and_cache_do_not_leak_mutations(caplog):
    caplog.set_level(logging.INFO, logger='httpx2')
    calls = []
    def handle(request):
        calls.append(request)
        assert request.url.params['function'] == 'OVERVIEW'
        assert request.url.params['apikey'] == 'private-test-key'
        return httpx2.Response(200, json={'Symbol': 'IBM', 'EPS': '10'})
    async def run():
        client = AlphaVantage('private-test-key', transport=httpx2.MockTransport(handle))
        first = await client.fetch('OVERVIEW', 'ibm')
        first['data']['EPS'] = '999'
        second = await client.fetch('OVERVIEW', 'IBM')
        assert second['cached'] is True
        assert second['data']['EPS'] == '10'
        assert first['retrieved_at'] == second['retrieved_at']
        assert 'private-test-key' not in json.dumps(second)
        client.cache[('OVERVIEW', 'IBM')] = (0, second)
        assert not (await client.fetch('OVERVIEW', 'IBM'))['cached']
    anyio.run(run)
    assert len(calls) == 2
    assert 'private-test-key' not in caplog.text
    assert '[REDACTED]' in caplog.text


@pytest.mark.parametrize('body', [{'Note': 'secret'}, {'Information': 'secret'},
                                 {'Error Message': 'secret'}, {}, [], {'Symbol': 'MSFT'}])
def test_http_200_errors_are_not_financial_data(body):
    async def run():
        client = AlphaVantage('secret', transport=httpx2.MockTransport(lambda r: httpx2.Response(200, json=body)))
        with pytest.raises(AlphaVantageError) as caught:
            await client.fetch('OVERVIEW', 'IBM')
        assert 'secret' not in str(caught.value)
        assert not client.cache
    anyio.run(run)


@pytest.mark.parametrize('failure', ['http', 'timeout', 'json'])
def test_transport_errors_never_expose_api_key(failure):
    def handle(request):
        if failure == 'timeout':
            raise httpx2.ReadTimeout('secret', request=request)
        if failure == 'json':
            return httpx2.Response(200, text='not json: secret')
        return httpx2.Response(429, text='secret')
    async def run():
        client = AlphaVantage('secret', transport=httpx2.MockTransport(handle))
        with pytest.raises(AlphaVantageError) as caught:
            await client.fetch('OVERVIEW', 'IBM')
        assert 'secret' not in str(caught.value)
    anyio.run(run)


def test_live_mode_loads_secret_without_returning_key(monkeypatch):
    from unittest.mock import Mock
    import alpha_vantage
    secret = Mock()
    secret.get_secret_value.return_value = {'SecretString': ' private-key\n'}
    monkeypatch.setattr(alpha_vantage.boto3, 'client', lambda *args, **kwargs: secret)
    monkeypatch.setenv('ALPHA_VANTAGE_MODE', 'live')
    monkeypatch.setenv('ALPHA_VANTAGE_SECRET_ARN', 'arn:aws:secretsmanager:eu-west-1:123:secret:test')
    api = AlphaVantage.from_environment()
    assert api.api_key == 'private-key'
    secret.get_secret_value.assert_called_once()


def test_fixture_mode_does_not_load_secret(monkeypatch):
    import alpha_vantage
    monkeypatch.setenv('ALPHA_VANTAGE_MODE', 'fixture')
    monkeypatch.setenv('ALPHA_VANTAGE_SECRET_ARN', 'unused')
    monkeypatch.setattr(alpha_vantage.boto3, 'client', lambda *a, **kw: pytest.fail('Must not load secret'))
    assert AlphaVantage.from_environment().mode == 'fixture'


def test_secret_loading_errors_are_redacted(monkeypatch):
    import alpha_vantage
    def fail(*args, **kwargs):
        raise RuntimeError('private-key')
    monkeypatch.setenv('ALPHA_VANTAGE_MODE', 'live')
    monkeypatch.setenv('ALPHA_VANTAGE_SECRET_ARN', 'arn:aws:secretsmanager:eu-west-1:123:secret:test')
    monkeypatch.setattr(alpha_vantage.boto3, 'client', fail)
    with pytest.raises(AlphaVantageError) as caught:
        AlphaVantage.from_environment()
    assert 'private-key' not in str(caught.value)


def test_provider_limit_details_are_preserved_without_credentials():
    body = {'Information': 'Limit: 5 calls per minute. Key private-test-key; https://example.com/?apikey=other-key'}
    async def run():
        client = AlphaVantage('private-test-key', transport=httpx2.MockTransport(lambda r: httpx2.Response(200, json=body)))
        with pytest.raises(AlphaVantageError) as caught:
            await client.fetch('OVERVIEW', 'IBM')
        message = str(caught.value)
        assert '5 calls per minute' in message
        assert 'private-test-key' not in message
        assert 'other-key' not in message
    anyio.run(run)


def test_only_uncached_live_requests_are_paced(monkeypatch):
    import alpha_vantage
    now, sleeps, calls = [100.0], [], []
    monkeypatch.setattr(alpha_vantage.time, 'monotonic', lambda: now[0])
    async def sleep(delay):
        sleeps.append(delay)
        now[0] += delay
    monkeypatch.setattr(alpha_vantage.asyncio, 'sleep', sleep)
    def handle(request):
        calls.append(now[0])
        return httpx2.Response(200, json={'Symbol': request.url.params['symbol']})
    async def run():
        client = AlphaVantage('test-key', request_interval=15, transport=httpx2.MockTransport(handle))
        await client.fetch('OVERVIEW', 'IBM')
        await client.fetch('OVERVIEW', 'IBM')
        await client.fetch('OVERVIEW', 'AAPL')
    anyio.run(run)
    assert calls == [100, 115]
    assert sleeps == [15]
