"""Post-TEST reporting only. No model, index or pipeline parameter changes."""
from run_v2_final_retrieval import *
import csv

def csvwrite(p,rows):
 with (ROOT/p).open('w',encoding='utf-8',newline='') as f:
  w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
def summarize():
 assert not (ROOT/F/'summary.json').exists(),'final summary already exists'
 lock=read(F/'pre_test_lock.json')
 for p,h in lock['protected_hashes'].items():assert sha(p)==h,p
 run=read(F/'test_run.json');assert run['status']=='COMPLETE' and run['attempt']==1 and len(run['cases'])==40
 frozen=read(F/'test_metrics_frozen.json');assert frozen['run_sha256']==sha(F/'test_run.json')
 queries_test=queries('test');ids=[q['query_id'] for q in queries_test];assert [r['query_id'] for r in run['cases']]==ids
 events=[json.loads(x) for x in (ROOT/F/'query_execution_journal.jsonl').read_text().splitlines()];assert len(events)==80
 assert [(e['query_id'],e['state']) for e in events]==[(q,state) for q in ids for state in ('STARTED','COMPLETED')]
 mapping=read(F/'test_gold_validation.json')['mapping'];metrics=frozen['metrics'];assert metrics==evaluate(run['cases'],mapping)
 cases=run['cases'];diag=[];errors=[];gain=[];paired=[]
 def pos(ids,gs):return next((i+1 for i,c in enumerate(ids) if c in gs),None)
 for c in cases:
  qid=c['query_id'];groups={g:set(v) for g,v in mapping.items() if g.startswith(qid+':')}
  for g,gs in groups.items():
   hr=pos(c['hybrid'],gs);rr=pos(c['reranked20'],gs);before=hr is not None and hr<=10;after=rr is not None and rr<=10;candidate=hr is not None and hr<=20
   label='NOT_IN_TOP20' if not candidate else 'STAYED_IN_TOP10' if before and after else 'DEMOTED_OUT_OF_TOP10' if before else 'PROMOTED_INTO_TOP10' if after else 'CANDIDATE_PRESENT_BUT_MISSED'
   row={'query_id':qid,'gold_id':g,'chunk_id':'|'.join(sorted(gs)),'hybrid_rank':hr,'reranker_rank':rr,'classification':label,'Gold_present_lower_than_hybrid_Top10':hr is not None and hr>10};diag.append(row)
   if after and not before:gain.append({'query_id':qid,'gold_id':g,'change':'RECOVERED'})
   if before and not after:gain.append({'query_id':qid,'gold_id':g,'change':'LOST'})
   if not after:
    reason='NOT_IN_HYBRID_TOP20' if not candidate else 'DEMOTED_BY_RERANKER' if before else 'IN_TOP20_RERANKER_FAILED_TO_PROMOTE' if rr is not None else 'OTHER_VALID_EVALUATION_MISS'
    errors.append({**row,'error_category':reason})
  before=metrics['hybrid']['per_query'][qid];after=metrics['reranked']['per_query'][qid];delta=after['R@10']-before['R@10']
  paired.append({'query_id':qid,'R@10_delta':delta,'classification':'improved' if delta>0 else 'regressed' if delta<0 else 'unchanged','MRR@10_delta_secondary':after['MRR@10']-before['MRR@10']})
 dev=read(F/'dev_reproduction.json')['metrics'];deltas={k:metrics['reranked']['metrics'][k]-dev['reranked']['metrics'][k] for k in FINAL}
 deltas.update({k:metrics['hybrid']['metrics'][k]-dev['hybrid']['metrics'][k] for k in ('CR@20','CR@30','CR@50')})
 worst=max(-deltas[k] for k in FINAL);movement='STABLE' if worst<.05 else 'MODERATE DROP' if worst<=.15 else 'LARGE DROP'
 useful=metrics['reranked']['metrics']['R@10']>metrics['hybrid']['metrics']['R@10']
 generalization='STRONG' if movement=='STABLE' and useful else 'ACCEPTABLE' if movement!='LARGE DROP' and useful else 'WEAK'
 breakdown={}
 for kind in dict.fromkeys(q['query_type'] for q in queries_test):
  subset=[c for c in cases if c['query_type']==kind];ms=evaluate(subset,mapping)
  breakdown[kind]={'n':len(subset),'description':'descriptive / low-sample','final_R@10':ms['reranked']['metrics']['R@10'],'final_MRR@10':ms['reranked']['metrics']['MRR@10'],'Hybrid_CR@20':ms['hybrid']['metrics']['CR@20'],'Hybrid_CR@50':ms['hybrid']['metrics']['CR@50']}
 def percentile(v,p):
  v=sorted(v);i=(len(v)-1)*p;lo=math.floor(i);hi=math.ceil(i);return v[lo]+(v[hi]-v[lo])*(i-lo)
 latency={key:{'mean_ms':statistics.mean(c['timings_ms'][key] for c in cases),'p50_ms':statistics.median(c['timings_ms'][key] for c in cases),'p95_ms':percentile([c['timings_ms'][key] for c in cases],.95)} for key in cases[0]['timings_ms']}
 diagnostics={'counts':dict(collections.Counter(x['classification'] for x in diag)),'Gold_units':diag,'gain_loss':gain,'paired_queries':paired,'errors':errors,'error_counts':dict(collections.Counter(x['error_category'] for x in errors)),'error_query_ids':{cat:sorted({x['query_id'] for x in errors if x['error_category']==cat}) for cat in sorted({x['error_category'] for x in errors})},'secondary_lower_than_Top10_count':sum(x['Gold_present_lower_than_hybrid_Top10'] for x in errors),'error_rule':'mutually exclusive A/C/B/E precedence; D is explicitly secondary because lower-ranked Gold overlaps A/B/C','metrics_frozen_before_analysis_sha256':sha(F/'test_metrics_frozen.json')}
 write(F/'test_diagnostics.json',diagnostics);csvwrite(B/'v2_f_test_error_analysis.csv',errors)
 csvwrite(B/'v2_f_test_metrics.csv',[{'route':route,**{k:row['metrics'].get(k,'') for k in ALL},**{'Gold_hits@'+k:row['Gold_hit_counts'].get(k,'') for k in ('5','10','20','30','50')}} for route,row in metrics.items()])
 csvwrite(B/'v2_f_test_query_types.csv',[{'query_type':k,**v} for k,v in breakdown.items()])
 # The original pre-TEST bytes remain preserved. The manifest changes validation provenance only.
 manifest=read(B/'final_retrieval_manifest.json');assert sha(B/'final_retrieval_manifest.json')==lock['pre_test_manifest_sha256']
 manifest.update(TEST_VALIDATED=True,pre_test_manifest_sha256=lock['pre_test_manifest_sha256'],test_execution_count=1,test_run_sha256=sha(F/'test_run.json'),test_metrics_sha256=sha(F/'test_metrics_frozen.json'),test_validated_at=now())
 write(B/'final_retrieval_manifest.json',manifest);finalhash=sha(B/'final_retrieval_manifest.json');(ROOT/B/'final_retrieval_manifest.sha256').write_text(finalhash+'  final_retrieval_manifest.json\n',encoding='utf-8')
 rec=[x['gold_id'] for x in gain if x['change']=='RECOVERED'];lost=[x['gold_id'] for x in gain if x['change']=='LOST']
 protected={k:v for k,v in lock['protected_hashes'].items() if k!=str(B/'final_retrieval_manifest.json')}
 summary={'status':'EVALUATED_PENDING_REGRESSION','pre_test_manifest_sha256':lock['pre_test_manifest_sha256'],'final_manifest_sha256':finalhash,'DEV_metrics':dev,'TEST_metrics':metrics,'TEST_queries':40,'TEST_Gold_units':len(mapping),'TEST_execution_count':1,'reranker_contribution':{'recovered':rec,'lost':lost,'net':len(rec)-len(lost),'paired':dict(collections.Counter(x['classification'] for x in paired))},'DEV_to_TEST_delta':deltas,'movement':movement,'generalization':generalization,'generalization_is_descriptive_only':True,'comparability_note':read(F/'protocol.json')['comparability_note'],'query_type_breakdown':breakdown,'cross_document':breakdown.get('cross_document'),'error_counts':diagnostics['error_counts'],'error_query_ids':diagnostics['error_query_ids'],'secondary_Gold_lower_than_Top10':diagnostics['secondary_lower_than_Top10_count'],'latency':latency,'latency_boundary':read(F/'protocol.json')['latency_boundary'],'protected_hashes':protected,'production_changed':False,'post_TEST_tuning':False,'pre_test_lock':'PASS','TEST_Gold_validation':'PASS','runtime_audit':run['runtime_audit'],'tests':{'status':'PENDING'}}
 summary['artifact_hashes']={str(F/name):sha(F/name) for name in ['test_run.json','test_metrics_frozen.json','test_execution_lock.json','query_execution_journal.jsonl','test_diagnostics.json','pre_test_lock.json']}
 for name,h in protected.items():assert sha(name)==h,name
 write(F/'summary.json',summary)
 print(json.dumps({k:summary[k] for k in ['TEST_queries','TEST_Gold_units','reranker_contribution','DEV_to_TEST_delta','movement','generalization','final_manifest_sha256']},indent=2),flush=True)
 for route,d in metrics.items():print(route,d['metrics'],d['Gold_hit_counts'],flush=True)

if __name__=='__main__':summarize()
