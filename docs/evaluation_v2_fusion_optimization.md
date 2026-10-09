# V2-D Controlled Fusion Optimization

Status: **COMPLETE**.30 tests passed,0 failed; protected hashes and git diff --check passed. This is an offline25-point DEV rank-fusion experiment. No BM25/Dense retrieval, model inference, reranker run, TEST evaluation or production-default change occurred. V2-E has not started.

## Frozen protocol and baseline

Chunking: existing TextChunker700/100, page-contained,3837 chunks. Dense: BAAI/bge-m3 revision5617a9f61b028005a4858fdac845db406aefb181, RAW query/doc, CLS, normalized1024 dimensions, max8192. Both saved authoritative route inputs have depth200; fused retention is100. Gold uses all55 human-approved C1R exact spans with100% containment.

Baseline equal-weight RRF60 reproduces all35 C1R BASE rankings and metrics exactly (precision tolerance1e-12). Production code remains unchanged. Weighted arithmetic is implemented only in the offline evaluation module and independently verified against a separate formula implementation.

The predeclared grid contains BM25 weights0.50/0.75/1.00/1.25/1.50 ? k20/40/60/80/120, with Dense weight1.0. Contributions use1-indexed ranks; absent route contributes zero. Dedup uses authoritative occurrence IDs, with unchanged dense-first stable insertion ties. Authority membership/document/version/text checks precede fusion.

Selection priority is CR20,CR30,CR50,R10,MRR10, gain/loss, cross-document, duplicate waste, simplicity. The predeclared conservative interpretation of no material cross-document regression in one-unit gateB is no CR20 decline. No weighted aggregate score, new parameter, score normalization or post-result tuning is used.

Recall metrics are35-query macro averages. Integer evidence hits use55 Query?Gold units. One unit is1/55=1.818 percentage points only for micro coverage; the replacement/safety gates use integer units and do not confuse this with macro Recall.

## Route diagnostics

| Route | Hit@5 | R@5 | R@10 | MRR@10 | CR@20 | CR@30 | CR@50 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| bm25 | 45.71% | 35.71% | 46.67% | 0.2518 | 60.00% | 64.29% | 71.43% |
| dense | 57.14% | 45.24% | 51.19% | 0.3115 | 61.19% | 62.62% | 70.71% |

Union is diagnostic only: per-route TopK union has up to2K candidates, not an equal-budget competitor.

| Route depth | BM25-only | Dense-only | Both | Neither | Union units | Union micro | Union macro |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 20 | 9 | 7 | 24 | 15 | 40 | 72.73% | 77.14% |
| 30 | 10 | 7 | 25 | 13 | 42 | 76.36% | 80.00% |
| 50 | 6 | 5 | 32 | 12 | 43 | 78.18% | 81.43% |
| 200 | 3 | 2 | 44 | 6 | 49 | 89.09% | 91.43% |

## All25 configurations

| BM25 w | k | Hit@5 | R@5 | R@10 | MRR@10 | CR20 (units) | CR30 (units) | CR50 (units) | Front flag |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 0.5 | 120 | 48.57% | 35.71% | 56.90% | 0.3358 | 69.29% (35) | 75.00% (39) | 82.14% (42) | False |
| 0.5 | 20 | 51.43% | 39.52% | 57.86% | 0.3498 | 69.29% (35) | 77.86% (40) | 81.43% (43) | False |
| 0.5 | 40 | 54.29% | 41.43% | 58.81% | 0.3452 | 69.29% (35) | 75.00% (39) | 81.43% (43) | False |
| 0.5 | 60 | 48.57% | 35.71% | 59.76% | 0.3414 | 69.29% (35) | 75.00% (39) | 80.71% (42) | False |
| 0.5 | 80 | 48.57% | 35.71% | 59.76% | 0.3395 | 69.29% (35) | 75.00% (39) | 80.71% (42) | False |
| 0.75 | 120 | 48.57% | 35.71% | 55.48% | 0.3323 | 73.57% (38) | 77.86% (40) | 84.29% (44) | False |
| 0.75 | 20 | 54.29% | 40.48% | 61.67% | 0.3530 | 75.00% (38) | 79.29% (41) | 80.00% (42) | False |
| 0.75 | 40 | 48.57% | 35.71% | 61.19% | 0.3424 | 73.57% (38) | 79.29% (41) | 81.43% (43) | False |
| 0.75 | 60 | 48.57% | 35.71% | 61.19% | 0.3400 | 73.57% (38) | 79.29% (41) | 84.29% (44) | False |
| 0.75 | 80 | 48.57% | 35.71% | 61.19% | 0.3390 | 73.57% (38) | 79.29% (41) | 84.29% (44) | False |
| 1.0 | 120 | 45.71% | 32.86% | 54.05% | 0.3335 | 70.71% (37) | 79.29% (41) | 84.29% (44) | False |
| 1.0 | 20 | 48.57% | 34.76% | 58.81% | 0.3432 | 76.43% (39) | 80.00% (42) | 80.00% (42) | False |
| 1.0 | 40 | 45.71% | 32.86% | 56.90% | 0.3387 | 76.43% (39) | 80.00% (42) | 81.43% (43) | False |
| 1.0 | 60 | 45.71% | 32.86% | 54.05% | 0.3355 | 73.57% (38) | 79.29% (41) | 84.29% (44) | False |
| 1.0 | 80 | 45.71% | 32.86% | 54.05% | 0.3355 | 73.57% (38) | 79.29% (41) | 84.29% (44) | False |
| 1.25 | 120 | 48.57% | 34.29% | 51.19% | 0.2875 | 70.71% (37) | 79.29% (41) | 84.29% (44) | False |
| 1.25 | 20 | 54.29% | 39.05% | 54.05% | 0.3081 | 77.86% (40) | 78.57% (41) | 80.00% (42) | False |
| 1.25 | 40 | 51.43% | 36.19% | 51.19% | 0.2902 | 75.00% (39) | 80.00% (42) | 82.86% (43) | False |
| 1.25 | 60 | 48.57% | 34.29% | 51.19% | 0.2878 | 75.00% (39) | 80.00% (42) | 84.29% (44) | False |
| 1.25 | 80 | 48.57% | 34.29% | 51.19% | 0.2875 | 70.71% (37) | 80.00% (42) | 84.29% (44) | False |
| 1.5 | 120 | 51.43% | 36.19% | 51.19% | 0.2935 | 69.29% (36) | 77.14% (41) | 84.29% (44) | False |
| 1.5 | 20 | 54.29% | 39.05% | 50.24% | 0.2831 | 77.86% (40) | 78.57% (41) | 80.00% (42) | True |
| 1.5 | 40 | 54.29% | 39.05% | 51.19% | 0.2959 | 75.00% (39) | 80.00% (42) | 80.00% (42) | False |
| 1.5 | 60 | 51.43% | 36.19% | 51.19% | 0.2949 | 73.57% (38) | 80.00% (42) | 82.86% (43) | False |
| 1.5 | 80 | 51.43% | 36.19% | 51.19% | 0.2935 | 73.57% (38) | 80.00% (42) | 84.29% (44) | False |

Complete integer counts at5/10/20/30/50/100, duplicates and fusion timings are in grid CSV (`benchmarks/real_research/v2/v2_d_fusion_grid.csv`; private historical artifact, not distributed). Exact recovered/lost query_id/gold_id records for every config and depth are in gain/loss CSV (`benchmarks/real_research/v2/v2_d_gain_loss.csv`; private historical artifact, not distributed). All35-query paired classifications for every config are in paired CSV (`benchmarks/real_research/v2/v2_d_paired_queries.csv`; private historical artifact, not distributed).

## Selected candidate and replacement gate

Lexicographic leader and selected DEV candidate: **BM25 weight1.25, Dense weight1.0, k20**. Top20 hits rise38?40, with two recoveries and no loss: V2Q038:G1 and V2Q074:G2. Macro CR20 rises73.57%?77.86%. **GateA PASS** (net+2 units). R10 remains54.05%/28 hits. MRR10 falls0.3355?0.3081 (?0.0274, within the0.05 safety bound), so no front-ranking flag.

This is a Top20 candidate-budget trade-off, not uniform superiority. Top30 recovers V2Q061:G3 and loses V2Q068:G2 (net0), with macro CR30 falling79.29%?78.57% because queries have different Gold counts. Top50 loses V2Q043:G1 and V2Q063:G1 (net?2); CR50 falls84.29%?80.00%. Paired lexicographic query results:8 improved,17 unchanged,10 regressed. These limitations remain visible despite meeting the prespecified gate. MATERIAL is the gate-defined DEV classification, not a statistical-significance/generalization claim.

No existing V2 evaluation bootstrap utility was found; bootstrap was not run and no new dependency was introduced.

## Cross-document diagnostic

Frozen n=7. All25 configurations are in cross-document CSV (`benchmarks/real_research/v2/v2_d_cross_document.csv`; private historical artifact, not distributed). For the selected config: R10=34.52%, MRR10=0.2077, CR20=46.43%, CR30=50.00%, CR50=57.14%. CR20 is unchanged versus baseline; deeper coverage declines. These descriptive metrics did not override primary selection.

## Fusion retention

Route input availability is measured at the fixed Top200 per route: BM25 has47 units, Dense46, union49. Of the union,3 are BM25-only,2 Dense-only,44 present in both routes. Selected-config retention:

| Fused K | BM25 available | Dense available | Union available | Retained units | BM25-only retained | Dense-only retained | Both retained |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 20 | 47 | 46 | 49 | 40 | 0/3 | 0/2 | 40/44 |
| 30 | 47 | 46 | 49 | 41 | 0/3 | 0/2 | 41/44 |
| 50 | 47 | 46 | 49 | 42 | 0/3 | 0/2 | 42/44 |

Thus the selected configuration improves early ordering of shared-route evidence; it does not solve retention of the five route-exclusive units at Top50. Full25-config diagnostics are in fusion_retention.json (`artifacts/evaluation_v2/d/fusion_retention.json`; private historical artifact, not distributed).

## Duplicate evidence

An equivalent chunk contributes no extra recall. Queries-with-duplicates counts any repeated evidence unit; redundant chunks count chunks contributing no new unit at all, so a chunk additionally supporting a new unit is not counted as wasted. Selected config: Top20 has0 duplicate queries/0 redundant slots; Top50 has1 duplicate query/1 redundant slot out of1750 (0.0571%). This matches baseline. Every config is retained in the grid and summary.

## Latency and cost

Only offline fusion arithmetic was timed:35-query warm-up followed by3 repetitions (105 timing samples/config), excluding Gold scoring, retrieval, models, HTTP and storage. All timings remain in the grid. Selected mean/p50/p95 ms: 0.3889 / 0.3753 / 0.6795. These small host timings are descriptive, not an end-to-end speedup claim or selection tie-break.

## Freeze and protection

[final_fusion_config.json](../benchmarks/real_research/v2/final_fusion_config.json): weighted_rrf, BM251.25/Dense1.0/k20, routes200/200, fusedTop100. DEV_SELECTED=true, TEST_VALIDATED=false, PRODUCTION_DEFAULT=false. Config SHA-256:

`f1707c358cadd7ceb162119811976ecfa1ea57fe6f40588bbd7a55b479c24360`

Chunking/Dense config, DEV/opaque TEST bytes, original Gold, reviewed Gold, BM25 implementation, saved Dense/Hybrid/reranker rankings and existing B6/reranker configuration are protected by before/after hashes. Existing C0/C1/C1R/C2 history and retained indexes are preserved. 30 tests passed,0 failed, including independent verification of all25 formula outputs and Gold hit counts, safety gates, frozen chunking contract and protected hashes. Ready for V2-E: **YES**. V2-E has not started.
