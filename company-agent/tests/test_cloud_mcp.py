"""Signing, credential refresh, and selecting the cloud transport."""
from pathlib import Path
import sys
from unittest.mock import Mock

from botocore.credentials import Credentials
import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'agents'))
import cloud_mcp

ARN = 'arn:aws:bedrock-agentcore:eu-west-1:123456789012:runtime/financial_mcp-abc123'


def test_signs_body_and_refreshes_credentials_each_request():
    credentials = Mock()
    credentials.get_frozen_credentials.return_value = Credentials('TESTKEY', 'TESTSECRET', 'TESTTOKEN')
    auth = cloud_mcp.AwsSigV4(credentials, 'eu-west-1')
    for _ in range(2):
        request = httpx.Request('POST', 'https://bedrock-agentcore.eu-west-1.amazonaws.com/test',
                                content=b'{"jsonrpc":"2.0"}', headers={'Connection':'keep-alive'})
        signed = next(auth.auth_flow(request))
        assert '/eu-west-1/bedrock-agentcore/aws4_request' in signed.headers['Authorization']
        assert signed.headers['X-Amz-Security-Token'] == 'TESTTOKEN'
        assert 'connection' not in signed.headers['Authorization']
    assert credentials.get_frozen_credentials.call_count == 2


def test_cloud_endpoint_uses_arn_region_and_encodes_resource(monkeypatch):
    session = Mock()
    session.client.return_value.meta.endpoint_url = 'https://bedrock-agentcore.eu-west-1.amazonaws.com'
    monkeypatch.setattr(cloud_mcp.boto3, 'Session', lambda **kwargs: session)
    url, auth = cloud_mcp.runtime_endpoint(ARN)
    assert 'arn%3Aaws%3Abedrock-agentcore%3Aeu-west-1' in url
    assert url.endswith('/invocations?qualifier=DEFAULT')
    assert auth.region == 'eu-west-1'


@pytest.mark.parametrize('arn', ['not-arn','arn:aws:s3:::bucket','arn:aws:bedrock-agentcore:eu-west-1:123:gateway/test'])
def test_invalid_runtime_arns_are_rejected(arn):
    with pytest.raises(ValueError):
        cloud_mcp.runtime_endpoint(arn)


def test_runtime_arn_selects_signed_transport_and_session_header(monkeypatch):
    monkeypatch.setenv('MCP_RUNTIME_ARN', ARN)
    monkeypatch.setattr(cloud_mcp, 'runtime_endpoint', lambda arn: ('https://example.test', 'signer'))
    monkeypatch.setattr(cloud_mcp, 'streamablehttp_client', lambda *args, **kwargs: (args, kwargs))
    args, kwargs = cloud_mcp.mcp_transport()
    assert args == ('https://example.test',)
    assert kwargs['auth'] == 'signer'
    assert kwargs['terminate_on_close'] is False
    assert len(kwargs['headers']['X-Amzn-Bedrock-AgentCore-Runtime-Session-Id']) == 36


def test_local_transport_does_not_load_aws_credentials(monkeypatch):
    monkeypatch.delenv('MCP_RUNTIME_ARN', raising=False)
    monkeypatch.setenv('MCP_URL', 'http://localhost:8000/mcp')
    monkeypatch.setattr(cloud_mcp, 'streamablehttp_client', lambda url: url)
    assert cloud_mcp.mcp_transport() == 'http://localhost:8000/mcp'
