# Current architecture

ResearchGraph is a single-user local research assistant. The [README](../README.md)
summarizes the product, diagrams and frozen measurements.

## Authority, indexing and recovery

MySQL is authoritative for Document, DocumentVersion, Chunk, Evidence metadata,
IndexJob, Entity and Relation. Chroma is a derived current-active-version index.
Raw sources are persisted locally in content-addressed storage. DocumentVersion
is immutable; historical Evidence remains in MySQL after current-version changes.

Async import/reprocess returns a job ID. MySQL persists queued/running/succeeded/
failed state, stage and error. One in-process worker reuses the indexing pipeline.
Document locks protect concurrent work; manual retry and reconciliation preserve
idempotent identities. Interrupted jobs have explicit recovery semantics. MySQL
and Chroma use eventual consistency, authoritative candidate validation, and
reconciliation rather than a cross-store transaction.

## Retrieval and Evidence

Production: BAAI/bge-small-zh-v1.5, 512 dimensions, CPU; Dense + BM25 + RRF.
BGE reranker is optional and OFF. Graph expansion is conditional/experimental;
GRAPH_EXTRACTION_ENABLED=false. Real-corpus Graph/Auto validation remains deferred.

Explicit document scopes filter candidates before final ranking; no global fallback
for an empty scope. Search scope eligibility comes from the Documents API.
Ranked evidence may not answer a question; no uncalibrated threshold is added.

Stable Evidence locator: document_id + document_version_id + chunk_id. Display
citation labels C1/C2 are local to a response. Resolution includes available page,
section and source text. Validation checks structure, references and ownership;
it does not judge semantic entailment.

## QA and Research

Ordinary Search/QA use service calls, not LangGraph or Harness. Empty QA evidence
avoids an LLM call. Only actually cited evidence is returned; invalid citations
and LLM failures do not become trusted answers.

Research uses LangGraph for plan, retrieval, extraction, coverage, bounded query
refinement, synthesis and citation validation. The Harness provides tool allowlists,
timeouts, bounded retries, schema checks, budgets and execution trace. Research API
execution remains synchronous. Partial coverage is explicit where allowed.

Fact extraction isolates each document/version. The fact_document_mismatch check
rejects foreign evidence. Cross-document combination occurs in synthesis.
Comparison citations are bound deterministically from validated Fact supports for
the document and field, deduplicated, then mapped to response citation labels.
Summary/limitations retain their citation validation contract. No automatic
semantic-support judge is claimed.

## Product and deployment

React workspaces: Overview, Library, Detail/Versions, Jobs, Search, Ask and Research.
Evidence uses a desktop side panel or responsive Drawer. Frontend nginx proxies
/api and /health to FastAPI in Compose; MySQL, Chroma, raw bytes and model cache
have persistent volumes. See [deployment](deployment.md).

Backend Vertical Gate and Final Browser Product Gate: PASS. Browser acceptance is
owner-confirmed; screenshots are DEFERRED / OPTIONAL. Quality pilot numbers remain
frozen independently of product correctness changes; see [evaluation](evaluation.md).
