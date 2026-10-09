"""Render all controlled EF results, two figures, and append the experiment ledger."""
import csv,json
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
R=Path(__file__).resolve().parents[2];A=R/'artifacts/evaluation_v2';B=R/'benchmarks/real_research/v2';p=A/'b2_ef_sweep.json';r=json.loads(p.read_text());assert r['status']=='COMPLETE'
assert r['quality_identical_all_ef'] and r['ranking_identical_all_ef'],'decision requires reassessment if data differ'
source='https://github.com/chroma-core/hnswlib/blob/0.7.6/hnswlib/hnswalg.h#L1597-L1607'
r['decision']={'selected_ef':10,'ann_bottleneck':'MINOR','quality_delta_vs_ef10':0,'further_ann_optimization':'Further ANN optimization is not justified.','ready_for_b3':True,'scope':'Frozen Global DEV, same stable graph, n_results=200; no claim for smaller request depths','reason':'All quality metrics and complete Top200 rankings identical at every tested ef. Keep ef10; no quality benefit justifies a setting change. Latency varies non-monotonically and cannot be interpreted as a causal ef cost difference when native search width is unchanged.','source_explanation':'hnswlib0.7.6 searchKnn uses max(ef_, k). Requested200 neighbors dominate all tested ef values; index.ef setting was verified for every query. This is an operational plateau across the tested range, not evidence of saturation at10 for low-k searches.','source_url':source,'production_defaults_changed':False}
p.write_text(json.dumps(r,indent=2)+'\n')
rows=r['results'];efs=[e['ef'] for e in rows];exact=r['exact'];plt.rcParams.update({'font.size':10,'axes.spines.top':False,'axes.spines.right':False})
fig,ax=plt.subplots(figsize=(9,5),layout='constrained')
for key,color,marker in [('CR@20','#2463a6','o'),('CR@50','#d47718','s')]:
 ax.plot(efs,[100*e['metrics'][key] for e in rows],color=color,marker=marker,label=key+' (ANN)')
 ax.axhline(100*exact[key],color=color,linestyle='--',alpha=.75,label=key+f' Exact ({100*exact[key]:.2f}%)')
ax.set(xlabel='search_ef',ylabel='Gold evidence recall (%)',title='Quality vs search_ef\nFrozen DEV (35 queries), same graph, n_results=200',xticks=efs,ylim=(0,40));ax.grid(axis='y',alpha=.2);ax.legend(loc='lower right')
for ext in ['png','svg']:fig.savefig(A/f'b2_ef_quality.{ext}',dpi=160)
plt.close(fig)
fig,ax=plt.subplots(figsize=(9,5),layout='constrained')
for key,color,marker in [('p50','#2463a6','o'),('p95','#8b4bb5','s')]:ax.plot(efs,[e['metrics'][key] for e in rows],color=color,marker=marker,label=key)
ax.set(xlabel='search_ef',ylabel='Local Chroma query latency (ms)',title='Latency vs search_ef\n5 rounds x 35 queries/config; embedding inference excluded',xticks=efs,ylim=(0,None));ax.grid(axis='y',alpha=.2);ax.legend()
for ext in ['png','svg']:fig.savefig(A/f'b2_ef_latency.{ext}',dpi=160)
plt.close(fig)
# Append only newly named experiments; preserve every existing row/field.
ledger=B/'experiments.csv'
with ledger.open(encoding='utf-8',newline='') as f:rd=csv.DictReader(f);fields=list(rd.fieldnames);old=list(rd)
new=[]
for e in rows:
 m=e['metrics'];row=dict(experiment_id=f'v2b2-controlled-ef{e["ef"]}',phase='V2-B2',status='COMPLETE',split='dev',backend='stable-original-image-hnsw',ef_search=e['ef'],effective_ef=e['effective_ef'],n_results=200,rounds=5,timed_queries=175,embedding=r['identity']['identity']['model'],model_revision=r['identity']['identity']['revision'],vector_fingerprint=r['identity']['identity']['vector_fingerprint'],dense_r10=m['Recall@10'],dense_mrr10=m['MRR@10'],dense_cr20=m['CR@20'],dense_cr50=m['CR@50'],p50=m['p50'],p95=m['p95'],mean_ms=m['mean_ms'],notes='Same existing graph; index.set_ef only. Native max(ef,k) floor200. No model inference or corpus encoding; production defaults unchanged.')
 for k in [10,20,50,100]:row[f'ann_fidelity_{k}']=m[f'fidelity@{k}']
 if not any(x['experiment_id']==row['experiment_id'] for x in old):new.append(row)
for row in new:
 for key in row:
  if key not in fields:fields.append(key)
if new:
 temp=ledger.with_suffix('.csv.tmp')
 with temp.open('w',encoding='utf-8',newline='') as f:w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(old+new)
 temp.replace(ledger)
lines=['## V2-B2 Controlled EF Sweep','','Status: COMPLETE. Same stable graph; only search_ef changed. Ready for B3, not started.','','### Protocol','',
'Six effective index.ef settings10/20/40/80/120/200 in one process, pinned original Chroma0.5.23/chroma-hnswlib0.7.6 image. M16/construction_ef100/squared L2 unchanged. Existing3800-node graph plus37-item exact buffer, total3837 vectors. No create_collection, insertion, graph rebuild, model inference or corpus encoding.',
'Global Frozen DEV35 queries. Existing Exact ranking reused byte-identically; frozen Query vectors reused and fingerprinted. n_results200 held constant to match frozen Dense source acquisition. Every group warmed with all35 queries; five timed rounds retain all175 samples per setting. EF order rotates by round. Graph file hashes, native index object, label mapping and frozen inputs checked between groups; rankings stable across repetitions. ef restored to10 after completion.',
'Timing boundary: local collection.query, including Python/SQLite filtering, HNSW search and exact-buffer merge; excludes HTTP, query embedding, model/index cold load, metric calculations, and MySQL authority work. Percentiles use existing nearest-rank convention. Index cold load excluded: '+f'{r["protocol"]["index_load_ms_excluded"]:.3f}'+' ms.',
'',
'### Primary results','','|search_ef|R10 %|MRR10|CR20 %|CR50 %|Exact Top50 overlap %|Mean ms|p50 ms|p95 ms|','|---|---:|---:|---:|---:|---:|---:|---:|---:|',
'|Exact|'+f'{100*exact["Recall@10"]:.2f}|{exact["MRR@10"]:.4f}|{100*exact["CR@20"]:.2f}|{100*exact["CR@50"]:.2f}|100.00|N/A|N/A|N/A|']
for e in rows:
 m=e['metrics'];lines.append(f'|{e["ef"]}|{100*m["Recall@10"]:.2f}|{m["MRR@10"]:.4f}|{100*m["CR@20"]:.2f}|{100*m["CR@50"]:.2f}|{100*m["fidelity@50"]:.2f}|{m["mean_ms"]:.3f}|{m["p50"]:.3f}|{m["p95"]:.3f}|')
lines+=['','### Delta and Exact gap','','Every setting has delta vs ef10: R10=0pp, MRR10=0, CR20=0pp, CR50=0pp. Every setting has Exact-minus-ANN gap: R10=0pp, MRR10=0, CR20=1.428571pp, CR50=1.428571pp. These are unchanged across the complete sweep; all Top200 returned ID lists are identical across settings. Per-setting deltas and gaps are saved in JSON.','','### Ranking convergence','','|ef|Top10 overlap|Top20 overlap|Top50 overlap|Exact Top10 order equal|Top20 order equal|Top50 order equal|','|---|---:|---:|---:|---:|---:|---:|']
for e in rows:
 m=e['metrics'];lines.append(f'|{e["ef"]}|{100*m["fidelity@10"]:.2f}%|{100*m["fidelity@20"]:.2f}%|{100*m["fidelity@50"]:.2f}%|{m["exact_order_equal@10"]}/35|{m["exact_order_equal@20"]}/35|{m["exact_order_equal@50"]}/35|')
lines+=['','### Curves','','![Quality vs ef](../artifacts/evaluation_v2/b2_ef_quality.png)','','![Latency vs ef](../artifacts/evaluation_v2/b2_ef_latency.png)','','PNG and SVG versions both retained; all six settings shown.','','### Why the curve is flat','',
'Version-matched [chroma-hnswlib0.7.6 source]('+source+') passes max(ef_,k) to searchBaseLayerST. For this frozen request depth200, all tested ef settings have the same native search-width floor. The configuration DID change (index.ef checked every query), but the effective exploration width did not increase. This is not a metadata-no-op error and not evidence that ef never matters at smaller k. No additional variable or out-of-range ef was tested.',
'',
'### Decision','',
'ANN bottleneck: **MINOR**. Existing Exact upper-bound gap remains1.43pp in CR20/50, with no R10/MRR10 gap. Increasing ef within the allowed range buys zero candidate/ranking quality here. Recommend **search_ef=10 for the current frozen n_results200 path**. Observed latency varies non-monotonically; because native search width is unchanged, do not interpret the ef200 p95 increase or ef20 reduction as proven causal effects. Do not select a parameter from timing noise.',
'**Further ANN optimization is not justified.** Close V2-B2 and proceed to B3 only when requested. This does not endorse ef10 for future smaller-depth search without separate validation. Production settings remain unchanged.',
'',
'### Artifacts and integrity','',
'Raw result with per-query rankings/all175 latency samples per setting: `artifacts/evaluation_v2/b2_ef_sweep.json`. Complete query-type summaries are included. Existing B2.1 and original Exact/ef10 results preserved. DEV/TEST hash unchanged; TEST bytes hashed only, no TEST parsing/ranking/retrieval/encoding. Embedding/instruction/normalization/pooling/chunking/Gold/BM25/RRF/reranker unchanged. No external LLM.',
'Runner: `backend/scripts/run_v2_ef_sweep.py`; renderer: `backend/scripts/report_v2_ef_sweep.py`. Ledger: six new controlled-sweep rows appended without dropping previous results.','']
doc=R/'docs/evaluation_v2_embedding_optimization.md';text=doc.read_text();assert '## V2-B2 Controlled EF Sweep' not in text;text+='\n'+'\n'.join(lines);doc.write_text(text,encoding='utf-8');print('Figures, report, ledger and decision saved.')
