from pathlib import Path
import sys

import boto3
from moto import mock_aws
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'mcp_server'))
from knowledge import KnowledgeStore


@pytest.fixture
def store():
    with mock_aws():
        s3 = boto3.client('s3', region_name='us-east-1')
        s3.create_bucket(Bucket='internal-notes')
        for key, content in {
            'knowledge/companies/IBM/research.md': '# IBM\nHybrid cloud workshop.\n',
            'knowledge/companies/IBM/strategy.markdown': '# Strategy\nInterview customers first.\n',
            'knowledge/companies/OTHER/notes.md': '# Another company\nUnrelated research.\n',
            'knowledge/companies/IBM/logo.png': 'not Markdown',
            'knowledge-private/secret.md': 'Outside the allowed prefix',
        }.items():
            s3.put_object(Bucket='internal-notes', Key=key, Body=content.encode())
        yield KnowledgeStore(s3, 'internal-notes', 'knowledge')
