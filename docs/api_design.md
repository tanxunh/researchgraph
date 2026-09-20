# API Design

Current active API surface for LifeFlow ResearchGraph.

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/health` | Backend health check |
| GET | `/api/system/status` | Counts for documents, chunks, entities, relations, index jobs, and embedding status |
| POST | `/api/documents/import` | Import text or URL document |
| POST | `/api/documents/import/file` | Import PDF, DOCX, TXT, or Markdown file |
| GET | `/api/documents` | List indexed documents |
| GET | `/api/documents/{document_id}` | Get document detail and chunks |
| POST | `/api/documents/{document_id}/reindex` | Reindex in `full`, `embedding_only`, or `graph_only` mode |
| DELETE | `/api/documents/{document_id}` | Delete document and clean vectors, mentions, and relations |
| POST | `/api/search` | Search with `vector`, `hybrid`, or `graph_enhanced` mode |
| POST | `/api/qa` | Generate grounded answer with citations |
| POST | `/api/evaluations/run` | Run retrieval evaluation |
| GET | `/api/evaluations/latest` | Read latest evaluation report |

Removed API families: Agent, Todo, Skill, Memory, MCP, external sync, and legacy resource CRUD.
## Phase 1 response contract

Existing paths and success envelope remain. Normal successful Search results are
complete SQL-backed evidence; missing/orphan/non-ready candidates are excluded.
Search may return an empty results list if no valid candidates remain.

QA retains answer/citations/search and adds data.status:

```json
{"code":0,"message":"success","data":{"status":"insufficient_evidence","answer":"Evidence is insufficient.","citations":[],"search":{"results":[]}}}
```

The actual no-evidence text is Chinese. No LLM call occurs for this result.
A generated answer uses status=answered.

LLM failures are an intentional correction to previous success-shaped failures.
HTTP 200 is retained for this existing business-error envelope; clients must
inspect code, as the central frontend client already does:

```json
{"code":1,"message":"LLM_API_KEY is not configured.","data":{"error_type":"llm_configuration_error"}}
```

Other error_type values: llm_timeout, llm_network_error, invalid_model_response,
llm_provider_error, retrieval_error. Error responses contain no answer or provider
response body. Consumers that relied on error text as a successful answer must
handle code=1. Citation semantics are not validated by this contract.

Import ParserError now returns HTTP 400 with code=1, message and data=null.
No OCR or parsing feature was added.

Document status may now be publishing or publish_failed as well as legacy states.
Only ready/current-version chunks are evidence candidates. Update success can
include data.stats.cleanup_pending=true; delete success includes
data.cleanup_pending=true when SQL deletion succeeded but vector cleanup failed.
The job records cleanup_failed; reconciliation finishes derived-index cleanup.
Reindex failure returns code=1; it never reports a partial vector rebuild as
success. Graph-only verifies existing vectors rather than silently embedding.

## Phase 4 QA contract (additive fields, stricter success admission)

POST /api/qa and request fields remain unchanged. The existing default mode is
still graph_enhanced; use mode=hybrid explicitly for Dense + BM25 + RRF.
QA success is typed as QASuccessEnvelope / QAResponse; business failures retain
HTTP 200 with code=1. No migration or new conversation persistence is required.

- Existing status, answer, citations, search fields remain.
- evidence_count and retrieved_evidence_count both count unique evidence admitted
  to the prompt after contract filtering and budgeting (not raw retrieval hits).
- citation_validation includes valid, used_citation_ids, invalid_citation_ids,
  missing_citation, warnings and reason. Validation is structural/referential only.
- citations contains only actually referenced evidence, ordered by evidence rank;
  repeated [C1] references yield one entry and a repeated_citation warning.
- Each citation retains citation_id, chunk_id, document, location and
  document_version_id, and adds document_id, document_title, page, section,
  ordinal, snippet (at most 1,000 characters), source_type, source_reference and
  source_snapshot_available. page/section may be null when the parser has no value.
- C1 is response-local. Persist document_id + document_version_id + chunk_id for
  durable identity, and resolve that exact version rather than current_version.
- source_reference is an opaque document-version:<id> reference, not a downloadable
  URL. For source privacy, nested document.source_uri in QA citations and QA search
  results uses that same opaque reference. No local storage key or absolute source
  path is exposed as a locator. This is a documented value-semantic tightening;
  the field itself remains present. Search API source_uri behavior is unchanged.
- source_snapshot_available describes an SQL reference, not a file integrity probe;
  legacy absent snapshots produce raw_source_unavailable in validation warnings.
- search.results contains only evidence admitted to the prompt; candidates and
  actual citations are not interchangeable. Whole evidence entries are capped at
  20 and 12,000 rendered evidence characters including metadata; oversized entries
  are skipped rather than silently truncating their text. Request top_k still applies.

Zero admitted evidence returns status=insufficient_evidence, citations=[],
evidence_count=0 without calling the LLM. With evidence, the prompt permits exactly
`无法从提供的资料确认答案。` as an uncited insufficiency response; additional uncited
content fails conservatively. Other uncited nonempty answers, malformed IDs such as
[C01], unknown IDs such as [C999], or unresolvable/mismatched historical evidence return:

```json
{"code":1,"message":"Answer citation validation failed.","data":{"error_type":"citation_validation_failed","citation_validation":{"valid":false,"used_citation_ids":["C999"],"invalid_citation_ids":["C999"],"missing_citation":false,"warnings":[],"reason":"citation_validation_failed"}}}
```

The rejected answer is not returned and there is no automatic ID repair, second
LLM call or semantic judge. Existing typed LLM errors remain distinct from evidence
insufficiency. The historical resolver now supports batch locators; no public
source-download/historical-resolution route was added. A successful reference check
uses the SQL session snapshot and does not establish semantic claim support,
physical source-file integrity, or durability after intentional document deletion.

## Swagger/manual checks

Start backend as documented in the root/backend README and open /docs.
With a configured formal graph LLM, POST /api/documents/import:

```json
{"source_type":"text","title":"Phase 1 check","source_uri":"manual:phase1","text":"Method Alpha is evaluated on Dataset Beta."}
```

Expected: code=0, data.status=ready, index_action=created (or unchanged on repeat).
Inspect GET /api/documents/{id}; then POST /api/search with
{"query":"Method Alpha","mode":"hybrid","top_k":5}. All returned rows have text,
document, location and scores. POST /api/qa with the same question returns
answered with a working LLM, or a code=1 typed model error. On an empty isolated
test index it returns insufficient_evidence and does not contact LLM.

For repeatable offline checks, use the smoke test and fault-test commands in
[Testing and CI](testing_ci.md). They create only disposable synthetic data.

## Phase 2 additions (existing paths retained)

| Method | Path | Request / result |
| --- | --- | --- |
| GET | /api/documents/{document_id}/versions | limit=50 (max 200), offset=0; list of version row id, per-document version number, current/pending flags, timestamp, source checksum, raw_source_available, parser/chunker/config identity |
| POST | /api/documents/{document_id}/reprocess | {} selects current snapshot; {"source_version_id":12} selects an owned version row; uses current parser/chunker config |
| POST | /api/documents/import/file | Existing multipart file plus optional source_uri to distinguish logical documents with the same filename |

raw_source_available describes the presence of a stored SQL reference, not a live storage integrity probe. Reprocess verifies actual bytes/checksum. No public source-download or historical-resolver API is introduced.

Text/file/URL imports now persist raw bytes before parsing; URL fetches once and parses that snapshot. Same logical source and current config remains unchanged. Changed raw checksum/parser/chunker creates a version; embedding_only/graph_only/full reindex uses stored chunks without a new version. Supplying an older snapshot creates the next version if different from current.

Document detail adds pending_version and per-chunk document_version_id/occurrence_index. Its chunk list is current membership. Search retains existing fields and adds top-level document_version_id, chunk_occurrence_id, document.version_id and location.ordinal. QA citation mappings include document_version_id, so clients can persist version + chunk identity. These locators preserve evidence identity, not proof of claim support.

Legacy/corrupt/missing raw source example (HTTP 200 business-error envelope):

```json
{"code":1,"message":"raw_source_unavailable: upload the original source before reprocessing.","data":{"error_type":"raw_source_unavailable"}}
```

Version list example (abbreviated):

```json
{"code":0,"message":"success","data":[{"id":12,"version":2,"is_current":true,"is_pending":false,"raw_source_available":true}]}
```

For Swagger validation, first migrate/start as documented, import a small UTF-8 document, record version id and chunk id, then repeat import (unchanged). Change parser/chunker config, restart the backend, reprocess with {} and list versions (new version, old retained). Search should only return new current membership. A PDF/DOCX reprocess reads its stored upload bytes. The resolver service is covered directly by integration tests.

Safe ASCII PowerShell example against an already configured running backend:

```powershell
$body = @{source_type="text"; title="Phase 2 check"; source_uri="manual:phase2"; text="Method Alpha is evaluated on Dataset Beta."} | ConvertTo-Json
$result = Invoke-RestMethod -Uri http://127.0.0.1:8000/api/documents/import -Method POST -ContentType "application/json; charset=utf-8" -Body $body
$documentId = $result.data.document_id
Invoke-RestMethod -Uri "http://127.0.0.1:8000/api/documents/$documentId/versions"
Invoke-RestMethod -Uri "http://127.0.0.1:8000/api/documents/$documentId/reprocess" -Method POST -ContentType "application/json" -Body '{}'
```

A working configured graph LLM is needed for business import. Offline smoke uses isolated Fake/mock services instead. Common failures: migrate incomplete schema; restore storage path/permissions; upload original legacy sources; restore Chroma then reconcile/retry publication. No empty AI output is treated as success.


## Phase 7 async indexing

Existing synchronous import/reprocess routes remain compatible. New endpoints:

| Method | Path | Behavior |
| --- | --- | --- |
| POST | `/api/documents/import/async` | Existing text/URL request schema; commit queued job and return HTTP 202 |
| POST | `/api/documents/import/file/async` | Multipart file and optional source_uri; PDF/DOCX/TXT/Markdown, maximum 8 MiB |
| POST | `/api/documents/{document_id}/reprocess/async` | Existing reprocess schema; pin owned source version at enqueue |
| GET | `/api/index-jobs/{job_id}` | Durable status, progress_stage, error, attempts, document_id, pipeline_job_id and result |
| POST | `/api/index-jobs/{job_id}/retry` | Requeue only failed jobs; same job_id; attempts increments on worker claim |

Accepted example: `{"code":0,"message":"success","data":{"job_id":123,"status":"queued"}}`.
HTTP acceptance waits for upload/request validation and SQL persistence, not parsing
or indexing. Statuses: queued / running / succeeded / failed. Progress stages:
queued, starting, fetching (URL), parsing, chunking, indexing, publishing, completed.
A failed job retains its last stage and exposes a sanitized error/error_type.
Payload/source bytes are never returned by status APIs. Unknown job: 404; invalid
input: 400; non-failed retry: 409; unavailable job storage: 503 with code=1.

Only the background worker calls the existing ingestion/indexing pipeline. Pipeline
jobs remain separate audit records linked through pipeline_job_id; their existing
publishing/cleanup states do not replace the four async lifecycle states. A valid
old ready version can remain ready when preparation of new input fails; failed new
publication cannot activate an unverified version. Cleanup-pending remains the
existing verified-publication warning, not an indexing failure.

Run/migration, retry, interruption and limits: [Phase 7 validation](evaluation.md).


## Public document scope (Pre-Phase 11 API Contract Closure)

POST `/api/search` and POST `/api/qa` accept optional `document_ids: list[int] | null`.
Omitted/null retains existing global behavior. A non-null list is forwarded to the
existing retrieval filter before candidate ranking and Top-K. An empty list or
scope without eligible current-ready documents yields no evidence, never global
fallback; QA does not call the LLM when evidence is empty.
Scoped `auto` uses `hybrid` explicitly at the public API boundary (response mode is
`hybrid`); scoped `vector` and `hybrid` retain their existing implementation.
Scoped `graph_enhanced` returns HTTP 422 because existing Graph retrieval does not
support scope. Unscoped Auto/Graph behavior is unchanged. Evidence/Citation response
contracts and production retrieval configuration are unchanged.
Example: `{"query":"optimization objective", "mode":"hybrid", "document_ids":[1], "top_k":5}`.
QA uses `question` instead of `query`.

Async document resolution: **VIA JOB RESOURCE**. POST async import retains HTTP
202 `{job_id,status}`; GET `/api/index-jobs/{job_id}` exposes `document_id` once
associated, and callers poll until terminal status. No ID reservation, response
change, lifecycle change, dependency or migration is introduced.


## RG-003: optional Graph enrichment

Graph is optional derived enrichment. `GRAPH_EXTRACTION_ENABLED=false` is the
production default. Base document readiness depends on raw source, parsing,
chunking, embedding and verified vector publication; it does not require Graph.
Disabled import/full reindex skips Graph extraction and does not send Graph LLM
requests. New chunks record `not-extracted`; extraction counts remain zero.
Explicit `graph_only` reindex requires enabling extraction. Existing Graph is not
silently deleted when extraction is disabled; current-version validation still applies.
With `GRAPH_EXTRACTION_ENABLED=true`, the existing extraction algorithm and
pre-publication failure semantics remain unchanged. Enabling the flag alone does
not backfill unchanged documents; use the existing explicit graph_only reindex.

Graph availability is based on current-ready evidence-backed relations, not merely
the extraction flag. Explicit graph_enhanced with unavailable Graph returns
`graph_unavailable`. Auto keeps the same query classification and falls back to
Hybrid with `graph_enabled=false` and reason `graph_unavailable_hybrid_fallback`.
Search/QA and Research's stable non-Graph retrieval remain usable without Graph.
Real Graph validation remains **OPEN / DEFERRED**. No model, ranking parameters,
Graph algorithm, prompt, Research workflow or Harness changes are part of this fix.

## Public Index Jobs (Phase 11A.1)

GET `/api/index-jobs` returns `{code:0,message:"success",data:{items,page,page_size,total,summary}}`.
Query: page >= 1 (default 1), page_size 1..100 (default 20), optional status
(queued/running/succeeded/failed), operation (async_import/async_reprocess), and
positive document_id. Items and total follow all filters. Summary always counts
ALL user-facing async jobs across the database, ignoring every filter and page:
queued, running, succeeded, failed. Internal pipeline jobs are excluded via job_type.

Items reuse GET-by-id serialization: job_id, document_id (nullable), job_type,
status, progress_stage, attempts, pipeline_job_id, error_type, error, created_at,
started_at, finished_at, result. Raw payload/source bytes and storage paths are not
added. No source_name is derived from arbitrary source URIs. Queued imports with
no document association remain discoverable; later reads reflect the real association.
Ordering: non-null created_at first, created_at DESC, id DESC; historical NULLs
last, id DESC. Pagination is offset-based, not a snapshot across concurrent writes.
GET by id adds only nullable created_at; retry and system/status contracts are unchanged.

Creation time is written using the existing UTC application timestamp helper on
new async and pipeline records. It is never changed by retry. started_at retains
its existing behavior (initialized at enqueue, overwritten when an attempt starts);
finished_at remains completion/failure time. Neither is used to backfill created_at.
Historical jobs created before migration may have created_at=null.

Existing databases: stop application writers, back up MySQL, then run from backend:
`python -m scripts.migrate_index_job_created_at`. For Compose, after building the
updated backend: `docker compose stop backend`, then
`docker compose run --rm --no-deps backend python -m scripts.migrate_index_job_created_at`,
then `docker compose up -d backend`. Apply earlier required migrations first.
The additive MySQL migration uses an advisory lock and revision ledger, is safe to
rerun, and performs NO backfill or SQL timestamp default. Fresh databases get the
column through existing schema creation; existing schemas missing it fail startup
with the migration command. No business database was migrated by the test run.

Example: `GET /api/index-jobs?page=1&page_size=20&status=failed`.
Retry a listed failed item with POST `/api/index-jobs/{job_id}/retry`; its job_id and
created_at remain stable. Non-failed jobs still reject retry (409).

## Phase 11D.1 Search scope eligibility

POST /api/search resolves explicit document scope against MySQL before retrieval.
Omitted/null document_ids preserves global behavior and adds scope={mode:global}.
An empty list returns HTTP 422, code=1, data.error_type=empty_document_scope.
A non-empty scope with no eligible documents returns HTTP 200, code=1,
data.error_type=no_eligible_documents; neither case calls Retrieval.
Eligibility means status=ready and a matching current DocumentVersion exists.
Existing but non-eligible documents use not_ready; absent IDs use not_found.

Successful explicit searches add data.scope containing mode=explicit,
requested_document_ids (deduplicated in request order), eligible_document_ids,
and excluded_documents=[{document_id,reason}]. Partial scopes search only eligible
IDs using the existing pre-ranking filter. Valid scope with no hits remains
code=0/results=[]. Error responses also include data.scope. Global metadata does
not enumerate the corpus. Existing Evidence/result fields, modes and top-k remain
unchanged; QA scope behavior is unchanged. Metadata describes resolution before
retrieval; existing authoritative candidate validation remains in place.

Example: {"query":"local PDF ingestion","mode":"hybrid","document_ids":[25,2147483647]}.
When 25 is ready with a current version, only 25 is searched; the missing ID is
listed as not_found. Use Swagger POST /api/search with [] to verify the 422 code.
Do not interpret no_eligible_documents as a successful zero-result query and do
not retry it globally. No migration, new dependency or external LLM is required.
