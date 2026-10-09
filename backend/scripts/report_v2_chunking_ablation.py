"""C1 portable-unit report. Never loads TEST semantics."""
import sys,types,json,csv,hashlib,statistics,io
from pathlib import Path
R=Path(__file__).resolve().parents[2];sys.path.insert(0,str(R/'backend'));O=R/'artifacts/evaluation_v2/c1';B=R/'benchmarks/real_research/v2'
pkg=types.ModuleType('app.services.evaluation');pkg.__path__=[str(R/'backend/app/services/evaluation')];sys.modules['app.services.evaluation']=pkg
from app.services.evaluation.chunking_ablation import score_portable,duplicate_equivalent,score_reranked_portable
import numpy as np

def read(p):return json.loads(p.read_text(encoding='utf-8'))
def save(p,v):p.write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
def csvwrite(p,rows):
    fields=list(dict.fromkeys(k for row in rows for k in row))
    with p.open('w',encoding='utf-8',newline='') as f:
        w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(rows)
def metrics(cases,mapping,path):
    rows=[score_portable(c[path],mapping,c['query_id']) for c in cases]
    return {k:statistics.mean(r[k] for r in rows) for k in rows[0]}
def units(c,path,mapping,k):return {a for a,v in mapping.items() if a.startswith(c['query_id']+':') and set(v)&set(c[path][:k])}
def latency(vals):return dict(p50=float(np.percentile(vals,50)),p95=float(np.percentile(vals,95)))
protocol=read(O/'protocol.json')
for p,h in protocol['protected_hashes'].items():assert hashlib.sha256((R/p).read_bytes()).hexdigest()==h,p
base=read(O/'BASE_retrieval.json');bm=read(O/'BASE_corpus.json')['mapping'];miss=read(R/'artifacts/evaluation_v2/c0/miss_review.json')
summary={'status':'COMPLETE','protocol':protocol,'configs':{},'limitations':['50% raw-span coverage is an operational portability proxy, not semantic entailment.','Fixed absolute overlap100 has different relative proportions across chunk sizes.','Raw union uses up to 2K candidates and is diagnostic only.','Latency excludes cold load, HTTP and live MySQL roundtrip; authority is a frozen corpus snapshot.','Reranked E2E is per-query median retrieval plus measured reranker latency.']};paired=[];mappingrows=[];ledger=[]
for key in ('BASE','A','B','C'):
    corpus=read(O/f'{key}_corpus.json');mapping=corpus['mapping'];out=read(O/f'{key}_retrieval.json');audit=corpus['audit']
    r={'status':out['status'],'audit':audit,'statistics':out['statistics'],'ann':out['ann']};summary['configs'][key]=r
    mappingrows.append(dict(config=key,mapped=audit['mapped'],unmapped=len(audit['unmapped']),ambiguous=audit['ambiguous'],**audit['multiplicity']))
    if out['status']!='COMPLETE':continue
    cases=out['cases'];r['metrics']={p:metrics(cases,mapping,p) for p in ('bm25','dense','hybrid')}
    r['query_types']={t:dict(n=sum(c['query_type']==t for c in cases),**metrics([c for c in cases if c['query_type']==t],mapping,'hybrid')) for t in sorted({c['query_type'] for c in cases})}
    r['raw_union']={};r['retention']={};r['duplicates']={};r['miss_recovery']={};r['c0_categories']={}
    for k in (20,30,50):
        unioncases=[dict(c,union=list(dict.fromkeys(c['bm25'][:k]+c['dense'][:k]))) for c in cases]
        r['raw_union'][str(k)]=statistics.mean(len(units(c,'union',mapping,2*k))/sum(a.startswith(c['query_id']+':') for a in mapping) for c in unioncases)
        retained=den=0
        for c in cases:
            d=units(c,'dense',mapping,50);den+=len(d);retained+=len(d&units(c,'hybrid',mapping,k))
        r['retention'][str(k)]=dict(retained=retained,dense_top50_units=den)
    for k in (20,50):
        dup=[duplicate_equivalent(c['hybrid'],mapping,c['query_id'],k) for c in cases]
        r['duplicates'][str(k)]=dict(queries=sum(n>0 for n in dup),chunks=sum(dup))
        recovered=set();lost=set()
        for c,b in zip(cases,base['cases']):
            assert c['query_id']==b['query_id'];old=units(b,'hybrid',bm,k);new=units(c,'hybrid',mapping,k)
            recovered|=new-old;lost|=old-new
        r['miss_recovery'][str(k)]=dict(recovered=sorted(recovered),lost=sorted(lost),net=len(recovered)-len(lost))
        r['c0_categories'][str(k)]={cat:dict(baseline_misses=sum(m['diagnosis']==cat and m[f'miss_top{k}'] for m in miss),recovered=sum(m['diagnosis']==cat and m[f'miss_top{k}'] and m['anchor_id'] in recovered for m in miss)) for cat in ('BOUNDARY_SPLIT','CHUNK_TOO_BROAD','NOT_CHUNKING_RELATED','UNCLEAR')}
    for c,b in zip(cases,base['cases']):
        p={'config':key,'query_id':c['query_id'],'query_type':c['query_type']}
        scores=[]
        for label,row,mp in [('baseline',b,bm),('alternative',c,mapping)]:
            ms=score_portable(row['hybrid'],mp,c['query_id']);scores.append(tuple(ms[x] for x in ('CR@50','CR@30','CR@20','R@10','MRR@10')))
            relevant={sid for a,v in mp.items() if a.startswith(c['query_id']+':') for sid in v}
            p[label+'_best_gold_rank']=next((i+1 for i,s in enumerate(row['hybrid']) if s in relevant),None)
            for k in (20,30,50):p[f'{label}_hits{k}']=len(units(row,'hybrid',mp,k))
        p['classification']='IMPROVED' if scores[1]>scores[0] else 'REGRESSED' if scores[1]<scores[0] else 'UNCHANGED';paired.append(p)
    rr=read(O/f'{key}_reranked.json');scores=[score_reranked_portable(c['reranked'],c['hybrid'],mapping,c['query_id']) for c in rr['cases']];r['reranked']={m:statistics.mean(s[m] for s in scores) for m in scores[0]}
    r['latency']={name:latency([t[name] for c in cases for t in c['timings']]) for name in cases[0]['timings'][0]}
    r['latency']['reranked_e2e_ms']=latency([c['reranked_e2e_ms'] for c in rr['cases']])
    r['cost']={k:out[k] for k in ('chunk_encode_sec','index_build_sec','index_size_bytes')};r['cost']['historical_base_encode_sec']=out.get('historical_encode_sec')
    h=r['metrics']['hybrid'];d=r['metrics']['dense'];b=r['metrics']['bm25']
    ledger.append(dict(experiment_id='V2-C1-'+key,phase='V2-C1',status='COMPLETE',chunk_strategy=audit['config']['strategy'],target_size=audit['config']['target'],hard_max=audit['config']['hard_max'],overlap=100,page_policy='page-contained',chunking_config_hash=audit['chunking_config_hash'],chunk_count=audit['chunk_count'],gold_mapped=audit['mapped'],gold_ambiguous=audit['ambiguous'],mean_gold_mapping_multiplicity=audit['multiplicity']['mean'],ann_overlap20=out['ann']['overlap20'],ann_overlap50=out['ann']['overlap50'],bm25_r10=b['R@10'],bm25_cr20=b['CR@20'],bm25_cr50=b['CR@50'],dense_r10=d['R@10'],dense_cr20=d['CR@20'],dense_cr50=d['CR@50'],hybrid_r10=h['R@10'],hybrid_mrr10=h['MRR@10'],hybrid_cr20=h['CR@20'],hybrid_cr30=h['CR@30'],hybrid_cr50=h['CR@50'],reranked_r10=r['reranked']['R@10'],reranked_mrr10=r['reranked']['MRR@10'],recovered_baseline_miss20=len(r['miss_recovery']['20']['recovered']),recovered_baseline_miss50=len(r['miss_recovery']['50']['recovered']),lost_baseline_hit20=len(r['miss_recovery']['20']['lost']),lost_baseline_hit50=len(r['miss_recovery']['50']['lost']),duplicate_gold_equivalent20=r['duplicates']['20']['chunks'],duplicate_gold_equivalent50=r['duplicates']['50']['chunks'],hybrid_p50=r['latency']['retrieval_ms']['p50'],hybrid_p95=r['latency']['retrieval_ms']['p95'],chunk_encode_sec=out['chunk_encode_sec'],index_size_mb=out['index_size_bytes']/1024**2))
valid={k:v for k,v in summary['configs'].items() if v['status']=='COMPLETE'}
summary['metric_leader']=max(valid,key=lambda k:tuple(valid[k]['metrics']['hybrid'][m] for m in ('CR@50','CR@30','CR@20','R@10','MRR@10')))
summary['decision']='PENDING_COST_REVIEW';summary['status']='ANALYSIS_READY'
if (O/'closeout_robustness.json').exists():
    audit=read(O/'closeout_robustness.json')
    summary.update(closeout=audit['decision'],decision=audit['decision']['selected_candidate'],status=audit['decision']['status'])
save(O/'summary.json',summary);csvwrite(B/'c1_chunking_paired_cases.csv',paired);csvwrite(B/'c1_gold_mapping_summary.csv',mappingrows)
# Keep proposed rows separate until final analysis; historical ledger remains unchanged.
save(O/'ledger_rows.json',ledger)
print(json.dumps({k:v.get('metrics',{}).get('hybrid') for k,v in summary['configs'].items()},indent=2))
