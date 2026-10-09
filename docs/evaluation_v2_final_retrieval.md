# V2-F Retrieval Freeze + Final TEST

Status: **COMPLETE**.

## Immutable retrieval manifest

Pre-TEST SHA-256: `25ad0da5ba9de34e6e488d593a2fd972f4410712ab7e23d22631961e03cf850f`.
Final SHA-256: `bc601f31786987de88a1a9b1851508960332371654bc9d3a81f0e4a8a4f94e7a`.

Frozen pipeline: TextChunker target 700 / overlap 100 / page-contained, 3,837 chunks; BAAI/bge-m3 RAW query/document, CLS normalized 1024 dimensions, max length 8192; production BM25 Top200 and Dense Top200; weighted RRF 1.25 / 1.0, k=20, fused Top100; BAAI/bge-reranker-base Top20 to Top10, alpha=1.

Every component is pinned through its existing configuration SHA, model revision and index identity. The original manifest bytes are retained in `pre_test_manifest.json`. After successful TEST execution, only validation state/provenance were added to the final manifest; individual component configurations are unchanged. The final hash is stored externally, avoiding a self-referential hash.

`DEV_SELECTED=true`, `TEST_VALIDATED=true`, `PRODUCTION_DEFAULT=false`. No production rollout or workflow evaluation is implied.

## Execution discipline

One complete DEV reproduction was run first. All 35 queries reproduced frozen BM25 Top200, Dense Top200, Hybrid Top100 and reranker Top20 order. Metrics matched D/E exactly. TEST queries were not read until DEV passed. TEST Gold was then mechanically validated against authoritative BASE chunk text, document/version, source offsets, source hash and immutable chunk IDs; no semantic changes or portable remapping were made.

PRE_TEST_LOCK was saved before any TEST inference. Each of the 40 TEST queries has exactly one STARTED and one COMPLETED journal entry under that manifest. A filesystem exclusive execution lock rejects repeated invocations. Warm-up used a previously seen DEV query, never a TEST query. No TEST-based parameter change, candidate selection, retry or second evaluation occurred.

BM25 used the exact existing implementation over the immutable B6 authority snapshot in occurrence-ID order. Chroma queried a copy of the frozen index; original index files were protected by hashes. Local models ran offline on CPU. This is the real local retrieval/model stack with snapshot authority, not HTTP/live-MySQL benchmarking. Corpus vectors were not re-encoded or reinserted.

## Gold and metric interpretation

DEV: 35 queries / 55 reviewed minimal evidence spans, evaluated with 100% containment mapping. TEST: 40 queries / 63 original frozen BASE chunk-locator Gold units.

DEV and TEST use their respective frozen annotation contracts. TEST was not retroactively converted into minimal-span labels. Consequently direct DEV-to-TEST differences combine dataset difficulty and annotation-granularity effects; they do not isolate generalization or prove algorithm improvement.

Metrics are query-macro averages. Each Gold unit contributes at most once. Document hits are never substituted for Evidence hits. Candidate recall belongs exclusively to pre-rerank Hybrid; the final reranker exposes only Hit@5, R@5, R@10 and MRR@10.

## DEV reproduction

| Stage | Hit@5 | R@5 | R@10 | MRR@10 | CR@20 | CR@30 | CR@50 |
|---|---:|---:|---:|---:|---:|---:|---:|
| hybrid | 54.29% | 39.05% | 54.05% | 0.3081 | 77.86% | 78.57% | 80.00% |
| reranked | 62.86% | 47.62% | 68.81% | 0.3206 | N/A | N/A | N/A |

## TEST metrics

| Stage | Hit@5 | R@5 | R@10 | MRR@10 | CR@20 | CR@30 | CR@50 |
|---|---:|---:|---:|---:|---:|---:|---:|
| bm25 | 35.00% | 30.00% | 39.58% | 0.2900 | 51.04% | 61.04% | 72.29% |
| dense | 40.00% | 34.17% | 42.92% | 0.3087 | 52.92% | 56.25% | 71.88% |
| hybrid | 45.00% | 35.83% | 46.25% | 0.2830 | 62.50% | 71.88% | 79.38% |
| reranked | 55.00% | 45.83% | 59.17% | 0.3802 | N/A | N/A | N/A |

Integer Gold hits (query/Gold-unit identity, not macro percentage denominators):

| Stage | @5 | @10 | @20 | @30 | @50 |
|---|---:|---:|---:|---:|---:|
| bm25 | 15 | 21 | 29 | 35 | 42 |
| dense | 19 | 24 | 29 | 31 | 41 |
| hybrid | 20 | 26 | 33 | 40 | 46 |
| reranked | 23 | 31 | N/A | N/A | N/A |

## Reranker contribution on TEST

Recovered 6, lost 1, net +5.
Paired queries, based on per-query R@10: {'improved': 6, 'regressed': 1, 'unchanged': 33}.

Recovered IDs: ['V2Q003:G1', 'V2Q006:G1', 'V2Q009:G1', 'V2Q013:G1', 'V2Q014:G1', 'V2Q048:G1'].
Lost IDs: ['V2Q062:G2'].

Per-Gold categories: {'CANDIDATE_PRESENT_BUT_MISSED': 1, 'DEMOTED_OUT_OF_TOP10': 1, 'NOT_IN_TOP20': 30, 'PROMOTED_INTO_TOP10': 6, 'STAYED_IN_TOP10': 25}.

Full unit locators, Hybrid and reranker ranks, paired reciprocal-rank movement and exact gain/loss IDs are preserved in `test_diagnostics.json`. These diagnostics did not change reranker selection.

## DEV to TEST movement

| Metric | TEST minus DEV |
|---|---:|
| CR@20 | -0.1536 (-15.36 pp) |
| CR@30 | -0.0670 (-6.70 pp) |
| CR@50 | -0.0063 (-0.63 pp) |
| Hit@5 | -0.0786 (-7.86 pp) |
| MRR@10 | +0.0596 |
| R@10 | -0.0964 (-9.64 pp) |
| R@5 | -0.0179 (-1.79 pp) |

Movement: **MODERATE DROP**. Generalization: **ACCEPTABLE**, descriptive only.

The movement rubric was declared before reading TEST: STABLE if the largest final recall/hit-rate drop and MRR drop are below .05; MODERATE DROP if none exceeds .15; otherwise LARGE DROP. This is not a pass/fail gate and cannot authorize tuning. The summary also considers whether reranking still improves Hybrid R@10. With 35 DEV and 40 TEST queries, one single-Gold TEST success changes macro recall by 2.5 percentage points; multi-Gold questions contribute smaller per-hit increments. Annotation-granularity differences further limit interpretation.

## Frozen query-type breakdown

| Type | n | Final R@10 | Final MRR@10 | Hybrid CR@20 | Hybrid CR@50 |
|---|---:|---:|---:|---:|---:|
| cross_document | 8 | 4.17% | 0.0156 | 8.33% | 44.79% |
| exact_term | 5 | 80.00% | 0.4867 | 80.00% | 100.00% |
| factual | 8 | 75.00% | 0.4083 | 75.00% | 75.00% |
| multi_hop | 6 | 63.89% | 0.6556 | 63.89% | 86.11% |
| relational | 5 | 50.00% | 0.6000 | 50.00% | 80.00% |
| semantic | 8 | 87.50% | 0.3063 | 100.00% | 100.00% |

All subgroups are descriptive / low-sample. Categories and membership are unchanged. The cross_document row is the frozen cross-paper subset.

The overall ACCEPTABLE label must not hide the weak cross-document subset: n=8, final R@10=4.17%, MRR@10=0.0156, Hybrid CR@20=8.33%, CR@50=44.79%. This is a material limitation of the frozen global retrieval candidate budget on this subset. Of 32 final Gold misses overall, 30 were absent from Hybrid Top20; the reranker cannot repair those misses. No causal claim beyond the observed rankings is made, and no TEST-driven changes were applied.

## Non-intervention error analysis

Metrics were persisted and hashed before error analysis. Categories below are mutually exclusive: absent from Hybrid Top20 first; then demoted from Hybrid Top10; then candidate present but not promoted; then any other valid evaluation miss. `GOLD_PRESENT_LOWER_THAN_TOP10` is an additional nonexclusive flag, because it otherwise overlaps the other categories.

| Category | Gold misses | Query IDs |
|---|---:|---|
| NOT_IN_HYBRID_TOP20 | 30 | V2Q004, V2Q008, V2Q017, V2Q018, V2Q019, V2Q020, V2Q021, V2Q022, V2Q025, V2Q026, V2Q033, V2Q058, V2Q059, V2Q060, V2Q062, V2Q064, V2Q073, V2Q075 |
| IN_TOP20_RERANKER_FAILED_TO_PROMOTE | 1 | V2Q012 |
| DEMOTED_BY_RERANKER | 1 | V2Q062 |
| OTHER_VALID_EVALUATION_MISS | 0 | none |

Secondary Gold present below Hybrid Top10 among final misses: 20. This is not added to the exclusive total.

## Latency

local sequential BM25 + M3 query encode + copied frozen Chroma query + authority validation + weighted RRF + base reranker; excludes HTTP/SQL/network/cold model load, checkpoint writes and scoring.

First and only TEST execution supplies all timing samples. No latency-only rerun. CPU float32, four PyTorch threads / one interop thread, local Docker image `rg-phase11h-backend:local`, 6 GiB memory limit. Cold model loading and initial warm-up are excluded; per-query tokenization, embedding inference, search, authority checks and reranking are included. Percentiles use linear interpolation.

| Stage | Mean ms | P50 ms | P95 ms |
|---|---:|---:|---:|
| bm25 | 416.63 | 365.97 | 627.34 |
| dense_search_and_authority | 39.51 | 22.19 | 46.10 |
| end_to_end | 10564.51 | 9329.55 | 16093.14 |
| fusion | 0.41 | 0.31 | 1.00 |
| query_encoding | 595.67 | 397.33 | 1421.00 |
| reranker | 9512.29 | 8560.37 | 14526.92 |
| retrieval | 1051.80 | 794.23 | 2027.39 |

## Integrity / regression

Protected hashes: 227 verified. TEST exactly once: PASS. Gold validation: PASS. Pre-test lock: PASS.
Tests: {'failed': 0, 'junit_xml': 'artifacts/evaluation_v2/f/regression_tests.xml', 'passed': 69, 'pre_TEST_synthetic_passed': 10, 'skipped': 0}. git diff --check: PASS.

No B/C/D/E artifact, original Gold, query, corpus, BM25 implementation or frozen Dense index was modified. Only final-manifest TEST validation state/provenance changed. Production remains unchanged.

## Output artifacts

- `final_retrieval_manifest.json` and `.sha256`: final immutable selection and validation provenance.
- `artifacts/evaluation_v2/f/pre_test_manifest.json`, `pre_test_lock.json`: original pre-TEST identity.
- `dev_reproduction.json`, `test_gold_validation.json`, `test_execution_lock.json`, `query_execution_journal.jsonl`: gating and exactly-once records.
- `test_run.json`: complete BM25/Dense/Hybrid/reranker rankings, scores and timings.
- `test_metrics_frozen.json`, `summary.json`, `test_diagnostics.json`: immutable metrics and descriptive diagnosis.
- `v2_f_test_metrics.csv`, `v2_f_test_error_analysis.csv`, `v2_f_test_query_types.csv`: complete metric/diagnostic tables.

Ready for V2-G: YES. Research/Cross-paper Workflow Evaluation was not started.
