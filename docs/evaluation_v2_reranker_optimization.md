# V2-E Controlled Reranker Optimization

Status: **COMPLETE**. DEV only; TEST not evaluated; production unchanged.

## Frozen contract

35 frozen DEV queries, 55 human-approved evidence units; a chunk must contain 100% of the exact reviewed span. Gold counts are deduplicated per unit; metrics are macro averages across queries, not total hit counts divided by 55.

Upstream remains TextChunker 700 / overlap 100 / page-contained, 3,837 chunks; BAAI/bge-m3 RAW query / RAW passage, normalized CLS; weighted RRF BM25 1.25, Dense 1.0, k=20, route depths 200/200. Only the saved winning Hybrid Top20 is admitted. Final output depth is 10.

Candidate CR@20: **77.86%**, 40/55 distinct units present. This is pre-rerank coverage, never a final-output recall field. No reranker can recover the other 15 units.

Only base and v2-m3 were scored. Both use CPU float32, four PyTorch threads / one interop thread, batch 8, max length 512. Input is raw query + raw chunk, with only the existing CrossEncoder internal `str.strip()` behavior. No metadata, instructions, title or adjacent context.

Rank blend: alpha/(10 + reranker_rank) + (1-alpha)/(10 + fusion_rank), one-based ranks, alpha in {1, .75, .5}; descending score and original fusion rank for ties. Every blend uses the same cached 700 pair scores per model. No fusion or retrieval reruns.

## Baseline and implementation audit

NO_RERANK was reproduced first; current base was then scored on the NEW V2-D candidates and its per-Gold error audit saved before model B was run. Historical B6 scores/metrics were not substituted.

Both scorers use pinned model and tokenizer snapshots. The production wrapper was reused unchanged. An independent tokenizer/model-logit check reproduced wrapper scores; warm-up and measured first-query score vectors matched exactly. Production rerank mapping was exercised with cached scores, validating unchanged candidate identities and ordering. A scoring failure would abort the experiment instead of using fallback retrieval results.

| Model | Revision | Score | Truncated pairs | Token lengths min / median / p95 / max |
|---|---|---|---:|---|
| BAAI/bge-reranker-base | `465b4b7ddf2be0a020c8ad6e525b9bb1dbb708ae` | Sigmoid() | 0/700 (0.00%) | 118 / 206.0 / 273.0 / 307 |
| BAAI/bge-reranker-v2-m3 | `953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e` | Sigmoid() | 0/700 (0.00%) | 118 / 206.0 / 273.0 / 307 |

Special tokens are supplied by the pinned tokenizer; query precedes passage, dynamic padding and `longest_first` truncation at 512. XLM-R pair format uses its configured special tokens. Scores are descending; equal scores retain fusion order. Tokenizer configurations, special-token maps, pair lengths, file hashes, model fingerprints and tokenizer fingerprints are preserved in `reranker_audit.json`.

Chunk character lengths (700 pair occurrences): {'max': 700, 'median': 700.0, 'min': 316, 'p95': 700.0}.

## All predeclared configurations

| Config | Hit@5 | R@5 | R@10 | MRR@10 | Gold hits@10 | Recovered / lost / net vs current | Front safety flag |
|---|---:|---:|---:|---:|---:|---|---|
| NO_RERANK | 54.29% | 39.05% | 54.05% | 0.3081 | 28 | 1 / 7 / -6 | True |
| base_a0.50 | 65.71% | 50.95% | 61.67% | 0.3519 | 31 | 0 / 3 / -3 | False |
| base_a0.75 | 62.86% | 49.52% | 65.95% | 0.3086 | 33 | 0 / 1 / -1 | False |
| base_a1.00 | 62.86% | 47.62% | 68.81% | 0.3206 | 34 | 0 / 0 / +0 | False |
| m3_a0.50 | 71.43% | 56.67% | 70.24% | 0.4588 | 34 | 3 / 3 / +0 | False |
| m3_a0.75 | 77.14% | 63.81% | 70.71% | 0.4813 | 34 | 4 / 4 / +0 | False |
| m3_a1.00 | 74.29% | 62.38% | 72.14% | 0.5153 | 35 | 4 / 3 / +1 | False |

## Current reranker evidence audit

Counts: {'CANDIDATE_PRESENT_BUT_STILL_MISSED': 5, 'DEMOTED_OUT_OF_TOP10': 1, 'NOT_IN_TOP20': 15, 'PROMOTED_INTO_TOP10': 7, 'STAYED_IN_TOP10': 27}.

Demoted Gold IDs: V2Q069:G3.

`v2_e_error_audit.csv` records every one of the 55 units for each configuration, with the original and final ranks plus equivalent immutable chunk IDs. NOT_IN_TOP20 units cannot be fixed by reranking.

## Paired queries and cross-document subset

Paired classifications use per-query R@10 only. Reciprocal-rank movement is recorded separately in `paired_queries.json` and never upgrades a recall tie to an improved query.

| Config | Improved / unchanged / regressed | Cross-doc R@10 | Cross-doc MRR@10 | Cross-doc recovered / lost / net |
|---|---|---:|---:|---|
| NO_RERANK | 1 / 27 / 7 | 34.52% | 0.2077 | 1 / 0 / +1 |
| base_a0.50 | 0 / 32 / 3 | 29.76% | 0.1417 | 0 / 0 / +0 |
| base_a0.75 | 0 / 34 / 1 | 29.76% | 0.1204 | 0 / 0 / +0 |
| base_a1.00 | 0 / 35 / 0 | 29.76% | 0.1061 | 0 / 0 / +0 |
| m3_a0.50 | 3 / 29 / 3 | 34.52% | 0.2032 | 1 / 0 / +1 |
| m3_a0.75 | 3 / 29 / 3 | 36.90% | 0.2349 | 2 / 1 / +1 |
| m3_a1.00 | 3 / 30 / 2 | 36.90% | 0.1478 | 2 / 1 / +1 |

Cross-document n=7; these are descriptive DEV observations, not generalization claims.

## Replacement and safety decision

Frozen priority: R@10, MRR@10, R@5, Hit@5, paired gain/loss, cross-document, demotions, latency/memory, simplicity. Gate A requires at least two net additional Gold hits and improved macro R@10. Gate B requires one net hit, improved R@10, nondecreasing MRR/R@5, no cross-document R@10 decline and no increased demotions (conservative predeclared interpretation).

Front-safety flags are evaluated relative to current pure base: improved R@10 with MRR loss >0.05, or at least two fewer Gold hits@5. Flagged candidates are excluded from replacement; no post-hoc exceptions were used.

Lexicographic leader: **m3_a1.00**. Selected: **base_a1.00**. Replacement gate: **FAIL ? retain current**.

The metric leader v2-m3 alpha=1 recovers four Gold units and loses three (net +1), so Gate A is not met. MRR, R@5 and cross-document R@10 improve, but demotions rise from 1 to 2. Gate B therefore fails the predeclared conservative no-increase condition. No front-safety flag is triggered. Base is retained because of this gate, not because a latency penalty was substituted for the quality objective.

Leader demotions relative to Hybrid Top10: V2Q069:G1 and V2Q070:G2. Current base demotes V2Q069:G3. Exact recovered/lost IDs are retained for all configurations in the gain/loss CSV.

Current reranker value reproduced vs NO_RERANK: True. Selected vs NO_RERANK: {'lost': ['V2Q069:G3'], 'net': 6, 'recovered': ['V2Q034:G1', 'V2Q037:G1', 'V2Q038:G1', 'V2Q046:G1', 'V2Q054:G2', 'V2Q055:G1', 'V2Q071:G2']}.

Selected vs current recovered IDs: []; lost IDs: [].

Optimization opportunity: **MINOR**. Reranker contribution vs NO_RERANK: **MATERIAL**. These are separate decisions.

## Latency and practical cost

CPU: AMD Ryzen 7 4800H; x86_64 WSL2. Full environment is retained in `environment.json`.

One warmed 35-query pass per model; 20 pairs/query. Timing includes tokenizer + forward pass + score extraction, excludes model loading, integrity checks, retrieval and offline rank blending. Same Docker image, machine, CPU thread counts and 6 GiB container memory limit; inference was sequential and offline. p95 is linearly interpolated. Measurements describe this local run, not a production SLA. No additional performance rounds were used.

| Model | Parameters | Snapshot bytes | Peak process RSS MiB | Mean ms/query | P50 ms | P95 ms | Pairs/s |
|---|---:|---:|---:|---:|---:|---:|---:|
| BAAI/bge-reranker-base | 278044417 | 1117276712 | 1865.0 | 7982.83 | 7997.39 | 9086.58 | 2.505 |
| BAAI/bge-reranker-v2-m3 | 567755777 | 2293242108 | 3627.9 | 27464.41 | 27495.52 | 31812.81 | 0.728 |

Peak RSS includes model loading, tokenization and auditing in the process; disk bytes are the locally cached snapshot files, not an estimate from parameter count. All three alpha values for a model share its inference cost.

## Frozen reranker

Model: `BAAI/bge-reranker-base`; revision/tokenizer revision: `465b4b7ddf2be0a020c8ad6e525b9bb1dbb708ae`.
Max length 512; batch 8; candidate depth 20; final Top10; alpha 1.0; blend k=10.

Config SHA-256: `5c800c65a9cf9b5549d81023a9467e58a15b75389d482d1e04f5aba8c01e6870`.

`DEV_SELECTED=true`, `TEST_VALIDATED=false`, `PRODUCTION_DEFAULT=false`. This is an evaluation selection; production configuration is not modified.

## Integrity and validation

- `final_chunking_config.json`: `008845cdc4c45d8921173138d8b8591fa06d85e44082a5d73627801be3887079` (unchanged).
- `final_dense_config.json`: `8842ce493055ce775fdff46c3851420e6965d80959f01faf5c5d2da2a37b1f96` (unchanged).
- `final_fusion_config.json`: `f1707c358cadd7ceb162119811976ecfa1ea57fe6f40588bbd7a55b479c24360` (unchanged).
- `dev_gold_evidence_spans_v2.json`: `1152c9da9355b1daade667255cb6f1ab89ed02a837f121ea05c8ce162a8a5085` (unchanged).
- `queries_dev.jsonl`: `2977076711400a1ff41ee4886c48e9fdd8f68f4e8fd41e2e5a5bd96e537fc7b9` (unchanged).
- `queries_test.jsonl`: `5b94e93eed901c3ef05df7a9d4efa4d14b9aef19fbdb160d83c314f15306c419` (unchanged).

All 200 protected historical/input hashes verified. TEST accessed only for byte hashing; no TEST records, rankings, metrics or models evaluated. B6 history retained. No new embedding, chunking, fusion, retrieval or LLM execution.

Tests: {'failed': 0, 'junit_xml': 'artifacts/evaluation_v2/e/regression_tests.xml', 'passed': 53, 'skipped': 0}. git diff --check: PASS.

## Artifacts

- `artifacts/evaluation_v2/e/protocol.json`: predeclared configuration and input hashes.
- `base_scores.json`, `m3_scores.json`: all raw score vectors, candidate IDs, per-query timings and audit records.
- `current_baseline_audit.json`, `reranker_audit.json`: pre-comparison baseline and full model audit.
- `summary.json`, `final_rankings.json`, `paired_queries.json`: complete offline analysis.
- `benchmarks/real_research/v2/v2_e_reranker_grid.csv`, `v2_e_gain_loss.csv`, `v2_e_error_audit.csv`, `v2_e_cross_document.csv`: full six-config comparisons plus NO_RERANK.
- `final_reranker_config.json` and `.sha256`: deterministic selected configuration.

Official model input/scoring reference: [BAAI/bge-reranker-v2-m3](https://huggingface.co/BAAI/bge-reranker-v2-m3). The local pinned snapshot and saved runtime audit determine the actual implementation used here.

Ready for V2-F: YES. V2-F is not started.
