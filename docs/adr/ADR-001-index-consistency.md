# ADR-001: SQL authority and recoverable vector publication

- Status: Accepted for Phase 1
- Date: 2026-09-14
- Scope: Index Consistency & Failure Recovery
- No schema migration, new dependency, worker, scheduler or distributed transaction.

## Context and previous failure paths

MySQL transactions cannot roll back Chroma requests. The previous indexer issued
Chroma writes before graph extraction and SQL commit. Retrieval trusted vector
metadata and emitted missing-row placeholders. QA then dereferenced those
placeholders, or returned LLM errors inside successful answers.

| Path | Previous order | Failure consequence |
| --- | --- | --- |
| New import | Job commit; uncommitted document/chunks; vector upsert; graph; SQL commit | Graph/SQL failure leaves orphan vectors |
| Same import | Hash/parser equality; succeeded job | Failed documents and missing vectors can be reported unchanged |
| Content update | Uncommitted version/chunks; vector upsert; graph; SQL commit | New vectors survive rollback |
| Stale chunks | Chroma delete; SQL deletes; commit | SQL rollback can leave still-current chunks without vectors |
| Embedding rebuild | Upsert; ready/job success; SQL commit | Partial external work has no durable publication boundary |
| Graph rebuild | Graph writes; ready/job success; SQL commit | Ready does not verify the required vector index |
| Document delete | Chroma delete; SQL delete; commit | Chroma outage prevents logical deletion; SQL rollback can lose vectors |

## Decision

MySQL is authoritative for documents, current versions, chunk text, graph facts
and jobs. Chroma is a derived, rebuildable index for the configured embedding
collection. Retrieval returns SQL text/provenance, never vector-stored text as
authority.

Consistency is eventual across stores, with a strict evidence admission boundary.
This does not promise zero physical orphan vectors or linearizability across an
LLM call. Evidence must be active in the SQL snapshot used for resolution.

### Write and update

1. Parse/chunk and capture the expected document version. Persist a running job.
2. Extract and validate graph output for changed chunks **outside a SQL transaction**.
3. Lock an existing document row and check the captured version. A concurrent
   content change causes a retryable failure instead of overwriting newer chunks.
4. In one SQL transaction, save document/version/current chunks/graph, delete stale
   chunks and their graph references, set document/job to publishing, then commit.
5. Lock the document for publication; check version and the publishing job ID.
   Only committed chunks are sent to Chroma.
6. Upsert new or missing chunk vectors in batches of 128. Refresh retained
   chunk metadata without re-embedding unchanged text. Retry/rebuild upserts all.
7. Verify every required stable ID and expected metadata field. Clean stale
   vectors after SQL commit. A cleanup failure is recorded and does not resurrect
   stale SQL chunks.
8. Commit document ready and job succeeded together. If cleanup alone failed,
   document may be ready but job is cleanup_failed and API exposes cleanup_pending.

For C1/C2/C3 -> C1/C2/C4, SQL contains only C1/C2/C4 before C3 vector cleanup.
Any remaining C3 vector fails authoritative resolution.

If Stage A fails, SQL rolls back and no vector publication occurred. A previously
ready document remains the unchanged old authoritative document; a failed new
import has a failed job, no newly ready document. If Stage B/C fails, committed
chunks remain and the document becomes publish_failed. If recording the failure
also fails, the already committed publishing state remains non-retrievable.

The publication transaction holds a document row lock during Chroma/embedding
I/O to serialize document mutations and activation. This is a deliberate,
synchronous single-user compromise: it is not a short transaction for large
documents. Graph LLM calls do not hold that lock. A worker/outbox and a more
complete generation/fencing model may later reduce this critical section.

### Graph readiness choice

Current import explicitly requires successful graph extraction and persistence,
and Search/QA default to graph_enhanced. This phase preserves that existing
import contract: graph preparation failure does not publish a new document.
It does not add graph routing, alias resolution or multi-hop quality as readiness
requirements. Decoupled optional graph availability would require a separate
graph-readiness contract and is deferred.

A graph-only rebuild prepares graph data outside the transaction, commits it with
non-ready publication state, and verifies existing vectors before activation.
It does not silently embed missing vectors. An embedding-only retry is allowed
for ready/publishing/publish_failed documents; older ambiguous failed/pending
states require full preparation.

### Same-content import and rebuild

Only ready documents whose vectors verify can return unchanged. Failed
publication retries use SQL chunks without creating another document version.
Ready documents with missing/stale vectors trigger embedding rebuild.

Collection naming already includes provider, model hash, dimension and version.
Rebuild publishes only to the configured collection and never merges collections.
Partial publication cannot activate a document. Changing embedding behavior
without changing its model/version identity is still unsafe; comprehensive
embedding-generation lifecycle belongs to Phase 3.

### Delete

Commit SQL graph/chunk/version/document removal first. Preserve IndexJob history
with nullable document_id and original ID in deletion stats. Only then contact
Chroma. Lazy Chroma initialization ensures a connection outage cannot prevent SQL
deletion. A failed cleanup leaves an invalid vector and an explicit cleanup_pending
response/job; reconciliation can finish removal. Repeated vector deletion is safe.

### Retrieval boundary and Top-K

Batch-join candidate chunk IDs to Document and DocumentVersion. Require ready,
current-version ownership and matching stable chunk ID. Dense hits additionally
must match SQL document ID, version ID and chunk hash. Invalid candidates are
excluded before fusion and final serialization, with internal ID/count logging.
Graph evidence paths must belong to their resolved chunk. Entity labels are
fetched in one batch, removing the prior candidate serialization N+1.

Chroma query has no result cursor. Start with max(2 * requested_k, DENSE_TOP_K),
capped at 200; if too few active hits remain, double the prefix, at most three
queries. Exhaustion or reaching the cap returns fewer valid results, never fake
placeholders. BM25 fetches at most 200 candidates for filtering; its existing
per-query corpus rebuild is unchanged. Graph traversal itself is not redesigned.

### Reconciliation

The service/CLI defaults to dry-run. It compares IDs in the **configured collection**
with all committed current SQL chunks, including non-ready publication states.
It reports orphan, missing and stale-metadata IDs/counts. A completely absent
collection is read as empty; dry-run does not create it.

Chroma IDs use get(limit, offset), SQL chunks use primary-key pagination. Each
page is bounded (128 by default, maximum 1000). Orphan IDs are spooled to a temporary
file before deletion so offset pagination cannot skip rows. Reports retain at
most 1000 IDs per category; --ids-jsonl streams every ID without an unbounded list.

Repair rechecks SQL before deleting an orphan, re-embeds/upserts missing or stale
entries and verifies publication. It never edits SQL or marks documents ready.
Use a dedicated clean SQL session. Pause concurrent imports/rebuilds/deletes
during repair for a stable inventory; concurrent writes can make a scan
approximate and require another pass. Any transient stale vector still fails
retrieval's identity/version/status checks. No cross-store atomic snapshot is
claimed.

Reconciliation does not rewrite historical failed jobs. Inspect documents and
retry reindex to activate publishing/publish_failed documents. For Stage-A errors,
retry the original import (raw source bytes are not retained).

### QA/error contract and observability

No valid complete evidence -> status=insufficient_evidence, no LLM call.
LLM errors propagate as code=1 with typed error data; configuration, timeout,
network, invalid response and provider errors are distinct. Successful QA adds
status=answered and retains answer/citations/search. ParserError maps to HTTP 400.

Logs include orphan_candidate_filtered_count, vector_publish_failure,
vector_delete_failure, reconciliation_orphan_count, reconciliation_missing_count.
Structured LogRecord extras hold IDs/counts, not credentials or provider bodies.
No new metrics framework. Citation identifiers/semantic support are not validated
by this phase.

## Alternatives

| Alternative | Assessment |
| --- | --- |
| Chroma first + compensating deletion | Rejected: graph/SQL rollback and cleanup failure still leave invalid vectors; can lose valid vectors on update |
| Bare DB first | Necessary but insufficient: without a non-ready gate, verification and retries, missing indexes still look successful |
| SQL authority + publication gate + filtering + reconciliation | Selected: small synchronous change, observable and replayable |
| Distributed transaction / 2PC | Rejected: the Chroma API used here is not enlisted in the SQL transaction; operational complexity exceeds this single-machine scope |
| Transactional outbox + async worker | Deferred: useful for unattended durable retries and throughput, but requires scheduling/worker state outside this phase |

## Consequences and limits

Physical orphan/missing vectors can temporarily exist. Repair is operator-driven.
Graph preparation and embedding can still be expensive; graph cleanup/traversal
retain existing query costs. Large-corpus reconciliation is bounded in memory but
has not been load-tested at a million vectors. Parallel write/read/reconcile and
ambiguous network outcomes are not comprehensively stress-tested.

Duplicate chunk identity, raw source preservation, immutable historical evidence,
real BGE quality/defaults, BM25 caching, graph routing/aliases/multi-hop, citation
semantic validation and benchmark metric corrections remain open.

See [validation](../evaluation.md) and [known issues](../KNOWN_ISSUES.md).
