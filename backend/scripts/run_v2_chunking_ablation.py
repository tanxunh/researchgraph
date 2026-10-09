"""Offline C1 primary retrieval; frozen DEV only, resumable encoding."""
import os
os.environ.update(LLM_API_KEY='',GRAPH_EXTRACTION_ENABLED='false',HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',ANONYMIZED_TELEMETRY='false')
import sys,types,json,time,hashlib,shutil,statistics
from pathlib import Path
from types import SimpleNamespace
R=Path(__file__).resolve().parents[2];sys.path.insert(0,str(R/'backend'));O=R/'artifacts/evaluation_v2/c1';A=R/'artifacts/evaluation_v2';B=R/'benchmarks/real_research/v2'
pkg=types.ModuleType('app.services.evaluation');pkg.__path__=[str(R/'backend/app/services/evaluation')];sys.modules['app.services.evaluation']=pkg
from app.services.evaluation.chunking_ablation import fingerprint
from app.services.evaluation.hybrid_integration import fuse
from app.services.evaluation.ann_exactness import exact_order,vector_fingerprint
from app.services.evaluation.ann_reproducibility import persist_experimental_graph
from app.services.indexing.bm25_index import BM25Index
MODEL='BAAI/bge-m3';REV='5617a9f61b028005a4858fdac845db406aefb181'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def save(p,v):
    tmp=p.with_suffix('.tmp');tmp.write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n',encoding='utf-8');tmp.replace(p)
def guard():
    for p,h in json.loads((O/'protocol.json').read_text())['protected_hashes'].items():assert sha(R/p)==h,p
def run(key):
    guard();target=O/f'{key}_retrieval.json'
    if target.exists():assert json.loads(target.read_text())['status'] in ('COMPLETE','ANN_CONFUND');return
    corpus=json.loads((O/f'{key}_corpus.json').read_text());assert corpus['audit']['status']=='GATE_PASS'
    chunks=corpus['chunks'];ids=[c['chunk_id'] for c in chunks];texts=[c['text'] for c in chunks];mapping=corpus['mapping'];occ={sid:i+1 for i,sid in enumerate(ids)}
    queries=[json.loads(l) for l in (B/'queries_dev.jsonl').read_text().splitlines() if l.strip()];assert len(queries)==35
    items=[SimpleNamespace(id=occ[c['chunk_id']],stable_chunk_id=c['chunk_id'],text=c['text']) for c in chunks]
    class SnapshotSession:
        def scalars(self,statement):return SimpleNamespace(all=lambda:items)
    bm=BM25Index(SnapshotSession())
    bmrows={q['query_id']:[h.stable_chunk_id for h in bm.search(q['query'],200)] for q in queries}
    save(O/f'{key}_bm25.json',{'implementation':'production BM25Index; per-query statistics construction included in retrieval latency','rankings':bmrows})
    import numpy as np,torch,chromadb
    from sentence_transformers import SentenceTransformer
    from chromadb.config import Settings
    from chromadb.segment import VectorReader
    torch.set_num_threads(4);torch.set_num_interop_threads(1)
    model=SentenceTransformer(MODEL,revision=REV,device='cpu',cache_folder='/models/model_cache',local_files_only=True)
    assert model[0].auto_model.config._commit_hash==REV and model.max_seq_length==8192
    assert model[1].pooling_mode_cls_token and not model[1].pooling_mode_mean_tokens and model[2].__class__.__name__=='Normalize'
    assert not model.prompts and model.default_prompt_name is None
    def dist(vals,qs):return {str(q):float(np.percentile(vals,q)) for q in qs}
    stats={'chars':dist([len(t) for t in texts],[0,25,50,75,95,100]),'m3_tokens':dist([len(t) for t in model.tokenizer(texts,truncation=False)['input_ids']],[0,50,95,100])}
    namespace='v2c1-'+key.lower()+'-'+fingerprint({'chunking':corpus['audit']['chunking_config_hash'],'model':MODEL,'revision':REV,'dimension':1024})[:20]
    out={'key':key,'status':'RUNNING','namespace':namespace,'statistics':stats,'cases':[],'mapping_gate':corpus['audit'],'protocol_sha256':sha(O/'protocol.json')}
    old=json.loads((A/'b4/m3.json').read_text());oldvec=np.load(A/'b4/m3_vectors.npz')
    if key=='BASE':
        lookup={str(s):v for s,v in zip(oldvec['ids'],oldvec['vectors'])};vectors=np.array([lookup[s] for s in ids]);seconds=0
        out['encoding_cost_note']='Reused frozen identical BASE embeddings; prior B4 measured cost recorded separately.'
        out['historical_encode_sec']=old['index_encode_sec']
    else:
        folder=O/f'{key}_encoding';folder.mkdir(exist_ok=True);parts=[];seconds=0
        for offset in range(0,len(ids),256):
            p=folder/f'{offset}.npy';meta=p.with_suffix('.json')
            if p.exists() and meta.exists():
                m=json.loads(meta.read_text());assert m['namespace']==namespace and m['sha256']==sha(p);v=np.load(p);elapsed=m['seconds']
            else:
                t=time.perf_counter();v=model.encode(texts[offset:offset+256],batch_size=4,normalize_embeddings=True,show_progress_bar=False);elapsed=time.perf_counter()-t
                np.save(p,v);save(meta,dict(namespace=namespace,seconds=elapsed,sha256=sha(p)))
            assert v.shape==(min(256,len(ids)-offset),1024) and np.isfinite(v).all()
            parts.append(v);seconds+=elapsed;out.update(encoded_chunks=min(offset+256,len(ids)),chunk_encode_sec=seconds)
            save(O/f'{key}_progress.json',out);print('ENCODED',key,out['encoded_chunks'],flush=True)
        vectors=np.concatenate(parts)
    assert np.allclose(np.linalg.norm(vectors,axis=1),1,atol=1e-5)
    out['chunk_encode_sec']=seconds
    qv=model.encode([q['query'] for q in queries],batch_size=1,normalize_embeddings=True,show_progress_bar=False)
    assert np.allclose(qv,oldvec['query_vectors'],atol=1e-5)
    np.savez(O/f'{key}_vectors.npz',ids=np.array(ids),vectors=vectors,query_vectors=qv)
    folder=R/'.tmp/v2c1'/namespace;folder.parent.mkdir(parents=True,exist_ok=True)
    marker=O/f'{key}_index.json';t=time.perf_counter()
    if marker.exists():
        built=json.loads(marker.read_text());assert built['namespace']==namespace
        client=chromadb.PersistentClient(path=str(folder),settings=Settings(anonymized_telemetry=False));coll=client.get_collection(built['collection_name'],embedding_function=None)
    else:
        assert not folder.exists(),'partial_index_requires_diagnosis_no_rebuild'
        if key=='BASE':shutil.copytree(R/'.tmp/v2b4'/old['index_namespace'],folder)
        client=chromadb.PersistentClient(path=str(folder),settings=Settings(anonymized_telemetry=False))
        if key=='BASE':coll=client.get_collection(old['collection_name'],embedding_function=None)
        else:
            coll=client.create_collection(namespace,embedding_function=None,metadata={'hnsw:space':'l2','hnsw:M':16,'hnsw:construction_ef':100,'hnsw:search_ef':10,'hnsw:num_threads':16,'hnsw:batch_size':100,'hnsw:sync_threshold':1000})
            for offset in range(0,len(ids),100):
                coll.add(ids=ids[offset:offset+100],embeddings=vectors[offset:offset+100].tolist(),documents=texts[offset:offset+100],metadatas=[dict(document_id=c['document_id'],document_version_id=c['document_version_id'],page=c['page'],occurrence_id=occ[c['chunk_id']],embedding_identity=namespace) for c in chunks[offset:offset+100]])
        coll.query(query_embeddings=[qv[0].tolist()],n_results=200)
        seg=client._server._manager.get_segment(coll.id,VectorReader);assert seg._index.ef==10
        if key!='BASE':persist_experimental_graph(seg,folder,R/'.tmp/v2c1')
        built=dict(namespace=namespace,collection_name=coll.name,index_build_sec=time.perf_counter()-t,index_size_bytes=sum(p.stat().st_size for p in folder.rglob('*') if p.is_file()))
        save(marker,built)
    out.update(built)
    stored=coll.get(include=['embeddings','documents','metadatas']);assert vector_fingerprint(stored['ids'],stored['embeddings'])==vector_fingerprint(ids,vectors)
    expected={c['chunk_id']:c for c in chunks}
    for sid,text,m in zip(stored['ids'],stored['documents'],stored['metadatas']):
        c=expected[sid];assert text==c['text'] and m['document_id']==c['document_id'] and m['document_version_id']==c['document_version_id']
    metadata=dict(zip(stored['ids'],stored['metadatas']))
    def dense(v):
        got=coll.query(query_embeddings=[v.tolist()],n_results=200,include=['metadatas'])
        for sid,m in zip(got['ids'][0],got['metadatas'][0]):assert m==metadata[sid]
        return got['ids'][0]
    for i,q in enumerate(queries):
        d=dense(qv[i]);b=bmrows[q['query_id']];ex=exact_order(ids,vectors,qv[i])[:200]
        out['cases'].append(dict(query_id=q['query_id'],query_type=q['query_type'],bm25=b,dense=d,exact=ex,hybrid=fuse(b,d,occ,100),timings=[]))
    def recall(case,path,k):
        gs=[a for a in mapping if a.startswith(case['query_id']+':')]
        return sum(bool(set(mapping[a])&set(case[path][:k])) for a in gs)/len(gs)
    ann={f'overlap{k}':statistics.mean(len(set(c['dense'][:k])&set(c['exact'][:k]))/k for c in out['cases']) for k in (20,50)}
    ann.update(ann_cr50=statistics.mean(recall(c,'dense',50) for c in out['cases']),exact_cr50=statistics.mean(recall(c,'exact',50) for c in out['cases']))
    out['ann']=ann
    if ann['overlap50']<.98 or abs(ann['ann_cr50']-ann['exact_cr50'])>.02:
        out['status']='ANN_CONFUND';save(target,out);guard();print(key,'ANN_CONFUND',ann,flush=True);return
    def retrieve(i):
        q=queries[i];t=time.perf_counter();b=[h.stable_chunk_id for h in bm.search(q['query'],200)];bt=time.perf_counter()
        v=model.encode([q['query']],normalize_embeddings=True,show_progress_bar=False)[0];et=time.perf_counter();d=dense(v);dt=time.perf_counter();h=fuse(b,d,occ,100);end=time.perf_counter()
        c=out['cases'][i];assert b==c['bm25'] and d==c['dense'] and h==c['hybrid']
        return dict(bm25_ms=(bt-t)*1000,encode_ms=(et-bt)*1000,search_ms=(dt-et)*1000,fusion_ms=(end-dt)*1000,retrieval_ms=(end-t)*1000)
    for i in range(35):retrieve(i)
    for repeat in range(3):
        for i,c in enumerate(out['cases']):c['timings'].append(retrieve(i))
        save(O/f'{key}_progress.json',out);print('RETRIEVAL',key,repeat+1,flush=True)
    if key=='BASE':
        baseline=json.loads((A/'b6/m3.json').read_text())
        for c,b in zip(out['cases'],baseline['cases']):assert all(c[p]==b[p] for p in ('bm25','dense','hybrid')),'BASE drift'
    out['status']='COMPLETE';guard();save(target,out);print('COMPLETE',key,flush=True)
if __name__=='__main__':run(sys.argv[1])
