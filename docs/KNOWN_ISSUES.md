# Known limitations

These items remain OPEN / DEFERRED; they do not invalidate completed product gates.

- Research API execution is synchronous; async indexing uses a single-node,
  in-process worker, with no distributed queue or scheduler.
- Retrieval recall remains limited on the small real-paper pilot. Hybrid candidate
  coverage and final Top-K ranking show a trade-off; fusion diagnostics are deferred.
- English embedding improved candidate coverage but did not provide a clear overall
  win. Chinese-oriented BGE-small-zh-v1.5 remains the production default.
- Reranker remains optional/default OFF because measured CPU latency was high.
- Citation validity is structural/reference correctness, not full semantic entailment.
  Single-document Fact evidence must belong to that document; violations fail closed.
  Per-document extraction isolation and deterministic comparison binding enforce
  provenance without retroactively changing the frozen failed pilot cases.
- Real Graph/Auto evaluation remains deferred. Graph enrichment defaults OFF.
- The real Agent pilot is small (10 tasks); human review covers only 30 units from
  7 trusted reports. Unsupported 0% is not a zero hallucination-rate claim.
- Portfolio screenshots are DEFERRED / OPTIONAL, not a completion blocker. Frontend build emits a large-bundle warning.

See [frozen evaluation](evaluation.md) and [architecture](CURRENT_ARCHITECTURE.md).
