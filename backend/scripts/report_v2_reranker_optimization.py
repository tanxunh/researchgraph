"""Render the complete V2-E report from saved offline results."""
from run_v2_reranker_optimization import ROOT,B,E,MODELS,read,sha
s=read(E/'summary.json');p=read(E/'protocol.json');a=read(E/'reranker_audit.json');cfg=read(B/'final_reranker_config.json');current=s['configs'][s['current']];winner=s['configs'][s['selected']]
percent=lambda x:f'{100*x:.2f}%'
lines=['# V2-E Controlled Reranker Optimization','',f"Status: **{s['status']}**. DEV only; TEST not evaluated; production unchanged.",'','## Frozen contract','',
'35 frozen DEV queries, 55 human-approved evidence units; a chunk must contain 100% of the exact reviewed span. Gold counts are deduplicated per unit; metrics are macro averages across queries, not total hit counts divided by 55.',
'',
'Upstream remains TextChunker 700 / overlap 100 / page-contained, 3,837 chunks; BAAI/bge-m3 RAW query / RAW passage, normalized CLS; weighted RRF BM25 1.25, Dense 1.0, k=20, route depths 200/200. Only the saved winning Hybrid Top20 is admitted. Final output depth is 10.',
'',f"Candidate CR@20: **{percent(s['candidate_CR@20'])}**, {s['candidate_Gold_hits']}/55 distinct units present. This is pre-rerank coverage, never a final-output recall field. No reranker can recover the other {55-s['candidate_Gold_hits']} units.",'',
'Only base and v2-m3 were scored. Both use CPU float32, four PyTorch threads / one interop thread, batch 8, max length 512. Input is raw query + raw chunk, with only the existing CrossEncoder internal `str.strip()` behavior. No metadata, instructions, title or adjacent context.',
'',
'Rank blend: alpha/(10 + reranker_rank) + (1-alpha)/(10 + fusion_rank), one-based ranks, alpha in {1, .75, .5}; descending score and original fusion rank for ties. Every blend uses the same cached 700 pair scores per model. No fusion or retrieval reruns.',
'',
'## Baseline and implementation audit','',
'NO_RERANK was reproduced first; current base was then scored on the NEW V2-D candidates and its per-Gold error audit saved before model B was run. Historical B6 scores/metrics were not substituted.',
'',
'Both scorers use pinned model and tokenizer snapshots. The production wrapper was reused unchanged. An independent tokenizer/model-logit check reproduced wrapper scores; warm-up and measured first-query score vectors matched exactly. Production rerank mapping was exercised with cached scores, validating unchanged candidate identities and ordering. A scoring failure would abort the experiment instead of using fallback retrieval results.',
'',
'| Model | Revision | Score | Truncated pairs | Token lengths min / median / p95 / max |',
'|---|---|---|---:|---|']
for key,aa in a['models'].items():
    lengths=aa['pair_token_lengths'];ls=' / '.join(str(lengths[k]) for k in ('min','median','p95','max'))
    lines.append(f"| {aa['model']} | `{aa['revision']}` | {aa['score_extraction']} | {aa['truncated_pairs']}/700 ({aa['truncated_percentage']:.2f}%) | {ls} |")
lines+=['','Special tokens are supplied by the pinned tokenizer; query precedes passage, dynamic padding and `longest_first` truncation at 512. XLM-R pair format uses its configured special tokens. Scores are descending; equal scores retain fusion order. Tokenizer configurations, special-token maps, pair lengths, file hashes, model fingerprints and tokenizer fingerprints are preserved in `reranker_audit.json`.',
'',f"Chunk character lengths (700 pair occurrences): {a['models']['base']['chunk_char_lengths']}.",'','## All predeclared configurations','',
'| Config | Hit@5 | R@5 | R@10 | MRR@10 | Gold hits@10 | Recovered / lost / net vs current | Front safety flag |',
'|---|---:|---:|---:|---:|---:|---|---|']
for name,c in s['configs'].items():
    m=c['metrics'];lines.append(f"| {name} | {percent(m['Hit@5'])} | {percent(m['R@5'])} | {percent(m['R@10'])} | {m['MRR@10']:.4f} | {c['hit_count10']} | {len(c['recovered'])} / {len(c['lost'])} / {c['net']:+d} | {c['gate']['front_safety_flag']} |")
lines+=['','## Current reranker evidence audit','',f"Counts: {current['error_counts']}.",'',f"Demoted Gold IDs: {', '.join(current['demoted_ids']) or 'none'}.",'',
'`v2_e_error_audit.csv` records every one of the 55 units for each configuration, with the original and final ranks plus equivalent immutable chunk IDs. NOT_IN_TOP20 units cannot be fixed by reranking.',
'','## Paired queries and cross-document subset','',
'Paired classifications use per-query R@10 only. Reciprocal-rank movement is recorded separately in `paired_queries.json` and never upgrades a recall tie to an improved query.',
'',
'| Config | Improved / unchanged / regressed | Cross-doc R@10 | Cross-doc MRR@10 | Cross-doc recovered / lost / net |',
'|---|---|---:|---:|---|']
for name,c in s['configs'].items():
    pa=c['paired'];cr=c['cross'];rec=len(c['cross_recovered']);lost=len(c['cross_lost'])
    lines.append(f"| {name} | {pa['improved']} / {pa['unchanged']} / {pa['regressed']} | {percent(cr['R@10'])} | {cr['MRR@10']:.4f} | {rec} / {lost} / {rec-lost:+d} |")
lines+=['','Cross-document n=7; these are descriptive DEV observations, not generalization claims.',
'',
'## Replacement and safety decision','',
'Frozen priority: R@10, MRR@10, R@5, Hit@5, paired gain/loss, cross-document, demotions, latency/memory, simplicity. Gate A requires at least two net additional Gold hits and improved macro R@10. Gate B requires one net hit, improved R@10, nondecreasing MRR/R@5, no cross-document R@10 decline and no increased demotions (conservative predeclared interpretation).',
'',
'Front-safety flags are evaluated relative to current pure base: improved R@10 with MRR loss >0.05, or at least two fewer Gold hits@5. Flagged candidates are excluded from replacement; no post-hoc exceptions were used.',
'',f"Lexicographic leader: **{s['lexicographic_leader']}**. Selected: **{s['selected']}**. Replacement gate: **{'PASS' if s['replacement_gate']['pass'] else 'FAIL ? retain current'}**.",
'' ,
'The metric leader v2-m3 alpha=1 recovers four Gold units and loses three (net +1), so Gate A is not met. MRR, R@5 and cross-document R@10 improve, but demotions rise from 1 to 2. Gate B therefore fails the predeclared conservative no-increase condition. No front-safety flag is triggered. Base is retained because of this gate, not because a latency penalty was substituted for the quality objective.',
'',
'Leader demotions relative to Hybrid Top10: V2Q069:G1 and V2Q070:G2. Current base demotes V2Q069:G3. Exact recovered/lost IDs are retained for all configurations in the gain/loss CSV.',
'',f"Current reranker value reproduced vs NO_RERANK: {s['current_value_reproduced']}. Selected vs NO_RERANK: {s['selected_vs_NO_RERANK']}.",
'',f"Selected vs current recovered IDs: {winner['recovered']}; lost IDs: {winner['lost']}.",
'',f"Optimization opportunity: **{s['optimization_opportunity']}**. Reranker contribution vs NO_RERANK: **{s['reranker_contribution']}**. These are separate decisions.",
'','## Latency and practical cost','',
'CPU: AMD Ryzen 7 4800H; x86_64 WSL2. Full environment is retained in `environment.json`.','',
'One warmed 35-query pass per model; 20 pairs/query. Timing includes tokenizer + forward pass + score extraction, excludes model loading, integrity checks, retrieval and offline rank blending. Same Docker image, machine, CPU thread counts and 6 GiB container memory limit; inference was sequential and offline. p95 is linearly interpolated. Measurements describe this local run, not a production SLA. No additional performance rounds were used.',
'',
'| Model | Parameters | Snapshot bytes | Peak process RSS MiB | Mean ms/query | P50 ms | P95 ms | Pairs/s |',
'|---|---:|---:|---:|---:|---:|---:|---:|']
for key,l in s['latency'].items():
    cost=s['cost'][key];lines.append(f"| {MODELS[key][0]} | {cost['parameter_count']} | {cost['model_disk_bytes']} | {l['peak_rss_bytes']/1024**2:.1f} | {l['mean_ms']:.2f} | {l['p50_ms']:.2f} | {l['p95_ms']:.2f} | {l['pairs_per_second']:.3f} |")
lines+=['','Peak RSS includes model loading, tokenization and auditing in the process; disk bytes are the locally cached snapshot files, not an estimate from parameter count. All three alpha values for a model share its inference cost.',
'','## Frozen reranker','',f"Model: `{cfg['model']}`; revision/tokenizer revision: `{cfg['revision']}`.",
f"Max length {cfg['max_length']}; batch {cfg['batch_size']}; candidate depth 20; final Top10; alpha {cfg['rank_blend_alpha']}; blend k=10.",
'',f"Config SHA-256: `{s['final_config_sha256']}`.",
'',
'`DEV_SELECTED=true`, `TEST_VALIDATED=false`, `PRODUCTION_DEFAULT=false`. This is an evaluation selection; production configuration is not modified.',
'','## Integrity and validation','']
for name in ['final_chunking_config.json','final_dense_config.json','final_fusion_config.json','dev_gold_evidence_spans_v2.json','queries_dev.jsonl','queries_test.jsonl']:
    lines.append(f"- `{name}`: `{sha(B/name)}` (unchanged).")
lines+=['',f"All {len(s['protected_hashes'])} protected historical/input hashes verified. TEST accessed only for byte hashing; no TEST records, rankings, metrics or models evaluated. B6 history retained. No new embedding, chunking, fusion, retrieval or LLM execution.",
'',f"Tests: {s.get('tests', 'PENDING')}. git diff --check: {s.get('git_diff_check','PENDING')}.",
'','## Artifacts','',
'- `artifacts/evaluation_v2/e/protocol.json`: predeclared configuration and input hashes.',
'- `base_scores.json`, `m3_scores.json`: all raw score vectors, candidate IDs, per-query timings and audit records.',
'- `current_baseline_audit.json`, `reranker_audit.json`: pre-comparison baseline and full model audit.',
'- `summary.json`, `final_rankings.json`, `paired_queries.json`: complete offline analysis.',
'- `benchmarks/real_research/v2/v2_e_reranker_grid.csv`, `v2_e_gain_loss.csv`, `v2_e_error_audit.csv`, `v2_e_cross_document.csv`: full six-config comparisons plus NO_RERANK.',
'- `final_reranker_config.json` and `.sha256`: deterministic selected configuration.',
'','Official model input/scoring reference: [BAAI/bge-reranker-v2-m3](https://huggingface.co/BAAI/bge-reranker-v2-m3). The local pinned snapshot and saved runtime audit determine the actual implementation used here.',
'',f"Ready for V2-F: {'YES' if s['status']=='COMPLETE' else 'NO ? validation pending'}. V2-F is not started.",'']
(ROOT/'docs/evaluation_v2_reranker_optimization.md').write_text('\n'.join(lines),encoding='utf-8')
print('V2-E report written')
