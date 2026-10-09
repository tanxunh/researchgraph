"""Frozen DEV-only B4, one model per process. Offline, isolated indices, resumable corpus encoding."""
import os
os.environ.update(LLM_API_KEY="",GRAPH_EXTRACTION_ENABLED="false",HF_HUB_OFFLINE="1",
 TRANSFORMERS_OFFLINE="1",ANONYMIZED_TELEMETRY="false",HF_HUB_DISABLE_TELEMETRY="1")
import sys,types,json,hashlib,time,shutil,random,statistics,resource
from pathlib import Path
from importlib.metadata import version
import numpy as np
R=Path(__file__).resolve().parents[2];A=R/"artifacts/evaluation_v2/b4";B=R/"benchmarks/real_research/v2"
pkg=types.ModuleType("app.services.evaluation");pkg.__path__=[str(R/"backend/app/services/evaluation")];sys.modules["app.services.evaluation"]=pkg
from app.services.evaluation.embedding_comparison import CONFIGS,validate_vectors,validate_payload,ann_diagnostic
from app.services.evaluation.query_instruction import fingerprint,summary
from app.services.evaluation.ann_exactness import exact_order,vector_fingerprint,percentile
from app.services.evaluation.ann_reproducibility import persist_experimental_graph

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def save(p,v):
 tmp=p.with_suffix(".tmp");tmp.write_text(json.dumps(v,ensure_ascii=False,indent=2)+"\n",encoding="utf-8");tmp.replace(p)
def rss():
 return int(next(l.split()[1] for l in Path("/proc/self/status").read_text().splitlines() if l.startswith("VmRSS:")))*1024
def size(p):return sum(f.stat().st_size for f in p.rglob("*") if f.is_file())
def run(key):
 cfg=CONFIGS[key];target=A/f"{key}.json"
 assert not target.exists(),"completed_or_stopped_result_exists"
 prior=json.loads((R/"artifacts/evaluation_v2/b3_query_instruction.json").read_text())
 source=json.loads((A/"corpus.json").read_text());ids=source["ids"];rows=source["rows"];assert len(ids)==3837
 frozen=json.loads((B/"results/dev_baseline_frozen_gold.json").read_text())
 identity=cfg.identity(source["manifest"]["identity"]["corpus_hash"],frozen["metadata"]["chunking"])
 fp=fingerprint(identity);namespace=f"v2b4-{key}-{fp[:16]}";index_dir=R/".tmp/v2b4"/namespace
 protected={**prior["protected_hashes"],"artifacts/evaluation_v2/b4/corpus.json":sha(A/"corpus.json")}
 def guard():
  for name,digest in protected.items():assert sha(R/name)==digest,name
  for name,digest in source["manifest"]["graph_hashes"].items():assert sha(R/source["manifest"]["snapshot_path"]/name)==digest,name
  assert sha(B/"corpus_manifest.json")==identity["corpus_manifest_hash"]
 guard()
 queries=[json.loads(l) for l in (B/"queries_dev.jsonl").read_text().splitlines() if l.strip()];assert len(queries)==35
 expected_source={sid:row for sid,row in zip(ids,rows)}
 report={"status":"RUNNING","key":key,"config":identity,"config_fingerprint":fp,"index_namespace":namespace,
  "protected_hashes":protected,"official_source":f"https://huggingface.co/{cfg.model}/blob/{cfg.revision}/README.md",
  "protocol":{"rounds":3,"warmup_per_track":35,"cpu_threads":4,"corpus_batch_size":cfg.batch_size,
  "latency":"Contiguous local Dense query: query encoding + Chroma query + frozen-authority membership/metadata validation. Excludes HTTP and live MySQL roundtrip; model/index load excluded.",
  "authority":"B1/B2 immutable authoritative corpus snapshot, checked against frozen corpus manifest; same membership/locator/text for every model.",
  "exact":"Exhaustive float64 dot ordering on stored normalized vectors; cosine ordering also checked. No near-tie adjustment.",
  "build":"Same HNSW M16/construction_ef100/search_ef10/num_threads16/batch100/sync1000. Frozen sorted insertion order for new models; baseline is an isolated copy of its verified graph."}}
 save(A/f"{key}.progress.json",report)
 import torch,chromadb
 from sentence_transformers import SentenceTransformer
 from chromadb.config import Settings
 from chromadb.segment import VectorReader
 torch.set_num_threads(4);torch.set_num_interop_threads(1)
 assert chromadb.__version__=="0.5.23" and version("chroma-hnswlib")=="0.7.6"
 start=time.perf_counter()
 model=SentenceTransformer(cfg.model,revision=cfg.revision,device="cpu",cache_folder="/models/model_cache",local_files_only=True)
 report["model_load_sec"]=time.perf_counter()-start;report["rss_after_load_bytes"]=rss()
 assert model[0].auto_model.config._commit_hash==cfg.revision,"wrong_model_revision"
 assert model.get_sentence_embedding_dimension()==cfg.dimension and model.max_seq_length==cfg.max_length,"wrong_model_contract"
 assert model[1].pooling_mode_cls_token and not model[1].pooling_mode_mean_tokens and model[2].__class__.__name__=="Normalize","wrong_pooling"
 assert model.default_prompt_name is None and not model.prompts
 report["parameter_count"]=sum(p.numel() for p in model.parameters())
 snap=Path("/models/model_cache")/("models--"+cfg.model.replace("/","--"))/"snapshots"/cfg.revision
 report["model_snapshot_bytes"]=size(snap)
 report["runtime"]={"chromadb":chromadb.__version__,**{p:version(p) for p in ("torch","transformers","sentence-transformers","chroma-hnswlib","numpy")}}
 print("MODEL LOADED",key,report["parameter_count"],report["rss_after_load_bytes"],flush=True)
 texts=[cfg.text(row["document"],False) for row in rows]
 lengths=[len(x) for x in model.tokenizer(texts,truncation=False,padding=False)["input_ids"]]
 report["document_tokens"]={"max":max(lengths),"truncated":sum(n>cfg.max_length for n in lengths),"max_length":cfg.max_length}
 # Checkpoint each 256 chunks; resume completed encoding shards without seed/model changes.
 shard_dir=A/f"{key}_encoding";shard_dir.mkdir(exist_ok=True);parts=[];seconds=0;peak=rss()
 for offset in range(0,len(ids),256):
  stem=shard_dir/str(offset);npfile=stem.with_suffix(".npy");meta=stem.with_suffix(".json")
  if npfile.exists() and meta.exists():
   info=json.loads(meta.read_text());assert info["config_fingerprint"]==fp and info["sha256"]==sha(npfile)
   v=np.load(npfile);elapsed=info["seconds"]
  else:
   t=time.perf_counter();v=model.encode(texts[offset:offset+256],batch_size=cfg.batch_size,normalize_embeddings=True,show_progress_bar=False)
   elapsed=time.perf_counter()-t
   validate_vectors(ids[offset:offset+256],v,ids[offset:offset+256],cfg.dimension)
   np.save(npfile,v);save(meta,{"config_fingerprint":fp,"sha256":sha(npfile),"seconds":elapsed})
  parts.append(v);seconds+=elapsed;peak=max(peak,rss())
  report.update(index_encode_sec=seconds,encoded_chunks=min(offset+256,len(ids)),rss_sampled_peak_encoding_bytes=peak)
  save(A/f"{key}.progress.json",report);print("ENCODED",key,report["encoded_chunks"],flush=True)
 fresh=np.concatenate(parts);report["process_peak_rss_through_encoding_bytes"]=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024
 # Use the unchanged baseline graph/vectors; full baseline encoding above measures cost and verifies compatibility.
 vectors=fresh
 if key=="zh":
  vectors=np.load(A/"baseline_document_vectors.npz")["vectors"]
  assert np.allclose(fresh,vectors,atol=1e-5),"baseline_document_vector_mismatch"
  report["baseline_fresh_max_abs_error"]=float(np.max(np.abs(fresh-vectors)))
 report["vector_validation"]=validate_vectors(ids,vectors,ids,cfg.dimension)
 qtexts=[cfg.text(q["query"],True) for q in queries]
 original_tokenize=model.tokenize;observed=[]
 def capture(v,*args,**kwargs):
  observed.extend(v);return original_tokenize(v,*args,**kwargs)
 model.tokenize=capture
 qvectors=model.encode(qtexts,batch_size=1,normalize_embeddings=True,show_progress_bar=False)
 model.tokenize=original_tokenize
 assert sorted(observed)==sorted(qtexts),"prefix_not_in_tokenizer"
 assert np.allclose(np.linalg.norm(qvectors,axis=1),1,atol=1e-5)
 report["query_samples"]=[{"query_id":q["query_id"],"raw_query":q["query"],"encoded_query":text,
   "token_count":len(model.tokenizer(text,truncation=False)["input_ids"]),"dimension":len(v),"norm":float(np.linalg.norm(v))}
   for q,text,v in zip(queries,qtexts,qvectors)]
 np.savez(A/f"{key}_vectors.npz",vectors=vectors,query_vectors=qvectors,ids=np.array(ids))
 report["document_vector_fingerprint"]=vector_fingerprint(ids,vectors)
 report["query_vector_fingerprint"]=vector_fingerprint([q["query_id"] for q in queries],qvectors)
 metadata=[dict(row["metadata"]) for row in rows]
 if key!="zh":
  for m in metadata:m.update(embedding_model=cfg.model,embedding_dimension=cfg.dimension,embedding_provider="bge",embedding_version=namespace)
 expected={sid:{"metadata":m,"document":row["document"]} for sid,m,row in zip(ids,metadata,rows)}
 assert not index_dir.exists(),"index_already_exists_no_rebuild"
 t=time.perf_counter()
 if key=="zh":shutil.copytree(R/source["source_copy"],index_dir)
 client=chromadb.PersistentClient(path=str(index_dir),settings=Settings(anonymized_telemetry=False))
 if key=="zh":coll=client.get_collection(source["collection_name"],embedding_function=None)
 else:
  coll=client.create_collection(namespace,embedding_function=None,metadata={"hnsw:space":"l2","hnsw:M":16,
   "hnsw:construction_ef":100,"hnsw:search_ef":10,"hnsw:num_threads":16,"hnsw:batch_size":100,"hnsw:sync_threshold":1000})
  for offset in range(0,len(ids),100):
   coll.add(ids=ids[offset:offset+100],embeddings=vectors[offset:offset+100].tolist(),
      metadatas=metadata[offset:offset+100],documents=[r["document"] for r in rows[offset:offset+100]])
 report["index_build_sec"]=time.perf_counter()-t
 report["index_build_kind"]="existing_graph_copy" if key=="zh" else "new_chroma_index"
 stored=coll.get(include=["embeddings","metadatas","documents"])
 validate_vectors(stored["ids"],stored["embeddings"],ids,cfg.dimension)
 validate_payload(stored["ids"],stored["metadatas"],stored["documents"],expected)
 assert vector_fingerprint(stored["ids"],stored["embeddings"])==report["document_vector_fingerprint"],"stored_vector_mismatch"
 indices=sorted(random.Random(20260930).sample(range(len(ids)),3))
 sample=model.encode([texts[i] for i in indices],batch_size=cfg.batch_size,normalize_embeddings=True,show_progress_bar=False)
 report["fresh_reencode_checks"]=[]
 for j,i in enumerate(indices):
  err=float(np.max(np.abs(sample[j]-vectors[i])));assert np.allclose(sample[j],vectors[i],atol=1e-5),"fresh_vector_mismatch"
  report["fresh_reencode_checks"].append({"chunk_id":ids[i],"max_abs_error":err})
 qlists=qvectors.tolist()
 def search(v,q,track):
  kw={} if track=="global" else {"where":{"document_id":{"$in":q["document_scope"]}}}
  got=coll.query(query_embeddings=[v],n_results=200,include=["distances","metadatas"],**kw)
  for sid,m in zip(got["ids"][0],got["metadatas"][0]):
   assert sid in expected and m==expected[sid]["metadata"],"authority_rejection"
   if track=="scoped":assert m["document_id"] in q["document_scope"],"scope_violation"
  return got["ids"][0]
 search(qlists[0],queries[0],"global")
 segment=client._server._manager.get_segment(coll.id,VectorReader)
 assert segment._index.ef==10 and segment._params.M==16 and segment._params.construction_ef==100
 if key!="zh":persist_experimental_graph(segment,index_dir,R/".tmp/v2b4")
 report.update(index_size_bytes=size(index_dir),collection_id=str(coll.id),collection_name=coll.name)
 docs=np.array([m["document_id"] for m in metadata]);id_array=np.array(ids);cases={}
 for track in ("global","scoped"):
  cases[track]=[]
  for i,q in enumerate(queries):
   mask=np.ones(len(ids),dtype=bool) if track=="global" else np.isin(docs,q["document_scope"])
   exact=exact_order(id_array[mask].tolist(),vectors[mask],qvectors[i])
   cosine=exact_order(id_array[mask].tolist(),vectors[mask],qvectors[i],"cosine")
   ranked=search(qlists[i],q,track)
   cases[track].append({"query_id":q["query_id"],"query_type":q["query_type"],"ids":ranked,
     "exact":exact,"gold":[g["chunk_id"] for g in q["gold_evidence"]],
     "dot_cosine_top100_equal":exact[:100]==cosine[:100],"latency_ms":[],"encode_ms":[],"search_ms":[]})
  print("ANN CHECK",key,track,flush=True)
 report["ann_fidelity"]={tr:ann_diagnostic(cs) for tr,cs in cases.items()}
 report["cases"]=cases
 if any(x["ann_confound"] for x in report["ann_fidelity"].values()):
  report["status"]="ANN_CONFUND";guard();save(target,report)
  print("STOP: ANN CONFUND",key,json.dumps(report["ann_fidelity"]),flush=True);return 17
 # Full encode+search warmup, model/index load and exact diagnostics excluded from timing.
 for track in cases:
  for i,q in enumerate(queries):
   v=model.encode([qtexts[i]],normalize_embeddings=True,show_progress_bar=False)[0]
   search(v.tolist(),q,track)
 for repeat in range(3):
  for track in ("global","scoped") if repeat%2==0 else ("scoped","global"):
   for i,q in enumerate(queries):
    start=time.perf_counter_ns()
    v=model.encode([qtexts[i]],normalize_embeddings=True,show_progress_bar=False)[0]
    encoded=time.perf_counter_ns()
    ranked=search(v.tolist(),q,track)
    ended=time.perf_counter_ns()
    row=cases[track][i]
    assert np.allclose(v,qvectors[i],atol=1e-5),"query_vector_mismatch"
    # Record harmless batch-vs-single precision ordering differences instead of silently changing metric ranks.
    assert ranked==row["ids"], "single_query_ranking_changed"
    row.setdefault("single_query_top50_equal",[]).append(True)
    row["latency_ms"].append((ended-start)/1e6);row["encode_ms"].append((encoded-start)/1e6);row["search_ms"].append((ended-encoded)/1e6)
   print("TIMED",key,repeat+1,track,flush=True)
  save(A/f"{key}.progress.json",report)
 tracks={}
 for track,cs in cases.items():
  overall=summary(cs);by={ty:summary([c for c in cs if c["query_type"]==ty]) for ty in sorted({c["query_type"] for c in cs})}
  timing={}
  for field in ("encode_ms","search_ms","latency_ms"):
   values=[v for c in cs for v in c[field]]
   timing[field]={"p50":percentile(values,.5),"p95":percentile(values,.95),"n":len(values)}
  tracks[track]={"overall":overall,"by_type":by,"latency":timing}
 after=coll.get(include=["embeddings"]);assert vector_fingerprint(after["ids"],after["embeddings"])==report["document_vector_fingerprint"]
 guard()
 report.update(status="COMPLETE",tracks=tracks,peak_process_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024,
  integrity={"DEV_frozen":True,"TEST_hash_only":True,"TEST_ranking_read":False,"TEST_run":False,"Gold_unchanged":True,
  "chunking_unchanged":True,"production_unchanged":True,"reranker_run":False,"LLM_calls":0},
  baseline_top50_agreement=sum(c["ids"][:50]==b["ids"][:50] for c,b in zip(cases["global"],prior["experiments"][1]["cases"]["global"])) if key=="zh" else None)
 save(target,report);print("B4 COMPLETE",key,json.dumps(tracks["global"]["overall"]),flush=True)
 return 0
if __name__=="__main__":
 key=sys.argv[1]
 try:sys.exit(run(key))
 except Exception as exc:
  save(A/f"{key}.failure-{time.time_ns()}.json",{"status":"FAILED","type":type(exc).__name__,"error":str(exc)})
  raise

