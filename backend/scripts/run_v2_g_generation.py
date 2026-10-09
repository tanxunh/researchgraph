"""V2-G2 sequential, at-most-once frozen generation; no semantic scoring."""
import asyncio,hashlib,json,os,sys,time
from pathlib import Path
from types import SimpleNamespace
from validate_v2_g_reconstructed_runtime import ROOT,B,G,read,write,sha
from v2_g_reconstructed_runtime import FrozenRetrievalAdapter,RecordingLLM,evaluation_tool_binding
RUN=G/'g2'

def append(path,row):
 p=ROOT/path;p.parent.mkdir(parents=True,exist_ok=True)
 with p.open('a',encoding='utf-8') as f:
  f.write(json.dumps(row,ensure_ascii=False,sort_keys=True)+'\n');f.flush();os.fsync(f.fileno())

def load_lines(path):
 p=ROOT/path
 return [json.loads(s) for s in p.read_text(encoding='utf-8').splitlines() if s] if p.exists() else []

def public_tasks():
 # Strict whitelist: Gold, expected answers and annotation hints never enter runtime.
 return [dict(query_id=t['query_id'],query_type=t['query_type'],question=t['question'],document_scope=t['document_scope']) for t in read(B/'v2_g_workflow_benchmark.json')['tasks']]

def prepare():
 audit=read(G/'reconstructed_runtime_audit.json')
 assert all(audit[k]=='PASS' for k in ['generation_lock','track_a_lock','track_b_lock'])
 assert sha(B/'v2_g_workflow_benchmark.json')=='39b30aa7152b6d12aae82a2902a7baa731685de182499e2d505b329ab8493658'
 assert sha(B/'final_retrieval_manifest.json')=='bc601f31786987de88a1a9b1851508960332371654bc9d3a81f0e4a8a4f94e7a'
 paths=[str(B/n) for n in ['v2_g_workflow_benchmark.json','v2_g_generation_config.json','v2_g_track_a_context_config.json','v2_g_track_b_reconstructed_config.json','final_retrieval_manifest.json','final_chunking_config.json','final_dense_config.json','final_fusion_config.json','final_reranker_config.json','queries_test.jsonl']]
 paths += [str(G/n) for n in ['track_a_frozen_contexts.json','review_item_mapping_private.json','reconstructed_document_metadata.json']]
 hashes={p:sha(p) for p in paths};hashes.update(read(B/'v2_g_track_b_reconstructed_config.json')['source_hashes'])
 for p,h in hashes.items():assert sha(p)==h,p
 tasks=public_tasks();assert len(tasks)==len({t['query_id'] for t in tasks})==40
 ctx=read(G/'track_a_frozen_contexts.json')['tasks'];assert len(ctx)==40 and sum(len(c['passages']) for c in ctx)==400
 protocol=dict(status='FROZEN_BEFORE_GENERATION',hashes=hashes,query_order=[t['query_id'] for t in tasks],
  runtime_type='RECONSTRUCTED_EVALUATION_RUNTIME',order='A40 then B-R40',
  retry_policy='Track A existing GroundedAnswerService has no retry; Track B existing ModelGateway transient retry max2; no semantic or whole-task retry',
  token_usage='Unavailable through unchanged LLMClient: provider response usage is not exposed. No extra call to obtain it.',
  blind_order='Reuse pre-existing private mapping byte-for-byte; no new shuffle or invented seed',
  interruption='Started item without durable result is INDETERMINATE; never automatically regenerate',
  runner_sha256=sha('backend/scripts/run_v2_g_generation.py'))
 p=ROOT/RUN/'protocol.json';p.parent.mkdir(parents=True,exist_ok=True)
 with p.open('x',encoding='utf-8') as f:json.dump(protocol,f,sort_keys=True,indent=2)
 print('G2 PROTOCOL PREPARED',flush=True)

def verify():
 protocol=read(RUN/'protocol.json')
 for p,h in protocol['hashes'].items():assert sha(p)==h,p
 assert protocol['runner_sha256']==sha('backend/scripts/run_v2_g_generation.py')
 return protocol

class ReplayContext:
 def __init__(self,task,context,resolver_adapter):
  self.task,self.context,self.base=task,context,resolver_adapter
  self.provided=[]
 def search(self,question,**kwargs):
  assert question==self.task['question']
  results=[]
  for p in self.context['passages']:
   meta=self.base.pipeline.rows[p['chunk_id']]['metadata'];doc=self.base.documents[p['document_id']]
   assert meta['document_version_id']==p['document_version_id']
   assert self.base.pipeline.rows[p['chunk_id']]['document']==p['content']
   results.append(dict(chunk_id=p['chunk_id'],document=dict(doc),document_version_id=p['document_version_id'],
    text=p['content'],source_type='pdf',source_snapshot_available=True,
    location=dict(ordinal=meta['chunk_index'],page_number=p['page'],section_title=p['section']),scores={}))
  from app.services.generation.evidence_builder import EvidenceBuilder
  evidence=EvidenceBuilder(max_count=10).build(dict(mode='hybrid',results=results))
  assert len(evidence)==10
  assert [e.context() for e in evidence]==[p['rendered_context'] for p in self.context['passages']]
  self.provided=[e.model_dump() for e in evidence]
  return dict(mode='hybrid',results=results)

def traced_service_class():
 from app.services.research.workflow import ResearchService
 class ObservedResearchService(ResearchService):
  async def retrieve_evidence(self,state):
   start=len(self.retrieval.calls)
   try:
    return await super().retrieve_evidence(state)
   finally:
    self.pending_call_indices=list(range(start,len(self.retrieval.calls)))
    for i in self.pending_call_indices:
     self.retrieval.calls[i].update(phase='supplemental' if state['retry_count'] else 'initial',
      covered_cells_before_retrieval=[c.model_dump() for c in state['coverage_status'].covered],
      covered_cells_after_retrieval=None,coverage_after_note='Computed at next existing check_coverage after extraction; null if workflow fails before that node')
  async def check_coverage(self,state):
   result=await super().check_coverage(state)
   for i in getattr(self,'pending_call_indices',[]):
    self.retrieval.calls[i]['covered_cells_after_retrieval']=[c.model_dump() for c in result['coverage_status'].covered]
    self.retrieval.calls[i]['missing_requested_cells']=[c.model_dump() for c in result['coverage_status'].missing]
   return result
 return ObservedResearchService

def trace_calls(adapter):
 admission={a['call_id']:a for a in adapter.admissions}
 output=[]
 for call in adapter.calls:
  a=admission.get(call['call_id']);raw=call['returned_results'];ids=[r['chunk_id'] for r in raw]
  eligible=a['scope_eligible'] if a else []
  admitted=[e['chunk_id'] for e in a['admitted']] if a else []
  output.append({**call,'global_top10_chunk_ids':ids,'global_top10_document_ids':[r['document']['id'] for r in raw],
   'admitted_chunk_ids':admitted,'rejected_by_scope':[i for i in ids if a and i not in eligible],
   'rejected_by_limit':[i for i in eligible if i not in admitted],
   'limit_definition':'existing max5 and rendered12000-character EvidenceBuilder admission limits',
   'admission':a})
 return output

async def execute():
 protocol=verify()
 # Import frozen engine before reading the credential; import clears env key.
 from run_v2_final_retrieval import Pipeline
 from app.core.config import Settings
 from app.core.llm_client import LLMClient
 from app.schemas.research import ResearchTaskRequest
 from app.services.generation.grounded_answer_service import GroundedAnswerService
 from app.services.generation.evidence_builder import EvidenceBuilder
 key=sys.stdin.readline().strip();assert key
 settings=Settings(_env_file=None,LLM_API_KEY=key,LLM_MODEL='deepseek-chat',LLM_BASE_URL='https://api.deepseek.com/v1',GRAPH_EXTRACTION_ENABLED=False)
 client=LLMClient();client.settings=settings
 tasks=public_tasks();assert [t['query_id'] for t in tasks]==protocol['query_order']
 contexts={c['query_id']:c for c in read(G/'track_a_frozen_contexts.json')['tasks']}
 docs={int(k):v for k,v in read(G/'reconstructed_document_metadata.json').items()}
 corpus=read('artifacts/evaluation_v2/b4/corpus.json')
 resolver=FrozenRetrievalAdapter(SimpleNamespace(rows=dict(zip(corpus['ids'],corpus['rows']))),docs)
 pipe=None
 for track in ['A','B-R']:
  file=G/('track_a_answers.jsonl' if track=='A' else 'track_b_answers.jsonl')
  existing=load_lines(file);done={r['query_id'] for r in existing};assert len(done)==len(existing)
  if track=='B-R':
   assert len(load_lines(G/'track_a_answers.jsonl'))==40
   pipe=Pipeline()
  for task in tasks:
   qid=task['query_id']
   if qid in done:continue
   verify()
   lock=ROOT/RUN/f'{track}_{qid}.started.json'
   with lock.open('x',encoding='utf-8') as f:json.dump(dict(track=track,query_id=qid,started_at=time.time()),f)
   start=time.perf_counter();llm=RecordingLLM(client)
   record=dict(query_id=qid,query_type=task['query_type'],question=task['question'],track=track,
    runtime_type='RECONSTRUCTED_EVALUATION_RUNTIME',token_usage=None,token_usage_note=protocol['token_usage'])
   if track=='A':
    replay=ReplayContext(task,contexts[qid],resolver)
    svc=GroundedAnswerService(replay,llm,evidence_builder=EvidenceBuilder(max_count=10),resolver=resolver.resolve)
    try:
     result=await svc.answer(task['question'],mode='hybrid',top_k=10)
     record.update(result,status=result['status'],answer=result['answer'],abstention=result['status']=='insufficient_evidence')
    except Exception as exc:
     record.update(status='failed',answer=None,citations=[],abstention=False,error_type=getattr(exc,'error_type',type(exc).__name__))
     if hasattr(exc,'result'):record['citation_validation']=exc.result.model_dump()
    record.update(provided_evidence=replay.provided,provided_context=contexts[qid]['order'],
     provided_document_ids=[p['document_id'] for p in contexts[qid]['passages']],technical_retry_count=0,retrieval_calls=0)
   else:
    adapter=FrozenRetrievalAdapter(pipe,docs);svc=traced_service_class()(adapter,llm,resolver=adapter.resolve,settings=settings)
    with evaluation_tool_binding():result=await svc.run(ResearchTaskRequest(question=task['question'],document_ids=task['document_scope']))
    report=result.report.model_dump(mode='json') if result.report else None
    covered={(c.document_id,c.field) for c in result.coverage.covered}
    supported={(c.document_id,c.field) for c in result.report.comparison if c.status=='supported'} if result.report else set()
    assert supported<=covered
    events=[e.model_dump(mode='json') for e in svc.runtime.context.trace]
    citations_reached=any(e['event_type']=='node_finished' and e['node']=='validate_citations' and e['status']=='succeeded' for e in events)
    # Existing last_state is updated only after successful node execution.
    citations_reached=svc.last_state.get('current_step')=='validate_citations' and result.status!='failed'
    provided={}
    for a in adapter.admissions:
     for e in a['admitted']:provided.setdefault((e['document_id'],e['document_version_id'],e['chunk_id']),e)
    final=[e.model_dump() for e in getattr(svc,'final_evidence',[])]
    record.update(status=result.status,answer=report,report=report,citations=[c.model_dump() for c in result.citations],
     provided_evidence=list(provided.values()),final_admitted_evidence=final,final_admitted_evidence_ids=[e['chunk_id'] for e in final],
     documents_used=sorted({c.document_id for c in result.citations}),covered_cells=[c.model_dump() for c in result.coverage.covered],
     insufficient_evidence_cells=[c.model_dump() for c in result.coverage.missing],
     citation_validation=dict(reached=citations_reached,structural_pass=citations_reached,semantic_scoring=False),
     unsupported_cells_emitted=sorted(supported-covered),errors=result.errors,execution_summary=svc.execution_summary.model_dump(mode='json'),
     technical_retry_count=svc.execution_summary.retries,supplemental_rounds=result.retry_count,
     workflow_trace=events,business_diagnostics=[d.model_dump() for d in svc.business_diagnostics])
    calls=trace_calls(adapter)
    trace=dict(query_id=qid,original_question=task['question'],
     planner_output=[c.get('response') for c in llm.calls if json.loads(c['prompt']).get('operation')=='plan'],
     generated_subqueries=[c['actual_query'] for c in calls],retrieval_calls=calls,
     initial_retrieval_calls=sum(c.get('phase')=='initial' for c in calls),
     supplemental_retrieval_calls=sum(c.get('phase')=='supplemental' for c in calls),total_retrieval_calls=len(calls),
     missing_requested_cells=record['insufficient_evidence_cells'])
    record['retrieval_trace']=trace
   record.update(latency_ms=(time.perf_counter()-start)*1000,llm_calls=len(llm.calls),model_io=llm.calls)
   append(file,record)
   if track=='B-R':append(G/'track_b_retrieval_trace.jsonl',record['retrieval_trace'])
   print(track,qid,record['status'],len(load_lines(file)),'/40',round(record['latency_ms']/1000,1),'s',flush=True)
 verify();print('G2 GENERATION ATTEMPTS COMPLETE',flush=True)

if __name__=='__main__':
 if sys.argv[1]=='prepare':prepare()
 elif sys.argv[1]=='run':asyncio.run(execute())
 else:raise ValueError('Unknown action')
