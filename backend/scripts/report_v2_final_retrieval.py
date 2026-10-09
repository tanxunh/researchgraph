"""Human-readable V2-F report from frozen artifacts only."""
from run_v2_final_retrieval import *
s=read(F/'summary.json');manifest=read(B/'final_retrieval_manifest.json');p=read(F/'protocol.json');d=read(F/'test_diagnostics.json')
pct=lambda x:f'{100*x:.2f}%'
lines=['# V2-F Retrieval Freeze + Final TEST','',f"Status: **{s['status']}**.",'','## Immutable retrieval manifest','',f"Pre-TEST SHA-256: `{s['pre_test_manifest_sha256']}`.",f"Final SHA-256: `{s['final_manifest_sha256']}`.",'',
'Frozen pipeline: TextChunker target 700 / overlap 100 / page-contained, 3,837 chunks; BAAI/bge-m3 RAW query/document, CLS normalized 1024 dimensions, max length 8192; production BM25 Top200 and Dense Top200; weighted RRF 1.25 / 1.0, k=20, fused Top100; BAAI/bge-reranker-base Top20 to Top10, alpha=1.',
'',
'Every component is pinned through its existing configuration SHA, model revision and index identity. The original manifest bytes are retained in `pre_test_manifest.json`. After successful TEST execution, only validation state/provenance were added to the final manifest; individual component configurations are unchanged. The final hash is stored externally, avoiding a self-referential hash.',
'',
'`DEV_SELECTED=true`, `TEST_VALIDATED=true`, `PRODUCTION_DEFAULT=false`. No production rollout or workflow evaluation is implied.',
'','## Execution discipline','',
'One complete DEV reproduction was run first. All 35 queries reproduced frozen BM25 Top200, Dense Top200, Hybrid Top100 and reranker Top20 order. Metrics matched D/E exactly. TEST queries were not read until DEV passed. TEST Gold was then mechanically validated against authoritative BASE chunk text, document/version, source offsets, source hash and immutable chunk IDs; no semantic changes or portable remapping were made.',
'',
'PRE_TEST_LOCK was saved before any TEST inference. Each of the 40 TEST queries has exactly one STARTED and one COMPLETED journal entry under that manifest. A filesystem exclusive execution lock rejects repeated invocations. Warm-up used a previously seen DEV query, never a TEST query. No TEST-based parameter change, candidate selection, retry or second evaluation occurred.',
'',
'BM25 used the exact existing implementation over the immutable B6 authority snapshot in occurrence-ID order. Chroma queried a copy of the frozen index; original index files were protected by hashes. Local models ran offline on CPU. This is the real local retrieval/model stack with snapshot authority, not HTTP/live-MySQL benchmarking. Corpus vectors were not re-encoded or reinserted.',
'','## Gold and metric interpretation','',
f"DEV: 35 queries / 55 reviewed minimal evidence spans, evaluated with 100% containment mapping. TEST: 40 queries / {s['TEST_Gold_units']} original frozen BASE chunk-locator Gold units.",
'',
'DEV and TEST use their respective frozen annotation contracts. TEST was not retroactively converted into minimal-span labels. Consequently direct DEV-to-TEST differences combine dataset difficulty and annotation-granularity effects; they do not isolate generalization or prove algorithm improvement.',
'',
'Metrics are query-macro averages. Each Gold unit contributes at most once. Document hits are never substituted for Evidence hits. Candidate recall belongs exclusively to pre-rerank Hybrid; the final reranker exposes only Hit@5, R@5, R@10 and MRR@10.',
'','## DEV reproduction','',
'| Stage | Hit@5 | R@5 | R@10 | MRR@10 | CR@20 | CR@30 | CR@50 |','|---|---:|---:|---:|---:|---:|---:|---:|']
def metricrow(name,metrics):
 return '| '+name+' | '+' | '.join(f"{metrics[k]:.4f}" if k=='MRR@10' else pct(metrics[k]) if k in metrics else 'N/A' for k in ALL)+' |'
for name in ('hybrid','reranked'):lines.append(metricrow(name,s['DEV_metrics'][name]['metrics']))
lines+=['','## TEST metrics','',
'| Stage | Hit@5 | R@5 | R@10 | MRR@10 | CR@20 | CR@30 | CR@50 |','|---|---:|---:|---:|---:|---:|---:|---:|']
for name,row in s['TEST_metrics'].items():lines.append(metricrow(name,row['metrics']))
lines+=['','Integer Gold hits (query/Gold-unit identity, not macro percentage denominators):','',
'| Stage | @5 | @10 | @20 | @30 | @50 |','|---|---:|---:|---:|---:|---:|']
for name,row in s['TEST_metrics'].items():lines.append('| '+name+' | '+' | '.join(str(row['Gold_hit_counts'].get(k,'N/A')) for k in ('5','10','20','30','50'))+' |')
con=s['reranker_contribution'];lines+=['','## Reranker contribution on TEST','',f"Recovered {len(con['recovered'])}, lost {len(con['lost'])}, net {con['net']:+d}.",f"Paired queries, based on per-query R@10: {con['paired']}.",'',f"Recovered IDs: {con['recovered']}.",f"Lost IDs: {con['lost']}.",'',f"Per-Gold categories: {d['counts']}.",
'',
'Full unit locators, Hybrid and reranker ranks, paired reciprocal-rank movement and exact gain/loss IDs are preserved in `test_diagnostics.json`. These diagnostics did not change reranker selection.',
'','## DEV to TEST movement','',
'| Metric | TEST minus DEV |','|---|---:|']
for k,v in s['DEV_to_TEST_delta'].items():lines.append(f"| {k} | {v:+.4f}"+(' |' if k=='MRR@10' else f" ({100*v:+.2f} pp) |"))
lines+=['',f"Movement: **{s['movement']}**. Generalization: **{s['generalization']}**, descriptive only.",'',
'The movement rubric was declared before reading TEST: STABLE if the largest final recall/hit-rate drop and MRR drop are below .05; MODERATE DROP if none exceeds .15; otherwise LARGE DROP. This is not a pass/fail gate and cannot authorize tuning. The summary also considers whether reranking still improves Hybrid R@10. With 35 DEV and 40 TEST queries, one single-Gold TEST success changes macro recall by 2.5 percentage points; multi-Gold questions contribute smaller per-hit increments. Annotation-granularity differences further limit interpretation.',
'','## Frozen query-type breakdown','',
'| Type | n | Final R@10 | Final MRR@10 | Hybrid CR@20 | Hybrid CR@50 |','|---|---:|---:|---:|---:|---:|']
for k,v in s['query_type_breakdown'].items():lines.append(f"| {k} | {v['n']} | {pct(v['final_R@10'])} | {v['final_MRR@10']:.4f} | {pct(v['Hybrid_CR@20'])} | {pct(v['Hybrid_CR@50'])} |")
lines+=['','All subgroups are descriptive / low-sample. Categories and membership are unchanged. The cross_document row is the frozen cross-paper subset.',
'','## Non-intervention error analysis','',
'Metrics were persisted and hashed before error analysis. Categories below are mutually exclusive: absent from Hybrid Top20 first; then demoted from Hybrid Top10; then candidate present but not promoted; then any other valid evaluation miss. `GOLD_PRESENT_LOWER_THAN_TOP10` is an additional nonexclusive flag, because it otherwise overlaps the other categories.',
'','| Category | Gold misses | Query IDs |','|---|---:|---|']
for cat in ('NOT_IN_HYBRID_TOP20','IN_TOP20_RERANKER_FAILED_TO_PROMOTE','DEMOTED_BY_RERANKER','OTHER_VALID_EVALUATION_MISS'):
 lines.append(f"| {cat} | {s['error_counts'].get(cat,0)} | {', '.join(s['error_query_ids'].get(cat,[])) or 'none'} |")
lines+=['',f"Secondary Gold present below Hybrid Top10 among final misses: {s['secondary_Gold_lower_than_Top10']}. This is not added to the exclusive total.",
'','## Latency','',s['latency_boundary']+'.',
'',
'First and only TEST execution supplies all timing samples. No latency-only rerun. CPU float32, four PyTorch threads / one interop thread, local Docker image `rg-phase11h-backend:local`, 6 GiB memory limit. Cold model loading and initial warm-up are excluded; per-query tokenization, embedding inference, search, authority checks and reranking are included. Percentiles use linear interpolation.',
'','| Stage | Mean ms | P50 ms | P95 ms |','|---|---:|---:|---:|']
for name,v in s['latency'].items():lines.append(f"| {name} | {v['mean_ms']:.2f} | {v['p50_ms']:.2f} | {v['p95_ms']:.2f} |")
lines+=['','## Integrity / regression','',f"Protected hashes: {len(s['protected_hashes'])} verified. TEST exactly once: PASS. Gold validation: PASS. Pre-test lock: PASS.",f"Tests: {s['tests']}. git diff --check: {s.get('git_diff_check','PENDING')}.",'',
'No B/C/D/E artifact, original Gold, query, corpus, BM25 implementation or frozen Dense index was modified. Only final-manifest TEST validation state/provenance changed. Production remains unchanged.',
'','## Output artifacts','',
'- `final_retrieval_manifest.json` and `.sha256`: final immutable selection and validation provenance.',
'- `artifacts/evaluation_v2/f/pre_test_manifest.json`, `pre_test_lock.json`: original pre-TEST identity.',
'- `dev_reproduction.json`, `test_gold_validation.json`, `test_execution_lock.json`, `query_execution_journal.jsonl`: gating and exactly-once records.',
'- `test_run.json`: complete BM25/Dense/Hybrid/reranker rankings, scores and timings.',
'- `test_metrics_frozen.json`, `summary.json`, `test_diagnostics.json`: immutable metrics and descriptive diagnosis.',
'- `v2_f_test_metrics.csv`, `v2_f_test_error_analysis.csv`, `v2_f_test_query_types.csv`: complete metric/diagnostic tables.',
'',f"Ready for V2-G: {'YES' if s['status']=='COMPLETE' else 'NO ? regression pending'}. Research/Cross-paper Workflow Evaluation was not started.",'']
(ROOT/'docs/evaluation_v2_final_retrieval.md').write_text('\n'.join(lines),encoding='utf-8');print('V2-F report saved')
