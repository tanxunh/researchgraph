import sys
from pathlib import Path
from types import SimpleNamespace
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'scripts'))
from run_v2_g_generation import ReplayContext, traced_service_class, trace_calls
from test_v2_g_reconstructed_runtime import adapter
from test_research_workflow import Model
from app.schemas.research import ResearchTaskRequest
from app.services.generation.evidence_builder import EvidenceBuilder
from v2_g_reconstructed_runtime import evaluation_tool_binding

def test_frozen_context_replay_no_retrieval():
 a=adapter();raw=a.translate(a.pipeline.run({}));e=EvidenceBuilder(max_count=10).build(raw)
 ctx={'order':[x.chunk_id for x in e],'passages':[{**x.model_dump(),'rendered_context':x.context()} for x in e]}
 before=a.pipeline.calls
 replay=ReplayContext({'question':'synthetic'},ctx,a)
 assert len(replay.search('synthetic')['results'])==10
 assert a.pipeline.calls==before
 assert [x['chunk_id'] for x in replay.provided]==ctx['order']
 with pytest.raises(AssertionError):replay.search('different')

@pytest.mark.asyncio
async def test_read_only_trace_preserves_supplemental_workflow():
 a=adapter();s=traced_service_class()(a,Model(missing='method'),resolver=a.resolve)
 with evaluation_tool_binding():r=await s.run(ResearchTaskRequest(question='Synthetic',document_ids=[1],requested_fields=['method']))
 assert r.status=='completed' and r.retry_count==1
 calls=trace_calls(a)
 assert [c['phase'] for c in calls]==['initial','supplemental']
 assert calls[0]['covered_cells_before_retrieval']==[]
 assert calls[0]['covered_cells_after_retrieval']==[]
 assert calls[1]['covered_cells_after_retrieval']==[{'document_id':1,'field':'method'}]
 assert calls[0]['rejected_by_scope']==['chunk-0','chunk-2','chunk-4','chunk-6','chunk-8']
 assert len(calls[0]['admitted_chunk_ids'])==5
