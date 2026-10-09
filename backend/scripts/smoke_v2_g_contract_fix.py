"""One explicitly authorized post-contract-fix synthetic workflow smoke."""
import asyncio,json,sys
from validate_v2_g_reconstructed_runtime import ROOT,B,G,read,write,sha
from v2_g_reconstructed_runtime import FrozenRetrievalAdapter,RecordingLLM,evaluation_tool_binding,registry_class

async def main():
 contract=read(G/'g16_fix_contract.json')
 for p,h in contract['source_hashes'].items():assert sha(p)==h,p
 for p,h in read(G/'runtime_audit.json')['protected_hashes'].items():
  expected=contract['source_hashes'][p] if p in {'backend/app/services/research/workflow.py','backend/app/schemas/research.py'} else h
  assert sha(p)==expected,p
 from run_v2_final_retrieval import Pipeline
 from app.core.config import Settings
 from app.core.llm_client import LLMClient
 from app.services.research.workflow import ResearchService
 from app.schemas.research import ResearchTaskRequest
 from app.services.runtime.tools import SearchInput
 key=sys.stdin.readline().strip();assert key
 old=read(G/'reconstructed_workflow_smoke.json')
 pipe=Pipeline();docs={int(k):v for k,v in read(G/'reconstructed_document_metadata.json').items()}
 adapter=FrozenRetrievalAdapter(pipe,docs)
 # Same-input deterministic replay checks retrieval and admission independently of LLM variability.
 registry=registry_class()(adapter,adapter.resolve)
 comparisons=[]
 for admission in old['admissions']:
  previous=old['retrieval_calls'][admission['call_id']-1]
  registry.get('search_evidence').handler(SearchInput(query=previous['actual_query'],top_k=previous['requested_top_k'],document_scope=previous['requested_scope']))
  current=adapter.calls[-1]
  assert current['returned_results']==previous['returned_results'],'retrieval output drift'
  for field in ['global_top10','scope_eligible','admitted','backfill','max_evidence','max_characters','document_scope']:
   assert adapter.admissions[-1][field]==admission[field],field+' admission drift'
  comparisons.append(dict(query=previous['actual_query'],retrieval_equal=True,admission_equal=True))
 write(G/'g16_fix_upstream_equivalence.json',dict(status='PASS',comparisons=comparisons,method='same-input replay of all prior workflow calls; no model generation'))
 print('UPSTREAM REPLAY PASS',len(comparisons),flush=True)
 settings=Settings(_env_file=None,LLM_API_KEY=key,LLM_MODEL='deepseek-chat',LLM_BASE_URL='https://api.deepseek.com/v1',GRAPH_EXTRACTION_ENABLED=False)
 client=LLMClient();client.settings=settings
 adapter=FrozenRetrievalAdapter(pipe,docs);llm=RecordingLLM(client)
 service=ResearchService(adapter,llm,resolver=adapter.resolve,settings=settings)
 with (ROOT/G/'g16_fix_smoke_execution_lock.json').open('x',encoding='utf-8') as f:json.dump(dict(attempt=1,synthetic_only=True),f)
 request=ResearchTaskRequest(**contract['smoke_request'])
 with evaluation_tool_binding():result=await service.run(request)
 record=dict(status=result.status,response=result.model_dump(mode='json'),execution_summary=service.execution_summary.model_dump(mode='json'),
  model_calls=llm.calls,retrieval_calls=adapter.calls,admissions=adapter.admissions,
  diagnostics=[d.model_dump() for d in service.business_diagnostics],trace=[e.model_dump(mode='json') for e in service.runtime.context.trace],
  final_evidence=[e.model_dump() for e in getattr(service,'final_evidence',[])],source_hashes=contract['source_hashes'],runtime_type='RECONSTRUCTED_EVALUATION_RUNTIME',track='TRACK_B_R',synthetic=True)
 covered={(c.document_id,c.field) for c in result.coverage.covered}
 emitted={(c.document_id,c.field) for c in result.report.comparison if c.status=='supported'} if result.report else set()
 missing={(c.document_id,c.field) for c in result.coverage.missing}
 abstained={(c.document_id,c.field) for c in result.report.comparison if c.status=='insufficient_evidence' and c.value=='not enough evidence'} if result.report else set()
 reached=service.last_state.get('current_step')=='validate_citations'
 checks=dict(retrieval_unchanged=True,admission_unchanged=True,unsupported_generated_cells=sorted(emitted-covered),
  covered_cells=sorted(covered),missing_requested_cells=sorted(missing),abstention=bool(result.report) and missing<=abstained,
  citation_validation_reached=reached,doc7_objective_insufficient=(7,'optimization_objective') in abstained,
  supplemental_rounds=result.retry_count)
 record['checks']=checks
 record['smoke_pass']=result.status!='failed' and reached and bool(result.citations) and checks['abstention'] and not emitted-covered and checks['doc7_objective_insufficient']
 write(G/'g16_fix_workflow_smoke.json',record)
 for p,h in read(G/'runtime_audit.json')['protected_hashes'].items():
  expected=contract['source_hashes'][p] if p in {'backend/app/services/research/workflow.py','backend/app/schemas/research.py'} else h
  assert sha(p)==expected,p
 print('FIX_SMOKE',record['smoke_pass'],result.status,json.dumps(checks),flush=True)

if __name__=='__main__':asyncio.run(main())
