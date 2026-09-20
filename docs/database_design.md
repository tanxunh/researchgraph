# Current Database Design

MySQL (utf8mb4) is the authority for ten application tables: documents, document_versions, document_chunks, document_version_chunks, entities, entity_aliases, entity_mentions, relations, index_jobs, evaluation_runs. schema_migrations records formal revisions. Chroma stores current derived vectors; local storage holds original bytes.

## Evidence tables

| Table | Identity / fields | Semantics |
| --- | --- | --- |
| documents | Existing unique(source_type, source_uri), current_version; new nullable pending_version | Logical document and publication state. current_version is a number, not the version row ID; zero before first activation |
| document_versions | Unique(document_id, version); source_checksum/key/content_type/encoding/type/uri/title; parser_version; chunker_version, size, overlap, config hash, evidence identity hash | Immutable source and parser/chunker snapshot. Raw/config fields can be NULL for legacy |
| document_chunks | Stable ID; unique(document_id, chunk_hash, occurrence_index) | Reusable occurrence and immutable text. Existing version/location fields record creation provenance only |
| document_version_chunks | Version FK, chunk FK, ordinal, page_number, section_title; unique(version, chunk), unique(version, ordinal) | Immutable membership and location for that version |

Both membership foreign keys are indexed. Version source_storage_key and evidence_identity_hash are indexed. Existing document/version and chunk/stable-ID uniqueness supports direct historical lookup. Source keys are relative content-addressed keys, not user paths. No unlimited configuration JSON is stored. Parser-provided page/section and ordinal are stored; unavailable character offsets are not invented.

ORM guards reject updates to evidence fields; derived embedding/graph metadata can change. These guards do not prevent administrator SQL changes. Historical graph versions are not stored. EntityMention/Relation continue to reference chunk IDs and represent current retrieval only.

## Migration

Run revision 20260914_evidence_versions through [the migration CLI](../backend/migrations/README.md) before starting against an existing Phase 1 database. It adds columns/membership/indexes and backfills only surviving evidence. It preserves IDs, text and rows; no user-table drop/recreation. Legacy original-source fields remain NULL. Old deleted chunks/overwritten history cannot be reconstructed.

Empty database startup initializes schema and migration ledger. Existing schema startup requires the revision to be complete. Existing SQLite schema upgrades are intentionally unsupported; SQLite is a disposable test substrate, not the production migration target.

## Publication and deletion

Prepared version/membership and graph commit with pending_version/publishing; current_version advances only after verified vector publication. Normal retrieval joins ready/current memberships. Reconciliation expects pending/current membership to finish publication without activating SQL.

Updates retain historical SQL chunks and memberships while removing historical-only vectors. Document deletion removes its full evidence history and graph references, commits SQL, then removes vectors and unreferenced blobs. Shared source bytes survive other documents' references. [ADR-002](adr/ADR-002-raw-source-and-evidence-versioning.md) describes invariants and backup/GC coordination.


## Phase 7 IndexJob extension

MySQL remains job source of truth; no new table or queue infrastructure. Additive
revision `20260916_async_index_jobs` extends index_jobs with nullable progress_stage,
payload_json, source_data (MySQL LONGBLOB), pipeline_job_id and attempts (default 0).
Existing rows, statuses, IDs and audit records are preserved. job_type async_import /
async_reprocess identifies queue records; pipeline_job_id links the existing pipeline
audit job without changing its publication fencing. document_id remains nullable
before document creation and ON DELETE SET NULL after deletion.

Text/file bytes are durable in source_data before HTTP 202. URL bytes are persisted
once fetched, before parsing; retries reuse that snapshot. Reprocess pins a source
version ID. Completed/failed task input remains retained for manual retry/audit;
there is no automatic payload-retention cleanup in Phase 7. Raw-source persistence
and immutable DocumentVersion membership still belong to the existing pipeline.

Stop application writers, then run from backend:
`python -m scripts.migrate_async_index_jobs`. Migration is additive/restartable;
existing tables are never recreated. Startup checks required columns. Existing
pre-Phase-2 databases must first complete the evidence-version migration. Empty
DB initialization creates the current model schema directly.

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
