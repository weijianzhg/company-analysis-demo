# Internal knowledge MCP

Read company Markdown documents from an existing S3 bucket. The agent discovers
three tools from this service, alongside the financial tools from Alpha Vantage.
The service has no model, embeddings, database or write tools.

| Tool | Purpose |
| --- | --- |
| `list_internal_documents` | Browse one folder, returning subfolders and Markdown files |
| `search_internal_knowledge` | Search keywords recursively within a folder |
| `read_internal_document` | Read a document and return its S3 source, modification date and retrieval time |

## Folder layout

Keep ordinary UTF-8 `.md` or `.markdown` files in S3:

```text
s3://your-bucket/knowledge/
└── companies/
    ├── IBM/
    │   ├── research.md
    │   └── meetings/2026-10-29.md
    └── ACME/
        └── strategy.md
```

With `KNOWLEDGE_PREFIX=knowledge/`, the agent sees paths such as
`companies/IBM/research.md`. Paths are relative to the configured root. The caller
cannot select a different bucket or escape the prefix.

Search matches all whitespace-separated terms, case-insensitively, across a file's
path and contents. It scans one S3 page per call (20 keys by default, at most 100).
Use a company folder to narrow the search. Pass `next_cursor` as `cursor`, keeping
the same query, folder and page size, to continue. Browse is also paginated; pages
containing only non-Markdown files can be empty and still have a next cursor.

Files are limited to 64 KiB each. Search reports oversized, unreadable or invalid
UTF-8 files as `skipped`, and reports `partial` when files were skipped or more pages
remain. An empty page is not proof that the bucket contains no matching information.
This intentionally simple scan suits a small demo corpus; large collections need
an index. Read results are not cached, so later reads see document updates.

## Run locally

See the [three-service local guide](../docs/local.md). The key settings are:

```dotenv
KNOWLEDGE_BUCKET=your-internal-knowledge-bucket
KNOWLEDGE_PREFIX=knowledge/
AWS_PROFILE=your-profile
AWS_REGION=eu-west-1
MCP_PORT=8001
```

Set `INTERNAL_KNOWLEDGE_MCP_URL=http://127.0.0.1:8001/mcp` on the agent. The
financial MCP remains on port 8000. Each deployed container uses port 8000.

To try fictional notes, upload the included example into your chosen bucket:

```bash
aws s3 cp internal-knowledge-mcp/examples/ s3://YOUR-BUCKET/knowledge/ --recursive
```

The example is explicitly labeled synthetic and contains no real internal research.

## Deploy

The [root guide](../README.md) builds and deploys all three services. Set
`knowledge_bucket` and `knowledge_prefix` in this service's `infra/terraform.tfvars`.
The bucket must already exist in the deployment region. Terraform grants the runtime
role `s3:ListBucket` restricted by prefix and `s3:GetObject` on that prefix. It does
not create, upload, change or delete knowledge documents.

For customer-managed SSE-KMS encryption, set `knowledge_kms_key_arn` and allow the
runtime role in the key policy. Cross-account buckets also need a bucket policy.
All agent users share this service's configured knowledge scope; the demo does not
implement per-user document permissions.

Copy this stack's `agent_runtime_arn` into
`internal_knowledge_mcp_runtime_arn` in the agent Terraform settings. Only the MCP
role reads S3; the agent role gets permission to invoke the configured MCP runtimes.

After uploading the sample and deploying, verify both MCPs and real model tool use:

```bash
uv run --project company-agent/agents --frozen python cloud/test_end_to_end.py \
  --mode fixture --knowledge-path companies/IBM/research.md --require-tool-events
```

## Read the code and test

- `mcp_server/server.py` declares the three MCP tools.
- `mcp_server/knowledge.py` handles S3 access, paths, pagination and keyword matching.
- `infra/` defines the MCP runtime, image repository and scoped IAM role.
- `tests/` uses Moto to exercise S3 without AWS credentials.

Run `./test-local.sh` at the repository root. It also starts both MCPs over HTTP and
runs one Strands analysis that uses financial data, folder browsing, search and a
full document read. The scripted test model verifies integration, not model quality.
