"""Small, read-only Markdown store. S3 keys preserve the company's folder layout."""

from datetime import datetime, timezone
import os

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

MAX_DOCUMENT_BYTES = 64 * 1024


class KnowledgeError(ValueError):
    """A safe, actionable error that can be returned to an MCP caller."""


def validate_path(path: str, *, folder=False) -> str:
    """Paths are relative to the configured root; never accept bucket URLs."""
    value = path.removesuffix('/') if folder else path
    if (not value and not folder) or value.startswith('/') or '\\' in value or ':' in value:
        raise KnowledgeError('Use a relative document path or folder, not a URL or absolute path')
    if value and any(part in ('', '.', '..') for part in value.split('/')):
        raise KnowledgeError('Paths must not contain empty, dot or parent segments')
    if any(ord(char) < 32 for char in value):
        raise KnowledgeError('Paths must not contain control characters')
    return value + '/' if folder and value else value


def is_markdown(path):
    return path.lower().endswith(('.md', '.markdown'))


class KnowledgeStore:
    def __init__(self, s3, bucket: str, prefix: str = ''):
        if not bucket.strip():
            raise KnowledgeError('Set KNOWLEDGE_BUCKET to the S3 bucket containing Markdown documents')
        self.s3 = s3
        self.bucket = bucket
        self.prefix = validate_path(prefix, folder=True)

    @classmethod
    def from_environment(cls):
        bucket = os.environ.get('KNOWLEDGE_BUCKET', '')
        if not bucket:
            raise KnowledgeError('Set KNOWLEDGE_BUCKET to the S3 bucket containing Markdown documents')
        return cls(boto3.client('s3', region_name=os.environ.get('AWS_REGION'), config=Config(
            connect_timeout=5, read_timeout=15, retries={'max_attempts': 2})),
            bucket, os.environ.get('KNOWLEDGE_PREFIX', ''))

    def _request(self, operation, **kwargs):
        try:
            return getattr(self.s3, operation)(Bucket=self.bucket, **kwargs)
        except ClientError as exc:
            code = exc.response.get('Error', {}).get('Code')
            if code in ('NoSuchKey', 'NoSuchBucket', '404'):
                raise KnowledgeError('Document or bucket not found') from None
            if code in ('AccessDenied', '403'):
                raise KnowledgeError('S3 access denied; check the bucket, prefix and runtime role permissions') from None
            raise KnowledgeError('S3 request failed; check configuration and retry') from None
        except BotoCoreError:
            raise KnowledgeError('S3 is unavailable; check AWS credentials and connectivity') from None

    def _source(self, key, metadata):
        modified = metadata.get('LastModified')
        return {'path': key[len(self.prefix):], 'source': f's3://{self.bucket}/{key}',
                'last_modified': modified.isoformat() if modified else None,
                'retrieved_at': datetime.now(timezone.utc).isoformat()}

    def _page(self, folder, cursor, page_size, *, recursive):
        if not 1 <= page_size <= 100:
            raise KnowledgeError('page_size must be between 1 and 100')
        options = {'Prefix': self.prefix + validate_path(folder, folder=True), 'MaxKeys': page_size}
        if not recursive:
            options['Delimiter'] = '/'
        if cursor:
            options['ContinuationToken'] = cursor
        return self._request('list_objects_v2', **options)

    def list_documents(self, folder='', cursor=None, page_size=50):
        page = self._page(folder, cursor, page_size, recursive=False)
        return {
            'folder': folder,
            'folders': [item['Prefix'][len(self.prefix):] for item in page.get('CommonPrefixes', [])],
            'documents': [dict(self._source(item['Key'], item), size_bytes=item['Size'])
                          for item in page.get('Contents', []) if is_markdown(item['Key'])],
            'next_cursor': page.get('NextContinuationToken'),
        }

    def read_document(self, path):
        path = validate_path(path)
        if not is_markdown(path):
            raise KnowledgeError('Only .md and .markdown documents are supported')
        key = self.prefix + path
        result = self._request('get_object', Key=key)
        body = result['Body']
        try:
            if result.get('ContentLength', 0) > MAX_DOCUMENT_BYTES:
                raise KnowledgeError('Document exceeds the 64 KiB demo limit; split it into smaller Markdown files')
            content = body.read(MAX_DOCUMENT_BYTES + 1)
            if len(content) > MAX_DOCUMENT_BYTES:
                raise KnowledgeError('Document exceeds the 64 KiB demo limit; split it into smaller Markdown files')
            text = content.decode('utf-8-sig')
        except UnicodeDecodeError:
            raise KnowledgeError('Document must be UTF-8 Markdown') from None
        except BotoCoreError:
            raise KnowledgeError('S3 document download failed; retry the request') from None
        finally:
            body.close()
        return dict(self._source(key, result), content=text)

    def search(self, query, folder='', cursor=None, page_size=20):
        if not query.strip() or len(query) > 200:
            raise KnowledgeError('query must contain between 1 and 200 characters')
        terms = query.casefold().split()
        page = self._page(folder, cursor, page_size, recursive=True)
        matches, skipped = [], []
        scanned = 0
        for item in page.get('Contents', []):
            path = item['Key'][len(self.prefix):]
            if not is_markdown(path):
                continue
            scanned += 1
            try:
                document = self.read_document(path)
            except KnowledgeError as exc:
                skipped.append({'path': path, 'reason': str(exc)})
                continue
            content = document.pop('content')
            haystack = (path + '\n' + content).casefold()
            if all(term in haystack for term in terms):
                start = max(0, content.casefold().find(terms[0]) - 80)
                matches.append(dict(document, excerpt=content[start:start + 400]))
        cursor = page.get('NextContinuationToken')
        return {'query': query, 'matches': matches, 'scanned_documents': scanned,
                'skipped': skipped, 'next_cursor': cursor,
                'status': 'partial' if cursor or skipped else 'complete',
                'search_scope': 'This S3 page only; pass next_cursor with the same query and folder to continue.'}
