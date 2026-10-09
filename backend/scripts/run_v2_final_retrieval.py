"""V2-F: one frozen DEV reproduction followed by one explicitly locked TEST run."""
from __future__ import annotations
import os
os.environ.update(LLM_API_KEY='',GRAPH_EXTRACTION_ENABLED='false',HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',ANONYMIZED_TELEMETRY='false')
import argparse,collections,datetime,hashlib,json,math,shutil,statistics,sys,tempfile,time,types
from pathlib import Path
from types import SimpleNamespace
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'backend'))
pkg=types.ModuleType('app.services.evaluation');pkg.__path__=[str(ROOT/'backend/app/services/evaluation')];sys.modules['app.services.evaluation']=pkg
from app.services.evaluation.chunking_ablation import score_portable
from app.services.evaluation.chunking_freeze import corpus_identities,canonical_hash
from app.services.evaluation.fusion_optimization import weighted_rrf
B=Path('benchmarks/real_research/v2');F=Path('artifacts/evaluation_v2/f')
FINAL=('Hit@5','R@5','R@10','MRR@10');ALL=FINAL+('CR@20','CR@30','CR@50')
def now():return datetime.datetime.now(datetime.timezone.utc).isoformat()
def read(p):return json.loads((ROOT/p).read_text(encoding='utf-8'))
def sha(p):
 h=hashlib.sha256()
 with (ROOT/p).open('rb') as f:
  for x in iter(lambda:f.read(1024*1024),b''):h.update(x)
 return h.hexdigest()
def write(p,d):
 p=ROOT/p;p.parent.mkdir(parents=True,exist_ok=True);tmp=p.with_suffix(p.suffix+'.tmp');tmp.write_text(json.dumps(d,sort_keys=True,ensure_ascii=False,indent=2)+'\n',encoding='utf-8');tmp.replace(p)
def queries(split):return [json.loads(x) for x in (ROOT/B/('queries_'+split+'.jsonl')).read_text(encoding='utf-8').splitlines() if x.strip()]
def corpus():return {c['chunk_id']:c for c in read('artifacts/evaluation_v2/c1/BASE_corpus.json')['chunks']}
def verify():
 p=read(F/'protocol.json')
 for name,h in p['protected_hashes'].items():assert sha(name)==h,name
 return p

def evaluate(cases,mapping):
 result={}
 for route in ('bm25','dense','hybrid','reranked'):
  keys=FINAL if route=='reranked' else ALL
  per={c['query_id']:{k:v for k,v in score_portable(c[route],mapping,c['query_id']).items() if k in keys} for c in cases}
  counts={str(k):sum(bool(set(ids)&set(c[route][:k])) for c in cases for g,ids in mapping.items() if g.startswith(c['query_id']+':')) for k in ((5,10) if route=='reranked' else (5,10,20,30,50))}
  result[route]={'metrics':{k:statistics.mean(v[k] for v in per.values()) for k in keys},'per_query':per,'Gold_hit_counts':counts,'n':len(cases)}
 return result

def exclusive_lock(path,data):
 p=ROOT/path;p.parent.mkdir(parents=True,exist_ok=True)
 with p.open('x',encoding='utf-8') as f:json.dump(data,f,sort_keys=True,indent=2);f.write('\n')

def prepare():
 assert not (ROOT/F/'protocol.json').exists(),'F protocol exists'
 e=read('artifacts/evaluation_v2/e/summary.json');assert e['status']=='COMPLETE' and e['tests']['failed']==0
 protected=e['protected_hashes'].copy()
 for n in ['final_chunking_config.json','final_dense_config.json','final_fusion_config.json','final_reranker_config.json','split_manifest.json']:
  protected[str(B/n)]=sha(B/n)
 for p in (ROOT/'artifacts/evaluation_v2/e').glob('*.json'):protected[str(p.relative_to(ROOT)).replace('\\','/')]=sha(p)
 for p in ['backend/scripts/run_v2_final_retrieval.py','backend/app/services/indexing/bm25_index.py','backend/app/services/evaluation/fusion_optimization.py','backend/app/services/retrieval/reranker.py','artifacts/evaluation_v2/c1/BASE_retrieval.json','artifacts/evaluation_v2/d/fused_rankings.json','artifacts/evaluation_v2/b6/m3.json','artifacts/evaluation_v2/b4/corpus.json']:
  protected[p]=sha(p)
 cfg=read(B/'final_dense_config.json');index=ROOT/cfg['index_path'];indexhash={str(p.relative_to(ROOT)).replace('\\','/'):sha(p) for p in index.rglob('*') if p.is_file()};protected.update(indexhash)
 frozen={'final_chunking_config.json':'008845cdc4c45d8921173138d8b8591fa06d85e44082a5d73627801be3887079','final_fusion_config.json':'f1707c358cadd7ceb162119811976ecfa1ea57fe6f40588bbd7a55b479c24360','final_reranker_config.json':'5c800c65a9cf9b5549d81023a9467e58a15b75389d482d1e04f5aba8c01e6870'}
 for n,h in frozen.items():assert sha(B/n)==h
 chunks=corpus();docs=read('artifacts/evaluation_v2/c0/source_reconstruction.json')['documents'];ident=corpus_identities(list(chunks.values()),docs);cc=read(B/'final_chunking_config.json')
 for k,v in ident.items():assert cc[k]==v,k
 src=read('artifacts/evaluation_v2/b4/corpus.json');rows=dict(zip(src['ids'],src['rows']))
 assert set(rows)==set(chunks)
 for cid,c in chunks.items():
  row=rows[cid];assert c['text']==row['document']
  for k in ('document_id','document_version_id'):assert c[k]==row['metadata'][k]
 bmidentity=canonical_hash(sorted([[sid,r['metadata']['document_chunk_id'],hashlib.sha256(r['document'].encode()).hexdigest()] for sid,r in rows.items()]))
 protocol={'status':'PREDECLARED','created_at':now(),'protected_hashes':protected,'dense_index_files':indexhash,'corpus_identity':ident,'bm25_index_identity':bmidentity,'bm25_index_contract':'unchanged production BM25Index over immutable B6 authority rows sorted by occurrence ID; same tokenization k1=1.5 b=.75 stable ties; global scope','DEV_runs':1,'TEST_runs':1,'TEST_warmup':False,'warmup':'one saved DEV query only, before timed DEV; TEST uses no TEST warmup','query_scope':'global corpus, as B6/D/E; document_scope is annotation provenance, not retrieval filtering','latency_boundary':'local sequential BM25 + M3 query encode + copied frozen Chroma query + authority validation + weighted RRF + base reranker; excludes HTTP/SQL/network/cold model load, checkpoint writes and scoring','test_gold_rule':'frozen exact BASE chunk locators; no portable remap or semantic changes','dev_gold_rule':'55 approved minimal spans, existing 100%-containment mapping','comparability_note':'DEV and TEST Gold annotation granularity differs; direct deltas are descriptive, not a controlled estimate of optimization gain','error_precedence':['NOT_IN_HYBRID_TOP20','DEMOTED_BY_RERANKER','IN_TOP20_RERANKER_FAILED_TO_PROMOTE','OTHER_VALID_EVALUATION_MISS'],'lower_than_top10_note':'GOLD_PRESENT_LOWER_THAN_TOP10 is a secondary nonexclusive flag for hybrid rank >10; otherwise overlaps A/B/C','descriptive_delta_guidance':'before TEST: largest final R10/R5/Hit5 absolute drop <.05 and MRR drop <.05 -> STABLE; <=.15 on all -> MODERATE DROP; else LARGE DROP. Not a pass/fail gate; explain mixed metric directions, sample sizes and label granularity. STRONG/ACCEPTABLE/WEAK remain descriptive only.'}
 write(F/'protocol.json',protocol);verify();print('F protocol prepared; TEST records not read',flush=True)

class Pipeline:
 def __init__(self):
  from app.services.indexing.bm25_index import BM25Index
  from app.services.retrieval.reranker import CrossEncoderReranker
  from app.services.evaluation.ann_exactness import vector_fingerprint
  import torch,numpy as np,chromadb
  from sentence_transformers import SentenceTransformer
  from chromadb.config import Settings
  torch.set_num_threads(4);torch.set_num_interop_threads(1);torch.use_deterministic_algorithms(True)
  cfg=read(B/'final_dense_config.json');self.cfg=cfg;src=read('artifacts/evaluation_v2/b4/corpus.json');self.rows=dict(zip(src['ids'],src['rows']));self.occ={sid:r['metadata']['document_chunk_id'] for sid,r in self.rows.items()}
  chunks=sorted([SimpleNamespace(id=self.occ[sid],stable_chunk_id=sid,text=r['document']) for sid,r in self.rows.items()],key=lambda c:c.id)
  class SnapshotSession:
   def scalars(self,stmt):return SimpleNamespace(all=lambda:chunks)
  self.bm=BM25Index(SnapshotSession())
  self.copy=Path(tempfile.mkdtemp(prefix='v2-f-frozen-index-'))/'index';shutil.copytree(ROOT/cfg['index_path'],self.copy)
  self.client=chromadb.PersistentClient(path=str(self.copy),settings=Settings(anonymized_telemetry=False));self.coll=self.client.get_collection(cfg['collection_name'],embedding_function=None)
  stored=self.coll.get(include=['embeddings']);assert vector_fingerprint(stored['ids'],stored['embeddings'])==cfg['document_vector_fingerprint']
  assert self.coll.count()==3837
  self.model=SentenceTransformer(cfg['model'],revision=cfg['revision'],device='cpu',cache_folder='/models/model_cache',local_files_only=True)
  assert self.model.max_seq_length==8192 and self.model[0].auto_model.config._commit_hash==cfg['revision']
  assert self.model[1].pooling_mode_cls_token and not self.model[1].pooling_mode_mean_tokens
  rc=read(B/'final_reranker_config.json');self.scorer=CrossEncoderReranker(rc['model'],rc['revision'],'cpu','/models/model_cache',True);self.scorer.load();assert self.scorer.model.model.config._commit_hash==rc['revision']
  self.audit={'dense_model':cfg['model'],'dense_revision':cfg['revision'],'dense_vector_fingerprint':cfg['document_vector_fingerprint'],'collection_metadata':self.coll.metadata,'torch':torch.__version__,'numpy':np.__version__,'chroma':chromadb.__version__,'reranker_revision':rc['revision'],'reranker_max_length':self.scorer.model.max_length,'dtype':str(next(self.scorer.model.model.parameters()).dtype),'pooling':'CLS','normalization':True,'threads':torch.get_num_threads(),'query_strategy':'RAW','document_strategy':'RAW'}
 def run(self,q):
  from app.services.retrieval.reranker import rerank_candidates
  import numpy as np
  start=time.perf_counter();bh=self.bm.search(q['query'],200);bt=time.perf_counter();bm=[h.stable_chunk_id for h in bh]
  vector=self.model.encode([q['query']],normalize_embeddings=True,show_progress_bar=False)[0];et=time.perf_counter();assert vector.shape==(1024,) and np.isfinite(vector).all() and abs(np.linalg.norm(vector)-1)<1e-5
  got=self.coll.query(query_embeddings=[vector.tolist()],n_results=200,include=['metadatas','distances']);dense=got['ids'][0]
  for sid,meta in zip(dense,got['metadatas'][0]):
   expected=dict(self.rows[sid]['metadata']);expected.update(embedding_model=self.cfg['model'],embedding_dimension=1024,embedding_provider='bge',embedding_version=self.cfg['index_namespace']);assert meta==expected,'authority identity mismatch'
  assert len(dense)==len(set(dense))==200 and len(set(bm))==len(bm)
  dt=time.perf_counter();hybrid=weighted_rrf(dense,bm,self.occ,1.25,20,100);ft=time.perf_counter()
  pool=[{'chunk_id':sid,'text':self.rows[sid]['document'],'scores':{}} for sid in hybrid[:20]];ordered,meta=rerank_candidates(q['query'],pool,self.scorer);end=time.perf_counter()
  assert not meta['reranker_failed'] and len(ordered)==20 and set(x['chunk_id'] for x in ordered)==set(hybrid[:20])
  return {'query_id':q['query_id'],'query_type':q['query_type'],'bm25':bm,'bm25_scores':[h.score for h in bh],'dense':dense,'dense_distances':got['distances'][0],'query_vector_sha256':hashlib.sha256(vector.astype('<f4').tobytes()).hexdigest(),'hybrid':hybrid,'reranked':[x['chunk_id'] for x in ordered[:10]],'reranked20':[x['chunk_id'] for x in ordered],'reranker_scores':[x['scores']['reranker_score'] for x in ordered],'timings_ms':{'bm25':(bt-start)*1000,'query_encoding':(et-bt)*1000,'dense_search_and_authority':(dt-et)*1000,'retrieval':(dt-start)*1000,'fusion':(ft-dt)*1000,'reranker':(end-ft)*1000,'end_to_end':(end-start)*1000}}

def dev():
 verify();exclusive_lock(F/'dev_execution_lock.json',{'started_at':now(),'attempt':1,'runner_sha256':sha('backend/scripts/run_v2_final_retrieval.py')})
 qs=queries('dev');assert len(qs)==35
 old={c['query_id']:c for c in read('artifacts/evaluation_v2/c1/BASE_retrieval.json')['cases']};fused={c['query_id']:c['hybrid'] for c in read('artifacts/evaluation_v2/d/fused_rankings.json')['bm25-1.25_k-20']};rerank={c['query_id']:c for c in read('artifacts/evaluation_v2/e/base_scores.json')['cases']}
 out={'status':'RUNNING','cases':[],'started_at':now()}
 try:
  pipe=Pipeline();out['runtime_audit']=pipe.audit;pipe.run(qs[0])
  for q in qs:
   row=pipe.run(q);qid=q['query_id'];out['cases'].append(row);write(F/'dev_reproduction.json',out)
   for route in ('bm25','dense'):assert row[route]==old[qid][route],qid+' '+route+' ranking drift'
   assert row['hybrid']==fused[qid],qid+' hybrid ranking drift'
   assert row['reranked20']==rerank[qid]['reranked'],qid+' reranker ranking drift'
   print('DEV',qid,len(out['cases']),'/35',round(row['timings_ms']['end_to_end'],2),'ms',flush=True)
  mapping=read('artifacts/evaluation_v2/c1r/mappings.json')['BASE'];out['metrics']=evaluate(out['cases'],mapping)
  expected=read('artifacts/evaluation_v2/e/summary.json')['configs']['base_a1.00']['metrics'];d=read('artifacts/evaluation_v2/d/summary.json')['configs']['bm25-1.25_k-20']['metrics']
  for k,v in expected.items():assert abs(out['metrics']['reranked']['metrics'][k]-v)<1e-12,k
  for k,v in d.items():
   if k in ALL:assert abs(out['metrics']['hybrid']['metrics'][k]-v)<1e-12,k
  verify();out['status']='PASS';out['completed_at']=now();write(F/'dev_reproduction.json',out);print('FINAL_DEV_REPRODUCTION_PASS',flush=True)
 except Exception as exc:
  out.update(status='FINAL_DEV_REPRODUCTION_FAIL',error=type(exc).__name__,detail=str(exc));write(F/'dev_reproduction.json',out);raise

if __name__=='__main__':
 a=argparse.ArgumentParser();a.add_argument('action',choices=['prepare','dev']);args=a.parse_args();prepare() if args.action=='prepare' else dev()
