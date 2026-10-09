"""B6 reporting only: frozen DEV, saved rankings and timing samples."""
import sys,types,json,csv,hashlib,statistics,argparse
from pathlib import Path
from collections import Counter
R=Path(__file__).resolve().parents[2];O=R/'artifacts/evaluation_v2/b6';B=R/'benchmarks/real_research/v2'
pkg=types.ModuleType('app.services.evaluation');pkg.__path__=[str(R/'backend/app/services/evaluation')];sys.modules['app.services.evaluation']=pkg
from app.services.evaluation.hybrid_integration import metrics,complement,retention,paired,BUDGETS
from app.services.evaluation.ann_exactness import percentile
parser=argparse.ArgumentParser();parser.add_argument('--transfer',required=True);parser.add_argument('--fusion-bottleneck',required=True);parser.add_argument('--reranker-benefit',required=True);parser.add_argument('--finding',required=True);parser.add_argument('--tests',type=int,required=True);args=parser.parse_args()
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
protocol=json.loads((O/'protocol.json').read_text(encoding='utf-8'));runs={k:json.loads((O/f'{k}.json').read_text(encoding='utf-8')) for k in ('zh','m3')}
assert all(x['status']=='COMPLETE' for x in runs.values())
for name,digest in protocol['protected_hashes'].items():assert sha(R/name)==digest,name
old=runs['zh']['cases'];new=runs['m3']['cases'];assert len(old)==len(new)==35
assert all(a['query_id']==b['query_id'] and a['bm25']==b['bm25'] and a['gold']==b['gold'] for a,b in zip(old,new))
paths={'BM25':(old,'bm25',False),'ZH Dense':(old,'dense',False),'M3 Dense':(new,'dense',False),'Old Hybrid':(old,'hybrid',False),'New Hybrid':(new,'hybrid',False),'Old Hybrid + Reranker':(old,'hybrid',True),'New Hybrid + Reranker':(new,'hybrid',True)}
overall={name:metrics(*a) for name,a in paths.items()}
cross={name:metrics([c for c in a[0] if c['query_type']=='cross_document'],a[1],a[2]) for name,a in paths.items() if name!='BM25'}
typeset=sorted({c['query_type'] for c in old})
bytype={key:{ty:metrics([c for c in runs[key]['cases'] if c['query_type']==ty],'hybrid') for ty in typeset} for key in runs}
comp={key:{str(k):complement(runs[key]['cases'],k) for k in (20,50)} for key in runs}
raw_union={key:{str(k):statistics.mean(len((set(c['bm25'][:k])|set(c['dense'][:k]))&set(c['gold']))/len(set(c['gold'])) for c in run['cases']) for k in BUDGETS} for key,run in runs.items()}
ret={str(k):retention(new,k) for k in BUDGETS};pairs=[paired(a,b) for a,b in zip(old,new)]
gain={str(k):{'new':sum(len(p[f'new_gold{k}']) for p in pairs),'lost':sum(len(p[f'lost_gold{k}']) for p in pairs)} for k in BUDGETS}
for v in gain.values():v['net']=v['new']-v['lost']
def percentiles(v):return {'p50':percentile(v,.5),'p95':percentile(v,.95),'n':len(v)}
lat={key:{field:percentiles([t[field] for c in run['cases'] for t in c['timings']]) for field in ('bm25_ms','encode_ms','search_ms','fusion_ms','retrieval_ms')} for key,run in runs.items()}
for key,run in runs.items():
 for field in ('reranker_ms','reranked_e2e_ms'):lat[key][field]=percentiles([c[field] for c in run['cases']])
summary={'status':'COMPLETE','selection_status':'DEV_SELECTED_ONLY','protocol':protocol,'global':overall,'cross_document':cross,'query_types':bytype,'complementarity':comp,'raw_union_diagnostic':raw_union,'dense_gold_retention':ret,'new_lost_gold':gain,'paired_classification':dict(Counter(p['classification'] for p in pairs)),'latency':lat,'finding':{'embedding_gain_transferred':args.transfer,'fusion_bottleneck_evidence':args.fusion_bottleneck,'reranker_benefited':args.reranker_benefit,'explanation':args.finding},'regression_passed':args.tests,'production_changed':False,'TEST_run':False,'TEST_ranking_read':False,'V2_C_started':False}
assert not (O/'summary.json').exists()
with (B/'b6_hybrid_paired_cases.csv').open('w',encoding='utf-8',newline='') as f:
 w=csv.DictWriter(f,fieldnames=list(pairs[0]));w.writeheader();w.writerows({k:json.dumps(v) if isinstance(v,(dict,list)) else v for k,v in p.items()} for p in pairs)
with (B/'experiments.csv').open(encoding='utf-8',newline='') as f:r=csv.DictReader(f);fields=list(r.fieldnames);prior=list(r)
canon=lambda rows:hashlib.sha256(json.dumps([{k:v for k,v in row.items() if v!=''} for row in rows],sort_keys=True).encode()).hexdigest()
assert len(prior)==protocol['prior_ledger_rows'] and canon(prior)==protocol['prior_ledger_canonical_sha256']
added=[]
for key,label in [('zh','Old Hybrid'),('m3','New Hybrid')]:
 cfg=runs[key]['config'];m=overall[label];c=cross[label];rr=overall[label+' + Reranker'];l=lat[key]
 row=dict(experiment_id='v2b6-'+key,phase='V2-B6',status='DEV_SELECTED',dense_model=cfg['model'],dense_revision=cfg['revision'],dense_fingerprint=hashlib.sha256(json.dumps(cfg,sort_keys=True,ensure_ascii=False).encode()).hexdigest(),candidate_policy='v2a_current_rrf_comparator_200_200',bm25_depth=200,dense_depth=200,fusion_budget=100,rrf_k=60,rerank_k=20,final_k=10,global_r10=m['R@10'],global_mrr10=m['MRR@10'],crossdoc_r10=c['R@10'],crossdoc_mrr10=c['MRR@10'],retrieval_p50=l['retrieval_ms']['p50'],retrieval_p95=l['retrieval_ms']['p95'],reranked_r10=rr['R@10'],reranked_mrr10=rr['MRR@10'],reranked_p50=l['reranked_e2e_ms']['p50'],reranked_p95=l['reranked_e2e_ms']['p95'],notes='RRF comparator retained; V2-A winner remains BM25100/rerank20/final10. CR30/50 are pre-rerank diagnostic prefixes, not reranker input depth. Local snapshot timing excludes live SQL/HTTP; reranked E2E composed per query. No TEST/production change.')
 for k in BUDGETS:row.update({f'global_cr{k}':m[f'CR@{k}'],f'crossdoc_cr{k}':c[f'CR@{k}'],f'raw_union_cr{k}':raw_union[key][str(k)]})
 for k in (20,50):
  for category,n in comp[key][str(k)]['counts'].items():row[category+'_gold'+str(k)]=n
 fields.extend(k for k in row if k not in fields);added.append(row)
with (B/'experiments.csv').open('w',encoding='utf-8',newline='') as f:w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(prior+added)
summary['ledger_prior_rows_preserved']=len(prior);summary['ledger_rows_added']=2
(O/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
def table(data,columns):
 lines=['|'+'|'.join(['Path']+columns)+'|','|'+'|'.join(['---']+['---:']*len(columns))+'|']
 for name,values in data.items():lines.append('|'+name+'|'+'|'.join(f'{values[k]:.4f}' if k=='MRR@10' else f'{100*values[k]:.2f}%' for k in columns)+'|')
 return lines
lines=['','## B6 Hybrid Integration','','Status: COMPLETE. DEV-only integration validation; no production switch and no V2-C execution.','','### Frozen Integration Contract','','V2-A selected BM25-only retrieve100 -> rerank20 -> final10 remains unchanged. No new Hybrid winner was frozen in V2-A. This experiment reuses its current RRF comparator: BM25200 + Dense200, RRF k60, equal weights, occurrence-ID dedup and production stable ties. Retain Top100 after fusion; compare equal-sized prefixes20/30/50. No protected union, depth sweep or new fusion. Old ZH uses B3 official instruction; M3 uses the B5 frozen RAW/CLS/normalized1024 contract.','Both reranker paths use BAAI/bge-reranker-base revision '+protocol['reranker_revision']+', batch8, max length512, input20, final10. Candidate CR20/30/50 shown on reranked rows is inherited PRE-rerank fusion coverage. Only20 candidates are actually scored; CR30/50 does not represent a larger reranker input.','','### Global Retrieval','','Frozen DEV35, PRIMARY RESULT. Production BM25 scoring is replayed on the immutable authoritative chunk snapshot and every result/score is checked against V2-A. Actual Chroma rankings are checked against B4; production RRF and reranker are invoked without modifications. This is a local integration experiment, not a live HTTP/MySQL acceptance gate.','']+table(overall,['Hit@5','R@5','R@10','MRR@10','CR@20','CR@30','CR@50'])
lines+=['','### Raw Union and Complementarity','','Raw Union@K uses each source TopK, up to2K candidates; coverage bound for truncated source sets only, NOT an equal-budget competitor or a bound on Top200/200 fusion.','|Dense|K|Raw Union CR|BM25-only|Dense-only|Both|Neither|Total pairs|','|---|---:|---:|---:|---:|---:|---:|---:|']
for key in runs:
 for k in BUDGETS:
  cp=comp[key].get(str(k));vals=[str(cp['counts'][c])+f" ({100*cp['ratios'][c]:.2f}%)" for c in ('bm25_only','dense_only','both','neither')] if cp else ['N/A']*4
  lines.append('|'+key+'|'+str(k)+'|'+f"{100*raw_union[key][str(k)]:.2f}%"+'|'+'|'.join(vals)+'|'+str(cp['total'] if cp else 'N/A')+'|')
lines+=['','### Fusion Retention and New/Lost Gold','','Counts are Query-Gold pairs. Retention denominator is M3 Dense Top50 Gold; fusion prefixes have the explicitly stated different budgets.','|Budget|Dense50 Gold retained|Retention|New vs old Hybrid|Lost|Net|','|---|---:|---:|---:|---:|---:|']
for k in BUDGETS:
 a=ret[str(k)];b=gain[str(k)];lines.append(f"|{k}|{a['retained']}/{a['dense_top50_gold']}|{100*a['ratio']:.2f}%|{b['new']}|{b['lost']}|{b['net']}|")
lines+=['','Paired classification (CR50 -> CR30 -> CR20 -> R10 -> MRR10): '+json.dumps(summary['paired_classification'])+'. Full ranks/hits/new/lost lists in `benchmarks/real_research/v2/b6_hybrid_paired_cases.csv`.','','### Cross-document','','n=7, DIAGNOSTIC ONLY.','']+table(cross,['R@10','MRR@10','CR@20','CR@30','CR@50'])
lines+=['','### Query-type Diagnostic','','DESCRIPTIVE ONLY; small category samples.','']
for ty in typeset:
 lines+=['',f"{ty} (n={bytype['zh'][ty]['n']}):",'']+table({'Old Hybrid':bytype['zh'][ty],'New Hybrid':bytype['m3'][ty]},['R@10','MRR@10','CR@20','CR@50'])
lines+=['','### Latency','',protocol['latency_boundary'],'Retrieval:35-query warmup then3 timed samples/query. Reranker:1 warmup then35 timed calls/path. CPU4 Torch threads. Cold model loads/index copy/corpus encoding excluded.','|Stage|Old p50/p95 ms|New p50/p95 ms|','|---|---:|---:|']
for field in lat['zh']:lines.append('|'+field+'|'+'|'.join(f"{lat[key][field]['p50']:.2f}/{lat[key][field]['p95']:.2f}" for key in ('zh','m3'))+'|')
lines+=['','### Main Finding','',args.finding,f'Embedding gain transferred: {args.transfer}; fusion bottleneck evidence: {args.fusion_bottleneck}; reranker benefited: {args.reranker_benefit}.','No statistical/generalization claim and no immediate RRF changes.','','### Integrity','',f'Relevant regression: {args.tests} passed. Frozen hashes and all retained index files checked. TEST hash only, retrieval NOT RUN, ranking NOT READ, metrics NOT COMPUTED. DEV/Gold/M3 vectors/chunking/BM25/RRF/reranker/production default unchanged. Original ledger records preserved; two B6 comparison records appended. `git diff --check` checked at closeout. V2-C not started.','']
doc=R/'docs/evaluation_v2_embedding_optimization.md';text=doc.read_text(encoding='utf-8');assert '## B6 Hybrid Integration' not in text
text=text.replace('B6 not started. No model replacement or production change.','B6 integration COMPLETE; V2-C not started. No production change.',1)
doc.write_text(text+'\n'.join(lines),encoding='utf-8')
print(json.dumps({k:summary[k] for k in ['global','complementarity','raw_union_diagnostic','dense_gold_retention','new_lost_gold','paired_classification','latency','finding']}))
