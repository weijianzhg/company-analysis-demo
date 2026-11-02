"""Only tool identity and lifecycle status are sent to the caller."""
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'agents'))
from tool_progress import ToolProgress


@pytest.mark.parametrize('status,exception,expected', [
    ('success', None, 'succeeded'), ('error', None, 'failed'),
    ('success', RuntimeError('private-error-body'), 'failed'),
])
def test_progress_correlates_calls_without_exposing_payloads(status, exception, expected):
    events = []
    progress = ToolProgress(events.append, {'read_internal_document': 'internal-knowledge'})
    event = SimpleNamespace(tool_use={'toolUseId': 'read-1', 'name': 'read_internal_document',
                                     'input': {'path': 'private-document.md'}},
                            result={'status': status, 'content': 'private-document-contents'},
                            exception=exception)
    progress.started(event)
    progress.finished(event)
    assert events == [
        {'type': 'tool_call', 'id': 'read-1', 'tool': 'read_internal_document',
         'server': 'internal-knowledge', 'status': state}
        for state in ('started', expected)
    ]
    assert 'private' not in str(events)
