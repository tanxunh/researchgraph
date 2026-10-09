# V2-A Candidate Generation

Status: COMPLETE. All policies remain experiment-only; production defaults and public APIs unchanged.

## Frozen Baseline

Corpus: 30 papers / 432 pages / 3837 chunks. DEV 35 human-reviewed queries; TEST 40 untouched.
DEV SHA-256: `2977076711400a1ff41ee4886c48e9fdd8f68f4e8fd41e2e5a5bd96e537fc7b9`
TEST SHA-256: `5b94e93eed901c3ef05df7a9d4efa4d14b9aef19fbdb160d83c314f15306c419`
Baseline: dev_baseline_frozen_gold.json. Annotation corrections are excluded from algorithm comparisons.

|Global baseline|R@10|MRR@10|CR@20|CR@50|E2E p50 ms|E2E p95 ms|
|---|---:|---:|---:|---:|---:|---:|
|bm25|46.67|0.2518|60.00|71.43|610.369|848.498|
|dense|25.24|0.1627|25.95|32.62|149.386|206.342|
|hybrid|38.81|0.2222|48.81|64.52|822.251|1438.190|
|hybrid_reranker|47.14|0.2951|48.81|64.52|7690.164|11404.726|

## Current Candidate Flow

Production BM25 requests 200 from BM25Index, then authoritative active-version validation. Dense requests min(200,max(2*top_k,dense_top_k)); validated rows are not sliced back to top_k. Thus frozen baseline search(top_k=100) sends up to 200 candidates PER SOURCE to fusion, not 100.
FusionRanker deduplicates by chunk occurrence ID; equal source RRF contributions use k=60. Fusion returns up to600, followed by active-version/scope validation, then [:top_k]. Baseline retains Top100; its scorer takes Top20 and returns Top10. Public rerank=True recursively searches with top_k=20, meaning Dense initially requests40 (default dense_top_k=8), BM25 requests200; that path is not identical to the benchmark acquisition path.
No BM25-prefix preservation is guaranteed by RRF. Two-source agreement can displace BM25-only high-ranked evidence.
Raw Union@K means each source Top-K union, up to2K. It is not an equal-budget comparison with RRF@K.

### Experiment A: RRF output depth (fixed 200/200 source depth)

|Track|Pool|Candidate recall|Cross-document candidate recall|R@10|MRR@10|
|---|---:|---:|---:|---:|---:|
|global|20|48.81|22.62|38.81|0.2222|
|global|30|57.38|22.62|38.81|0.2222|
|global|40|63.10|22.62|38.81|0.2222|
|global|50|64.52|29.76|38.81|0.2222|
|scoped|20|73.57|36.90|52.62|0.3751|
|scoped|30|84.76|52.38|52.62|0.3751|
|scoped|40|91.43|64.29|52.62|0.3751|
|scoped|50|92.86|71.43|52.62|0.3751|

## Retrieval Depth Analysis

B is coordinate analysis, not a16-point grid. Every source depth was actually fetched/warmed/timed; Dense overfetch is explicitly capped BEFORE fusion. Choosing a source depth cannot be confused with post-RRF top_k.
Coordinate selection rule: maximize mean Global CR@20/@30/@50, then cross-document coverage, then smaller depth. Choice: {'bm25_k': 40, 'dense_k': 100}
Individual recall below uses the full source depth; union uses all supplied candidates and has unequal pool sizes.

### global

|Sweep|BM25 k|Dense k|BM25 individual CR|Dense individual CR|Full union CR|RRF CR20|RRF CR30|RRF CR50|Retrieval p50 ms|Retrieval p95 ms|
|---|---|---|---|---|---|---|---|---|---|---|
|v2a-B-bm2520-b20-d100|20|100|60.00|52.14|71.43|54.52|59.29|61.43|746.241|1203.270|
|v2a-B-bm2540-b40-d100|40|100|68.57|52.14|72.86|56.43|65.48|68.57|702.373|1019.281|
|v2a-B-bm2560-b60-d100|60|100|80.00|52.14|84.29|56.43|63.10|68.57|713.241|982.852|
|v2a-B-bm25100-b100-d100|100|100|80.00|52.14|84.29|47.86|62.14|68.57|724.656|999.063|
|v2a-B-dense20-b40-d20|40|20|68.57|25.95|70.00|54.05|58.33|65.71|646.905|970.462|
|v2a-B-dense40-b40-d40|40|40|68.57|31.19|70.00|53.57|58.33|65.71|660.689|961.785|
|v2a-B-dense60-b40-d60|40|60|68.57|39.29|71.43|55.00|62.62|65.71|677.424|997.473|
|v2a-B-dense100-b40-d100|40|100|68.57|52.14|72.86|56.43|65.48|68.57|702.472|1019.237|
### scoped

|Sweep|BM25 k|Dense k|BM25 individual CR|Dense individual CR|Full union CR|RRF CR20|RRF CR30|RRF CR50|Retrieval p50 ms|Retrieval p95 ms|
|---|---|---|---|---|---|---|---|---|---|---|
|v2a-B-bm2520-b20-d100|20|100|69.76|95.71|95.71|69.76|75.48|91.43|157.946|207.367|
|v2a-B-bm2540-b40-d100|40|100|82.86|95.71|95.71|75.24|82.86|88.57|165.693|241.922|
|v2a-B-bm2560-b60-d100|60|100|94.29|95.71|97.14|73.10|87.62|94.29|172.889|261.327|
|v2a-B-bm25100-b100-d100|100|100|97.86|95.71|99.29|73.57|86.19|92.86|189.237|229.647|
|v2a-B-dense20-b40-d20|40|20|82.86|53.10|84.29|64.52|74.05|84.29|131.409|187.436|
|v2a-B-dense40-b40-d40|40|40|82.86|84.29|92.86|74.29|82.86|91.43|144.551|198.779|
|v2a-B-dense60-b40-d60|40|60|82.86|89.05|95.71|70.95|79.05|91.43|156.735|228.374|
|v2a-B-dense100-b40-d100|40|100|82.86|95.71|95.71|75.24|82.86|88.57|165.493|241.739|

## Equal-Budget Candidate Comparison

Each row compares actual candidate membership at the requested budget; M greater than the configured pool is reported unavailable, not as saturated CR@M. Single-source pools fetch100 (enough for M50), current RRF uses200/200, protected union uses coordinate-selected40/100.

### global

|Policy|Budget|CR@budget|Actual size min/max|H@5|R@5|R@10|MRR@10|Retrieval p50 ms|
|---|---|---|---|---|---|---|---|---|
|bm25|20|60.00|20/20|45.71|35.71|46.67|0.2518|598.687|
|dense|20|25.95|20/20|25.71|21.43|25.24|0.1627|120.170|
|rrf|20|48.81|20/20|37.14|28.10|38.81|0.2222|769.437|
|protected_union|20|52.62|20/20|40.00|30.95|45.48|0.2451|702.385|
|bm25|30|64.29|30/30|45.71|35.71|46.67|0.2518|598.684|
|dense|30|30.24|30/30|25.71|21.43|25.24|0.1627|120.160|
|rrf|30|57.38|30/30|37.14|28.10|38.81|0.2222|769.183|
|protected_union|30|62.62|30/30|37.14|28.10|45.48|0.2359|702.332|
|bm25|50|71.43|50/50|45.71|35.71|46.67|0.2518|598.690|
|dense|50|32.62|50/50|25.71|21.43|25.24|0.1627|120.158|
|rrf|50|64.52|50/50|37.14|28.10|38.81|0.2222|769.504|
|protected_union|50|65.71|50/50|37.14|28.10|39.76|0.2263|702.551|
### scoped

|Policy|Budget|CR@budget|Actual size min/max|H@5|R@5|R@10|MRR@10|Retrieval p50 ms|
|---|---|---|---|---|---|---|---|---|
|bm25|20|69.76|20/20|57.14|43.81|55.71|0.3498|60.009|
|dense|20|53.10|20/20|40.00|30.71|41.67|0.2692|124.904|
|rrf|20|73.57|20/20|54.29|42.86|52.62|0.3751|196.390|
|protected_union|20|70.24|20/20|54.29|42.86|52.62|0.3751|165.716|
|bm25|30|82.86|30/30|57.14|43.81|55.71|0.3498|60.010|
|dense|30|76.90|30/30|40.00|30.71|41.67|0.2692|124.907|
|rrf|30|84.76|30/30|54.29|42.86|52.62|0.3751|196.389|
|protected_union|30|81.90|30/30|54.29|42.86|52.62|0.3751|165.526|
|bm25|50|91.43|50/50|57.14|43.81|55.71|0.3498|60.007|
|dense|50|84.29|50/50|40.00|30.71|41.67|0.2692|124.906|
|rrf|50|92.86|50/50|54.29|42.86|52.62|0.3751|196.775|
|protected_union|50|88.57|50/50|54.29|42.86|52.62|0.3751|165.640|

## Protected Union Experiment

Protect floor(M/2) from each source, deduplicate, fill remaining slots from unchanged RRF order, then order chosen membership by RRF. No weights, model, or scoring normalization change.
At Global budgets20/30/50 protected CR is52.62/62.62/65.71%, versus BM25-only60.00/64.29/71.43%. Protected union is not selected; it remains only as a reproducible ablation, with no production adoption.
Original C budget50 BM25 erroneously retained40 due to coordinate source depth. That record is preserved as INVALID_EQUAL_BUDGET and excluded from selection. C2 fixes source capacity and recomputes only deterministic construction on already collected source results. See v2a_candidates.status.json and ledger.

## Cross-document Analysis

All candidate experiments also store cross-document metrics in their JSON. Below is the equal-budget source comparison; no scoped metric was used to choose parameters.

|Track|Policy|Budget|CR@budget|R@10|MRR@10|
|---|---|---|---|---|---|
|global|bm25|20|42.86|11.90|0.0561|
|global|dense|20|8.33|4.76|0.0159|
|global|rrf|20|22.62|8.33|0.0490|
|global|protected_union|20|15.48|8.33|0.0490|
|global|bm25|30|50.00|11.90|0.0561|
|global|dense|30|8.33|4.76|0.0159|
|global|rrf|30|22.62|8.33|0.0490|
|global|protected_union|30|34.52|8.33|0.0490|
|global|bm25|50|50.00|11.90|0.0561|
|global|dense|50|8.33|4.76|0.0159|
|global|rrf|50|29.76|8.33|0.0490|
|global|protected_union|50|50.00|8.33|0.0490|
|scoped|bm25|20|46.43|19.05|0.0778|
|scoped|dense|20|29.76|8.33|0.0561|
|scoped|rrf|20|36.90|22.62|0.0958|
|scoped|protected_union|20|41.67|22.62|0.0958|
|scoped|bm25|30|64.29|19.05|0.0778|
|scoped|dense|30|36.90|8.33|0.0561|
|scoped|rrf|30|52.38|22.62|0.0958|
|scoped|protected_union|30|52.38|22.62|0.0958|
|scoped|bm25|50|71.43|19.05|0.0778|
|scoped|dense|50|54.76|8.33|0.0561|
|scoped|rrf|50|71.43|22.62|0.0958|
|scoped|protected_union|50|64.29|22.62|0.0958|

## Rerank Depth Trade-off

Global primary track; current RRF vs candidate-source winner. Each depth has its own one-query warmup then35 timed queries. No LLM or external model service. Scoped A/B/C reported separately; no scoped D grid.

|Policy|Depth|Candidate recall|Cross candidate recall|R@10|MRR@10|Cross R@10|Retrieval p50/p95 ms|Reranker p50/p95 ms|E2E p50/p95 ms|
|---|---|---|---|---|---|---|---|---|---|
|bm25|20|60.00|42.86|55.95|0.3037|34.52|600.107/839.556|5621.453/6553.535|6325.042/7227.491|
|bm25|30|64.29|50.00|53.57|0.2510|29.76|598.931/838.802|8670.060/9521.282|9300.047/10332.144|
|bm25|40|68.57|50.00|56.90|0.2406|29.76|598.715/838.563|14861.879/20030.335|15422.878/20698.375|
|bm25|50|71.43|50.00|56.19|0.2221|26.19|598.685/838.422|18243.806/32238.650|18822.275/32799.051|
|rrf|20|48.81|22.62|47.14|0.2951|19.05|772.821/1275.447|6014.450/8605.717|6827.783/9325.432|
|rrf|30|57.38|22.62|48.57|0.2770|11.90|769.530/1273.360|10012.109/12803.005|10882.954/13506.690|
|rrf|40|63.10|22.62|51.90|0.2605|11.90|773.321/1275.267|13644.384/16963.440|14480.817/17903.861|
|rrf|50|64.52|29.76|50.48|0.2379|19.05|769.839/1274.297|13833.799/15906.181|14754.820/16866.648|

## Latency

Source retrieval is measured separately per retriever/depth/track after warmup. Hybrid retrieval-only time sums the measured source paths and construction time. Reranker-only is timed fresh per query/depth. E2E sums per-query retrieval and reranker times, then takes percentiles; it is not the sum of percentiles and not one contiguous HTTP request. SQL validation/serialization work differs slightly from the original production runner; latency comparisons are diagnostic, not a strict service SLO claim.
Embedding cold load (ms): 12006.562668000015
Reranker cold loads across initial/resumed sessions (ms): [12183.285146000002, 16511.556341000003]. Model loading excluded from all steady-state metrics. BM25 Top50 completed after a process interruption on the following session; seven completed groups were preserved without reruns.

## Selected DEV Configuration

```json
{
  "id": "v2a-D-candidate_winner-20",
  "policy": "bm25",
  "bm25_k": 100,
  "budget": 20,
  "rerank_k": 20,
  "dense_k": 0
}
```

Production defaults: UNCHANGED. This selection is DEV-only and requires a later separate TEST evaluation before a generalization claim.

## Why Selected

Candidate-source winner is BM25-only on Global DEV: equal-budget CR20/30/50 = 60.00/64.29/71.43%, versus current RRF 48.81/57.38/64.52%.
Select the practical operating point Top20 rerank -> Top10, not the maximum-coverage pool: Top40 adds only 0.95 percentage points Recall@10 over Top20 (56.90 vs55.95), reduces MRR (0.2406 vs0.3037), and raises measured E2E p50 from6.33s to15.42s.
Top50 gives only 0.24 percentage points extra Recall@10 (56.19 vs55.95), reduces MRR to0.2221 and cross-document Recall@10 to26.19% versus34.52%; its resumed-session p50 is18.82s. Cross-session timing is observational, but ranking degradation also argues against selecting it.
Top30 is worse than Top20 in final Recall@10 and MRR and costs more. Protected union improves coverage over current RRF at some budgets but never exceeds BM25-only at the same budget; not selected.
This prioritizes a better candidate source, then rejects deeper pools with very small final quality gains and substantially higher costs. Coverage-optimal diagnostic point (Top50, CR71.43%) is distinct from selected reranker input (Top20, CR60.00%).
BM25 retrieve_k=100 is retained from the measured winning source experiment. Dense k=0 means not used by this experimental single-source policy; the production embedding and Hybrid defaults are unchanged.

## Limitations

- 35 DEV questions, only7 cross-document cases; results are observations, not significance/generalization claims.
- No TEST evaluation or ranking inspection.
- Source selection and depth tuned on DEV, with fixed reviewed Gold; no annotation changes.
- Scoped corpus filtering provides extra information and is not comparable to global search difficulty.
- Raw union versus RRF has different candidate budgets; equal-budget C2 is the fair pool-size comparison.
- Reranking cannot recover evidence outside its candidate pool.
- English queries still use fixed Chinese BGE; embedding changes deferred to V2-B.
- Protected-union membership is not necessarily nested across budgets; CR@M is computed for the actual constructed pool.
- All old/failed experiments retained; no best-seed reruns.

## Regression and Final Integrity

- Targeted backend suite: 194 passed (before two additional candidate guard tests).
- Final complete backend suite: 413 passed, 5 skipped, 0 failed in 184.18s. Skips require real MySQL DDL migration fixtures; this offline regression does not claim those migration checks passed.
- Frontend initial parallel run: 113 passed / 21 timeout failures. Build overlapped part of this run. Preserved as a failed run.
- Frontend serial verification: 134 passed / 0 failed across 12 files in 262.81s; `npm test -- --run --maxWorkers=1 --no-file-parallelism`. No assertions or timeout limits changed. A preceding serial attempt lost its process result and is not counted as PASS.
- Frontend production build: PASS (44.94s), existing >500 kB bundle warning retained. No frontend code changes.
- `git diff --check`: PASS.
- DEV and TEST SHA-256 rechecked unchanged; no TEST ranking read or evaluation run.
- Production retrieval, fusion, reranker, embedding, config and chunker hashes match pre-experiment records.
- Eight D result groups retained; seven completed before interruption remain byte-identical. Original invalid equal-budget run and interruption records are preserved.
- Isolated experiment MySQL/Chroma services stopped; data volumes preserved.
- Ready for V2-B: YES. V2-B was not started.
