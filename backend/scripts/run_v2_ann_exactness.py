"""Frozen DEV ANN audit. export reads production; run operates only on isolated snapshot."""
import os
os.environ.update(LLM_API_KEY='',GRAPH_EXTRACTION_ENABLED='false',HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',ANONYMIZED_TELEMETRY='false')
import argparse,csv,hashlib,json,time,traceback,statistics
from pathlib import Path
import numpy as np
from app.services.evaluation import ann_exactness as a
ROOT=Path('/workspace');BASE=ROOT/'benchmarks/real_research/v2';TMP=ROOT/'.tmp/v2b2';OUT=BASE/'results/v2b2_ann_exactness.json'

def save(p,v):p.write_text(json.dumps(v,ensure_ascii=False,indent=2,default=str)+'\n',encoding='utf-8')
def guard():
    baseline=json.loads((BASE/'results/v2a_integrity.json').read_text())
    for s in ['dev','test']:assert hashlib.sha256((BASE/f'queries_{s}.jsonl').read_bytes()).hexdigest()==baseline[f'{s}_sha256']
    for p,h in baseline['production_hashes'].items():assert hashlib.sha256((ROOT/p).read_bytes()).hexdigest()==h,p
    return baseline

def export():
    guard();assert not (TMP/'vectors.npz').exists()
    from app.core.config import get_settings
    from app.vectorstore.chroma_store import ChromaStore
    from app.vectorstore.embeddings import get_embedding_provider
    from app.services.evaluation.v2_benchmark import load_inputs,validate_queries,ensure_corpus_state
    from app.services.indexing.version_chunks import membership_query,VersionChunk
    from app.models.document import Document
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    s=get_settings();store=ChromaStore(create_collection=False);p=get_embedding_provider()
    assert s.embedding_model=='BAAI/bge-small-zh-v1.5' and s.embedding_normalize and s.embedding_dimension==512
    corpus,manifest,queries=load_inputs(BASE,'dev');assert len(queries)==35
    engine=create_engine(s.database_url)
    with Session(engine) as db:
        ensure_corpus_state(db,corpus);assert all(q['valid'] for q in validate_queries(db,corpus,queries,require_human=True))
        chunks=[VersionChunk(c,mc,v) for c,mc,v,d in db.execute(membership_query().where(Document.status=='ready')).all()]
        expected={c.stable_chunk_id:c for c in chunks};ids=[];vectors=[];docs=[]
        for offset in range(0,store.count(),128):
            data=store.collection.get(limit=128,offset=offset,include=['embeddings','metadatas','documents'])
            for i,sid in enumerate(data['ids']):
                c=expected[sid];assert store.metadata_matches(data['metadatas'][i],store.chunk_metadata([c])[0]) and data['documents'][i]==c.text
                ids.append(sid);vectors.append(data['embeddings'][i]);docs.append(c.document_id)
        assert set(ids)==set(expected) and len(ids)==3837
    engine.dispose();t=time.perf_counter();m=p._get_model();cold=(time.perf_counter()-t)*1000
    rev=m[0].auto_model.config._commit_hash;assert rev=='7999e1d3359715c523056ef9478215996d62a620'
    qv=np.asarray(p.embed_documents([q['query'] for q in queries]),dtype=np.float32)
    x=np.asarray(vectors,dtype=np.float32);assert np.allclose(np.linalg.norm(x,axis=1),1,atol=1e-6)
    reference={}
    for track in ['global','scoped']:
        reference[track]={}
        for q,v in zip(queries,qv):
            kw={} if track=='global' else {'where':{'document_id':{'$in':q['document_scope']}}}
            reference[track][q['query_id']]=store.collection.query(query_embeddings=[v.tolist()],n_results=200,include=['distances'],**kw)['ids'][0]
    np.savez(TMP/'vectors.npz',ids=np.array(ids),vectors=x,document_ids=np.array(docs),query_vectors=qv)
    identity=dict(model=s.embedding_model,revision=rev,pooling='CLS',normalization=True,metric='l2',query_encoding='raw',document_encoding='raw',dimension=512,corpus_hash=hashlib.sha256((BASE/'corpus_manifest.json').read_bytes()).hexdigest(),vector_fingerprint=a.vector_fingerprint(ids,x))
    save(TMP/'export.json',dict(identity=identity,collection=store.collection_name,collection_metadata=store.collection.metadata,queries=queries,baseline_ranking=reference,model_load_ms=cold,baseline_fingerprints=guard(),query_vector_fingerprint=a.vector_fingerprint([q['query_id'] for q in queries],qv)))
    print('EXPORT COMPLETE: stored vectors only, 35 DEV query encodings; baseline ef10 reference captured.',flush=True)

def run():
    guard();assert not OUT.exists();e=json.loads((TMP/'export.json').read_text());z=np.load(TMP/'vectors.npz');ids=z['ids'].tolist();x=z['vectors'];docs=z['document_ids'];qv=z['query_vectors'];queries=e['queries']
    assert a.vector_fingerprint(ids,x)==e['identity']['vector_fingerprint']
    import chromadb
    from chromadb.config import Settings
    from chromadb.segment import VectorReader
    t=time.perf_counter();client=chromadb.PersistentClient(path=str(TMP/'chroma_snapshot'),settings=Settings(anonymized_telemetry=False));coll=client.get_collection(e['collection'],embedding_function=None)
    assert coll.count()==len(ids)
    snapshot=coll.get(include=['embeddings']);assert a.vector_fingerprint(snapshot['ids'],snapshot['embeddings'])==e['identity']['vector_fingerprint']
    coll.query(query_embeddings=[qv[0].tolist()],n_results=200,include=['distances'])
    seg=client._server._manager.get_segment(coll.id,VectorReader);idx=seg._index
    assert idx is not None and idx.ef==10
    report=dict(status='RUNNING',identity=e['identity'],dev_sha256=guard()['dev_sha256'],test_sha256=guard()['test_sha256'],index_load_ms=(time.perf_counter()-t)*1000,model_load_ms=e['model_load_ms'],ann_requested_depth=200,repeats=3,latency_unit='ms',latency_scope='search-only; embeddings precomputed; local Chroma includes Python/SQLite filtering; exact in-memory exhaustive sort; no HTTP/model load',effective_ef_control='isolated PersistentLocalHnswSegment._index.set_ef; assert index.ef before/after queries',experiments=[],ranking_agreement={})
    exacts={};exactcases={}
    for track in ['global','scoped']:
        exacts[track]={};cases=[]
        for i,q in enumerate(queries):
            mask=np.ones(len(ids),dtype=bool) if track=='global' else np.isin(docs,q['document_scope']);si=np.array(ids)[mask].tolist();sx=x[mask]
            dot=a.exact_order(si,sx,qv[i]);cos=a.exact_order(si,sx,qv[i],'cosine')
            # Both full orderings are recorded if float32 near ties differ; top100 must agree before experiments.
            assert dot[:100]==cos[:100],f'dot_cosine_top100_mismatch:{q["query_id"]}'
            exacts[track][q['query_id']]=dot
            ms=[]
            for _ in range(3):
                t=time.perf_counter();rank=a.exact_order(si,sx,qv[i]);ms.append((time.perf_counter()-t)*1000);assert rank==dot
            cases.append(dict(query_id=q['query_id'],query_type=q['query_type'],ids=dot,exact=dot,gold=[g['chunk_id'] for g in q['gold_evidence']],latency_ms=ms,full_dot_cosine_equal=dot==cos))
        exactcases[track]=cases
    report['ranking_agreement']={track:dict(top100_all_equal=True,full_order_equal_queries=sum(c['full_dot_cosine_equal'] for c in cases),queries=35) for track,cases in exactcases.items()}
    def package(name,ef,tracks,extra=None):
        namespace={**e['identity'],'ef_search':ef};fingerprint=hashlib.sha256(json.dumps(namespace,sort_keys=True).encode()).hexdigest()
        return dict(id='v2b2-'+name,backend=name,ef_search=ef,namespace='v2b2-'+fingerprint,namespace_identity=namespace,tracks={tr:dict(overall=a.summarize(cs),by_type={ty:a.summarize([c for c in cs if c['query_type']==ty]) for ty in sorted({c['query_type'] for c in cs})}) for tr,cs in tracks.items()},cases=tracks,**(extra or {}))
    report['experiments'].append(package('exact',None,exactcases));save(OUT.with_suffix('.progress.json'),report)
    def ann(ef):
        idx.set_ef(ef);assert idx.ef==ef;tracks={};probes={};baseline_equal=True
        for track in ['global','scoped']:
            tracks[track]=[];probes[track]={str(k):[] for k in [10,20,50,100]}
            for i,q in enumerate(queries):
                kw={} if track=='global' else {'where':{'document_id':{'$in':q['document_scope']}}}
                def search(k):return coll.query(query_embeddings=[qv[i].tolist()],n_results=k,include=['distances'],**kw)['ids'][0]
                warm=search(200);ms=[]
                for _ in range(3):
                    t=time.perf_counter();rank=search(200);ms.append((time.perf_counter()-t)*1000);assert rank==warm and idx.ef==ef
                assert len(set(rank))==len(rank) and all(sid in ids for sid in rank)
                if ef==10:baseline_equal=baseline_equal and rank==e['baseline_ranking'][track][q['query_id']]
                tracks[track].append(dict(query_id=q['query_id'],query_type=q['query_type'],ids=rank,exact=exacts[track][q['query_id']],gold=[g['chunk_id'] for g in q['gold_evidence']],latency_ms=ms))
                for k in [10,20,50,100]:probes[track][str(k)].append(a.fidelity(search(k),exacts[track][q['query_id']],min(k,len(exacts[track][q['query_id']]))))
        if ef==10 and not baseline_equal:
            save(TMP/f'failed-snapshot-ef10-cases-{time.time_ns()}.json',tracks)
            raise AssertionError('snapshot_ranking_differs_from_existing_baseline')
        ex=package(f'ef{ef}',ef,tracks,dict(effective_ef=int(idx.ef),direct_n_results_fidelity={tr:{k:statistics.mean(v) for k,v in values.items()} for tr,values in probes.items()},baseline_ranking_equal=baseline_equal if ef==10 else None));report['experiments'].append(ex);save(OUT.with_suffix('.progress.json'),report)
        print('COMPLETE',ex['backend'],ex['tracks']['global']['overall'],flush=True);return ex
    for ef in [10,32,64,128]:last=ann(ef)
    if last['tracks']['global']['overall']['fidelity@50']<.99:ann(256)
    choices=[ex for ex in report['experiments'][1:] if ex['tracks']['global']['overall']['fidelity@50']>=.99]
    report['selected_ef']=min(ex['ef_search'] for ex in choices) if choices else None
    report['selection_rule']='Smallest ef with Global primary Top50 fidelity >=99%; inspect task metric stability and latency. Primary n_results=200 matches frozen source acquisition. Direct n_results=K probes reported separately.'
    selected=next((ex for ex in report['experiments'] if ex['ef_search']==report['selected_ef'] and ex['backend']!='exact'),report['experiments'][-1]);base=report['experiments'][1]
    report['gold_loss']={}
    for track in ['global','scoped']:
        report['gold_loss'][track]={str(k):sum(len((set(c['exact'][:k])&set(c['gold']))-set(c['ids'][:k])) for c in base['cases'][track]) for k in [20,50]}
    rows=[]
    for tr in ['global','scoped']:
        for c,sc in zip(base['cases'][tr],selected['cases'][tr]):
            for gold in c['gold']:
                rank=lambda values:values.index(gold)+1 if gold in values else None
                rows.append(dict(track=tr,query_id=c['query_id'],gold_chunk_id=gold,exact_top20_gold_hit=gold in c['exact'][:20],ef10_top20_gold_hit=gold in c['ids'][:20],exact_gold_rank=rank(c['exact']),ef10_gold_rank=rank(c['ids']),selected_ef_gold_rank=rank(sc['ids']),notes='ANN absent rank means >200/not returned; exact rank exhaustive. Counts are query-gold units.'))
    with (BASE/'ann_exactness_error_cases.csv').open('w',newline='',encoding='utf-8') as f:
        writer=csv.DictWriter(f,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
    report['status']='COMPLETE';report['final_integrity']=guard();save(OUT,report)
    print('AUDIT COMPLETE selected_ef',report['selected_ef'],'gold_loss',report['gold_loss'],flush=True)

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('stage',choices=['export','run']);args=parser.parse_args()
    try:globals()[args.stage]()
    except Exception as exc:
        save(TMP/f'failure-{args.stage}-{time.time_ns()}.json',dict(status='FAILED',stage=args.stage,error_type=type(exc).__name__,error=str(exc)[:1000]));raise
