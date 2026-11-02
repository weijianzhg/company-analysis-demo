import io
from unittest.mock import Mock

from botocore.exceptions import ClientError
from botocore.response import StreamingBody
import pytest

from knowledge import KnowledgeError, KnowledgeStore, MAX_DOCUMENT_BYTES


def test_browse_preserves_folders_and_filters_non_markdown(store):
    assert store.list_documents()['folders'] == ['companies/']
    result = store.list_documents('companies/IBM/')
    assert [d['path'] for d in result['documents']] == [
        'companies/IBM/research.md', 'companies/IBM/strategy.markdown']
    assert result['next_cursor'] is None
    assert all('knowledge-private' not in str(d) for d in result['documents'])


def test_browse_paginates_even_when_page_has_no_markdown(store):
    result = store.list_documents('companies/IBM', page_size=1)
    assert result['documents'] == []  # logo.png sorts first
    paths = []
    while result['next_cursor']:
        result = store.list_documents('companies/IBM', result['next_cursor'], page_size=1)
        paths.extend(doc['path'] for doc in result['documents'])
    assert len(paths) == 2


def test_read_returns_full_content_and_citation(store):
    result = store.read_document('companies/IBM/research.md')
    assert result['content'] == '# IBM\nHybrid cloud workshop.\n'
    assert result['source'] == 's3://internal-notes/knowledge/companies/IBM/research.md'
    assert result['last_modified'] and result['retrieved_at']


@pytest.mark.parametrize('path', ['../secret.md', '/secret.md', 's3://other/file.md',
                                 'companies/../secret.md', 'companies//x.md',
                                 'companies\\x.md', 'x.md\n', 'x.txt', ''])
def test_invalid_reads_do_not_reach_s3(path):
    s3 = Mock()
    with pytest.raises(KnowledgeError):
        KnowledgeStore(s3, 'internal-notes', 'knowledge/').read_document(path)
    s3.get_object.assert_not_called()


def test_search_matches_path_and_content_case_insensitively(store):
    result = store.search('ibm HYBRID', folder='companies/IBM')
    assert result['status'] == 'complete'
    assert len(result['matches']) == 1
    assert result['matches'][0]['path'] == 'companies/IBM/research.md'
    assert 'Hybrid cloud' in result['matches'][0]['excerpt']
    assert store.search('no-such-word')['matches'] == []


def test_recursive_search_continues_across_pages(store):
    matches, cursor = [], None
    while True:
        result = store.search('research', cursor=cursor, page_size=1)
        matches.extend(result['matches'])
        cursor = result['next_cursor']
        if not cursor:
            break
        assert result['status'] == 'partial'
    assert {match['path'] for match in matches} == {
        'companies/IBM/research.md', 'companies/OTHER/notes.md'}


def test_search_reports_large_and_invalid_files_as_skipped(store):
    for key, body in [('large.md', b'x' * (MAX_DOCUMENT_BYTES + 1)), ('binary.md', b'\xff')]:
        store.s3.put_object(Bucket=store.bucket, Key=store.prefix + key, Body=body)
    result = store.search('hybrid')
    assert result['status'] == 'partial'
    assert len(result['matches']) == 1
    assert {item['path'] for item in result['skipped']} == {'large.md', 'binary.md'}


@pytest.mark.parametrize('length', [None, MAX_DOCUMENT_BYTES + 1])
def test_large_stream_is_bounded_and_closed(length):
    body = StreamingBody(io.BytesIO(b'x' * (MAX_DOCUMENT_BYTES + 1)), MAX_DOCUMENT_BYTES + 1)
    body.close = Mock(wraps=body.close)
    s3 = Mock()
    s3.get_object.return_value = {'Body': body}
    if length:
        s3.get_object.return_value['ContentLength'] = length
    with pytest.raises(KnowledgeError, match='64 KiB'):
        KnowledgeStore(s3, 'internal-notes').read_document('large.md')
    body.close.assert_called_once()


@pytest.mark.parametrize('operation,args', [('read_document', ('missing.md',)),
                                          ('list_documents', ('../',)),
                                          ('search', ('',))])
def test_missing_document_and_invalid_arguments(store, operation, args):
    with pytest.raises(KnowledgeError):
        getattr(store, operation)(*args)


@pytest.mark.parametrize('size', [0, 101, -1])
def test_invalid_page_sizes(store, size):
    with pytest.raises(KnowledgeError):
        store.search('IBM', page_size=size)


def test_access_denied_does_not_leak_provider_body():
    s3 = Mock()
    s3.get_object.side_effect = ClientError(
        {'Error': {'Code': 'AccessDenied', 'Message': 'private provider detail'}}, 'GetObject')
    with pytest.raises(KnowledgeError, match='access denied') as error:
        KnowledgeStore(s3, 'internal-notes').read_document('notes.md')
    assert 'private provider detail' not in str(error.value)


def test_missing_bucket_fails_before_credentials_are_loaded(monkeypatch):
    monkeypatch.delenv('KNOWLEDGE_BUCKET', raising=False)
    monkeypatch.setattr('knowledge.boto3.client', lambda *a, **k: pytest.fail('must validate first'))
    with pytest.raises(KnowledgeError, match='KNOWLEDGE_BUCKET'):
        KnowledgeStore.from_environment()
