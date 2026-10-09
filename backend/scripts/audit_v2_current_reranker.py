"""Persist current-baseline diagnostics before comparing model B."""
from run_v2_reranker_optimization import *
p=verify();qs,pools,corpus,mapping=inputs();s=read(E/'base_scores.json')
assert s['status']=='COMPLETE' and s['audit']['status']=='PASS'
r={x['query_id']:x['reranked'] for x in s['cases']};m,per=metrics(r,mapping,qs)
candidates=hits(pools,mapping,20);original=hits(pools,mapping);final=hits(r,mapping)
classes={g:classify(g in candidates,g in original,g in final) for g in mapping}
out={'metrics':m,'counts':dict(collections.Counter(classes.values())),'gold_classification':classes,'demoted':[g for g,c in classes.items() if c=='DEMOTED_OUT_OF_TOP10'],'base_scores_sha256':sha(E/'base_scores.json'),'new_fusion_candidates':True,'B6_metrics_reused':False,'no_rerank':p['no_rerank_metrics'],'audit_status':'PASS'}
write(E/'current_baseline_audit.json',out)
print(json.dumps(out,indent=2))
