# ADR-006: Optional post-fusion reranking and real evaluation

Status: accepted for engineering; quality decision NOT ENOUGH REAL DATA.

1. Synthetic fixtures test controlled behaviors; their invented vocabulary, labels
   and small scale cannot establish real-paper retrieval quality.
2. Gold must be independently human-reviewable. Structural locator checks cannot
   prove semantic relevance or human authorship; pending/unresolved Gold is unscored.
3. Candidate Recall@20 separates retrieval coverage from ordering. A reranker cannot
   recover evidence absent from its candidate set. Paired runs share the same set.
4. Reranking follows validated RRF fusion and precedes Evidence construction. Its
   scorer sees only text pairs, returns scores and cannot create evidence identities,
   query SQL, alter versions or participate in Citation validation.
5. Production remains disabled until real benchmark gains and acceptable latency are
   demonstrated. Failures preserve original ranking and emit observable diagnostics.
   Current disposition is optional infrastructure, not a validated quality feature.
6. Keep BGE-small-zh-v1.5 fixed to isolate the experiment. Possible English/domain
   mismatch is a remaining risk, not justification for a multi-model sweep here.

One model: BAAI/bge-reranker-base, pinned revision, CPU; existing optional
sentence-transformers runtime. No migration, Agent/Harness, Graph redesign or API
contract change. Phase 5 Graph decision remains KEEP AS CONDITIONAL.
