"""DEV-only V2-A candidate experiments. No production defaults or TEST execution."""
from __future__ import annotations
import argparse,copy,csv,hashlib,json,os,time,traceback
from pathlib import Path
from datetime import datetime,timezone
os.environ.update(LLM_API_KEY='',GRAPH_EXTRACTION_ENABLED='false',RERANKER_ENABLED='false',HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1')
from app.services.evaluation import v2_candidates as c
from app.services.evaluation import v2_benchmark as v
from app.services.evaluation.metrics import score_ranking

ROOT=Path(__file__).resolve().parents[2]/'benchmarks/real_research/v2'
OUT=ROOT/'results'
CACHE=ROOT.parents[2]/'.tmp/v2-baseline/v2a_sources.json'
DEV_HASH='2977076711400a1ff41ee4886c48e9fdd8f68f4e8fd41e2e5a5bd96e537fc7b9'
TEST_HASH='5b94e93eed901c3ef05df7a9d4efa4d14b9aef19fbdb160d83c314f15306c419'

def save(path,data):
    tmp=path.with_suffix(path.suffix+'.tmp');tmp.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8');tmp.replace(path)

def guard():
    assert v.sha256(ROOT/'queries_dev.jsonl')==DEV_HASH
    # TEST bytes used solely for hash verification, never parsed.
    assert v.sha256(ROOT/'queries_test.jsonl')==TEST_HASH
    corpus,m,rows=v.load_inputs(ROOT,'dev')
    assert len(rows)==35 and all(r['human_verified'] for r in rows) and m['dev_gold_frozen']
    from app.core.config import get_settings
    settings=get_settings()
    baseline=json.loads((OUT/'dev_baseline_frozen_gold.json').read_text())
    metadata=v.build_metadata(settings,'dev',corpus,m,{})
    for key in ['embedding','chunking','reranker','graph_extraction_enabled']:
        assert metadata[key]==baseline['metadata'][key],key
    assert settings.rrf_k==60 and settings.embedding_local_files_only
    assert settings.database_url.startswith('mysql+pymysql://')
    return corpus,m,rows,settings

def ledger(experiment):
    path=ROOT/'experiments.csv'
    with path.open(encoding='utf-8',newline='') as f:
        reader=csv.DictReader(f);fields=list(reader.fieldnames);old=list(reader)
    g=experiment.get('tracks',{}).get('global',{});overall=g.get('overall',{});cross=g.get('cross_document',{})
    row=dict(experiment_id=experiment['id'],phase='V2-A',status=experiment.get('status','COMPLETE'),date=datetime.now(timezone.utc).isoformat(),split='dev',corpus_version='v2_baseline',embedding='BAAI/bge-small-zh-v1.5',chunking='text-chunker-v1',candidate_policy=experiment.get('policy',''),bm25_k=experiment.get('bm25_k',''),dense_k=experiment.get('dense_k',''),candidate_budget=experiment.get('budget',''),rrf_k=60,rerank_k=experiment.get('rerank_k',0),notes=experiment.get('notes',''),dev_sha256=DEV_HASH,test_sha256=TEST_HASH)
    for key in ['HitRate@5','Recall@5','Recall@10','MRR@10','CR@20','CR@30','CR@50','candidate_recall','retrieval_p50','retrieval_p95','reranker_p50','reranker_p95','e2e_p50','e2e_p95']:
        row['Hit@5' if key=='HitRate@5' else key]=overall.get(key)
    for key in ['Recall@10','CR@20','CR@30','CR@50','candidate_recall']:row['cross_document_'+key]=cross.get(key)
    for key in row:
        if key not in fields:fields.append(key)
    assert not any(r['experiment_id']==row['experiment_id'] for r in old),'duplicate_experiment_id'
    # Expand schema while preserving every existing field value and row.
    tmp=path.with_suffix('.csv.tmp')
    with tmp.open('w',encoding='utf-8',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=fields);writer.writeheader();writer.writerows(old);writer.writerow(row)
    tmp.replace(path)

def collect():
    assert not CACHE.exists(),'source_cache_exists_do_not_rerun'
    corpus,m,rows,s=guard()
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from app.vectorstore.embeddings import get_embedding_provider
    from app.services.retrieval.retrieval_service import ResearchRetrievalService
    for d in corpus['documents']:assert v.sha256(ROOT.parent/'papers'/d['filename'])==d['sha256']
    start=time.perf_counter();get_embedding_provider()._get_model();cold=(time.perf_counter()-start)*1000
    data=dict(dev_hash=DEV_HASH,test_hash=TEST_HASH,embedding_cold_ms=cold,tracks={})
    engine=create_engine(s.database_url,pool_pre_ping=True)
    try:
        with Session(engine) as db:
            v.ensure_corpus_state(db,corpus);validated=v.validate_queries(db,corpus,rows,require_human=True);assert all(r['valid'] for r in validated)
            service=ResearchRetrievalService(db)
            for track in ['global','scoped']:
                data['tracks'][track]={}
                for depth in c.DEPTHS:
                    for source in ['bm25','dense']:
                        scope=rows[0]['document_scope'] if track=='scoped' else None
                        c.retrieve_source(service,rows[0]['query'],source,depth,scope)
                        for q in rows:
                            scope=q['document_scope'] if track=='scoped' else None
                            item=c.retrieve_source(service,q['query'],source,depth,scope)
                            data['tracks'][track].setdefault(q['query_id'],{}).setdefault(str(depth),{})[source]=item
                        print(f'COLLECT {track} {source} depth={depth} DONE',flush=True)
                    save(CACHE.with_suffix('.progress.json'),data)
    finally:engine.dispose()
    guard();save(CACHE,data);print('SOURCE COLLECTION COMPLETE',flush=True)

def cases_for(data,rows,track,policy,bk,dk,budget):
    return [c.make_case(q,data['tracks'][track][q['query_id']][str(bk)]['bm25'],data['tracks'][track][q['query_id']][str(dk)]['dense'],policy,budget) for q in rows]

def experiment(data,rows,eid,policy,bk,dk,budget):
    c.validate_source_budget(policy,bk,dk,budget)
    result=dict(id=eid,policy=policy,bm25_k=bk,dense_k=dk,budget=budget,status='COMPLETE',tracks={},cases={},notes='Experiment-only; no production change. Retrieval latency=sum of separately measured source paths plus pool construction; excludes cold load. CR above budget is unavailable.')
    for track in data['tracks']:
        cases=cases_for(data,rows,track,policy,bk,dk,budget)
        result['tracks'][track]=c.metrics(cases,budget)
        result['cases'][track]=[{k:v for k,v in case.items() if k not in ['pool','query']} for case in cases]
        union_values=[];b_values=[];d_values=[]
        for q in rows:
            sources=data['tracks'][track][q['query_id']];b=[r['chunk_id'] for r in sources[str(bk)]['bm25']['rows']];d=[r['chunk_id'] for r in sources[str(dk)]['dense']['rows']];gold=[g['chunk_id'] for g in q['gold_evidence']]
            union=list(dict.fromkeys(b+d));union_values.append(score_ranking(union,gold,max(1,len(union)))['Recall']);b_values.append(score_ranking(b,gold,max(1,bk))['Recall']);d_values.append(score_ranking(d,gold,max(1,dk))['Recall'])
        import statistics
        result['tracks'][track]['source_diagnostics']=dict(bm25_recall=statistics.mean(b_values),dense_recall=statistics.mean(d_values),full_union_recall=statistics.mean(union_values),union_budget='up to bm25_k+dense_k, NOT equal-budget comparison')
    return result

def candidates():
    corpus,m,rows,s=guard();data=json.loads(CACHE.read_text());assert data['dev_hash']==DEV_HASH
    path=OUT/'v2a_candidates_v2.json';assert not path.exists()
    report=dict(status='COMPLETE',dev_hash=DEV_HASH,test_hash=TEST_HASH,selection_rule='B: mean RRF candidate recall at budgets 20/30/50, then cross-document, then smaller source depth. C: highest Global candidate coverage at budget50, then cross-document coverage, Recall@10, MRR@10, latency. Same policy is also compared at budgets20/30.',experiments=[])
    def add(e):
        report['experiments'].append(e)
        if e['id'].startswith('v2a-C2'): ledger(e)
        save(path.with_suffix('.progress.json'),report)
    for budget in c.BUDGETS:add(experiment(data,rows,f'v2a-A-rrf200-{budget}','rrf',200,200,budget))
    def coordinate(axis,fixed):
        groups=[]
        for depth in [20,40,60,100]:
            bk,dk=(depth,100) if axis=='bm25' else (fixed,depth)
            group=[]
            for budget in [20,30,50]:
                e=experiment(data,rows,f'v2a-B-{axis}{depth}-b{bk}-d{dk}-m{budget}','rrf',bk,dk,budget);add(e);group.append(e)
            groups.append((depth,group))
        key=lambda item:(sum(e['tracks']['global']['overall']['candidate_recall'] for e in item[1])/3,sum(e['tracks']['global']['cross_document']['candidate_recall'] for e in item[1])/3,-item[0])
        return max(groups,key=key)[0]
    bk=coordinate('bm25',100);dk=coordinate('dense',bk);report['coordinate_choice']=dict(bm25_k=bk,dense_k=dk)
    for budget in [20,30,50]:
        for policy in ['bm25','dense','rrf','protected_union']:
            # 'current RRF' must retain the actual 200/200 baseline inputs.
            b,d=(200,200) if policy=='rrf' else ((100,100) if policy in ('bm25','dense') else (bk,dk))
            add(experiment(data,rows,f'v2a-C2-{policy}-{budget}',policy,b,d,budget))
    options=[e for e in report['experiments'] if e['id'].startswith('v2a-C2') and e['budget']==50]
    def key(e):
        g=e['tracks']['global'];o=g['overall'];return(o['candidate_recall'],g['cross_document']['candidate_recall'],o['Recall@10'],o['MRR@10'],-o['retrieval_p50'])
    winner=max(options,key=key);report['candidate_winner']={k:winner[k] for k in ['id','policy','bm25_k','dense_k','budget']}
    report['embedding_cold_ms']=data['embedding_cold_ms'];guard();save(path,report)
    print(json.dumps({'coordinate':report['coordinate_choice'],'winner':report['candidate_winner']}),flush=True)

def rerank():
    _,_,rows,s=guard();data=json.loads(CACHE.read_text());candidate=json.loads((OUT/'v2a_candidates_v2.json').read_text());winner=candidate['candidate_winner']
    from app.services.retrieval.reranker import get_reranker,rerank_candidates
    from app.services.retrieval.active_candidates import resolve_active,matches_candidate
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    scorer=get_reranker(s);start=time.perf_counter();scorer.load();cold=(time.perf_counter()-start)*1000
    policies=[('current_rrf','rrf',200,200)]
    if (winner['policy'],winner['bm25_k'],winner['dense_k'])!=('rrf',200,200):policies.append(('candidate_winner',winner['policy'],winner['bm25_k'],winner['dense_k']))
    # D is Global-primary; Scoped A/B/C remain fully reported. No unrequested scoped reranker grid.
    for label,policy,bk,dk in policies:
        for budget in c.BUDGETS:
            eid=f'v2a-D-{label}-{budget}';path=OUT/(eid+'.json')
            if path.exists():print('PRESERVE COMPLETED '+eid,flush=True);continue
            cases=cases_for(data,rows,'global',policy,bk,dk,budget)
            # Revalidate all cached candidates against authoritative current-version evidence.
            engine=create_engine(s.database_url,pool_pre_ping=True)
            with Session(engine) as db:
                for case in cases:
                    active=resolve_active(db,[r['chunk_occurrence_id'] for r in case['pool']])
                    for r in case['pool']:
                        pair=active.get(r['chunk_occurrence_id']);assert matches_candidate(pair,r['chunk_occurrence_id'],r['chunk_id']) and pair[0].document_version_id==r['document_version_id']
            engine.dispose()
            _,warm=rerank_candidates(cases[0]['query'],cases[0]['pool'],scorer);assert not warm['reranker_failed']
            for index,case in enumerate(cases,1):
                start=time.perf_counter();ordered,meta=rerank_candidates(case['query'],case['pool'],scorer);elapsed=(time.perf_counter()-start)*1000
                if meta['reranker_failed']:raise RuntimeError(f'{eid}:{case["query_id"]}:reranker_failed')
                case.update(returned_ids=[r['chunk_id'] for r in ordered[:10]],reranker_ms=elapsed,e2e_ms=case['retrieval_ms']+elapsed)
                if index%5==0:print(f'{eid}: {index}/35',flush=True)
            e=dict(id=eid,policy=policy,bm25_k=bk,dense_k=dk,budget=budget,rerank_k=budget,status='COMPLETE',reranker_cold_ms=cold,tracks={'global':c.metrics(cases,budget)},cases={'global':[{k:v for k,v in case.items() if k not in ['pool','query']} for case in cases]},notes='Global DEV only; one warmup then 35 timed rerank calls; model load excluded. E2E=sum of measured cached-source retrieval/construction and fresh reranker times, not one contiguous public API call.')
            guard();save(path,e);ledger(e);print('COMPLETE '+eid,flush=True)
    print('D COMPLETE',flush=True)

def main():
    parser=argparse.ArgumentParser();parser.add_argument('stage',choices=['collect','candidates','rerank']);args=parser.parse_args()
    try:{'collect':collect,'candidates':candidates,'rerank':rerank}[args.stage]()
    except Exception as exc:
        failure=dict(id=f'v2a-FAILED-{args.stage}-{time.time_ns()}',status='FAILED',notes=type(exc).__name__+': '+str(exc))
        save(OUT/(failure['id']+'.json'),failure);ledger(failure);raise
if __name__=='__main__':main()
