import os,sys,json,hashlib,shutil,inspect,sqlite3
os.environ['ANONYMIZED_TELEMETRY']='false'
from pathlib import Path
import numpy as np
import chromadb
from chromadb.config import Settings
from chromadb.segment import VectorReader
from chromadb.segment.impl.vector.batch import Batch
from chromadb.segment.impl.vector.local_hnsw import LocalHnswSegment
# Original Chroma image has no application SQL dependencies; load only pure audit modules.
import types
pkg=types.ModuleType('app.services.evaluation');pkg.__path__=['/workspace/backend/app/services/evaluation'];sys.modules['app.services.evaluation']=pkg
from app.services.evaluation.ann_exactness import vector_fingerprint
from app.services.evaluation.ann_reproducibility import persist_experimental_graph
R=Path('/workspace');T=R/'.tmp/v2b21';e=json.loads((R/'.tmp/v2b2/export.json').read_text());z=np.load(R/'.tmp/v2b2/vectors.npz')
name,mode=sys.argv[1:3];path=T/name
if mode!='reload':
 assert not path.exists();shutil.copytree('/baseline',path)
files=lambda:{str(p.relative_to(path)):hashlib.sha256(p.read_bytes()).hexdigest() for p in path.rglob('*') if p.is_file()}
before=files()
c=chromadb.PersistentClient(path=str(path),settings=Settings(anonymized_telemetry=False));co=c.get_collection(e['collection'],embedding_function=None)
stored=co.get(include=['embeddings','metadatas','documents']);assert vector_fingerprint(stored['ids'],stored['embeddings'])==e['identity']['vector_fingerprint']
meta={sid:{'metadata':stored['metadatas'][i],'document':stored['documents'][i]} for i,sid in enumerate(stored['ids'])};metahash=hashlib.sha256(json.dumps(meta,sort_keys=True).encode()).hexdigest()
co.query(query_embeddings=[z['query_vectors'][0].tolist()],n_results=200,include=['distances'])
seg=c._server._manager.get_segment(co.id,VectorReader);assert seg._index.ef==10
seq=sorted(seg._id_to_label,key=seg._id_to_label.get);r={'name':name,'mode':mode,'seed':os.environ.get('PYTHONHASHSEED','RANDOM'),'runtime_params':vars(seg._params),'effective_ef':seg._index.ef,'vector_fingerprint':e['identity']['vector_fingerprint'],'metadata_text_hash':metahash,'collection_id':str(co.id),'collection_name':co.name,'collection_metadata':co.metadata,'count':co.count(),'label_count':len(seq),'insertion_sequence':seq,'sequence_hash':hashlib.sha256(json.dumps(seq).encode()).hexdigest(),'pending_ids':[record['record']['id'] for record in seg._curr_batch._ids_to_records.values()],'runtime_max_seq_id':seg._max_seq_id,'files_before':before,'sources':{'Batch':inspect.getsource(Batch),'apply_batch':inspect.getsource(LocalHnswSegment._apply_batch)},'queries':[]}
for q,v in zip(e['queries'],z['query_vectors']):
 result=co.query(query_embeddings=[v.tolist()],n_results=200,include=['distances']);ids=result['ids'][0]
 r['queries'].append({'query_id':q['query_id'],'ids':ids,'distances':result['distances'][0],'matches_original':{str(k):ids[:k]==e['baseline_ranking']['global'][q['query_id']][:k] for k in [10,20,50,100,200]}})
if mode=='capture':
 r['capture_checkpoint']=persist_experimental_graph(seg,path,T)
 r['same_runtime_graph_after_capture']=seq==sorted(seg._id_to_label,key=seg._id_to_label.get)
 for q,v,old in zip(e['queries'],z['query_vectors'],r['queries']):
  assert co.query(query_embeddings=[v.tolist()],n_results=200,include=['distances'])['ids'][0]==old['ids'],'capture_changed_ranking'
r['files_after']=files();out=T/(name+'-'+mode+'.json');out.write_text(json.dumps(r,indent=2,default=str));print('DONE',name,mode,'labels',r['label_count'],'pending',len(r['pending_ids']),'hash',r['sequence_hash'],'original_agreement',{str(k):sum(q['matches_original'][str(k)] for q in r['queries']) for k in [10,20,50,100,200]},flush=True)
