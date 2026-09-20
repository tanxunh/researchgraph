import json
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError
from app.schemas.research import ResearchTaskRequest, FactClaim
from app.services.research.workflow import ResearchService,locator
from app.services.generation.evidence_builder import EvidenceBuilder


def candidate(doc=1,chunk='chunk-1',version=1):
    return {'document':{'id':doc,'version':1,'version_id':version,'title':f'Paper {doc}'},
        'document_version_id':version,'chunk_id':chunk,'text':'Supported research method and objective.',
        'location':{'page_number':1,'section_title':None,'ordinal':0},'source_type':'text','scores':{'fusion_score':.1}}


class Retrieval:
    def __init__(self,rows=None):self.rows=rows if rows is not None else [candidate()];self.calls=[]
    def search(self,question,**kwargs):
        self.calls.append((question,kwargs))
        scope=kwargs.get('document_ids')
        return {'mode':kwargs['mode'],'results':[r for r in self.rows if scope is None or r['document']['id'] in scope][:kwargs['top_k']]}


def resolver(rows):
    evidence=EvidenceBuilder().build({'mode':'hybrid','results':rows})
    return lambda keys:{e.locator:{'document':{'id':e.document_id},'version':{'id':e.document_version_id},
        'chunk_id':e.chunk_id,'text':e.content,'location':{'ordinal':e.ordinal,'page_number':e.page,'section_title':e.section}}
        for e in evidence if e.locator in keys}


class Model:
    def __init__(self,missing=None,forever=False):
        self.calls=[];self.counts={};self.missing=missing;self.forever=forever
    async def generate(self,prompt,system_prompt=None):
        p=json.loads(prompt);self.calls.append(p);data=p['input'];kind=p['operation']
        if kind=='plan':
            result={'subtasks':[{'subtask_id':f'S{i}','question':field,'target_field':field,
                'document_scope':data['document_scope'],'status':'pending'} for i,field in enumerate(data['requested_fields'],1)]}
        elif kind=='extract':
            field=data['field'];self.counts[field]=self.counts.get(field,0)+1
            evidence=data['evidence']
            empty=field==self.missing and (self.forever or self.counts[field]==1)
            result={'facts':[] if empty else [{'field':field,'fact_status':'SUPPORTED','value':'supported '+field,
                'document_id':e['locator']['document_id'],'document_version_id':e['locator']['document_version_id'],
                'supporting_evidence_ids':[e['id']]} for e in evidence]}
        else:
            unique={}
            for f in data['facts']:unique.setdefault((f['document_id'],f['field']),f)
            result={'summary':'Comparison ['+data['facts'][0]['citation_ids'][0]+'].','comparison':[
                {'document_id':f['document_id'],'field':f['field'],'value':f['value'],'status':'supported'}
                for f in unique.values()],'limitations':[]}
        return json.dumps(result)


def service(rows=None,model=None):
    retrieval=Retrieval(rows)
    return ResearchService(retrieval,model or Model(),resolver=resolver(retrieval.rows))


def request(fields=None):return ResearchTaskRequest(question='Compare methods',document_ids=[1],requested_fields=fields or ['method'])


def provenance_service():
    rows=[candidate(1,'m1',11),candidate(1,'m2',11),candidate(1,'objective',11),
          candidate(2,'b',22),candidate(2,'unused',22)]
    model=Model();original=model.generate
    async def generate(prompt,**kwargs):
        packet=json.loads(prompt);data=json.loads(await original(prompt,**kwargs))
        if packet['operation']=='extract':
            field=packet['input']['field']
            allowed={'m1','m2','b'} if field=='method' else {'objective'}
            data['facts']=[f for f in data['facts'] if f['supporting_evidence_ids'][0].rsplit(':',1)[-1] in allowed]
            if field=='method' and packet['input']['document_id']==1 and data['facts']:
                # Overlapping supports from several validated Facts must deduplicate.
                data['facts'][0]['supporting_evidence_ids']=['1:11:m1','1:11:m2','1:11:m1']
        return json.dumps(data)
    model.generate=generate
    return service(rows,model), ResearchTaskRequest(question='Compare',document_ids=[1,2],
        requested_fields=['method','optimization_objective'])


@pytest.mark.asyncio
async def test_cell_provenance_union_namespace_and_missing():
    s,req=provenance_service();result=await s.run(req)
    assert result.status=='partial'
    cells={(c.document_id,c.field):c for c in result.report.comparison}
    assert cells[1,'method'].value=='supported method [C1] [C2]'
    assert cells[1,'optimization_objective'].value=='supported optimization_objective [C4]'
    assert cells[2,'method'].value=='supported method [C3]'
    assert cells[2,'optimization_objective'].value=='not enough evidence'
    assert cells[2,'optimization_objective'].status=='insufficient_evidence'
    assert [(e.evidence_id,e.document_id,e.document_version_id,e.chunk_id) for e in s.final_evidence]==[
        ('C1',1,11,'m1'),('C2',1,11,'m2'),('C3',2,22,'b'),('C4',1,11,'objective')]
    assert {c.citation_id for c in result.citations}=={'C1','C2','C3','C4'}
    assert result.report.summary=='Comparison [C1].'
    from app.schemas.research import ResearchResponse
    assert ResearchResponse.model_validate(result.model_dump())==result


@pytest.mark.asyncio
async def test_out_of_scope_invariant_and_exact_logged_ids(caplog):
    s,req=provenance_service();original=s.synthesize
    async def tampered(state):
        output=await original(state)
        output['final_report'].comparison[0].value+=' [C3]'
        return output
    s.synthesize=tampered
    result=await s.run(req)
    assert result.status=='failed' and result.errors==['citation_validation_failed']
    assert result.report is None and result.citations==[]
    diagnostic=s.business_diagnostics[0]
    assert diagnostic.path=='comparison.document[1].method'
    assert diagnostic.invalid_reference_ids==['C3']
    assert diagnostic.allowed_reference_ids==['C1','C2']
    records=[r.getMessage().split('research_business_rejection ',1)[1] for r in caplog.records
             if 'research_business_rejection ' in r.getMessage()]
    logged=json.loads(records[-1])
    assert logged['run_id']==result.run_id and logged['invalid_reference_ids']==['C3']
    assert logged['allowed_reference_ids']==['C1','C2']
    assert 'supported method' not in records[-1]


@pytest.mark.asyncio
@pytest.mark.parametrize('reference',['[C1]','[C999]','[C01]'])
async def test_model_comparison_citations_are_rejected_not_removed(reference):
    model=Model();original=model.generate
    async def generate(prompt,**kwargs):
        data=json.loads(await original(prompt,**kwargs))
        if 'comparison' in data:data['comparison'][0]['value']+=' '+reference
        return json.dumps(data)
    model.generate=generate;s=service(model=model)
    result=await s.run(request())
    assert result.status=='failed' and result.report is None
    diagnostic=s.business_diagnostics[0]
    assert diagnostic.stage=='synthesize' and diagnostic.allowed_reference_ids==[]
    if reference!='[C01]':assert diagnostic.invalid_reference_ids==[reference[1:-1]]
    assert s.execution_summary.retries==0


@pytest.mark.asyncio
async def test_summary_invalid_reference_diagnostic_keeps_exact_ids():
    model=Model();original=model.generate
    async def generate(prompt,**kwargs):
        data=json.loads(await original(prompt,**kwargs))
        if 'summary' in data:data['summary']='Unknown [C999]'
        return json.dumps(data)
    model.generate=generate;s=service(model=model)
    result=await s.run(request())
    assert result.status=='failed' and result.errors==['citation_validation_failed']
    assert s.business_diagnostics[0].invalid_reference_ids==['C999']
    assert s.business_diagnostics[0].allowed_reference_ids==['C1']


@pytest.mark.asyncio
async def test_document_version_isolation_and_cross_document_synthesis():
    rows=[candidate(1,'a',11),candidate(2,'b',22)]
    model=Model();s=service(rows,model)
    result=await s.run(ResearchTaskRequest(question='Compare',document_ids=[1,2],requested_fields=['method']))
    assert result.status=='completed' and len(result.coverage.covered)==2
    inputs=[c['input'] for c in model.calls if c['operation']=='extract']
    assert len(inputs)==2 and {d['document_id'] for d in inputs}=={1,2}
    for d in inputs:
        assert {e['locator']['document_id'] for e in d['evidence']}=={d['document_id']}
        assert {e['locator']['document_version_id'] for e in d['evidence']}=={d['document_version_id']}
        assert d['allowed_support_ids']==[e['id'] for e in d['evidence']]
    synthesis=next(c['input'] for c in model.calls if c['operation']=='synthesize')
    assert {f['document_id'] for f in synthesis['facts']}=={1,2}
    assert all(all(e['document_id']==f['document_id'] for e in f['evidence_locators']) for f in synthesis['facts'])
    assert {c.document_id for c in result.citations}=={1,2}
    assert len(s.retrieval.calls)==1 and s.execution_summary.model_calls==4


@pytest.mark.asyncio
@pytest.mark.parametrize('remap', [False,True])
async def test_foreign_support_fails_closed_without_trimming_or_retry(remap):
    rows=[candidate(1,'a',11),candidate(2,'b',22)]
    model=Model();original=model.generate
    async def foreign(prompt,**kwargs):
        data=json.loads(await original(prompt,**kwargs))
        if data.get('facts'):
            data['facts'][0]['supporting_evidence_ids'].append('2:22:b')
            if remap:
                data['facts'][0]['document_id']=2
                data['facts'][0]['document_version_id']=22
                data['facts'][0]['supporting_evidence_ids']=['2:22:b']
        return json.dumps(data)
    model.generate=foreign;s=service(rows,model)
    result=await s.run(ResearchTaskRequest(question='Compare',document_ids=[1,2],requested_fields=['method']))
    assert result.status=='failed' and result.report is None and not result.citations
    assert s.business_diagnostics[0].validation_rule=='fact_document_mismatch'
    assert len([c for c in model.calls if c['operation']=='extract'])==1
    assert not any(c['operation']=='synthesize' for c in model.calls)
    assert len(s.retrieval.calls)==1 and s.execution_summary.retries==0


@pytest.mark.asyncio
async def test_plan_three_subtasks_retrieve_separately_no_retry():
    s=service();result=await s.run(request(['method','optimization_objective','main_findings']))
    assert result.status=='completed' and result.retry_count==0
    assert len(s.last_state['plan'].subtasks)==3 and len(s.retrieval.calls)==3
    assert all(c[1]['document_ids']==[1] for c in s.retrieval.calls)
    assert len([c for c in s.llm.calls if c['operation']=='plan'])==1


@pytest.mark.asyncio
@pytest.mark.parametrize('raw',['Step 1: compare','{}','{"subtasks":[]}','{"subtasks":[{"question":"x"}]}'])
async def test_malformed_planner_fails(raw):
    s=service(model=SimpleNamespace(generate=AsyncMock(return_value=raw)))
    r=await s.run(request());assert r.status=='failed' and r.errors==['invalid_model_response']
    assert s.retrieval.calls==[]


@pytest.mark.asyncio
async def test_retry_only_missing_field_then_success():
    s=service(model=Model('main_findings'))
    r=await s.run(request(['method','optimization_objective','main_findings']))
    assert r.status=='completed' and r.retry_count==1
    assert len(s.retrieval.calls)==4 and s.llm.counts['method']==1 and s.llm.counts['main_findings']==2
    assert 'Specific evidence' in s.retrieval.calls[-1][0]


@pytest.mark.asyncio
async def test_retry_exhaustion_partial_and_limit():
    s=service(model=Model('main_findings',True));r=await s.run(request(['method','main_findings']))
    assert r.status=='partial' and r.retry_count==1 and s.llm.counts['main_findings']==2
    assert any(c.field=='main_findings' and c.value=='not enough evidence' for c in r.report.comparison)
    synthesis=next(c for c in s.llm.calls if c['operation']=='synthesize')
    assert {f['field'] for f in synthesis['input']['facts']}=={'method'}


@pytest.mark.asyncio
async def test_no_evidence_no_extract_or_synthesis():
    s=service([]);r=await s.run(request())
    assert r.status=='partial' and not r.citations and r.retry_count==1
    assert [c['operation'] for c in s.llm.calls]==['plan']
    assert r.report.summary=='not enough evidence'


@pytest.mark.asyncio
async def test_evidence_dedup_and_immutable_identity():
    rows=[candidate(version=7),candidate(version=7)];s=service(rows)
    r=await s.run(request(['method','main_findings']))
    assert r.status=='completed' and len(r.citations)==1
    assert r.citations[0].document_version_id==7
    for fact in s.last_state['extracted_facts']:
        assert fact.supporting_evidence_ids==['1:7:chunk-1']
        assert fact.evidence_locators[0].document_version_id==7


@pytest.mark.asyncio
async def test_facts_must_match_admitted_locator():
    model=Model();original=model.generate
    async def bad(prompt,**kw):
        value=json.loads(await original(prompt,**kw))
        if 'facts' in value:
            for f in value['facts']:f['document_version_id']=999
        return json.dumps(value)
    model.generate=bad;s=service(model=model)
    assert (await s.run(request())).errors==['invalid_model_response']
    assert not any(c['operation']=='synthesize' for c in model.calls)


def test_fact_schema_requires_support_and_request_bounds():
    with pytest.raises(ValidationError):FactClaim(field='method',value='x',document_id=1,document_version_id=1,supporting_evidence_ids=[])
    with pytest.raises(ValidationError):ResearchTaskRequest(question='x',document_ids=[1,1])
    with pytest.raises(ValidationError):ResearchTaskRequest(question='x',retrieval_mode='graph_enhanced')


@pytest.mark.asyncio
async def test_invalid_c999_rejected_and_no_report_exposed():
    model=Model();original=model.generate
    async def bad(prompt,**kw):return (await original(prompt,**kw)).replace('[C1]','[C999]')
    model.generate=bad;r=await service(model=model).run(request())
    assert r.status=='failed' and r.report is None and not r.citations
    assert r.errors==['citation_validation_failed']


@pytest.mark.asyncio
async def test_only_actually_used_citations_returned():
    s=service([candidate(chunk='a'),candidate(chunk='b')]);r=await s.run(request())
    assert r.status=='completed' and len(s.final_evidence)==2 and len(r.citations)==2
    # Both validated supports are now actually cited by deterministic cell binding.
    assert [c.chunk_id for c in r.citations]==['a','b']
    assert r.report.comparison[0].value.endswith('[C1] [C2]')


@pytest.mark.asyncio
async def test_coverage_is_per_document_and_scope_cannot_expand():
    s=service();r=await s.run(ResearchTaskRequest(question='compare',document_ids=[1,2],requested_fields=['method']))
    assert r.status=='partial'
    assert [(c.document_id,c.field) for c in r.coverage.missing]==[(2,'method')]
    assert s.retrieval.calls[-1][1]['document_ids']==[2]


@pytest.mark.asyncio
async def test_zero_retry_and_evidence_budget():
    s=service([candidate(chunk='a'),candidate(chunk='b')],Model('method',True))
    s.settings=s.settings.model_copy(update={'research_max_retries':0,'research_max_evidence':1})
    r=await s.run(request());assert r.status=='partial' and r.retry_count==0
    assert sum(map(len,s.last_state['evidence_by_subtask'].values()))==1


@pytest.mark.asyncio
async def test_planner_cannot_change_document_scope():
    m=Model();original=m.generate
    async def bad(prompt,**kw):
        value=json.loads(await original(prompt,**kw))
        for t in value.get('subtasks',[]):t['document_scope']=[999]
        return json.dumps(value)
    m.generate=bad;s=service(model=m)
    assert (await s.run(request())).status=='failed' and not s.retrieval.calls


def test_research_api_returns_run_id_and_failure_envelope():
    from app.api.research import router,get_research_service
    app=FastAPI();app.include_router(router)
    app.dependency_overrides[get_research_service]=lambda:service()
    client=TestClient(app)
    r=client.post('/api/research/tasks',json=request().model_dump()).json()
    assert r['code']==0 and r['data']['run_id'] and r['data']['status']=='completed'
    app.dependency_overrides[get_research_service]=lambda:service(model=SimpleNamespace(generate=AsyncMock(return_value='bad')))
    r=client.post('/api/research/tasks',json=request().model_dump()).json()
    assert r['code']==1 and r['data']['status']=='failed' and r['data']['report'] is None


@pytest.mark.asyncio
async def test_ordinary_qa_does_not_enter_langgraph(monkeypatch):
    from app.api import qa as api
    from app.schemas.search import QARequest
    from app.services.generation.grounded_answer_service import GroundedAnswerService
    ret=Retrieval()
    qa=GroundedAnswerService(ret,SimpleNamespace(generate=AsyncMock(return_value='Supported [C1].')),resolver=resolver(ret.rows))
    from app.services.runtime.runtime import AgentRuntime
    monkeypatch.setattr(AgentRuntime,'__init__',lambda *args,**kwargs:(_ for _ in ()).throw(AssertionError('QA entered Harness')))
    monkeypatch.setattr(ResearchService,'graph',lambda self:(_ for _ in ()).throw(AssertionError('QA entered graph')))
    monkeypatch.setattr(api,'ResearchRetrievalService',lambda db:ret)
    monkeypatch.setattr(api,'GroundedAnswerService',lambda retrieval:qa)
    value=await api.qa(QARequest(question='method?',mode='hybrid'),db=None)
    assert value['code']==0 and value['data']['status']=='answered'


@pytest.mark.asyncio
async def test_planner_budget_rejection_and_duplicate_subtasks():
    s=service();s.settings=s.settings.model_copy(update={'research_max_subtasks':1})
    assert (await s.run(request(['method','main_findings']))).errors==['research_budget_exceeded']
    assert not s.llm.calls
    model=Model();original=model.generate
    async def duplicate(prompt,**kw):
        value=json.loads(await original(prompt,**kw))
        for t in value.get('subtasks',[]):t['subtask_id']='S1'
        return json.dumps(value)
    model.generate=duplicate
    r=await service(model=model).run(request(['method','main_findings']))
    assert r.errors==['invalid_model_response']


@pytest.mark.asyncio
async def test_missing_fact_ids_and_provider_errors_fail_explicitly():
    model=Model();original=model.generate
    async def bad(prompt,**kw):
        value=json.loads(await original(prompt,**kw))
        for f in value.get('facts',[]):f['supporting_evidence_ids']=['C1']
        return json.dumps(value)
    model.generate=bad
    assert (await service(model=model).run(request())).errors==['invalid_model_response']
    from app.core.llm_client import LLMClientError
    failing=SimpleNamespace(generate=AsyncMock(side_effect=LLMClientError('timeout','llm_timeout')))
    assert (await service(model=failing).run(request())).errors==['llm_timeout']


@pytest.mark.asyncio
async def test_unscoped_discovery_is_bounded_then_fixes_scope():
    s=service([candidate(1,'a'),candidate(2,'b')])
    r=await s.run(ResearchTaskRequest(question='compare',max_documents=1,requested_fields=['method']))
    assert r.status=='completed' and len(s.retrieval.calls)==2
    assert 'document_ids' not in s.retrieval.calls[0][1]
    assert s.retrieval.calls[1][1]['document_ids']==[1]
    assert {c.document_id for c in r.citations}=={1}


@pytest.mark.asyncio
async def test_runtime_summary_does_not_confuse_workflow_refinement_with_transient_retry():
    s=service(model=Model('main_findings',True))
    r=await s.run(request(['method','main_findings']))
    assert r.status=='partial' and r.retry_count==1
    assert s.execution_summary.retries==0 and s.execution_summary.status=='partial'
    assert s.execution_summary.model_calls==5 and s.execution_summary.retrieval_calls==3
    assert s.execution_summary.tool_calls==4


@pytest.mark.asyncio
async def test_budget_failure_does_not_publish_unvalidated_report():
    s=service();s.settings=s.settings.model_copy(update={'research_max_tool_calls':1})
    r=await s.run(request())
    assert r.errors==['budget_exceeded'] and r.report is None and not r.citations
    assert s.execution_summary.budget_exceeded and s.execution_summary.status=='failed'
    assert s.runtime.context.trace[-1].event_type=='run_finished'


@pytest.mark.asyncio
async def test_runs_have_fresh_contexts_and_single_resolver_query():
    a,b=service(),service();calls=[]; original=a.resolver
    def resolve(keys):
        calls.append(keys);return original(keys)
    a.resolver=resolve
    import asyncio
    ra,rb=await asyncio.gather(a.run(request(['method','main_findings'])),b.run(request()))
    assert ra.status==rb.status=='completed' and ra.run_id!=rb.run_id
    assert a.runtime.context is not b.runtime.context
    assert {e.run_id for e in a.runtime.context.trace}=={ra.run_id}
    assert {e.run_id for e in b.runtime.context.trace}=={rb.run_id}
    assert len(calls)==1
    first=a.runtime.context
    again=await a.run(request())
    assert again.status=='completed' and a.runtime.context is not first
    assert a.execution_summary.model_calls==3


@pytest.mark.asyncio
async def test_insufficient_fact_with_locator_stays_uncovered_then_partial():
    model=Model();original=model.generate
    async def insufficient(prompt,**kwargs):
        data=json.loads(await original(prompt,**kwargs))
        for f in data.get('facts',[]):
            f['fact_status']='INSUFFICIENT_EVIDENCE'
            f['value']='The specific optimization variables are not stated in supplied evidence.'
        return json.dumps(data)
    model.generate=insufficient;s=service(model=model)
    r=await s.run(request(['optimization_variables']))
    assert r.status=='partial' and r.retry_count==1
    assert not r.coverage.covered and len(r.coverage.missing)==1
    assert s.last_state['extracted_facts'][0].evidence_locators
    assert len(s.retrieval.calls)==2 and model.counts['optimization_variables']==2
    assert not any(c['operation']=='synthesize' for c in model.calls)
    assert not r.citations and not s.business_diagnostics


@pytest.mark.asyncio
async def test_insufficient_fields_excluded_from_synthesis_but_valid_facts_preserved():
    model=Model();original=model.generate
    async def mixed(prompt,**kwargs):
        data=json.loads(await original(prompt,**kwargs))
        for f in data.get('facts',[]):
            if f['field']=='optimization_variables':
                f['fact_status']='INSUFFICIENT_EVIDENCE';f['value']='Unknown from supplied evidence.'
        return json.dumps(data)
    model.generate=mixed;s=service(model=model)
    r=await s.run(request(['method','optimization_variables']))
    assert r.status=='partial' and r.retry_count==1
    assert [(c.document_id,c.field) for c in r.coverage.covered]==[(1,'method')]
    synth=next(c for c in model.calls if c['operation']=='synthesize')
    assert {f['field'] for f in synth['input']['facts']}=={'method'}
    assert r.citations and r.report.comparison[-1].status=='insufficient_evidence'


@pytest.mark.asyncio
@pytest.mark.parametrize('key,value,rule',[
    ('supporting_evidence_ids',['SECRET_FULL_PROMPT'],'extract_fact_support_not_allowed'),
    ('document_id',999,'fact_document_mismatch'),
    ('document_version_id',999,'fact_version_mismatch'),
    ('field','main_findings','extract_fact_field_mismatch')])
async def test_business_rejection_diagnostic_specific_and_redacted(key,value,rule,caplog):
    model=Model();original=model.generate
    async def invalid(prompt,**kwargs):
        data=json.loads(await original(prompt,**kwargs))
        for f in data.get('facts',[]):
            f[key]=value;f['value']='SECRET_FULL_PROMPT PDF text API key'
        return json.dumps(data)
    model.generate=invalid;s=service(model=model);s.diagnostic_task_id='A004'
    r=await s.run(request())
    assert r.status=='failed' and r.errors==['invalid_model_response']
    diagnostic=s.business_diagnostics[0]
    assert diagnostic.run_id==r.run_id and diagnostic.task_id=='A004'
    assert diagnostic.stage=='extract_facts' and diagnostic.validation_rule==rule
    assert diagnostic.path and diagnostic.reason and diagnostic.expected_summary and diagnostic.actual_summary
    assert 'SECRET_FULL_PROMPT' not in diagnostic.model_dump_json() and 'SECRET_FULL_PROMPT' not in caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize('case,rule',[
    ('duplicate','comparison_item_count_mismatch'),
    ('field','comparison_field_set_mismatch'),
    ('status','report_status_inconsistent')])
async def test_comparison_rejection_has_exact_diagnostic(case,rule):
    model=Model();original=model.generate
    async def invalid(prompt,**kwargs):
        data=json.loads(await original(prompt,**kwargs))
        if 'comparison' in data:
            if case=='duplicate':data['comparison'].append(dict(data['comparison'][0]))
            elif case=='field':data['comparison'][0]['field']='main_findings'
            else:data['comparison'][0]['status']='insufficient_evidence'
        return json.dumps(data)
    model.generate=invalid;s=service(model=model);r=await s.run(request())
    assert r.status=='failed' and s.business_diagnostics[0].validation_rule==rule


@pytest.mark.asyncio
async def test_citation_diagnostic_and_missing_status_schema_failure_remain_distinct():
    model=Model();original=model.generate
    async def invalid(prompt,**kwargs):return (await original(prompt,**kwargs)).replace('[C1]','[C999]')
    model.generate=invalid;s=service(model=model);r=await s.run(request())
    assert r.errors==['citation_validation_failed']
    assert s.business_diagnostics[0].validation_rule=='citation_reference_invalid'
    model=Model();original=model.generate
    async def no_status(prompt,**kwargs):
        data=json.loads(await original(prompt,**kwargs))
        for f in data.get('facts',[]):f.pop('fact_status')
        return json.dumps(data)
    model.generate=no_status;s=service(model=model);r=await s.run(request())
    assert r.status=='failed' and not s.business_diagnostics
    assert any(e.event_type=='model_call' and e.error_code=='model_output_invalid' for e in s.runtime.context.trace)
