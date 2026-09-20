# ADR-005: Conditional Graph Retrieval

Accepted for Phase 5, 2026-09-15. Decision: **KEEP AS CONDITIONAL**.

1. Graph supplements lexical/semantic retrieval for relationships and cross-document
   evidence discovery; it is not a factual-truth or claim-support oracle.
2. Do not enable it indiscriminately. The one synthetic ablation lowered semantic
   Recall@5 from 0.8333 to 0.5000 under always-on Graph, while cross-document Recall@5
   rose from 0.7708 to 0.8854. Auto preserved semantic results and improved overall
   Recall@5 from 0.8583 to 0.9042. Auto added one Top-10 Gold over Hybrid and lost none.
   This supports retaining the conditional mechanism, not generalizing a quality claim.
3. Existing MySQL normalized canonical/alias indexes, relation endpoint indexes and
   version-membership joins suffice at current scale. No migration or graph database.
   Every traversed edge must have current-ready nonempty SQL evidence.
4. Only bounded 1–2-hop BFS: visited entity/relation sets, seed/entity/path limits,
   per-hop joined SQL LIMIT, best discovered path per evidence chunk. Reverse
   navigation preserves original edge direction. It is candidate discovery rather
   than enumeration of all paths; global visited sets can omit alternative routes.
5. A centralized deterministic analyzer is explainable/testable/replacable and needs
   no LLM call. factual/semantic/exact_term -> Hybrid; relational/cross_document ->
   Hybrid + Graph. Search/QA default to auto; explicit old modes remain.
   Rules are heuristics, not a trained or validated language classifier.
6. Keep RRF: Dense/BM25 weight 1; supplemental Graph weight 0.5.
   Graph score = seed relevance × edge-confidence product × 0.7^(hop-1).
   One fixed configuration, no parameter sweep. Alias/canonical link relevance is
   1.0; text-mention fallback is 0.5. Scores are ranking heuristics.
   Existing hard_eval Gold keys are unchanged. Relational-labelled subset is absent;
   Real Research Benchmark remains unavailable. See [validation](../evaluation.md).

Evidence/Citation architecture and immutable version semantics are unchanged.
Ordinary QA remains a service pipeline, without Agent/LangGraph/Harness.
