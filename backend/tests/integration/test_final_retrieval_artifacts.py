"""After-run integrity checks only. No models or retrieval execution."""
import json,hashlib,statistics
from pathlib import Path
R=Path(__file__).resolve().parents[3];F='artifacts/evaluation_v2/f/';B='benchmarks/real_research/v2/'
def read(p):return json.loads((R/p).read_text(encoding='utf-8'))
def sha(p):return hashlib.sha256((R/p).read_bytes()).hexdigest()

def test_manifest_references_and_preserved_pre_test_identity():
 s=read(F+'summary.json');m=read(B+'final_retrieval_manifest.json');pre=read(F+'pre_test_manifest.json')
 assert sha(F+'pre_test_manifest.json')==s['pre_test_manifest_sha256']==m['pre_test_manifest_sha256']
 assert sha(B+'final_retrieval_manifest.json')==s['final_manifest_sha256']
 assert m['TEST_VALIDATED'] and not pre['TEST_VALIDATED'] and not m['PRODUCTION_DEFAULT']
 assert m['DEV_SELECTED'] and m['reranker_candidate_depth']==20 and m['final_top_k']==10
 for comp in ('chunking','dense','fusion','reranker'):assert sha(m[comp+'_config_path'])==m[comp+'_config_sha256']
 for key,val in pre.items():
  if key!='TEST_VALIDATED':assert m[key]==val
 for name,h in {**s['protected_hashes'],**s['artifact_hashes']}.items():assert sha(name)==h,name

def test_exactly_one_test_attempt_and_one_visit_per_query():
 lock=read(F+'test_execution_lock.json');run=read(F+'test_run.json');events=[json.loads(x) for x in (R/(F+'query_execution_journal.jsonl')).read_text().splitlines()]
 assert lock['attempt']==run['attempt']==1 and run['status']=='COMPLETE'
 ids=[r['query_id'] for r in run['cases']];assert len(ids)==len(set(ids))==40
 assert ids==lock['query_ids'] and len(events)==80
 assert [(x['query_id'],x['state']) for x in events]==[(q,k) for q in ids for k in ('STARTED','COMPLETED')]
 assert run['pre_test_manifest_sha256']==lock['pre_test_manifest_sha256']==sha(F+'pre_test_manifest.json')

def test_independent_test_metrics_and_identity():
 run=read(F+'test_run.json');v=read(F+'test_gold_validation.json');s=read(F+'summary.json');mapping=v['mapping'];assert v['status']=='PASS'
 for route in ('bm25','dense','hybrid','reranked'):
  per=[];counts={k:0 for k in (5,10,20,30,50)}
  for row in run['cases']:
   ids=row[route];assert len(ids)==len(set(ids))
   if route=='reranked':assert len(ids)==10 and set(ids)<=set(row['hybrid'][:20])
   gs=[set(ids) for gid,ids in mapping.items() if gid.startswith(row['query_id']+':')];rank=[next((i+1 for i,c in enumerate(ids) if c in g),None) for g in gs];best=min((x for x in rank if x is not None),default=None)
   rec={k:sum(x is not None and x<=k for x in rank)/len(gs) for k in counts}
   mm={'Hit@5':int(best is not None and best<=5),'R@5':rec[5],'R@10':rec[10],'MRR@10':1/best if best is not None and best<=10 else 0,**{'CR@'+str(k):rec[k] for k in (20,30,50)}};per.append(mm)
   for k in counts:counts[k]+=sum(x is not None and x<=k for x in rank)
  saved=s['TEST_metrics'][route]
  for k,val in saved['metrics'].items():assert abs(statistics.mean(x[k] for x in per)-val)<1e-12
  for k,val in saved['Gold_hit_counts'].items():assert counts[int(k)]==val
  if route=='reranked':assert not any(k.startswith('CR') for k in saved['metrics'])

def test_frozen_fusion_and_reranker_ranking_formula():
 run=read(F+'test_run.json');src=read('artifacts/evaluation_v2/b4/corpus.json');occ={cid:r['metadata']['document_chunk_id'] for cid,r in zip(src['ids'],src['rows'])}
 for c in run['cases']:
  dense=c['dense'];bm=c['bm25'];scores={};ids={}
  for route,w in ((dense,1.),(bm,1.25)):
   for rank,cid in enumerate(route,1):
    key=occ[cid];scores[key]=scores.get(key,0)+w/(20+rank);ids.setdefault(key,cid)
  expected=[ids[k] for k in sorted(scores,key=scores.get,reverse=True)[:100]];assert c['hybrid']==expected
  pairs=list(zip(c['reranked20'],c['reranker_scores']));byid=dict(pairs)
  expected=sorted(c['hybrid'][:20],key=lambda cid:(-byid[cid],c['hybrid'].index(cid)))
  assert expected==c['reranked20'] and c['reranked']==expected[:10]

def test_dev_reproduction_and_gold_immutability():
 dev=read(F+'dev_reproduction.json');assert dev['status']=='PASS' and len(dev['cases'])==35
 e=read('artifacts/evaluation_v2/e/summary.json');assert dev['metrics']['reranked']['metrics']==e['configs']['base_a1.00']['metrics']
 m=read(B+'final_retrieval_manifest.json');assert sha(m['DEV_Gold_path'])==m['DEV_Gold_sha256'];assert sha(m['TEST_Gold_path'])==m['TEST_Gold_sha256']
 qs=[json.loads(x) for x in (R/m['TEST_Gold_path']).read_text().splitlines()];projection=[{'query_id':q['query_id'],'gold_evidence':q['gold_evidence']} for q in qs]
 h=hashlib.sha256(json.dumps(projection,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()).hexdigest();assert h==m['TEST_Gold_canonical_sha256']

def test_diagnostics_partition_and_latency():
 s=read(F+'summary.json');d=read(F+'test_diagnostics.json');run=read(F+'test_run.json')
 assert sum(d['counts'].values())==s['TEST_Gold_units']
 assert len(d['errors'])==s['TEST_Gold_units']-s['TEST_metrics']['reranked']['Gold_hit_counts']['10']
 assert sum(d['error_counts'].values())==len(d['errors']) and len({x['gold_id'] for x in d['errors']})==len(d['errors'])
 assert sum(s['reranker_contribution']['paired'].values())==40
 for key,ms in s['latency'].items():assert abs(ms['mean_ms']-statistics.mean(c['timings_ms'][key] for c in run['cases']))<1e-9
 for c in run['cases']:
  t=c['timings_ms'];assert abs(t['end_to_end']-t['retrieval']-t['fusion']-t['reranker'])<1e-6
