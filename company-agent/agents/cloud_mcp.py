"""The same MCP transport locally or through an IAM-authenticated AgentCore runtime."""

import os
from urllib.parse import quote
from uuid import uuid4

import boto3
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest
import httpx
from mcp.client.streamable_http import streamablehttp_client


class AwsSigV4(httpx.Auth):
    requires_request_body = True

    def __init__(self, credentials, region):
        self.credentials, self.region = credentials, region

    def auth_flow(self, request):
        headers = {k: v for k, v in request.headers.items() if k.lower() != "connection"}
        signed = AWSRequest(method=request.method, url=str(request.url),
                            data=request.content, headers=headers)
        # Refresh runtime-role credentials and take an atomic key/token snapshot.
        SigV4Auth(self.credentials.get_frozen_credentials(), "bedrock-agentcore", self.region).add_auth(signed)
        request.headers.update(dict(signed.headers))
        yield request


def runtime_endpoint(arn: str):
    parts = arn.split(":", 5)
    if len(parts) != 6 or parts[2] != "bedrock-agentcore" or not parts[3] or not parts[5].startswith("runtime/"):
        raise ValueError("MCP_RUNTIME_ARN must be an AgentCore runtime ARN")
    session = boto3.Session(region_name=parts[3])
    credentials = session.get_credentials()
    if credentials is None:
        raise ValueError("AWS credentials are required to call the MCP runtime")
    endpoint = session.client("bedrock-agentcore").meta.endpoint_url
    return f"{endpoint}/runtimes/{quote(arn, safe='')}/invocations?qualifier=DEFAULT", AwsSigV4(credentials, parts[3])


def mcp_transport():
    arn = os.environ.get("MCP_RUNTIME_ARN")
    if not arn:
        return streamablehttp_client(os.environ.get("MCP_URL", "http://127.0.0.1:8000/mcp"))
    url, auth = runtime_endpoint(arn)
    return streamablehttp_client(url, auth=auth, terminate_on_close=False,
                                headers={"X-Amzn-Bedrock-AgentCore-Runtime-Session-Id": str(uuid4())})
