"""Prepare B4 public model assets and frozen corpus; never query TEST."""
import os
os.environ.update(ANONYMIZED_TELEMETRY="false",HF_HUB_DISABLE_TELEMETRY="1",HF_HUB_DISABLE_XET="1",LLM_API_KEY="")
import json,hashlib,shutil,sys,types,time,urllib.request
from pathlib import Path
R=Path("/workspace");A=R/"artifacts/evaluation_v2/b4";A.mkdir(parents=True,exist_ok=True)
B=R/"benchmarks/real_research/v2"
models=[("zh","BAAI/bge-small-zh-v1.5","7999e1d3359715c523056ef9478215996d62a620",512,512,"为这个句子生成表示以用于检索相关文章："),
        ("en","BAAI/bge-small-en-v1.5","5c38ec7c405ec4b44b94cc5a9bb96e735b38267a",384,512,"Represent this sentence for searching relevant passages: "),
        ("m3","BAAI/bge-m3","5617a9f61b028005a4858fdac845db406aefb181",1024,8192,"")]
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def save(p,v):p.write_text(json.dumps(v,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
if sys.argv[1]=="corpus":
 import chromadb
 from chromadb.config import Settings
 pkg=types.ModuleType("app.services.evaluation");pkg.__path__=[str(R/"backend/app/services/evaluation")];sys.modules["app.services.evaluation"]=pkg
 from app.services.evaluation.ann_exactness import vector_fingerprint
 import numpy as np
 prior=json.loads((R/"artifacts/evaluation_v2/b3_query_instruction.json").read_text());manifest=prior["identity"]
 for name,digest in prior["protected_hashes"].items():assert sha(R/name)==digest
 src=R/manifest["snapshot_path"];dst=R/".tmp/v2b4/source"
 assert not dst.exists(),"source_copy_already_exists"
 shutil.copytree(src,dst)
 client=chromadb.PersistentClient(path=str(dst),settings=Settings(anonymized_telemetry=False))
 c=client.get_collection(prior["collection_name"],embedding_function=None)
 d=c.get(include=["embeddings","metadatas","documents"])
 assert c.count()==3837 and vector_fingerprint(d["ids"],d["embeddings"])==manifest["identity"]["vector_fingerprint"]
 records={sid:{"metadata":d["metadatas"][i],"document":d["documents"][i]} for i,sid in enumerate(d["ids"])}
 assert hashlib.sha256(json.dumps(records,sort_keys=True).encode()).hexdigest()==manifest["metadata_text_hash"]
 corpus=json.loads((B/"corpus_manifest.json").read_text());versions={x["document_id"]:x["document_version_id"] for x in corpus["documents"]}
 for sid,row in records.items():
  m=row["metadata"];assert versions[m["document_id"]]==m["document_version_id"],sid
 ordered=sorted(records)
 save(A/"corpus.json",{"ids":ordered,"rows":[records[x] for x in ordered],"manifest":manifest,"collection_name":c.name,
      "collection_metadata":c.metadata,"authority":"Frozen MySQL-authoritative B1/B2 corpus export; all immutable document/version memberships checked against frozen corpus manifest","source_copy":str(dst.relative_to(R))})
 mapping=dict(zip(d["ids"],d["embeddings"]))
 np.savez(A/"baseline_document_vectors.npz",vectors=np.asarray([mapping[s] for s in ordered],dtype=np.float32))
 print("CORPUS PREPARED",len(ordered),"metadata_keys",list(records[ordered[0]]["metadata"]),flush=True)
else:
 from huggingface_hub import snapshot_download
 for key,model,rev,dim,maxlen,prefix in models:
  if key=="zh":continue
  root=A/"contracts"/key;root.mkdir(parents=True,exist_ok=True)
  if (root/"download.json").exists():
   print("MODEL ALREADY READY",key,flush=True);continue
  for file in ["README.md","config.json","sentence_bert_config.json","modules.json","1_Pooling/config.json"]:
   target=root/file.replace("/","_")
   if target.exists():continue
   url=f"https://huggingface.co/{model}/resolve/{rev}/{file}"
   with urllib.request.urlopen(url,timeout=90) as response:target.write_bytes(response.read())
  pool=json.loads((root/"1_Pooling_config.json").read_text())
  length=json.loads((root/"sentence_bert_config.json").read_text())
  assert pool["pooling_mode_cls_token"] and not pool["pooling_mode_mean_tokens"] and pool["word_embedding_dimension"]==dim
  assert length["max_seq_length"]==maxlen
  card=(root/"README.md").read_text()
  assert (prefix.strip() in card) if prefix else ("no longer requires adding instructions" in card)
  save(root/"contract.json",dict(model=model,revision=rev,dimension=dim,pooling="CLS",normalization=True,max_length=maxlen,
       query_instruction=prefix,document_instruction="",license="MIT",source=f"https://huggingface.co/{model}/blob/{rev}/README.md",
       source_hashes={name:sha(root/name) for name in ["README.md","config.json","sentence_bert_config.json","modules.json","1_Pooling_config.json"]}))
  print("OFFICIAL CONTRACT VERIFIED",key,rev,flush=True)
  weights="pytorch_model.bin" if key=="m3" else "model.safetensors"
  start=time.time()
  path=snapshot_download(model,revision=rev,cache_dir="/models/model_cache",
       allow_patterns=["*.json","*.txt","*.model","1_Pooling/*","2_Normalize/*",weights],
       max_workers=2,token=False)
  save(root/"download.json",{"model":model,"revision":rev,"duration_seconds":time.time()-start,"snapshot":path,
       "disk_bytes":sum(p.stat().st_size for p in Path(path).rglob("*") if p.is_file())})
  print("MODEL READY",key,flush=True)

