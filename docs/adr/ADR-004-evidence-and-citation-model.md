# ADR-004: Evidence and citation identity

Status: Accepted for Phase 4 (2026-09-15).

1. **Retrieval results are not Evidence.** Rankings and channel diagnostics are
   retrieval implementation details. A thin EvidenceBuilder admits the QA contract
   from already-authoritatively-validated current/ready candidates, without a
   second consistency scan. It deduplicates by document/version/stable chunk ID,
   preserves ranking order, and bounds the rendered context to 20 whole evidence
   entries and 12,000 characters. One Evidence schema supplies the prompt and
   citation mapping; Citation is its bounded public projection, not another domain model.
2. **Citations bind immutable versions.** C1/C2 identify entries only within one
   answer. Durable identity is document_id + document_version_id + stable chunk_id.
   Page/section/ordinal come from DocumentVersionChunk, not the chunk's creation
   location. Reuse the historical resolver through a batch adapter; never redirect
   an old citation to current_version. No migration or chat-history table is needed.
3. **Return actual citations only.** After generation, parse the used handles and
   return their Evidence projections in ranking order. Deduplicate repeated uses
   with a warning; candidate count and cited count are different concepts. Keep
   legacy answer/citations/search fields, but search contains only prompt-admitted
   entries. Public source references are opaque document-version references; raw
   storage keys and absolute filesystem source URIs are not citation API fields.
4. **Validate structure/references, not truth.** One deterministic validator checks
   canonical [C#] syntax, unknown/malformed/missing references, and batch-resolved
   historical SQL text/location/ownership. Invalid answers produce the existing
   code=1 envelope with citation_validation_failed, never a successful answer with
   silently repaired IDs. Repeated IDs are legal. No evidence means no LLM call;
   the exact prompted insufficiency sentence may omit citations, while arbitrary
   uncited content fails closed. No second LLM, NLI or semantic judge is introduced.
   Resolution uses the SQL session snapshot; it is not a cross-LLM-call transaction,
   claim-support proof, or raw-file integrity probe. Legacy absent raw sources are
   explicitly flagged and warned, not fabricated. Full document deletion removes
   history and makes future resolution fail.
5. **Ordinary QA remains a service pipeline.** Retrieval -> Evidence -> prompt ->
   one LLM call -> deterministic validation -> response needs neither LangGraph nor
   Harness. Keep API mode defaults for compatibility; hybrid remains an explicit
   request mode. Research tasks, graph correctness, semantic evaluation, workers
   and agent orchestration remain separate future scopes.
