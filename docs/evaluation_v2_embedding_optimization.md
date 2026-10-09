# V2-B Embedding Optimization

Status: B1 COMPLETE; historical B2 run preserved as BLOCKED; B2.1 reproducibility closure COMPLETE. Controlled B2 ef sweep COMPLETE; B3 query instruction ablation COMPLETE; B4 COMPLETE; B5 freeze COMPLETE (DEV_SELECTED); B6 integration COMPLETE; V2-C not started. No production change.

## Frozen Baseline

V2-A selected DEV: BM25-only retrieve100 -> current reranker20 -> final10.
CR20=60.00%, Recall10=55.95%, MRR10=0.3037. Observed composed latency p50/p95=6.33/7.23s; not a contiguous HTTP measurement.
Corpus: 30 papers, 3837 immutable current chunks. DEV35 / TEST40 frozen.

## Dense Pipeline Audit

### Model and runtime

- Model: BAAI/bge-small-zh-v1.5, 512 dimensions, CPU.
- Actual cached revision: 7999e1d3359715c523056ef9478215996d62a620. Application version label: embedding-v1 (not a model commit pin).
- Sentence Transformers3.4.1, Transformers4.46.3, Torch2.5.1+cpu, Chroma0.5.23.
- Query and document both call the same provider `_encode`; raw text, no prompt/prefix, no default SentenceTransformer prompt. No language routing, translation or mixed-language specialization.
- CLS pooling; mean/max pooling disabled. Actual model includes a final Normalize module. `encode(normalize_embeddings=True)` additionally requests normalization.
- Batch32, max sequence length512, right truncation, tokenizer lowercases. Chroma publication batches128; these are separate batch sizes.
- All3837 chunk token lengths: median233, p95=296.2, max473; 0 truncated. DEV query max51; 0 truncated. This excludes truncation as an observed cause in the audited frozen input.

### Encoding contract

The official BGE v1.5 model card permits instruction-free encoding and recommends testing its documented query instruction for short-query/long-passage retrieval. Passages need no instruction. Missing query instruction is an encoding ablation opportunity, not established implementation failure.

Official reference: https://huggingface.co/BAAI/bge-small-zh-v1.5

The model is Chinese-oriented; the frozen DEV queries are English. Language/domain fit is a hypothesis to test, not a proven sole cause of low Dense recall.

### Distance and rank semantics

- Existing collection uses squared L2; actual HNSW configuration: ef_search10, ef_construction100, M16. Do not substitute defaults from newer Chroma documentation.
- All stored vectors finite; norms range0.9999998918 to1.0000001375.
- For unit vectors, squared L2=2-2*cosine, so exact neighbor ordering is equivalent to cosine. Using L2 is not itself a ranking-direction bug.
- Chroma returns neighbors in distance order. Adapter computes max(0,1-distance), rounded4 decimals, but does not sort by that score; FusionRanker uses enumeration rank. No reversed rank direction found.
- That displayed score is not cosine similarity and clipping can collapse values. It does not drive current Dense/RRF ranking; do not infer calibrated relevance from it.
- ANN search is approximate. ef_search10 is a potential diagnostic factor; no exact-neighbor comparison was performed, so ANN loss is not quantified. Freeze ANN settings across model comparisons; any separate ANN correctness diagnostic must have its own experiment ID.

Distance reference: https://docs.trychroma.com/docs/collections/configure

### Index identity and authority

- Collection: lifeflow_rg_bge_fb38bc0249_512_embedding-v1.
- MySQL ready current memberships3837 across30 documents; Chroma3837.
- Full locator/model/version/hash/text audit: missing0, extra0, mismatch0.
- Three fixed position chunk re-encodings match stored vectors within max absolute error8.94e-8. This is a numerical spot check, not proof that every vector was independently recomputed.
- Publication encodes chunk text with the same provider, verifies vector metadata before ready activation, and refreshes retained version membership metadata.
- Dense candidates pass current ready membership, occurrence/stable ID, document ID, immutable version ID and chunk hash checks. Scoped filtering is pushed into Chroma and checked at final serialization.
- No observed stale/dirty index evidence in this corpus; authority filtering must remain intact.
- Dense acquisition starts at min(200,max(2*requested_k,dense_top_k)), up to3 rounds; returns validated prefix without slicing back. Evaluation must explicitly cap source depth as in V2-A.

### Reproducibility gaps to address in the experiment harness

1. Collection identity includes provider/model/dimension/application version, but not exact model revision, normalization, query/document encoding or max length. The loader does not pin a revision. This is a latent compatibility risk; no mismatch observed in the frozen index.
2. Every V2-B index must use a distinct experiment namespace plus a full encoding/revision fingerprint, verify that fingerprint on reuse, and preserve the old collection.
3. Normalization OFF cannot be implemented solely with encode(normalize_embeddings=False), because this cached model has an internal Normalize module. Any such ablation must explicitly control the effective module pipeline and verify vector norms; otherwise record it as ineffective, not a valid ablation.
4. Keep bug fixes, encoding ablations, model changes and ANN diagnostics under different experiment IDs. No production fix is justified as the established cause of current recall by this audit alone.

Evidence: benchmarks/real_research/v2/results/v2b_dense_audit.json. Audit script: local .tmp/v2b/audit_dense.py. No query ranking or benchmark execution in B1. Chroma emitted a telemetry-library compatibility warning; no LLM was called.

## Embedding Model Candidates

NOT RUN / not selected in B1. Choose2-3 candidates with official encoding contracts and feasible CPU cost during B2. Do not infer a winner from model names or leaderboards.

## Model Comparison

NOT RUN.

## Encoding Strategy Ablation

NOT RUN. Apply the effective-normalization and official-instruction controls above.

## Dense Depth Sweep

NOT RUN.

## BM25 vs Dense Complementarity

NOT RUN.

## Hybrid Candidate Experiments

NOT RUN.

## Reranker Trade-off

NOT RUN. V2-A results preserved.

## Selected DEV Embedding Policy

No V2-B selection. Production defaults unchanged.

## Improvement vs V2-A

Not measured. No improvement claim.

## Cross-document Diagnostics

Not run. Seven DEV cross-document queries remain a small diagnostic subset.

## Benchmark Integrity

DEV SHA-256: 2977076711400a1ff41ee4886c48e9fdd8f68f4e8fd41e2e5a5bd96e537fc7b9
TEST SHA-256: 5b94e93eed901c3ef05df7a9d4efa4d14b9aef19fbdb160d83c314f15306c419
Both unchanged. TEST bytes hashed only; no TEST parsing/ranking/analysis. Gold/split/chunking/BM25/RRF/reranker/production embedding unchanged. Existing frozen baseline results preserved.

## Regression

B1 is an audit only; no production code changes. Local model/index consistency checks above completed. Full backend/frontend/build regression is due after B2-B6 implementation; previous V2-A results are not relabeled as V2-B tests.

## Ready for V2-C?

NO. V2-B model and complementarity experiments have not started.

## B2 ANN Exactness

Status: BLOCKED - correctness guard stopped the ef sweep. No B3.

### Exact reference implementation

Original stored3837 float32 vectors were exported with stable locator mapping, validated against MySQL current ready memberships, fingerprinted, and searched exhaustively in float64. No corpus encoding. Unchanged BGE raw query vectors were encoded once and shared by Exact and ANN. Deterministic locator tie-break.
Every Global/Scoped Top100 ranking agrees between dot and cosine. Full Global order matches for10/35 queries; remaining differences occur below100 with non-exact unit norms. Full Scoped order matches35/35. No claim of full bit-identical Global ordering.

### ef_search implementation and failed isolation check

Installed Chroma0.5.23 uses hnsw:search_ef and calls index.set_ef when loading PersistentLocalHnswSegment. The evaluation-only controller sets the underlying index.ef in an isolated process and verifies it; no public per-query ef API or metadata-only update was assumed.
A read-only stopped-volume copy (34,366,261 bytes) was loaded as a separate PersistentClient snapshot. Its complete vector fingerprint matches the export. However ef10 does NOT reproduce the original service ranking:14/35 Global Top200 responses differ in membership, including one Top50 difference (V2Q036), and zero Scoped differences. Differences have unequal exact distances; not just tie order. Vector equality therefore does not prove identical ANN graph/runtime state. Snapshot restoration/replay is a possible source, not an established root cause.
The ef10 equality guard stopped execution before ef32/64/128. No ef256 run. Snapshot results were not silently substituted for the baseline. Failure record and diagnostic retained in results/v2b2_ann_exactness.json and .tmp/v2b2/failure-*.json.
Minimal next correctness work: establish a verifiably stable isolated ANN graph/state or explicitly separate a reconstructed-graph experiment from the original-service reference; do not relax the equality guard and claim identical original graph.

### ANN Fidelity and Task Metrics

Valid evidence below uses Exact and the original-service read-only ef10 export, not the failed snapshot. Primary n_results=200 matches frozen baseline source acquisition. Fidelity@K is the macro mean of prefix intersections/K, separate from Gold recall. Scoped denominator is min(K,available chunks).
Exact latency uses3 post-warmup repetitions per Query (105 samples per track), search-only. Original-service export was not timed; p50/p95 are unavailable. Snapshot timing is not a valid substitute. No model load/index load/encoding in steady-state timing. Direct-K sweep remains incomplete.

#### global

|Backend|Fidelity10|20|50|100|Hit5|R5|R10|MRR10|CR20|CR50|p50 ms|p95 ms|
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
|exact|100.00|100.00|100.00|100.00|25.71|21.43|25.24|0.1627|27.38|34.05|18.672|32.528|
|original_ef10|100.00|99.71|99.54|99.03|25.71|21.43|25.24|0.1627|25.95|32.62|NOT TIMED|NOT TIMED|

#### scoped

|Backend|Fidelity10|20|50|100|Hit5|R5|R10|MRR10|CR20|CR50|p50 ms|p95 ms|
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
|exact|100.00|100.00|100.00|100.00|40.00|30.71|41.67|0.2692|53.10|84.29|0.424|2.351|
|original_ef10|100.00|100.00|100.00|100.00|40.00|30.71|41.67|0.2692|53.10|84.29|NOT TIMED|NOT TIMED|

### Query-type diagnostic

|Type|Backend|R10|CR20|CR50|
|---|---|---:|---:|---:|
|semantic|exact|21.43|28.57|42.86|
|semantic|original_ef10|21.43|21.43|35.71|
|cross_document|exact|4.76|8.33|8.33|
|cross_document|original_ef10|4.76|8.33|8.33|
|multi_hop|exact|25.00|25.00|45.83|
|multi_hop|original_ef10|25.00|25.00|45.83|

Cross-document n=7, diagnostic only. Selected-ef results unavailable.

### Error cases

Global Exact Top20 but original ef10 misses:1 query-Gold unit. Exact Top50 but ef10 misses:1. Scoped:0/0. Full DEV-only locator/rank export: benchmarks/real_research/v2/ann_exactness_error_cases.csv. Empty selected_ef_gold_rank means no selected ef; missing ef10 rank means absent from returned Top200, not absent from corpus.

### Conclusion

ANN bottleneck: MINOR on the audited frozen200-candidate path. Exact CR20/CR50=27.38%/34.05%, compared with original ef10=25.95%/32.62% (+1.43pp each); R10 and MRR10 unchanged. Original Top50 fidelity=99.54%. There is measurable loss (one Gold), but exact search alone leaves Dense quality low. This does not establish a recommended ef, because the controlled sweep is blocked and latency comparison incomplete.

### Benchmark integrity

DEV frozen and TEST hash unchanged; TEST retrieval NOT RUN; TEST ranking NOT READ; TEST Gold unchanged. Production file hashes match V2-A. No embedding/instruction/normalization/pooling/chunking/BM25/RRF/reranker changes. Both original isolated services stopped; baseline volume preserved. All experiments/failed attempt appended to experiments.csv.

### Regression

Exact/Fidelity unit tests initially5 passed. Final related regression is recorded below. No production/API changes. B3 readiness: NO until the ANN audit correctness closure.

Final related regression: 17 passed / 0 failed (5.71s). `git diff --check`: PASS.


## B2.1 ANN Index Reproducibility

Status: COMPLETE. B2 reproducibility gate closed; ef sweep NOT RUN. B3 NOT STARTED.

### Original and old snapshot forensics

Collection name: `lifeflow_rg_bge_fb38bc0249_512_embedding-v1`.
Collection UUID: `b9d8b096-5eee-4875-bac2-3a8f9ea453d8`.
Vector segment: `9a873541-2f90-43c4-8965-dd9cbfed039e`.
The original and old snapshot preserve the same UUID in separate storage namespaces; they are not two collections in a shared database.

|Field|Original|Old snapshot|
|---|---|---|
|Chroma import version|0.5.23, source checkout|0.5.23, installed package|
|HNSW distribution|chroma-hnswlib0.7.6|chroma-hnswlib0.7.6|
|Python|3.11.11|3.11.15|
|NumPy|2.1.3|2.4.6|
|Architecture|x86_64|x86_64|
|space|l2|l2|
|M|16|16|
|construction_ef|100|100|
|search_ef|10|10|
|resize_factor|1.2|1.2|
|num_threads|16|16|
|batch_size|100|100|
|sync_threshold|1000|1000|
|Logical vector count|3837|3837|
|Persisted graph label count|3000|3000|
|Graph checkpoint|3000|3000|
|SQL metadata checkpoint|3837|3837|
|Retained queue rows|838 (3000..3837)|838 (3000..3837)|
|Creation timestamp|UNKNOWN (no collection timestamp field)|Inherited files; clone time is not collection creation time|

Configuration values above are read from persisted collection configuration and checked against installed HnswParams/source and the actual original-image segment parameters, not assumed from a current documentation default. Segment metadata is empty; collection creation metadata contains project/provider/model/dimension/application version. No hnsw overrides were stored there. Full metadata and source are in the forensic JSON.

Original persistence used a container-local Chroma directory and an environment-specific named volume. These private snapshots are not distributed; see [data policy](evaluation_data_policy.md).

Actual config difference: NONE. Runtime package difference: Python/NumPy and source-checkout versus installed-package loading. HNSW binary SHA-256 is identical: `83d8919b6f4ea4ddfa1a46f52065c24771adefd7cc0905ae4e39b2a744c47554`. Inspected HnswParams, initialization, record application, persistence and query source also match. This does not establish that every uninspected dependency is identical. Controlled replay tests use the original server image, so those Python/NumPy differences are removed from the comparison.

### Vector and insertion identity

Original and old snapshot storage files are byte-identical, including SQLite, HNSW binaries and index_metadata.pickle. Thus stored ID set, vectors, metadata and locator mappings are identical. Exported vector fingerprint is revalidated on every probe. Capture/control/reload metadata+text hashes match.

Persisted first3000 HNSW label-order hash: `cbf77ba83c855c05b32fb463f3fa3185c42bbf4f38be637b9a82331de5fe7e34`.
Historical original-process tail insertion order: UNKNOWN. It was not checkpointed and the historical process is gone. The complete original initial-write order cannot be reconstructed from purged WAL; retained WAL order is available for3000..3837, but WAL order is NOT HNSW batch insertion order.

The old snapshot was a storage copy, not an intentional3837-vector rebuild. On load it replays837 records after checkpoint3000:800 enter HNSW in batches, and37 remain in the brute-force buffer. Installed `Batch.get_written_ids()` returns `list(self._written_ids)` where `_written_ids` is a set. `LocalHnswSegment._apply_batch()` assigns labels and calls index.add_items in that order. Process string hashing can therefore change actual tail insertion order despite identical WAL order and bytes.

### Lifecycle

MySQL records30 succeeded new_document jobs, from2026-09-21 04:09:55 to04:16:59 (database timestamps). All30 documents are ready at version1; each has one DocumentVersion. No reprocess/version replacement is evidenced by those records. The838 retained WAL operations are UPSERT. Earlier queue history has been pruned; delete/update/reconciliation/reinsert history outside retained records is UNKNOWN, not asserted absent. Collection creation time itself is UNKNOWN.

### Controlled reproduction and capture

Seed0 and seed1 were fixed before these probes, solely to test process-hash reproducibility. No seed search or retrieval-quality selection was performed. Both run the original Chroma server image and ef10, with the same stored vectors and first3000 graph labels.

|Probe|Tail-inclusive label sequence hash|Top10 original agreement|Top20|Top50|Top100|Top200|
|---|---|---:|---:|---:|---:|---:|
|Predeclared seed0 capture|5197622490cb6072a13d1be8d3cc043f0e99ad3e424f7b47e1b06c552a9a3444|35/35|35/35|35/35|30/35|20/35|
|Seed1 uncaptured control|4e9a106e550a057f12a16d75ac5dcbae1bb0de5b0e1ace5a691a2b781fd7689e|35/35|35/35|34/35|25/35|19/35|
|Captured seed0 graph reloaded with seed1|same as seed0 capture|35/35|35/35|35/35|30/35|20/35|

The two uncaptured replays share the first3000 labels but differ in tail order and14 Top200 responses. This confirms a reproducible replay-order variation mechanism. Historical process hash seed/order remains UNKNOWN; parallel HNSW construction was not separately ablated, so the exact contribution of every construction detail is not claimed.

Evaluation-only capture persists the already-built3800-node graph without changing it and stores graph checkpoint3800, leaving37 queue entries for the brute-force buffer. It does NOT mark3837 as persisted while those37 vectors are absent from HNSW. Guarded implementation rejects pending updates/deletes, tail >= batch size and paths outside the experiment root. No original volume is written.

After cross-process reload with a different hash seed: graph file hashes,3800 label sequence,3837 vector fingerprint, metadata, and all35 complete Top200 IDs AND distances are identical to the captured run. Remaining37 records rebuild only the exact buffer, not HNSW edges. This is a stable same-graph experiment base, not a claim of bit-identical restoration of the original historical graph tail.

The chosen predeclared seed0 capture matches ALL original-service Top50 rankings and hence all Frozen DEV task metrics in scope. Its Top100/200 differences are retained and explained as replay-construction tail variation; original B2 measurements are preserved without overwrite.

### Detailed ranking differences

Old14-query difference export: `benchmarks/real_research/v2/ann_reproducibility_rank_diff.csv` (1085 differing rank positions). Each row includes both IDs, both exact ranks/scores, affected TopK boundary and recomputed squared-L2 distances. Historical raw ANN distances were not saved; distance source is explicitly RECOMPUTED_FLOAT64_FROM_FROZEN_VECTORS, not fabricated historical service output.

|Absolute delta|Minimum|Median|p95|Maximum|Exact zero|
|---|---:|---:|---:|---:|---:|
|Squared L2|3.36684e-8|0.0001757213|0.0008654431|0.0050312409|0|
|Dot score|5.60120e-8|0.0000878858|0.0004326686|0.0025156875|0|

No arbitrary near-tie threshold is used. Some differences are numerically small, but they are not all strict ties; no baseline reordering or threshold-based forgiveness was applied.

Unique old Top50 case V2Q036:

|Chunk|Gold?|Original rank|Old snapshot rank|Exact rank|Squared L2|Dot score|
|---|---|---:|---:|---:|---:|---:|
|doc-26-chunk-18de54ca2514492bb1b03db0|NO|outside returned200|25|25|0.6528776546|0.6735612604|
|doc-30-chunk-4d7be4acd5e1d24b849755ae|NO|50|51|51|0.6786078833|0.6606960313|

Neither differing member is Gold. This Top50 membership difference does not itself change this Query's CR50. It was still a valid reason to diagnose graph reproducibility.

### Post-processing and deterministic ties

Production Dense retrieval performs current-ready membership/occurrence/stable ID validation, document/version/hash checks, then fusion rank construction and truncation. Chroma emits distance order; the clipped displayed score is not used to re-sort Dense candidates. Fusion uses ranks; stable Python sort preserves insertion order on tied fusion scores. No new production tie-break was introduced.

The B2 export validated all3837 IDs/text/metadata against MySQL current memberships; B2.1 revalidates the identical vector/metadata universe and MySQL ready/version1 state. Therefore authority/version filtering removes zero candidates in these raw Chroma comparisons; scope and dedup likewise do not change the global unique-ID lists. Exact uses score descending then stable chunk_id ascending. It does not rewrite the original baseline to that tie rule.

### EF mutability and decision

Chroma0.5.23 initializes native HNSW with index.set_ef(search_ef); native search ef is runtime mutable on the same graph. No public per-query ef argument is assumed. The controlled evaluation mechanism is private `PersistentLocalHnswSegment._index.set_ef(value)` with effective `.ef` assertions and graph/vector fingerprints before/after, pinned to this backend version. It does not rebuild the graph or modify the production collection.

Stable index manifest: `benchmarks/real_research/v2/results/v2b21_stable_index_manifest.json`.
Same-graph ef sweep possible: YES.
Ready for B2 ef sweep: YES, using the verified stable snapshot and original server image.
Sweep performed in B2.1: NO.
Ready for B3: NO, B2 controlled sweep still pending.

### Preserved ANN conclusion and integrity

Original ef10 -> Exact: R10 25.24% ->25.24%; MRR10 0.1627 ->0.1627; CR20 25.95% ->27.38%; CR50 32.62% ->34.05%. ANN bottleneck remains MINOR.

Existing B2 result file is byte-identical (SHA-256 saved in B2.1 result). DEV/TEST hashes unchanged; no TEST ranking read/run/encoding. No corpus re-encoding, model/prefix/pooling/normalization/chunking/Gold/query/RRF/reranker/production changes. Initial import-path, missing application dependency and Docker-start failures are retained in the audit result/ledger. Read-only MySQL service stopped after forensics.

B2.1 related regression: **37 passed / 0 failed**, 5.55s. Final historical B2/DEV/TEST/production hashes unchanged.

## V2-B2 Controlled EF Sweep

Status: COMPLETE. Same stable graph; only search_ef changed. Ready for B3, not started.

### Protocol

Six effective index.ef settings10/20/40/80/120/200 in one process, pinned original Chroma0.5.23/chroma-hnswlib0.7.6 image. M16/construction_ef100/squared L2 unchanged. Existing3800-node graph plus37-item exact buffer, total3837 vectors. No create_collection, insertion, graph rebuild, model inference or corpus encoding.
Global Frozen DEV35 queries. Existing Exact ranking reused byte-identically; frozen Query vectors reused and fingerprinted. n_results200 held constant to match frozen Dense source acquisition. Every group warmed with all35 queries; five timed rounds retain all175 samples per setting. EF order rotates by round. Graph file hashes, native index object, label mapping and frozen inputs checked between groups; rankings stable across repetitions. ef restored to10 after completion.
Timing boundary: local collection.query, including Python/SQLite filtering, HNSW search and exact-buffer merge; excludes HTTP, query embedding, model/index cold load, metric calculations, and MySQL authority work. Percentiles use existing nearest-rank convention. Index cold load excluded: 3101.400 ms.

### Primary results

|search_ef|R10 %|MRR10|CR20 %|CR50 %|Exact Top50 overlap %|Mean ms|p50 ms|p95 ms|
|---|---:|---:|---:|---:|---:|---:|---:|---:|
|Exact|25.24|0.1627|27.38|34.05|100.00|N/A|N/A|N/A|
|10|25.24|0.1627|25.95|32.62|99.54|8.907|8.344|12.256|
|20|25.24|0.1627|25.95|32.62|99.54|7.903|7.816|9.530|
|40|25.24|0.1627|25.95|32.62|99.54|7.975|7.667|10.635|
|80|25.24|0.1627|25.95|32.62|99.54|8.312|7.734|11.533|
|120|25.24|0.1627|25.95|32.62|99.54|7.971|7.864|9.696|
|200|25.24|0.1627|25.95|32.62|99.54|11.004|8.499|24.422|

### Delta and Exact gap

Every setting has delta vs ef10: R10=0pp, MRR10=0, CR20=0pp, CR50=0pp. Every setting has Exact-minus-ANN gap: R10=0pp, MRR10=0, CR20=1.428571pp, CR50=1.428571pp. These are unchanged across the complete sweep; all Top200 returned ID lists are identical across settings. Per-setting deltas and gaps are saved in JSON.

### Ranking convergence

|ef|Top10 overlap|Top20 overlap|Top50 overlap|Exact Top10 order equal|Top20 order equal|Top50 order equal|
|---|---:|---:|---:|---:|---:|---:|
|10|100.00%|99.71%|99.54%|35/35|33/35|30/35|
|20|100.00%|99.71%|99.54%|35/35|33/35|30/35|
|40|100.00%|99.71%|99.54%|35/35|33/35|30/35|
|80|100.00%|99.71%|99.54%|35/35|33/35|30/35|
|120|100.00%|99.71%|99.54%|35/35|33/35|30/35|
|200|100.00%|99.71%|99.54%|35/35|33/35|30/35|

### Curves

!Quality vs ef (`artifacts/evaluation_v2/b2_ef_quality.png`; private historical artifact, not distributed)

!Latency vs ef (`artifacts/evaluation_v2/b2_ef_latency.png`; private historical artifact, not distributed)

PNG and SVG versions both retained; all six settings shown.

### Why the curve is flat

Version-matched [chroma-hnswlib0.7.6 source](https://github.com/chroma-core/hnswlib/blob/0.7.6/hnswlib/hnswalg.h#L1597-L1607) passes max(ef_,k) to searchBaseLayerST. For this frozen request depth200, all tested ef settings have the same native search-width floor. The configuration DID change (index.ef checked every query), but the effective exploration width did not increase. This is not a metadata-no-op error and not evidence that ef never matters at smaller k. No additional variable or out-of-range ef was tested.

### Decision

ANN bottleneck: **MINOR**. Existing Exact upper-bound gap remains1.43pp in CR20/50, with no R10/MRR10 gap. Increasing ef within the allowed range buys zero candidate/ranking quality here. Recommend **search_ef=10 for the current frozen n_results200 path**. Observed latency varies non-monotonically; because native search width is unchanged, do not interpret the ef200 p95 increase or ef20 reduction as proven causal effects. Do not select a parameter from timing noise.
**Further ANN optimization is not justified.** Close V2-B2 and proceed to B3 only when requested. This does not endorse ef10 for future smaller-depth search without separate validation. Production settings remain unchanged.

### Artifacts and integrity

Raw result with per-query rankings/all175 latency samples per setting: `artifacts/evaluation_v2/b2_ef_sweep.json`. Complete query-type summaries are included. Existing B2.1 and original Exact/ef10 results preserved. DEV/TEST hash unchanged; TEST bytes hashed only, no TEST parsing/ranking/retrieval/encoding. Embedding/instruction/normalization/pooling/chunking/Gold/BM25/RRF/reranker unchanged. No external LLM.
Runner: `backend/scripts/run_v2_ef_sweep.py`; renderer: `backend/scripts/report_v2_ef_sweep.py`. Ledger: six new controlled-sweep rows appended without dropping previous results.

### Validation

Related regression: **40 passed, 0 failed** (5.01s). Both convergence charts visually checked. Final protected production/DEV/TEST/Exact file hashes and stable graph file hashes: PASS. `git diff --check`: PASS. No production edits, no TEST ranking access, no B3 execution.

## B3 Query Instruction Ablation

Status: COMPLETE. Production remains unchanged. B4 not started.

### Official Model Contract

Model: BAAI/bge-small-zh-v1.5; revision: 7999e1d3359715c523056ef9478215996d62a620.
Official query prefix: `为这个句子生成表示以用于检索相关文章：` (Chinese full-width colon, directly concatenated with the unchanged English query; no extra separator).
The fixed-revision model card permits no-instruction retrieval with v1.5 and describes improved instruction-free performance. It recommends trying a query instruction for short-query/long-passage retrieval and selecting using task results. Documents/passages never receive an instruction.
Source: [fixed revision model card](https://huggingface.co/BAAI/bge-small-zh-v1.5/blob/7999e1d3359715c523056ef9478215996d62a620/README.md), Model List row for bge-small-zh-v1.5 and FAQ 3. This evaluates an optional encoding strategy, not a bug fix.

### Experimental Setup

Frozen 35 DEV queries; TEST bytes used only for SHA-256 protection. No query rewriting, translation, scope injection or Gold edits. CPU, 512 dimensions, CLS, normalization ON. Same existing 3,837 document vectors, same graph, squared L2, M16, construction_ef100, n_results200, search_ef10. No document encoding or insertion; no reranker or Hybrid execution.
Collection: `lifeflow_rg_bge_fb38bc0249_512_embedding-v1`; UUID `b9d8b096-5eee-4875-bac2-3a8f9ea453d8`.
Document vector fingerprint: `3e58338f4cc1a9753f0c7a5e69328ef9941a1a7a04081a00510c057a109ee79e`.
Corpus hash: `597f5c78d662774cadb7fa0fa15102b8b60ec27eb6d5bc429818d43ce308f465`.
Each configuration is fingerprinted with the actual frozen chunking config (version/size/overlap), model revision, query strategy/prefix, document strategy, pooling, normalization, dimension, metric and search controls. Chunker source hash is separately recorded.
Fresh raw batch query vectors are byte-identical to the frozen baseline (max absolute error 0.0). Every instructed query vector differs from raw; every tokenizer input was captured and checked, with no truncation. Full 35-query encoding details per strategy are in `artifacts/evaluation_v2/b3_query_encoding.json`.

- raw config fingerprint: `135428437278a96767844c2d836c947fe23a8b89e8615141dd1e05feed82013d`.
- official_instruction config fingerprint: `bf59a24b4ac4442f6f73a0bf5c326d2138fb62de48047601f13ea704862f8e74`.

Encoding verification samples (fixed positions 0, 17, 34; selected without ranking inspection):

- raw / V2Q027: tokens=30, dim=512, norm=1.000000119.
  Raw: What communication needs in the maritime ecosystem motivate the integration of UAVs?
  Encoded: What communication needs in the maritime ecosystem motivate the integration of UAVs?
- raw / V2Q050: tokens=30, dim=512, norm=1.000000000.
  Raw: How does the marine multi-UAV MEC design handle the limited computing and energy resources of UAVs?
  Encoded: How does the marine multi-UAV MEC design handle the limited computing and energy resources of UAVs?
- raw / V2Q074: tokens=39, dim=512, norm=1.000000000.
  Raw: How does the offshore multi-UAV system connect its caching architecture, constraints, and decomposition strategy?
  Encoded: How does the offshore multi-UAV system connect its caching architecture, constraints, and decomposition strategy?
- official_instruction / V2Q027: tokens=49, dim=512, norm=1.000000000.
  Raw: What communication needs in the maritime ecosystem motivate the integration of UAVs?
  Encoded: 为这个句子生成表示以用于检索相关文章：What communication needs in the maritime ecosystem motivate the integration of UAVs?
- official_instruction / V2Q050: tokens=49, dim=512, norm=1.000000000.
  Raw: How does the marine multi-UAV MEC design handle the limited computing and energy resources of UAVs?
  Encoded: 为这个句子生成表示以用于检索相关文章：How does the marine multi-UAV MEC design handle the limited computing and energy resources of UAVs?
- official_instruction / V2Q074: tokens=58, dim=512, norm=1.000000000.
  Raw: How does the offshore multi-UAV system connect its caching architecture, constraints, and decomposition strategy?
  Encoded: 为这个句子生成表示以用于检索相关文章：How does the offshore multi-UAV system connect its caching architecture, constraints, and decomposition strategy?

### Global Results

Primary selection track. Existing macro-averaged chunk-locator metrics; multi-Gold recall denominator preserved.

|Strategy|Hit@5|R@5|R@10|MRR@10|CR@20|CR@50|Search p50 ms|Search p95 ms|
|---|---:|---:|---:|---:|---:|---:|---:|---:|
|raw|25.71%|21.43%|25.24%|0.1627|25.95%|32.62%|12.870|19.836|
|official_instruction|25.71%|22.38%|24.52%|0.1377|30.24%|36.90%|16.817|27.255|

### Scoped Diagnostic

DIAGNOSTIC ONLY; document_id filter uses each frozen document scope. Scoped results do not independently select the strategy.

|Strategy|Hit@5|R@5|R@10|MRR@10|CR@20|CR@50|Search p50 ms|Search p95 ms|
|---|---:|---:|---:|---:|---:|---:|---:|---:|
|raw|40.00%|30.71%|41.67%|0.2692|53.10%|84.29%|1467.054|2337.068|
|official_instruction|42.86%|33.10%|47.38%|0.2689|51.67%|84.29%|1580.177|2761.961|

### Query-type Results

Global DEV; small category samples, descriptive observations only.

|Type|n|Strategy|R@10|MRR@10|CR@20|CR@50|
|---|---:|---|---:|---:|---:|---:|
|cross_document|7|raw|4.76%|0.0159|8.33%|8.33%|
|cross_document|7|official_instruction|8.33%|0.0464|15.48%|22.62%|
|exact_term|5|raw|20.00%|0.0667|20.00%|20.00%|
|exact_term|5|official_instruction|20.00%|0.0400|20.00%|20.00%|
|factual|7|raw|57.14%|0.3095|57.14%|57.14%|
|factual|7|official_instruction|57.14%|0.2714|57.14%|57.14%|
|multi_hop|4|raw|25.00%|0.1875|25.00%|45.83%|
|multi_hop|4|official_instruction|12.50%|0.0357|12.50%|45.83%|
|relational|5|raw|20.00%|0.2000|20.00%|30.00%|
|relational|5|official_instruction|20.00%|0.2000|20.00%|20.00%|
|semantic|7|raw|21.43%|0.1905|21.43%|35.71%|
|semantic|7|official_instruction|21.43%|0.1786|42.86%|50.00%|

### Paired Query Analysis

lexicographic (CR50, CR20, R10, MRR10); UNCHANGED means selected metrics equal, not identical full ranks. This predeclared comparison prioritizes candidate coverage; full per-Gold ranks and all mixed-direction changes are retained, including when the headline class is UNCHANGED.
Counts: {"REGRESSED": 6, "UNCHANGED": 22, "IMPROVED": 7}.
Complete 35-row export: `benchmarks/real_research/v2/b3_instruction_paired_cases.csv`. Ranks are within the Top200 result; blank/null means not returned, not an inferred exact rank.

### Candidate Gains and Losses

Counts are query-Gold pairs, not globally unique chunks; macro recall and these counts have different weighting.

|Cutoff|New Gold hits|Lost Gold hits|Net|
|---|---:|---:|---:|
|20|3|1|2|
|50|4|1|3|

### Cross-document Diagnostic

DIAGNOSTIC ONLY: few cross-document queries; no generalization claim.

|Strategy|n|R@10|MRR@10|CR@20|CR@50|
|---|---:|---:|---:|---:|---:|
|raw|7|4.76%|0.0159|8.33%|8.33%|
|official_instruction|7|8.33%|0.0464|15.48%|22.62%|

### Latency

Three rounds x 35 queries per strategy/track after a complete 35-query warmup. Strategy order alternates each round; all samples retained. Model load, index load and cold starts excluded. Query encoding and search measured separately in their pinned runtimes; values are not contiguous HTTP end-to-end latency. Search runs without concurrent tests.
Local Chroma collection.query including SQLite filter/HNSW/buffer merge, excludes embedding/HTTP/MySQL/metric calculation.
Encoding runtime: {"sentence-transformers": "3.4.1", "transformers": "4.46.3", "torch": "2.5.1+cpu", "numpy": "2.4.6"}. Search runtime: {"chromadb": "0.5.23", "chroma-hnswlib": "0.7.6", "numpy": "2.1.3"}. Both strategies share the same runtime for each measured component.

|Strategy|Encoding p50 ms|Encoding p95 ms|Global search p50 ms|Global search p95 ms|
|---|---:|---:|---:|---:|
|raw|63.785|205.990|12.870|19.836|
|official_instruction|62.546|149.632|16.817|27.255|

### Decision

Selected query strategy: **OFFICIAL_INSTRUCTION**. Instruction effect: **BENEFICIAL**.
Candidate-coverage benefit on Frozen DEV: Global CR50 increases from 32.62% to 36.90%, and CR20 from 25.95% to 30.24% (+4.29pp each). Gold pair gains/losses are 3/1 at20 and 4/1 at50; this is a net gain with regressions, not uniformly better retrieval. R10 falls from 25.24% to 24.52% (-0.71pp), MRR10 from 0.1627 to 0.1377 (-0.0250). The predeclared paired rule yields 7 improved, 6 regressed, 22 unchanged. Cross-document coverage rises, but its 7-query sample is diagnostic only; multi-hop early ranking regresses. Global search p50/p95 rises from 12.87/19.84ms to 16.82/27.26ms. Under the requested candidate-first priority, select official instruction for the next controlled Dense experiment; do not promote it to production or claim an overall ranking win.
Selection uses Frozen Global DEV, with CR50 before CR20/R10/MRR10, then cross-document coverage/regressions/latency. No claim that English queries inherently require an instruction or that this establishes model language fit.
Production configuration unchanged. Ready for B4; B4 not started.

### Integrity and Regression

DEV/Gold unchanged; TEST untouched, ranking unread; stable graph and document vector fingerprints unchanged; model/chunking/BM25/RRF unchanged; reranker not involved; external LLM calls zero.
Related regression: 35 passed / 0 failed. Two harness failures were retained: missing /chroma in PYTHONPATH before retrieval, then package-metadata lookup at final serialization. The latter lost its in-memory measurements; it was not a quality-based exclusion. The identical search protocol was rerun after correcting version reporting and adding per-round checkpoints. No query re-encoding or parameter changes.
Raw result: `artifacts/evaluation_v2/b3_query_instruction.json`. Query vectors and encoding validation retained alongside it. Exactly two V2-B3 rows appended to experiments.csv; previous rows preserved. An intermediate attempt was stopped before the measured protocol completed because lazy NPZ loading would contaminate search timing. Query vectors were materialized in memory before the final run; aborted-run provenance is retained. No strategy/quality-based run selection was performed.

Final closeout checks: frozen production/DEV/TEST/Exact/corpus hashes PASS; stable graph hashes PASS; previous 80 ledger rows preserved with exactly 2 B3 rows appended; 35 paired rows exported; all 105 timing samples per configuration/track retained; `git diff --check` PASS.

## B4 Embedding Model Comparison

Status: COMPLETE. Frozen DEV only; production defaults unchanged; B5/B6 not started.

### Model Contracts

All models CPU FP32, official CLS pooling plus unit normalization, original documents without prefix. Official model cards and fixed revision pooling/max-length configs checked before running. M3 uses Dense output only; no sparse/ColBERT mode.

|Key|Model|Revision|Dimension|Max length|Parameters|Query prefix|Document prefix|License|
|---|---|---|---:|---:|---:|---|---|---|
|zh|BAAI/bge-small-zh-v1.5|7999e1d3359715c523056ef9478215996d62a620|512|512|23,953,920|为这个句子生成表示以用于检索相关文章：|NONE|MIT|
|en|BAAI/bge-small-en-v1.5|5c38ec7c405ec4b44b94cc5a9bb96e735b38267a|384|512|33,360,000|Represent this sentence for searching relevant passages: |NONE|MIT|
|m3|BAAI/bge-m3|5617a9f61b028005a4858fdac845db406aefb181|1024|8192|567,754,752|NONE|NONE|MIT|

Source (zh): [fixed revision model card](https://huggingface.co/BAAI/bge-small-zh-v1.5/blob/7999e1d3359715c523056ef9478215996d62a620/README.md).
Source (en): [fixed revision model card](https://huggingface.co/BAAI/bge-small-en-v1.5/blob/5c38ec7c405ec4b44b94cc5a9bb96e735b38267a/README.md).
Source (m3): [fixed revision model card](https://huggingface.co/BAAI/bge-m3/blob/5617a9f61b028005a4858fdac845db406aefb181/README.md).

Document token lengths use each model tokenizer on the same unchanged chunks; model max-length differences are part of the official representation contract.

|Model|Max observed tokens|Model limit|Chunks truncated|
|---|---:|---:|---:|
|zh|473|512|0|
|en|567|512|1|
|m3|520|8192|0|

### Experimental Protocol

Same 3,837 immutable chunks and 35 frozen DEV queries; TEST only hashed, never parsed or ranked. Same frozen authoritative document/version/metadata membership. Same n_results200, search_ef10, M16, construction_ef100, HNSW threads16. Model-specific official representation settings are the sole retrieval treatment.
Each model runs in its own process, Torch4 threads, single-query encoding. Corpus batches16 for small models and4 for M3. Full corpus encoding checkpointed in256-chunk shards. No chunking, BM25, RRF, reranker, Graph or workflow changes.
Baseline uses a separately copied existing stable graph, preserving B3 identity; candidates use independently named collections. No graph seed sweep or rebuild selection. Baseline full corpus re-encoding is measured for cost and verified against stored vectors, but those stored vectors remain unchanged.
Exact float64 dot/cosine search uses each index stored vectors for diagnostics only. Primary metrics use Chroma and unchanged macro chunk-level scoring.

### Index Integrity

|Model|Chunks|Missing|Extra|Duplicates|Metadata/text mismatch|Fresh-vector checks|Fingerprint|
|---|---:|---:|---:|---:|---:|---|---|
|zh|3837|0|0|0|0|3/3 PASS|3e58338f4cc1a9753f0c7a5e69328ef9941a1a7a04081a00510c057a109ee79e|
|en|3837|0|0|0|0|3/3 PASS|d55ac22665453ec140d2cf2bdb7629996c59cfcd34f33e05c876d8d627ed55ea|
|m3|3837|0|0|0|0|3/3 PASS|65eae63ff2fbd1cc1441f87004a34f54a1a89b34b210970e9c08831b7d206409|

Query encoding audit includes all35 raw/actual texts, token counts, dimensions and norms per model. Prefix entry into tokenizer is asserted. Random chunk checks use fixed seed20260930. No sample is selected using ranking.

### ANN Fidelity

Global. Stop thresholds: mean Top50 overlap below98%, or absolute ANN/Exact Gold CR50 gap above2pp.

|Model|Top20|Top50|Top100|ANN CR50|Exact CR50|Exact-minus-ANN pp|
|---|---:|---:|---:|---:|---:|---:|
|zh|99.86%|99.37%|98.91%|36.90%|36.90%|0.000|
|en|99.86%|99.66%|99.54%|54.76%|54.76%|0.000|
|m3|100.00%|99.83%|99.54%|70.71%|70.71%|0.000|

Scoped fidelity also checked and passed; full diagnostics retained in each model JSON.

### Global Dense Results

PRIMARY RESULT.

|Model|Hit@5|R@5|R@10|MRR@10|CR@20|CR@50|
|---|---:|---:|---:|---:|---:|---:|
|zh|25.71%|22.38%|24.52%|0.1377|30.24%|36.90%|
|en|31.43%|23.81%|34.76%|0.2149|40.00%|54.76%|
|m3|57.14%|45.24%|51.19%|0.3115|61.19%|70.71%|

### Scoped Diagnostic

DESCRIPTIVE / DIAGNOSTIC ONLY; not used independently for model selection.

|Model|Hit@5|R@5|R@10|MRR@10|CR@20|CR@50|
|---|---:|---:|---:|---:|---:|---:|
|zh|42.86%|33.10%|47.38%|0.2689|51.67%|84.29%|
|en|40.00%|29.52%|47.62%|0.2915|64.29%|82.62%|
|m3|65.71%|50.95%|65.95%|0.4205|77.86%|91.43%|

### Query-type Diagnostic

DESCRIPTIVE / DIAGNOSTIC ONLY; category sample sizes are small.

|Type|n|Model|R10|MRR10|CR20|CR50|
|---|---:|---|---:|---:|---:|---:|
|cross_document|7|zh|8.33%|0.0464|15.48%|22.62%|
|cross_document|7|en|11.90%|0.0476|11.90%|35.71%|
|cross_document|7|m3|17.86%|0.1893|34.52%|60.71%|
|exact_term|5|zh|20.00%|0.0400|20.00%|20.00%|
|exact_term|5|en|60.00%|0.2619|60.00%|60.00%|
|exact_term|5|m3|40.00%|0.1333|60.00%|60.00%|
|factual|7|zh|57.14%|0.2714|57.14%|57.14%|
|factual|7|en|42.86%|0.3143|57.14%|57.14%|
|factual|7|m3|71.43%|0.3571|85.71%|85.71%|
|multi_hop|4|zh|12.50%|0.0357|12.50%|45.83%|
|multi_hop|4|en|33.33%|0.4583|41.67%|54.17%|
|multi_hop|4|m3|54.17%|0.3833|62.50%|62.50%|
|relational|5|zh|20.00%|0.2000|20.00%|20.00%|
|relational|5|en|40.00%|0.1467|40.00%|70.00%|
|relational|5|m3|80.00%|0.4467|80.00%|80.00%|
|semantic|7|zh|21.43%|0.1786|42.86%|50.00%|
|semantic|7|en|28.57%|0.1587|35.71%|57.14%|
|semantic|7|m3|50.00%|0.3776|50.00%|71.43%|

### Paired Gain/Loss Analysis

Compared with B4-A instruction baseline. Classification follows CR50, CR20, R10, MRR10 lexicographically; UNCHANGED refers to these measures, not all ranks. All per-Gold ranks retained, missing ranks mean not returned in Top200.
CSV: `benchmarks/real_research/v2/b4_embedding_paired_cases.csv`. Counts are Query-Gold pairs, not globally distinct chunks.

|Model|Improved|Unchanged|Regressed|New20|Lost20|Net20|New50|Lost50|Net50|
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
|en|17|8|10|12|7|5|17|8|9|
|m3|21|7|7|21|4|17|22|4|18|

### Cross-document Analysis

n=7, DIAGNOSTIC ONLY.

|Model|R10|MRR10|CR20|CR50|
|---|---:|---:|---:|---:|
|zh|8.33%|0.0464|15.48%|22.62%|
|en|11.90%|0.0476|11.90%|35.71%|
|m3|17.86%|0.1893|34.52%|60.71%|

### CPU Quality / Latency Trade-off

All timings milliseconds unless marked seconds. Each model:35 warmup queries per track then3 rounds,105 timed queries per track. Encoding and Chroma search are separately timed within the same contiguous local Dense call. E2E excludes public HTTP/live MySQL roundtrip; frozen-authority candidate validation included. Model load, index load, full corpus encoding and construction are excluded from warm query percentiles.
Model load and corpus/index costs include observed local conditions and are not service SLOs. Baseline index-build field measures an existing graph copy, not a fresh HNSW build; this is explicitly not a comparable construction-time experiment.
RSS is Linux process RSS; sampled encoding RSS is a lower bound, and high-water RSS through encoding includes earlier load. No GPU metrics. Index disk size is the entire isolated namespace. Model snapshot size includes local model assets.

|Model|Load s|Corpus encode s|Index build/copy s|Encode p50/p95 ms|Search p50/p95 ms|E2E p50/p95 ms|RSS after load MiB|Peak process MiB|Index MiB|Model snapshot MiB|
|---|---:|---:|---:|---|---|---|---:|---:|---:|---:|
|zh|1.00|355.28|2.47|23.77/32.80|130.84/216.12|154.73/242.82|435.4|1014.2|34.5|91.9|
|en|0.45|498.94|126.89|37.80/59.18|166.27/284.40|205.84/345.78|517.4|1034.9|32.4|128.2|
|m3|4.16|5746.11|133.88|349.23/504.88|184.03/252.18|530.46/829.84|694.5|2872.0|42.7|2208.2|

Scoped latency distributions and full per-query samples are retained in the JSON results.

### Dense Winner Recommendation

Quality winner: **m3**. Practical winner candidate: **m3**.
M3 is the recommended B5 candidate: versus EN, Global CR50 +15.95pp, CR20 +21.19pp, R10 +16.43pp and MRR10 +0.0966; cross-document CR50 +25.00pp (n=7 diagnostic only). This is a substantial observed coverage gain on frozen DEV, at 2.58x local Dense p50 latency (530 vs 206 ms), 11.52x corpus encoding time and 2.78x peak process RSS. For the current single-machine research use case, prioritize this coverage gain; EN remains the lower-cost alternative if resource/latency constraints dominate. No production switch or generalization claim.
No weighted aggregate ranking score is introduced. English-specific gains apply to this English scientific DEV benchmark; M3 differences cannot be attributed solely to multilingual capability because scale/architecture/training/dimension also differ. Production default unchanged; B5 must explicitly freeze a choice before B6 integration.

### Integrity and Validation

DEV35 and Gold frozen; TEST40 hash unchanged, retrieval NOT RUN, ranking NOT READ, metrics NOT COMPUTED. Chunking/BM25/Fusion/Reranker/production defaults unchanged. Only three model configurations evaluated. Related regression:138 passed,0 failed. Raw model results, queries/token audits, vector fingerprints, and all latency samples are under `artifacts/evaluation_v2/b4/`.
Preserved all earlier experiment rows and added exactly three V2-B4 rows. No B5/B6 execution.

Final closeout: `git diff --check` PASS; new B4 Python files syntax/whitespace PASS; original stable graph hashes and protected production files unchanged. Preserved 82 earlier ledger rows and appended exactly 3 B4 rows; paired export contains 70 rows. Machine-readable assertions: `artifacts/evaluation_v2/b4/final_validation.json`. All runs used offline containers with a 6 GiB memory limit. No fallback model was used.

## B5 Dense Winner Freeze

Status: COMPLETE. **DEV_SELECTED**, **not TEST_VALIDATED**, **not PRODUCTION_DEFAULT**. B6 not started.

### Frozen Configuration

Config: `benchmarks/real_research/v2/final_dense_config.json`. BAAI/bge-m3 revision `5617a9f61b028005a4858fdac845db406aefb181`. Query/document RAW, no instruction; CLS pooling; normalization ON; dimension 1024; max length 8192; squared L2; n_results=200; search_ef=10. HNSW construction settings unchanged.

### Selection Rationale

Predeclared priority: Global CR@50, CR@20, R@10, MRR@10, cross-document coverage, paired gain/loss, CPU cost. M3 leads the DEV quality metrics enough to justify its higher cost. No weighted/composite score. Global R@10=51.19%, MRR@10=0.3115, CR@20=61.19%, CR@50=70.71%. See B4 comparisons above; no model search or benchmark rerun.

### Quality / Cost Caveat

M3 is the current quality winner, not the cheapest configuration. BAAI/bge-small-en-v1.5 remains a **LOWER-COST ALTERNATIVE**, not the frozen winner.
Measured B4 costs: load 4.16 s; corpus encoding 5746.11 s; index build 133.88 s; query encoding p50/p95 349.23/504.88 ms; search p50/p95 184.03/252.18 ms; local Dense E2E p50/p95 530.46/829.84 ms; peak RSS 2872 MiB; index size 42.7 MiB. E2E excludes HTTP/live MySQL as defined in B4.
Cross-document R@10=17.86%, MRR@10=0.1893, CR@20=34.52%, CR@50=60.71%. **n=7, DIAGNOSTIC ONLY**; no statistical/generalization claim.

### Reproducibility Identity

- Embedding fingerprint: `a4e4b0deb6a1d1d08f690f61a0a7186b09932d3912d57c0ec777113331481346`.
- Chunking hash: `50d07999361f77aeb73684dcdf90946892e529d1b3d3b75646d58ad30995ff53`.
- Corpus manifest hash: `597f5c78d662774cadb7fa0fa15102b8b60ec27eb6d5bc429818d43ce308f465`.
- Namespace: `v2b4-m3-a4e4b0deb6a1d1d0`; collection ID: `019ad311-0490-472a-b772-8fecadcfdb75`.
- M3 labeled **V2 DENSE WINNER INDEX** in the final config. ZH/EN/M3 index files retained unchanged; no directory/collection renaming.
- Config file SHA-256: `8842ce493055ce775fdff46c3851420e6965d80959f01faf5c5d2da2a37b1f96`. Distinct from B4 embedding fingerprint; original embedding identity included for verification.

### Benchmark Integrity

DEV35/Gold frozen. TEST40 only hash-checked: retrieval NOT RUN, ranking NOT READ, metrics NOT COMPUTED; TEST Gold/hash unchanged. Chunking/BM25/Fusion/Reranker/production default unchanged. Production switching deferred until later retrieval stages and final TEST.
M3 integrity rechecked via Chroma get on temporary copy: 3837 chunks; zero missing/extra/duplicate/mismatch; dimension/finite/norms, metadata/text and vector fingerprint PASS. Original three index trees byte-identical. Artifact: `artifacts/evaluation_v2/b5_index_validation.json`.
Relevant config/index tests: **28 passed**. Preserved 85 earlier ledger records and appended exactly one V2-B5 record. `git diff --check` PASS. Ready for B6; B6 not started.

## B6 Hybrid Integration

Status: COMPLETE. DEV-only integration validation; no production switch and no V2-C execution.

### Frozen Integration Contract

V2-A selected BM25-only retrieve100 -> rerank20 -> final10 remains unchanged. No new Hybrid winner was frozen in V2-A. This experiment reuses its current RRF comparator: BM25200 + Dense200, RRF k60, equal weights, occurrence-ID dedup and production stable ties. Retain Top100 after fusion; compare equal-sized prefixes20/30/50. No protected union, depth sweep or new fusion. Old ZH uses B3 official instruction; M3 uses the B5 frozen RAW/CLS/normalized1024 contract.
Both reranker paths use BAAI/bge-reranker-base revision 465b4b7ddf2be0a020c8ad6e525b9bb1dbb708ae, batch8, max length512, input20, final10. Candidate CR20/30/50 shown on reranked rows is inherited PRE-rerank fusion coverage. Only20 candidates are actually scored; CR30/50 does not represent a larger reranker input.

### Global Retrieval

Frozen DEV35, PRIMARY RESULT. Production BM25 scoring is replayed on the immutable authoritative chunk snapshot and every result/score is checked against V2-A. Actual Chroma rankings are checked against B4; production RRF and reranker are invoked without modifications. This is a local integration experiment, not a live HTTP/MySQL acceptance gate.

|Path|Hit@5|R@5|R@10|MRR@10|CR@20|CR@30|CR@50|
|---|---:|---:|---:|---:|---:|---:|---:|
|BM25|45.71%|35.71%|46.67%|0.2518|60.00%|64.29%|71.43%|
|ZH Dense|25.71%|22.38%|24.52%|0.1377|30.24%|31.67%|36.90%|
|M3 Dense|57.14%|45.24%|51.19%|0.3115|61.19%|62.62%|70.71%|
|Old Hybrid|48.57%|34.52%|41.67%|0.2453|47.86%|55.95%|65.95%|
|New Hybrid|45.71%|32.86%|54.05%|0.3355|73.57%|79.29%|84.29%|
|Old Hybrid + Reranker|54.29%|40.48%|47.14%|0.3056|47.86%|55.95%|65.95%|
|New Hybrid + Reranker|68.57%|54.76%|67.86%|0.3074|73.57%|79.29%|84.29%|

### Raw Union and Complementarity

Raw Union@K uses each source TopK, up to2K candidates; coverage bound for those truncated source sets only, NOT an equal-budget competitor and NOT an upper bound on fusion fed by Top200/200. New Hybrid CR50 can exceed Raw Union50 by retaining evidence below source rank50.
|Dense|K|Raw Union CR|BM25-only|Dense-only|Both|Neither|Total pairs|
|---|---:|---:|---:|---:|---:|---:|---:|
|zh|20|61.43%|20 (36.36%)|1 (1.82%)|13 (23.64%)|21 (38.18%)|55|
|zh|30|65.71%|N/A|N/A|N/A|N/A|N/A|
|zh|50|75.71%|22 (40.00%)|3 (5.45%)|16 (29.09%)|14 (25.45%)|55|
|m3|20|77.14%|9 (16.36%)|7 (12.73%)|24 (43.64%)|15 (27.27%)|55|
|m3|30|80.00%|N/A|N/A|N/A|N/A|N/A|
|m3|50|81.43%|6 (10.91%)|5 (9.09%)|32 (58.18%)|12 (21.82%)|55|

### Fusion Retention and New/Lost Gold

Counts are Query-Gold pairs. Retention denominator is M3 Dense Top50 Gold; fusion prefixes have the explicitly stated different budgets.
|Budget|Dense50 Gold retained|Retention|New vs old Hybrid|Lost|Net|
|---|---:|---:|---:|---:|---:|
|20|35/37|94.59%|15|1|14|
|30|36/37|97.30%|14|1|13|
|50|37/37|100.00%|12|2|10|

Paired classification (CR50 -> CR30 -> CR20 -> R10 -> MRR10): {"UNCHANGED": 8, "REGRESSED": 6, "IMPROVED": 21}. Full ranks/hits/new/lost lists in `benchmarks/real_research/v2/b6_hybrid_paired_cases.csv`.

### Cross-document

n=7, DIAGNOSTIC ONLY.

|Path|R@10|MRR@10|CR@20|CR@30|CR@50|
|---|---:|---:|---:|---:|---:|
|ZH Dense|8.33%|0.0464|15.48%|15.48%|22.62%|
|M3 Dense|17.86%|0.1893|34.52%|41.67%|60.71%|
|Old Hybrid|15.48%|0.1310|15.48%|22.62%|36.90%|
|New Hybrid|34.52%|0.2194|46.43%|53.57%|64.29%|
|Old Hybrid + Reranker|11.90%|0.1190|15.48%|22.62%|36.90%|
|New Hybrid + Reranker|29.76%|0.1036|46.43%|53.57%|64.29%|

### Query-type Diagnostic

DESCRIPTIVE ONLY; small category samples.


cross_document (n=7):

|Path|R@10|MRR@10|CR@20|CR@50|
|---|---:|---:|---:|---:|
|Old Hybrid|15.48%|0.1310|15.48%|36.90%|
|New Hybrid|34.52%|0.2194|46.43%|64.29%|

exact_term (n=5):

|Path|R@10|MRR@10|CR@20|CR@50|
|---|---:|---:|---:|---:|
|Old Hybrid|20.00%|0.0667|40.00%|80.00%|
|New Hybrid|60.00%|0.1175|80.00%|100.00%|

factual (n=7):

|Path|R@10|MRR@10|CR@20|CR@50|
|---|---:|---:|---:|---:|
|Old Hybrid|71.43%|0.3016|71.43%|71.43%|
|New Hybrid|71.43%|0.3265|85.71%|85.71%|

multi_hop (n=4):

|Path|R@10|MRR@10|CR@20|CR@50|
|---|---:|---:|---:|---:|
|Old Hybrid|25.00%|0.2083|54.17%|87.50%|
|New Hybrid|50.00%|0.5833|75.00%|87.50%|

relational (n=5):

|Path|R@10|MRR@10|CR@20|CR@50|
|---|---:|---:|---:|---:|
|Old Hybrid|70.00%|0.3383|70.00%|80.00%|
|New Hybrid|70.00%|0.5333|90.00%|90.00%|

semantic (n=7):

|Path|R@10|MRR@10|CR@20|CR@50|
|---|---:|---:|---:|---:|
|Old Hybrid|42.86%|0.3857|42.86%|57.14%|
|New Hybrid|42.86%|0.3333|71.43%|85.71%|

### Latency

Local sequential production BM25 scoring on frozen authoritative snapshot + query encoding + Chroma query + authority validation + production RRF. Excludes HTTP/live SQL, cold load and index copy. Reranked E2E is composed per query: median of 3 retrieval samples + fresh reranker time; not contiguous HTTP. Snapshot BM25 includes cached-ranking/locator assertions.
Both indices are queried through isolated temporary copies on the container filesystem. B4 used workspace-mounted index paths; cross-stage Chroma latency differences must not be presented as an algorithmic speedup.
Retrieval:35-query warmup then3 timed samples/query. Reranker:1 warmup then35 timed calls/path. CPU4 Torch threads. Cold model loads/index copy/corpus encoding excluded.
|Stage|Old p50/p95 ms|New p50/p95 ms|
|---|---:|---:|
|bm25_ms|360.51/526.54|384.73/548.42|
|encode_ms|25.34/40.87|391.35/572.46|
|search_ms|16.65/21.62|17.88/23.80|
|fusion_ms|0.65/1.10|0.65/1.37|
|retrieval_ms|405.97/574.74|804.11/1224.67|
|reranker_ms|8735.93/11375.83|8896.25/10643.86|
|reranked_e2e_ms|9145.69/11764.41|9700.43/11421.12|

### Main Finding

M3 gains transfer to unchanged RRF: CR20/30/50 +25.71/+23.33/+18.33pp; R10 +12.38pp; MRR10 +0.0902. New Hybrid retains all 37 M3 Dense Top50 Gold pairs at Top50 and exceeds both standalone sources at equal Top50 budget; no candidate-coverage fusion bottleneck is supported here. Top5 remains mixed: Hybrid Hit5/R5 decrease versus old Hybrid. Frozen reranking raises R10 to 67.86% (old reranked 47.14%), but MRR10 is nearly flat versus old reranked (0.3074 vs 0.3056) and below new unreranked Hybrid (0.3355); partial ranking benefit, not an all-metric win. Cross-document/categories remain descriptive. V2-A BM25-only selection preserved; no production switch or V2-C execution.
Embedding gain transferred: YES; fusion bottleneck evidence: NO; reranker benefited: PARTIAL.
No statistical/generalization claim and no immediate RRF changes.

### Integrity

Relevant regression: 133 passed. Frozen hashes and all retained index files checked. TEST hash only, retrieval NOT RUN, ranking NOT READ, metrics NOT COMPUTED. DEV/Gold/M3 vectors/chunking/BM25/RRF/reranker/production default unchanged. Original ledger records preserved; two B6 comparison records appended. `git diff --check` checked at closeout. V2-C not started.
