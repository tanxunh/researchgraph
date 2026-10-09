"""Offline V2-E analysis. Reads cached scores only; never invokes a model."""
from __future__ import annotations
import collections,csv,json,statistics
from run_v2_reranker_optimization import (ROOT,B,E,MODELS,METRICS,read,write,sha,inputs,metrics,hits,blend,classify,paired,gate,verify)

def csvwrite(path,rows):
    with (ROOT/path).open('w',encoding='utf-8',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
def analysis():
    protocol=verify();qs,pools,corpus,mapping=inputs();cross=[q for q in qs if q['query_type']=='cross_document'];assert len(cross)==7
    candidate=hits(pools,mapping,20);original=hits(pools,mapping);sources={key:read(E/(key+'_scores.json')) for key in MODELS}
    for key,s in sources.items():
        assert s['status']=='COMPLETE' and s['audit']['status']=='PASS' and len(s['cases'])==35
        assert s['protocol_sha256']==sha(E/'protocol.json')
        assert s['audit']['model']==MODELS[key][0] and s['audit']['revision']==MODELS[key][1]
        for row,q in zip(s['cases'],qs):assert row['query_id']==q['query_id'] and row['candidate_ids']==pools[q['query_id']]
    rankings={'NO_RERANK':pools.copy()};meta={'NO_RERANK':{'model':None,'alpha':None}}
    for key,s in sources.items():
        for alpha in (1.,.75,.5):
            name=f'{key}_a{alpha:.2f}';rankings[name]={x['query_id']:blend(x['candidate_ids'],x['scores'],alpha) for x in s['cases']};meta[name]={'model':key,'alpha':alpha}
    current='base_a1.00';currenthits=hits(rankings[current],mapping);crossids={q['query_id'] for q in cross}
    configs={};auditrows=[];gainrows=[];crossrows=[];pairedrows=[]
    for name,rank in rankings.items():
        mm,per=metrics(rank,mapping,qs);cm,cp=metrics(rank,mapping,cross);hh=hits(rank,mapping);h5=hits(rank,mapping,5)
        recovered=sorted(hh-currenthits);lost=sorted(currenthits-hh)
        cats={g:classify(g in candidate,g in original,g in hh) for g in mapping};counts=dict(collections.Counter(cats.values()))
        cfg={'metrics':mm,'per_query':per,'hit_count10':len(hh),'hits5':len(h5),'recovered':recovered,'lost':lost,'net':len(recovered)-len(lost),'cross':cm,'cross_recovered':[g for g in recovered if g.split(':')[0] in crossids],'cross_lost':[g for g in lost if g.split(':')[0] in crossids],'error_counts':counts,'demotions':counts.get('DEMOTED_OUT_OF_TOP10',0),'demoted_ids':[g for g,c in cats.items() if c=='DEMOTED_OUT_OF_TOP10'],**meta[name]}
        configs[name]=cfg
        for g,cat in cats.items():
            q=g.split(':')[0];ids=set(mapping[g]);rankof=lambda a:next((i+1 for i,c in enumerate(a) if c in ids),None)
            auditrows.append({'config':name,'query_id':q,'gold_id':g,'classification':cat,'hybrid_rank':rankof(pools[q]),'reranked_rank':rankof(rank[q]),'equivalent_chunk_ids':'|'.join(sorted(ids))})
        for label,ids in [('RECOVERED',recovered),('LOST',lost)]:
            gainrows.extend({'config':name,'reference':current,'query_id':g.split(':')[0],'gold_id':g,'change':label} for g in ids)
        crossrows.append({'config':name,'n':7,'R@10':cm['R@10'],'MRR@10':cm['MRR@10'],'recovered':len(cfg['cross_recovered']),'lost':len(cfg['cross_lost']),'net':len(cfg['cross_recovered'])-len(cfg['cross_lost'])})
    base=configs[current]
    for name,c in configs.items():
        c['paired']=paired(c['per_query'],base['per_query']);c['gate']=gate(c,base)
        for q,pm in c['per_query'].items():
            before=base['per_query'][q];dr=pm['R@10']-before['R@10'];rr=pm['MRR@10']-before['MRR@10']
            pairedrows.append({'config':name,'query_id':q,'recall10_delta':dr,'classification':'improved' if dr>0 else 'regressed' if dr<0 else 'unchanged','reciprocal_rank_delta_secondary':rr})
    def priority(name):
        c=configs[name];lat=sources[c['model']]['latency'] if c['model'] else {'mean_ms':0,'peak_rss_bytes':0}
        return tuple(c['metrics'][k] for k in METRICS)+(c['net'],c['paired']['improved']-c['paired']['regressed'],c['cross']['R@10'],c['cross']['MRR@10'],-c['demotions'],-lat['mean_ms'],-lat['peak_rss_bytes'],int(c['model']=='base'),int(c['alpha']==1.))
    candidates=[n for n in configs if n!='NO_RERANK'];leader=max(candidates,key=priority)
    eligible=[n for n in candidates if n!=current and configs[n]['gate']['pass']]
    value=base['metrics']['R@10']>configs['NO_RERANK']['metrics']['R@10']
    if not value and not eligible:
        raise RuntimeError('RERANKER_VALUE_NOT_REPRODUCED: do not automatically freeze current')
    selected=max(eligible,key=priority) if eligible else current;best=configs[selected];key=best['model'];source=sources[key]
    winnerhits=hits(rankings[selected],mapping);vsnone={'recovered':sorted(winnerhits-original),'lost':sorted(original-winnerhits)};vsnone['net']=len(vsnone['recovered'])-len(vsnone['lost'])
    for label in ('recovered','lost'):
        gainrows.extend({'config':selected,'reference':'NO_RERANK','query_id':g.split(':')[0],'gold_id':g,'change':label.upper()} for g in vsnone[label])
    opportunity='MATERIAL' if eligible else 'MINOR' if any(c['net']>0 and c['metrics']['R@10']>base['metrics']['R@10'] for c in configs.values()) else 'NOT SUPPORTED'
    contribution='MATERIAL' if best['metrics']['R@10']>configs['NO_RERANK']['metrics']['R@10'] and vsnone['net']>=2 else 'MINOR' if best['metrics']['R@10']>configs['NO_RERANK']['metrics']['R@10'] else 'NONE'
    model,rev=MODELS[key];audit=source['audit']
    frozen={'selected_from':'V2-E','DEV_SELECTED':True,'TEST_VALIDATED':False,'PRODUCTION_DEFAULT':False,'model':model,'revision':rev,'tokenizer_revision':rev,'model_fingerprint':audit['model_fingerprint'],'tokenizer_fingerprint':audit['tokenizer_fingerprint'],'max_length':512,'batch_size':8,'device':'cpu','dtype':'float32','candidate_depth':20,'final_top_k':10,'rank_blend_alpha':best['alpha'],'rank_blend_k':10,'input_contract':'raw query / raw chunk','tie_breaking':'original fusion rank ascending','score_extraction':audit['score_extraction'],'protocol_sha256':sha(E/'protocol.json'),'final_fusion_config_sha256':sha(B/'final_fusion_config.json'),'source_scores_sha256':sha(E/(key+'_scores.json')),'runner_sha256':sha('backend/scripts/run_v2_reranker_optimization.py')}
    write(B/'final_reranker_config.json',frozen);fh=sha(B/'final_reranker_config.json');(ROOT/B/'final_reranker_config.sha256').write_text(fh+'  final_reranker_config.json\n',encoding='utf-8')
    write(E/'reranker_audit.json',{'status':'PASS','models':{k:s['audit'] for k,s in sources.items()},'current_error_counts':base['error_counts'],'current_demoted_ids':base['demoted_ids']})
    write(E/'final_rankings.json',{n:{q:ids[:10] for q,ids in ranks.items()} for n,ranks in rankings.items()})
    write(E/'paired_queries.json',pairedrows)
    summary={'status':'ANALYSIS_COMPLETE_PENDING_TESTS','DEV_queries':35,'cross_document_queries':7,'Gold_units':55,'candidate_CR@20':protocol['candidate_CR@20'],'candidate_Gold_hits':len(candidate),'configs':configs,'current':current,'lexicographic_leader':leader,'selected':selected,'replacement_gate':best['gate'],'selected_vs_NO_RERANK':vsnone,'current_value_reproduced':value,'optimization_opportunity':opportunity,'reranker_contribution':contribution,'latency':{k:s['latency'] for k,s in sources.items()},'cost':{k:{t:s['audit'][t] for t in ('parameter_count','model_disk_bytes','model_fingerprint','tokenizer_fingerprint')} for k,s in sources.items()},'final_config_sha256':fh,'protected_hashes':protocol['protected_hashes'],'outputs_sha256':{str(E/(k+'_scores.json')):sha(E/(k+'_scores.json')) for k in MODELS},'TEST_evaluated':False,'production_changed':False,'metric_definition':'macro query-average; each of 55 approved full-containment Gold units counted once; final metrics Top10, coverage from frozen pre-rerank Top20 only','latency_boundary':protocol['latency_boundary']}
    csvwrite(B/'v2_e_reranker_grid.csv',[{'config':n,'model':MODELS[c['model']][0] if c['model'] else 'none','alpha':c['alpha'],**c['metrics'],'Gold_hits10':c['hit_count10'],'recovered_vs_current':len(c['recovered']),'lost_vs_current':len(c['lost']),'net':c['net'],**c['paired'],'demoted':c['demotions'],'replacement_gate':c['gate']['pass'],'front_safety_flag':c['gate']['front_safety_flag']} for n,c in configs.items()])
    csvwrite(B/'v2_e_gain_loss.csv',gainrows);csvwrite(B/'v2_e_error_audit.csv',auditrows);csvwrite(B/'v2_e_cross_document.csv',crossrows)
    verify();write(E/'summary.json',summary)
    print(json.dumps({k:summary[k] for k in ('selected','lexicographic_leader','replacement_gate','optimization_opportunity','reranker_contribution','final_config_sha256')},indent=2))
    for n,c in configs.items():print(n,c['metrics'],c['error_counts'],c['net'])
    return summary
if __name__=='__main__':analysis()
