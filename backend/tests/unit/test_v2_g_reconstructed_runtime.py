import sys
from pathlib import Path
from types import SimpleNamespace
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'scripts'))
from v2_g_reconstructed_runtime import FrozenRetrievalAdapter, registry_class, evaluation_tool_binding
from app.services.runtime.tools import SearchInput

def adapter():
 ids=[f'chunk-{i}' for i in range(10)]
 row=dict(reranked=ids,reranked20=ids,reranker_scores=[.9-i*.01 for i in range(10)])
 rows={sid:dict(document='Original source text.',metadata=dict(document_id=1 if i%2 else 2,
  document_version_id=1 if i%2 else 2,document_chunk_id=i+1,chunk_index=i,page_number=1,section_title='')) for i,sid in enumerate(ids)}
 pipe=SimpleNamespace(rows=rows,calls=0)
 def run(q):pipe.calls+=1;return row
 pipe.run=run
 docs={i:dict(id=i,title=f'Paper {i}',version=1,version_id=i,source_uri=f'benchmark:{i}') for i in [1,2]}
 return FrozenRetrievalAdapter(pipe,docs)

def test_full_top10_order_scores_despite_legacy_flags():
 a=adapter();result=a.search('synthetic',top_k=5,rerank=False,document_ids=[1])
 assert [r['chunk_id'] for r in result['results']]==[f'chunk-{i}' for i in range(10)]
 assert [r['scores']['reranker_score'] for r in result['results']]==[.9-i*.01 for i in range(10)]
 assert a.pipeline.calls==1

def test_scope_admission_no_backfill():
 a=adapter();reg=registry_class()(a,a.resolve)
 result=reg.get('search_evidence').handler(SearchInput(query='synthetic',top_k=5,document_scope=[1]))
 assert [e.chunk_id for e in result]==[f'chunk-{i}' for i in [1,3,5,7,9]]
 assert a.pipeline.calls==1 and len(a.admissions[0]['global_top10'])==10
 empty=reg.get('search_evidence').handler(SearchInput(query='synthetic',top_k=5,document_scope=[3]))
 assert empty==[] and a.pipeline.calls==2

def test_resolver_rejects_wrong_version():
 a=adapter();assert a.resolve([(99,'chunk-1')])=={}
 assert a.resolve([(1,'chunk-1')])[(1,'chunk-1')]['text']=='Original source text.'

def test_binding_restored():
 from app.services.research import workflow
 old=workflow.ToolRegistry
 with evaluation_tool_binding():assert workflow.ToolRegistry is not old
 assert workflow.ToolRegistry is old

@pytest.mark.asyncio
async def test_existing_supplemental_path_with_evaluation_admission():
 from test_research_workflow import Model
 from app.services.research.workflow import ResearchService
 from app.schemas.research import ResearchTaskRequest
 a=adapter();model=Model(missing='method')
 s=ResearchService(a,model,resolver=a.resolve)
 with evaluation_tool_binding():
  result=await s.run(ResearchTaskRequest(question='Synthetic method check',document_ids=[1],requested_fields=['method']))
 assert result.status=='completed' and result.retry_count==1
 assert len(a.calls)==2 and 'Specific evidence:' in a.calls[1]['actual_query']
 assert result.citations and len(a.admissions)==2
