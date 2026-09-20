import json
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.api.research import router,get_research_service
from app.schemas.research import ResearchTaskRequest
from app.services.research.workflow import ResearchService
from app.services.indexing.ingestion import DocumentIngestion
from app.services.indexing.incremental_indexer import IncrementalIndexer
from app.services.indexing.evidence_resolver import resolve_version_chunks
from app.services.retrieval.retrieval_service import ResearchRetrievalService

pytestmark=pytest.mark.integration


class MockModel:
    def __init__(self,missing=False):self.missing=missing;self.extract_count=0
    async def generate(self,prompt,system_prompt=None):
        packet=json.loads(prompt);d=packet['input'];op=packet['operation']
        if op=='plan':return json.dumps({'subtasks':[dict(subtask_id=f'S{i}',question='Method Alpha research '+field,
            target_field=field,document_scope=d['document_scope'],status='pending') for i,field in enumerate(d['requested_fields'],1)]})
        if op=='extract':
            self.extract_count+=1
            return json.dumps({'facts':[] if self.missing and d['field']=='optimization_objective' else [dict(field=d['field'],fact_status='SUPPORTED',
                value='Method Alpha',document_id=e['locator']['document_id'],document_version_id=e['locator']['document_version_id'],
                supporting_evidence_ids=[e['id']]) for e in d['evidence']]})
        unique={}
        for f in d['facts']:unique.setdefault((f['document_id'],f['field']),f)
        return json.dumps({'summary':'Compared ['+d['facts'][0]['citation_ids'][0]+'].',
            'comparison':[dict(document_id=f['document_id'],field=f['field'],value=f['value'],status='supported') for f in unique.values()],
            'limitations':[]})


@pytest.fixture(params=[True, False], ids=['graph-enabled', 'graph-disabled'])
def research(integration_db,vector_store,rule_extractor,request,monkeypatch):
    from app.core.config import get_settings
    get_settings().graph_extraction_enabled = request.param
    if not request.param:
        def forbidden(*args, **kwargs):
            raise AssertionError('Graph extraction is disabled')
        monkeypatch.setattr(rule_extractor, 'extract', forbidden)
    ingestion=DocumentIngestion(IncrementalIndexer(vector_store,rule_extractor))
    docs=[ingestion.import_text(integration_db,f'Paper {i}',f'Method Alpha TARGETS Task Omega. Research scenario {i}.',f'research:{i}') for i in [1,2,3]]
    retrieval=ResearchRetrievalService(integration_db,vector_store)
    return integration_db,vector_store,ingestion,docs,retrieval


@pytest.mark.asyncio
async def test_real_storage_compare_happy_and_historical_citations(research):
    db,store,ingestion,docs,retrieval=research
    scope=[d['document_id'] for d in docs[:2]]
    service=ResearchService(retrieval,MockModel())
    response=await service.run(ResearchTaskRequest(question='Compare Method Alpha',document_ids=scope,requested_fields=['method']))
    assert response.status=='completed' and response.retry_count==0
    summary=service.execution_summary
    assert summary.run_id==response.run_id and summary.status=='completed'
    assert summary.model_calls==4 and summary.retrieval_calls==1 and summary.tool_calls==2
    assert summary.retries==0 and not summary.budget_exceeded
    assert [e.tool_name for e in service.runtime.context.trace if e.event_type=='tool_call']==['search_evidence','resolve_evidence']
    assert {c.document_id for c in response.citations}==set(scope)
    original=[(c.document_version_id,c.chunk_id) for c in response.citations]
    ingestion.import_text(db,'Paper 1 changed','Method Alpha USES Dataset Beta. Changed source.','research:1')
    historical=resolve_version_chunks(db,original)
    assert set(historical)==set(original)
    assert all(c['version']['number']==1 for c in historical.values())


@pytest.mark.asyncio
async def test_real_storage_missing_field_retry_partial(research):
    db,store,ingestion,docs,retrieval=research
    model=MockModel(missing=True);s=ResearchService(retrieval,model)
    response=await s.run(ResearchTaskRequest(question='Compare method and objective',document_ids=[docs[0]['document_id']],requested_fields=['method','optimization_objective']))
    assert response.status=='partial' and response.retry_count==1 and model.extract_count==3
    assert [(c.document_id,c.field) for c in response.coverage.missing]==[(docs[0]['document_id'],'optimization_objective')]
    assert response.report.comparison[-1].value=='not enough evidence'


def test_scope_applies_in_retrievers_before_top_k(research,monkeypatch):
    db,store,ingestion,docs,retrieval=research
    wanted=docs[2]['document_id']
    called=[];query=store.collection.query
    def capture(**kwargs):called.append(kwargs);return query(**kwargs)
    monkeypatch.setattr(store.collection,'query',capture)
    for mode in ['dense','bm25','hybrid']:
        result=retrieval.search('Method Alpha',mode=mode,top_k=1,document_ids=[wanted],rerank=False)
        assert len(result['results'])==1 and result['results'][0]['document']['id']==wanted
    assert all(c['where']=={'document_id':{'$in':[wanted]}} for c in called)
    assert retrieval.search('Method Alpha',mode='hybrid',top_k=5,document_ids=[],rerank=False)['results']==[]


def test_research_api_real_storage(research):
    db,store,ingestion,docs,retrieval=research
    app=FastAPI();app.include_router(router)
    app.dependency_overrides[get_research_service]=lambda:ResearchService(retrieval,MockModel())
    with TestClient(app) as client:
        response=client.post('/api/research/tasks',json={'question':'Compare methods','document_ids':[docs[0]['document_id']], 'requested_fields':['method']})
    assert response.status_code==200
    body=response.json();assert body['code']==0 and body['data']['run_id'] and body['data']['status']=='completed'


@pytest.mark.asyncio
async def test_real_storage_harness_transient_model_retry(research):
    from app.core.llm_client import LLMClientError
    db,store,ingestion,docs,retrieval=research
    model=MockModel(); original=model.generate; attempts=[]
    async def transient(prompt,**kwargs):
        attempts.append(1)
        if len(attempts)==1:
            raise LLMClientError("temporary connection failure", "llm_network_error")
        return await original(prompt,**kwargs)
    model.generate=transient
    service=ResearchService(retrieval,model)
    result=await service.run(ResearchTaskRequest(question='Compare Method Alpha',
        document_ids=[docs[0]['document_id']],requested_fields=['method']))
    assert result.status=='completed' and result.retry_count==0
    summary=service.execution_summary
    assert summary.model_calls==4 and summary.retries==1
    assert summary.retrieval_calls==1 and summary.tool_calls==2
    assert len(attempts)==4


@pytest.mark.asyncio
@pytest.mark.parametrize('limit',['research_max_model_calls','research_max_tool_calls'])
async def test_real_storage_harness_budget_termination(research,limit):
    db,store,ingestion,docs,retrieval=research
    service=ResearchService(retrieval,MockModel())
    service.settings=service.settings.model_copy(update={limit:1})
    result=await service.run(ResearchTaskRequest(question='Compare Method Alpha',
        document_ids=[docs[0]['document_id']],requested_fields=['method']))
    assert result.status=='failed' and result.errors==['budget_exceeded']
    assert result.report is None and not result.citations
    summary=service.execution_summary
    assert summary.status=='failed' and summary.budget_exceeded and summary.error_code=='budget_exceeded'
    assert summary.model_calls==1 if limit=='research_max_model_calls' else summary.tool_calls==1
    assert service.runtime.context.trace[-1].event_type=='run_finished'


@pytest.mark.asyncio
async def test_real_storage_insufficient_status_remains_partial(research):
    db,store,ingestion,docs,retrieval=research
    model=MockModel();original=model.generate
    async def insufficient(prompt,**kwargs):
        data=json.loads(await original(prompt,**kwargs))
        for f in data.get('facts',[]):
            f['fact_status']='INSUFFICIENT_EVIDENCE';f['value']='Not specified in supplied evidence.'
        return json.dumps(data)
    model.generate=insufficient;s=ResearchService(retrieval,model)
    r=await s.run(ResearchTaskRequest(question='Compare methods',document_ids=[docs[0]['document_id']],requested_fields=['method']))
    assert r.status=='partial' and r.retry_count==1 and not r.coverage.covered
    assert not r.citations and not s.business_diagnostics
