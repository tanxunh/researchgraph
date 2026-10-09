"""G1.6 deterministic validation and synthetic-only smoke. Never evaluates TEST."""
import os, sys, json, hashlib, platform, importlib.metadata as md, asyncio
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'backend'))
from v2_g_reconstructed_runtime import FrozenRetrievalAdapter, evaluation_tool_binding, RecordingLLM
B=Path('benchmarks/real_research/v2'); G=Path('artifacts/evaluation_v2/g')
def read(p): return json.loads((ROOT/p).read_text(encoding='utf-8-sig'))
def sha(p):
 h=hashlib.sha256()
 with (ROOT/str(p).replace(chr(92), '/')).open('rb') as f:
  for b in iter(lambda:f.read(1048576),b''):h.update(b)
 return h.hexdigest()
def write(p,d):
 p=ROOT/p;p.parent.mkdir(parents=True,exist_ok=True)
 p.write_text(json.dumps(d,ensure_ascii=False,sort_keys=True,indent=2)+'\n',encoding='utf-8')
def preflight():
 old=read(G/'runtime_audit.json');protected=old['protected_hashes']
 for p,h in read(B/'v2_g_track_b_agent_config.json')['source_hashes'].items():assert sha(p)==h,p
 for p,h in protected.items(): assert sha(p)==h,p
 for name in ['v2_g_generation_config.json','v2_g_runtime_provenance.json']:
  archive=ROOT/G/('g15_original_'+name)
  if not archive.exists():archive.write_bytes((ROOT/B/name).read_bytes())
 import importlib.util
 spec=importlib.util.spec_from_file_location('identity',ROOT/'backend/app/services/evaluation/chunking_freeze.py')
 identity=importlib.util.module_from_spec(spec);spec.loader.exec_module(identity)
 chunks=read('artifacts/evaluation_v2/c1/BASE_corpus.json')['chunks']
 docs=read('artifacts/evaluation_v2/c0/source_reconstruction.json')['documents']
 ident=identity.corpus_identities(chunks,docs);cfg=read(B/'final_chunking_config.json')
 for k,v in ident.items():assert cfg[k]==v,k
 raw=read('artifacts/evaluation_v2/b4/corpus.json');rows=dict(zip(raw['ids'],raw['rows']))
 assert len(rows)==len(chunks)==3837 and len(docs)==30
 for c in chunks:
  row=rows[c['chunk_id']];assert c['text']==row['document']
  for k in ['document_id','document_version_id']:assert c[k]==row['metadata'][k]
 manifest=read(B/'final_retrieval_manifest.json')
 assert sha(B/'final_retrieval_manifest.json')=='bc601f31786987de88a1a9b1851508960332371654bc9d3a81f0e4a8a4f94e7a'
 for p,h in manifest['dense_index_files'].items():assert sha(p)==h
 # Metadata only from prior DEV export; no ranking or Gold is used in selection.
 sources=read('.tmp/v2-baseline/v2a_sources.json')['tracks'];documents={}
 for queries in sources.values():
  for depths in queries.values():
   for routes in depths.values():
    for route in routes.values():
     for row in route.get('rows',[]):
      d=row['document'];key=d['id']
      if key in documents:assert documents[key]==d
      documents[key]=d
 assert set(documents)==set(range(1,31))
 write(G/'reconstructed_document_metadata.json',documents)
 packages={d.metadata['Name']:d.version for d in md.distributions() if d.metadata['Name']}
 snap=dict(python=platform.python_version(),packages=dict(sorted(packages.items())),image='sha256:bf25e5a01aad9e0e4a1acd70734dea0488eee9b23cd7955d19e7b404266b7d9c')
 write(G/'reconstructed_package_snapshot.json',snap)
 audit=dict(status='PREFLIGHT_PASS_SMOKES_PENDING',runtime_type='RECONSTRUCTED_EVALUATION_RUNTIME',
  corpus_compatibility='FULL_MATCH',corpus_documents=30,corpus_chunks=3837,corpus_identity=ident,
  protected_hashes=protected,protected_unchanged=True,benchmark_answers_generated=0,
  package_snapshot_sha256=sha(G/'reconstructed_package_snapshot.json'),
  adapter_sha256=sha('backend/scripts/v2_g_reconstructed_runtime.py'),
  scope_admission='HUMAN_APPROVED: unchanged global Top10, then scope filter and existing max5/12000-character EvidenceBuilder; no backfill',
  generation_lock='PENDING',track_a_lock='PASS',track_b_lock='PENDING')
 previous=read(G/'reconstructed_runtime_audit.json') if (ROOT/G/'reconstructed_runtime_audit.json').exists() else {}
 audit={**previous,**audit}
 write(G/'reconstructed_runtime_audit.json',audit)
 print('PREFLIGHT FULL_MATCH 30 documents / 3837 chunks; protected hashes PASS',flush=True)

async def smoke():
 preflight()
 # The frozen runner clears LLM_API_KEY at import. Credential arrives via stdin only afterward.
 from run_v2_final_retrieval import Pipeline
 from app.core.config import Settings
 from app.core.llm_client import LLMClient
 from app.services.research.workflow import ResearchService
 from app.schemas.research import ResearchTaskRequest
 key=sys.stdin.readline().strip()
 assert key,'Credential missing'
 settings=Settings(_env_file=None,LLM_API_KEY=key,LLM_MODEL='deepseek-chat',
   LLM_BASE_URL='https://api.deepseek.com/v1',GRAPH_EXTRACTION_ENABLED=False)
 client=LLMClient();client.settings=settings
 lock=ROOT/G/'g16_smoke_execution_lock.json'
 with lock.open('x',encoding='utf-8') as f:json.dump({'synthetic_only':True,'no_benchmark_answers':True},f)
 audit=read(G/'reconstructed_runtime_audit.json');audit['LLM_API_KEY_present']=True
 try:
  health=await client.generate('Synthetic runtime health check. Reply with the word READY.')
  write(G/'generation_health_smoke.json',dict(status='PASS',response=health,model='deepseek-chat',synthetic=True))
  audit['generation_lock']='PASS';write(G/'reconstructed_runtime_audit.json',audit)
  print('GENERATION HEALTH PASS',flush=True)
  pipe=Pipeline();documents={int(k):v for k,v in read(G/'reconstructed_document_metadata.json').items()}
  adapter=FrozenRetrievalAdapter(pipe,documents)
  question='Describe computational offloading methods for maritime unmanned aerial vehicles.'
  direct=pipe.run(dict(query_id='SYNTHETIC_HEALTH',query_type='synthetic',query=question))
  translated=adapter.search(question)
  expected=adapter.translate(direct)
  assert translated==expected,'Adapter equivalence failed'
  write(G/'adapter_equivalence.json',dict(status='PASS',query=question,synthetic=True,
    checks=['chunk_ids','order','document_ids','scores','ranks'],direct=expected,adapter=translated))
  print('REAL FROZEN RETRIEVAL + ADAPTER EQUIVALENCE PASS',flush=True)
  recorder=RecordingLLM(client)
  service=ResearchService(adapter,recorder,resolver=adapter.resolve,settings=settings)
  # Fixed synthetic smoke question and document pair, declared before any model output.
  request=ResearchTaskRequest(question='Describe the methods and optimization objectives of maritime UAV computation offloading in documents 2 and 7.',document_ids=[2,7])
  with evaluation_tool_binding():response=await service.run(request)
  write(G/'reconstructed_workflow_smoke.json',dict(status=response.status,response=response.model_dump(mode='json'),
   execution_summary=service.execution_summary.model_dump(mode='json'),model_calls=recorder.calls,
   retrieval_calls=adapter.calls,admissions=adapter.admissions,
   diagnostics=[d.model_dump() for d in service.business_diagnostics],
   final_evidence=[e.model_dump() for e in getattr(service,'final_evidence',[])],
   runtime_type='RECONSTRUCTED_EVALUATION_RUNTIME',track='TRACK_B_R',synthetic=True))
  operations=[json.loads(c['prompt']).get('operation') for c in recorder.calls]
  audit['smoke_workflow_status']=response.status
  audit['planner_executable']='plan' in operations
  audit['synthesis_executable']='synthesize' in operations
  audit['supplemental_retrieval_observed']=response.retry_count>0
  audit['citations_serialized']=bool(response.citations)
  audit['track_b_lock']='PASS' if response.status!='failed' and audit['synthesis_executable'] and response.citations else 'FAIL'
  audit['status']='SMOKES_COMPLETED'
 except Exception as exc:
  audit['status']='SMOKE_FAILED';audit['error_type']=getattr(exc,'error_type',type(exc).__name__)
  print('SMOKE_FAILED',audit['error_type'],flush=True)
 finally:
  for p,h in audit['protected_hashes'].items():assert sha(p)==h,p
  write(G/'reconstructed_runtime_audit.json',audit)
 print('Workflow smoke:',audit.get('smoke_workflow_status'),'lock:',audit['track_b_lock'],flush=True)

if __name__=='__main__':
 if sys.argv[1]=='retrieval':
  from run_v2_final_retrieval import Pipeline
  pipe=Pipeline()
  documents={int(k):v for k,v in read(G/'reconstructed_document_metadata.json').items()}
  adapter=FrozenRetrievalAdapter(pipe,documents)
  question='Describe computational offloading methods for maritime unmanned aerial vehicles.'
  direct=pipe.run(dict(query_id='SYNTHETIC_HEALTH',query_type='synthetic',query=question))
  translated=adapter.search(question)
  expected=adapter.translate(direct)
  assert translated==expected,'Adapter equivalence failed'
  write(G/'adapter_equivalence.json',dict(status='PASS',query=question,synthetic=True,
   checks=['chunk_ids','order','document_ids','scores','ranks'],direct=expected,adapter=translated))
  audit=read(G/'reconstructed_runtime_audit.json');audit['real_adapter_equivalence']='PASS'
  audit['retrieval_health']='PASS';write(G/'reconstructed_runtime_audit.json',audit)
  print('REAL FROZEN RETRIEVAL + ADAPTER EQUIVALENCE PASS',flush=True)
 elif sys.argv[1]=='preflight':preflight()
 elif sys.argv[1]=='smoke':asyncio.run(smoke())
 else:raise ValueError('No benchmark mode exists')
