"""B6 frozen DEV integration; real local models, production BM25/RRF/reranker on frozen authority snapshot."""
import os
os.environ.update(LLM_API_KEY='',GRAPH_EXTRACTION_ENABLED='false',HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',ANONYMIZED_TELEMETRY='false')
import sys,types,json,hashlib,time,shutil,tempfile,gc
from pathlib import Path
from types import SimpleNamespace
R=Path(__file__).resolve().parents[2];A=R/'artifacts/evaluation_v2';O=A/'b6';B=R/'benchmarks/real_research/v2';O.mkdir(exist_ok=True)
pkg=types.ModuleType('app.services.evaluation');pkg.__path__=[str(R/'backend/app/services/evaluation')];sys.modules['app.services.evaluation']=pkg
from app.services.evaluation.hybrid_integration import fuse
from app.services.evaluation.ann_exactness import vector_fingerprint
from app.services.indexing.bm25_index import BM25Index
from app.services.retrieval.reranker import CrossEncoderReranker,rerank_candidates

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def save(p,data):
    tmp=p.with_suffix('.tmp');tmp.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8');tmp.replace(p)

def run(key):
    assert key in ('zh','m3')
    target=O/f'{key}.json';assert not target.exists(),'completed_result_preserved'
    b4=json.loads((A/f'b4/{key}.json').read_text());source=json.loads((A/'b4/corpus.json').read_text());policy=json.loads((O/'protocol.json').read_text())
    def guard():
        for name,digest in policy['protected_hashes'].items():assert sha(R/name)==digest,name
    guard()
    queries=[json.loads(l) for l in (B/'queries_dev.jsonl').read_text().splitlines() if l.strip()];assert len(queries)==35
    cache=json.loads((R/'.tmp/v2-baseline/v2a_sources.json').read_text())
    expected=dict(zip(source['ids'],source['rows']));occ={sid:r['metadata']['document_chunk_id'] for sid,r in expected.items()}
    assert len(set(occ.values()))==3837
    chunks=sorted([SimpleNamespace(id=occ[sid],stable_chunk_id=sid,text=r['document']) for sid,r in expected.items()],key=lambda c:c.id)
    # Authoritative membership was exported/validated in B4/B5. Only database I/O is replaced by this immutable fixture.
    class SnapshotSession:
        def scalars(self,statement):return SimpleNamespace(all=lambda:chunks)
    bm25=BM25Index(SnapshotSession())
    def lexical(q):
        hits=bm25.search(q['query'],200);ids=[h.stable_chunk_id for h in hits]
        wanted=cache['tracks']['global'][q['query_id']]['200']['bm25']['rows']
        assert ids==[r['chunk_id'] for r in wanted],'bm25_ranking_drift'
        assert [h.score for h in hits]==[r['scores']['bm25_score'] for r in wanted],'bm25_score_drift'
        for row in wanted:
            r=expected[row['chunk_id']];m=r['metadata']
            assert row['text']==r['document'] and row['document_version_id']==m['document_version_id'] and row['chunk_occurrence_id']==m['document_chunk_id'] and row['document']['id']==m['document_id']
        return ids
    import torch,numpy as np,chromadb
    from sentence_transformers import SentenceTransformer
    from chromadb.config import Settings
    torch.set_num_threads(4);torch.set_num_interop_threads(1)
    cfg=b4['config'];src=R/'.tmp/v2b4'/b4['index_namespace'];copy=Path(tempfile.mkdtemp())/'index';shutil.copytree(src,copy)
    client=chromadb.PersistentClient(path=str(copy),settings=Settings(anonymized_telemetry=False));coll=client.get_collection(b4['collection_name'],embedding_function=None)
    stored=coll.get(include=['embeddings']);assert vector_fingerprint(stored['ids'],stored['embeddings'])==b4['document_vector_fingerprint']
    model=SentenceTransformer(cfg['model'],revision=cfg['revision'],device='cpu',cache_folder='/models/model_cache',local_files_only=True)
    qvectors=np.load(A/f'b4/{key}_vectors.npz')['query_vectors']
    out={'status':'RUNNING','key':key,'config':cfg,'cases':[],'protocol_sha256':sha(O/'protocol.json'),'latency_boundary':policy['latency_boundary']}
    def retrieve(i):
        q=queries[i];start=time.perf_counter_ns();b=lexical(q);bt=time.perf_counter_ns()
        vector=model.encode([cfg['query_prefix']+q['query']],normalize_embeddings=True,show_progress_bar=False)[0];et=time.perf_counter_ns()
        got=coll.query(query_embeddings=[vector.tolist()],n_results=200,include=['metadatas','distances']);d=got['ids'][0]
        for sid,m in zip(d,got['metadatas'][0]):
            em=dict(expected[sid]['metadata'])
            if key=='m3':em.update(embedding_model=cfg['model'],embedding_dimension=cfg['dimension'],embedding_provider='bge',embedding_version=b4['index_namespace'])
            assert m==em,'authority_identity_changed'
        dt=time.perf_counter_ns();h=fuse(b,d,occ,100);end=time.perf_counter_ns()
        assert np.allclose(vector,qvectors[i],atol=1e-5)
        assert d==b4['cases']['global'][i]['ids'],'dense_ranking_drift'
        return b,d,h,dict(bm25_ms=(bt-start)/1e6,encode_ms=(et-bt)/1e6,search_ms=(dt-et)/1e6,fusion_ms=(end-dt)/1e6,retrieval_ms=(end-start)/1e6)
    for i in range(35):retrieve(i)
    for i,q in enumerate(queries):
        samples=[]
        for repeat in range(3):
            b,d,h,timing=retrieve(i);samples.append(timing)
        out['cases'].append(dict(query_id=q['query_id'],query_type=q['query_type'],gold=sorted({g['chunk_id'] for g in q['gold_evidence']}),bm25=b,dense=d,hybrid=h,timings=samples))
        if (i+1)%5==0:save(O/f'{key}.progress.json',out);print('RETRIEVAL',key,i+1,flush=True)
    del model;gc.collect()
    scorer=CrossEncoderReranker('BAAI/bge-reranker-base',policy['reranker_revision'],'cpu','/models/model_cache',True);scorer.load()
    assert scorer.model.model.config._commit_hash==policy['reranker_revision']
    def rerank(i):
        c=out['cases'][i];pool=[{'chunk_id':sid,'text':expected[sid]['document'],'scores':{}} for sid in c['hybrid'][:20]]
        start=time.perf_counter_ns();ordered,meta=rerank_candidates(queries[i]['query'],pool,scorer);elapsed=(time.perf_counter_ns()-start)/1e6
        assert not meta['reranker_failed'] and set(r['chunk_id'] for r in ordered)==set(c['hybrid'][:20])
        return [r['chunk_id'] for r in ordered[:10]],elapsed,[r['scores']['reranker_score'] for r in ordered]
    rerank(0)
    for i,c in enumerate(out['cases']):
        ids,ms,scores=rerank(i);c.update(reranked=ids,reranker_ms=ms,reranker_scores=scores)
        # Per-query composed latency, never sum of percentiles; reranker timed once, retrieval median of 3 warm samples.
        c['reranked_e2e_ms']=sorted(t['retrieval_ms'] for t in c['timings'])[1]+ms
        save(O/f'{key}.progress.json',out)
        if (i+1)%5==0:print('RERANK',key,i+1,flush=True)
    guard();out['status']='COMPLETE';save(target,out);print('B6 COMPLETE',key,flush=True)
if __name__=='__main__':
    try:run(sys.argv[1])
    except Exception as exc:
        save(O/f'failure-{time.time_ns()}.json',{'error':type(exc).__name__,'detail':str(exc)});raise
