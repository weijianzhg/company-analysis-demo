"""Test-only HTTP server backed by Moto S3. Never shipped in the runtime image."""
from pathlib import Path
import os
import sys

import boto3
from moto import mock_aws

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'mcp_server'))
from knowledge import KnowledgeStore
import server

with mock_aws():
    s3 = boto3.client('s3', region_name='us-east-1')
    s3.create_bucket(Bucket='demo-knowledge')
    for path in (ROOT / 'examples').rglob('*.md'):
        s3.put_object(Bucket='demo-knowledge', Key='knowledge/' + path.relative_to(ROOT / 'examples').as_posix(),
                      Body=path.read_bytes())
    store = KnowledgeStore(s3, 'demo-knowledge', 'knowledge/')
    server.get_store = lambda: store
    server.mcp.run(transport='streamable-http', host='127.0.0.1',
                   port=int(os.environ['MCP_PORT']), stateless_http=True)
