# V2 evaluation

## Protocol and configuration

30 real papers; 35 DEV / 40 TEST. Configuration selection used DEV. The retrieval stack was frozen before the single final TEST evaluation; no post-TEST retrieval tuning. Frozen results are referenced here, not recalculated during release hardening.

TextChunker target 700 characters, overlap 100, page-contained; BGE-M3; BM25 and Dense depth 200; weighted RRF (BM25 1.25, Dense 1.0, k=20); BGE-reranker-base Top20 to Top10. This is an evaluation configuration, not the product default. See [frozen manifest](../benchmarks/real_research/v2/final_retrieval_manifest.json).

## Evidence retrieval

Macro query-level recall uses Gold evidence locators, not document hits. MRR@10 is truncated to rank 10. Candidate recall describes the pre-reranker candidate set; final output metrics are reported separately.

| Route | R@10 | MRR@10 | CR@20 | CR@50 |
|---|---:|---:|---:|---:|
| BM25 | 39.58% | 0.2900 | 51.04% | 72.29% |
| Dense | 42.92% | 0.3087 | 52.92% | 71.88% |
| Hybrid | 46.25% | 0.2830 | 62.50% | 79.38% |
| Reranked | 59.17% | 0.3802 | n/a | n/a |

Reranked R@5=45.83%, Hit@5=55.00%. Relative to Hybrid Top10: 6 recovered Gold units, 1 lost. Cross-document TEST remains a severe limitation. See [saved metric CSV](../benchmarks/real_research/v2/v2_f_test_metrics.csv).

## Workflow POC

Runtime: RECONSTRUCTED_EVALUATION_RUNTIME. Review: MODEL_ASSISTED_SEMANTIC_REVIEW, not independent human evaluation. Track A is FROZEN_CONTEXT; Track B-R is RECONSTRUCTED_RESEARCH_AGENT. Both retain n=40, including two B-R workflow failures.

| Track | Complete | Partial | Incorrect | Correctly cited complete |
|---|---:|---:|---:|---:|
| A | 23/40 (57.50%) | 9/40 (22.50%) | 8/40 (20.00%) | 23/40 (57.50%) |
| B-R | 28/40 (70.00%) | 9/40 (22.50%) | 3/40 (7.50%) | 28/40 (70.00%) |

Paired: 9 improved, 30 unchanged, 1 regressed; incomplete to complete 6, complete to incomplete 1. Strict cross-document FULL: A 0/8, B-R 1/8. Strict multi-hop FULL: A 2/6, B-R 1/6. These strict evidence-based criteria differ from semantic answer completeness.

Readiness remains PARTIAL. No production-readiness, reliable cross-document, generalization or causal claims follow from these small samples. V1 used different corpus/protocols and is not a controlled comparison. Full descriptive analysis: [POC report](V2_POC_FINAL_REPORT.md); [data policy](evaluation_data_policy.md); [test boundary](testing_ci.md).
