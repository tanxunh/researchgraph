import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.schemas.agent_evaluation import AgentTask, AgentRunRecord
from app.schemas.evidence import Evidence
from app.schemas.research import (ResearchResponse, ResearchReport, Coverage, CoverageCell,
    ComparisonItem, StructuredFact, EvidenceLocator)
from app.services.runtime.contracts import ExecutionSummary, TraceEvent
from app.services.generation.grounded_answer_service import GroundedAnswerService
from app.services.evaluation.agent_evaluation import (measure, aggregate, classify, badcase,
    review_markdown, load_agent_dataset, digest)


def fixture_data(status='completed'):
    e=Evidence(evidence_id='C1',document_id=1,document_version_id=7,document_version=1,
        chunk_id='old',document_title='Paper',ordinal=0,content='The method uses optimization.',
        source_type='text',source_reference='document-version:7',retrieval_source='hybrid')
    loc=EvidenceLocator(document_id=1,document_version_id=7,chunk_id='old')
    fact=StructuredFact(field='method',fact_status='SUPPORTED',value='optimization',document_id=1,document_version_id=7,
        supporting_evidence_ids=[loc.key],evidence_locators=[loc])
    task=AgentTask(task_id='A001',question='Compare methods',task_type='single_paper',document_scope=[1],
        required_fields=['method'],source_query_ids=['Q001','Q002'],notes='test',expected_evidence=[
          dict(**loc.model_dump(),benchmark_document_id='P001',page=None,section=None),
          dict(document_id=1,document_version_id=7,chunk_id='second',benchmark_document_id='P001',page=None,section=None)])
    citation=GroundedAnswerService._citation(e)
    report=ResearchReport(summary='Uses optimization [C1].',comparison=[ComparisonItem(document_id=1,
        field='method',value='Optimization [C1].')],citations=[citation])
    response=ResearchResponse(run_id='run',status=status,report=report,citations=[citation],
        coverage=Coverage(covered=[CoverageCell(document_id=1,field='method')]))
    state={'evidence_by_subtask':{'S1':[e]},'extracted_facts':[fact]}
    trace=[TraceEvent(run_id='run',event_type='tool_call',operation='search_evidence',tool_name='search_evidence',status='succeeded',attempt=1),
        TraceEvent(run_id='run',event_type='node_finished',node='check_coverage',operation='check_coverage',status='succeeded')]
    ex=ExecutionSummary(run_id='run',status=status,duration_ms=100,model_calls=3,tool_calls=1,retrieval_calls=1,retries=0,budget_exceeded=False)
    def resolver(keys):
        return {e.locator:dict(document={'id':1},version={'id':7},chunk_id='old',text=e.content,
            location={'ordinal':0,'page_number':None,'section_title':None})} if e.locator in keys else {}
    return task,response,state,ex,trace,resolver,[e]


def test_true_recall_and_completed_gold_miss_not_a_badcase():
    args=fixture_data();r=measure(*args)
    assert r.metrics.retrieved_expected_evidence_coverage==.5
    assert r.metrics.cited_expected_evidence_coverage==.5
    assert r.metrics.completion=='completed' and r.failure_category is None
    assert r.metrics.grounded_fact_rate==1 and r.metrics.citation_validation.valid
    assert badcase(args[0],r) is None


def test_partial_never_counted_completed_and_honest_partial():
    args=list(fixture_data('partial'));task,response,state,ex,trace,resolve,final=args
    task.required_fields.append('main_findings')
    response.coverage.missing.append(CoverageCell(document_id=1,field='main_findings'))
    response.report.comparison.append(ComparisonItem(document_id=1,field='main_findings',status='insufficient_evidence',value='not enough evidence'))
    response.retry_count=1
    r=measure(*args);summary=aggregate([r])
    assert summary['task_completion_rate']==0 and r.metrics.field_coverage==.5
    assert r.metrics.honest_partial and summary['honest_partial_rate']==1
    assert summary['workflow_retry_rate']==1 and summary['model_retry_rate']==0


def test_completed_missing_doc_field_is_correctness_failure():
    args=list(fixture_data());args[0].document_scope.append(2)
    r=measure(*args)
    assert r.metrics.field_coverage==1 and r.metrics.document_field_coverage==.5
    assert r.metrics.completion=='partial' and r.failure_category=='coverage_failure'
    assert 'completed_with_missing_coverage' in r.metrics.correctness_flags


def test_ungrounded_fact_is_flagged_and_not_covered():
    args=list(fixture_data());args[2]['extracted_facts'][0].supporting_evidence_ids=['wrong']
    r=measure(*args)
    assert r.metrics.grounded_fact_rate==0 and r.metrics.field_coverage==0
    assert 'ungrounded_structured_fact' in r.metrics.correctness_flags


def test_historical_version_mismatch_does_not_count_grounding():
    args=list(fixture_data());original=args[5]
    def wrong(keys):
        rows=original(keys)
        for row in rows.values():row['version']['id']=8
        return rows
    args[5]=wrong;r=measure(*args)
    assert r.metrics.grounded_fact_rate==0 and not r.metrics.citation_validation.valid


def test_invalid_citation_uses_existing_validator():
    args=list(fixture_data());args[1].report.summary='Bad [C999].'
    r=measure(*args)
    assert r.failure_category=='citation_failure' and r.metrics.invalid_citations==1
    assert not r.metrics.citation_validation.valid


def test_missing_citation_report_is_not_validated_as_success():
    args=list(fixture_data());args[1].report.summary='No references.'
    r=measure(*args)
    assert r.metrics.missing_citation and not r.metrics.citation_validation.valid


def test_empty_facts_citations_are_null_not_one_hundred_percent():
    args=list(fixture_data('failed'));args[1].report=None;args[1].citations=[]
    args[2]['extracted_facts']=[];args[2]['evidence_by_subtask']={};args[1].coverage=Coverage()
    r=measure(*args);s=aggregate([r])
    assert s['grounded_fact_rate'] is None and s['citation_structural_validity'] is None
    assert s['supported_claim_rate'] is None and s['unsupported_claim_rate'] is None
    assert s['semantic_review_status']=='SEMANTIC_REVIEW_PENDING'


def test_three_retry_types_and_tool_denominator_exclude_rejections():
    args=list(fixture_data());trace=args[4]
    trace.extend([
        TraceEvent(run_id='run',event_type='tool_call',operation='search_evidence',status='failed',attempt=1),
        TraceEvent(run_id='run',event_type='tool_call',operation='search_evidence',status='succeeded',attempt=2),
        TraceEvent(run_id='run',event_type='tool_call',operation='unregistered',status='rejected',attempt=0),
        TraceEvent(run_id='run',event_type='model_call',operation='plan',status='succeeded',attempt=2)])
    r=measure(*args)
    assert r.metrics.tool_success_rate==pytest.approx(2/3)
    assert r.metrics.model_transient_retries==1 and r.metrics.tool_transient_retries==1
    assert r.metrics.workflow_retries==0


@pytest.mark.parametrize('code,node,category',[
    ('budget_exceeded','extract_facts','budget_exhausted'),
    ('tool_internal_error','retrieve_evidence','tool_failure'),
    ('model_timeout','plan_task','model_failure'),
    ('invalid_model_response','plan_task','planning_failure'),
    ('invalid_model_response','extract_facts','extraction_failure'),
    ('invalid_model_response','synthesize','synthesis_failure'),
    ('citation_validation_failed','validate_citations','citation_failure')])
def test_failure_classification(code,node,category):
    args=list(fixture_data('failed'));args[1].report=None;args[1].citations=[]
    args[3].error_code=code;args[3].budget_exceeded=code=='budget_exceeded'
    args[4].append(TraceEvent(run_id='run',event_type='node_finished',node=node,operation=node,status='failed'))
    assert measure(*args).failure_category==category


def test_result_serializer_and_review_do_not_invent_semantic_labels():
    args=fixture_data();r=measure(*args)
    restored=AgentRunRecord.model_validate_json(r.model_dump_json())
    assert restored.metrics==r.metrics
    text=review_markdown([args[0]],[r])
    assert 'SEMANTIC_REVIEW_PENDING' in text and 'Human label: PENDING' in text
    assert 'old' in text and 'The method uses optimization.' in text
    assert 'system_prompt' not in r.model_dump_json() and 'LLM_API_KEY' not in r.model_dump_json()


def test_badcase_only_observed_failure_and_required_fields_saved():
    args=list(fixture_data('failed'));args[1].report=None;args[1].citations=[]
    args[3].error_code='model_timeout'
    r=measure(*args);bad=badcase(args[0],r)
    assert bad.failure_category=='model_failure' and bad.task_id=='A001'
    assert bad.expected_fields==['method'] and bad.regression_test_status=='RECORDED_NOT_FIXED'


def test_frozen_dataset_exact_gold_union_and_tamper_rejected(tmp_path):
    root=Path('/agent-benchmark')
    if not root.exists():root=Path(__file__).resolve().parents[3]/'benchmarks'/'agent'
    source=Path('/source-benchmark/real-research-pilot-v1.json')
    if not source.exists():source=root.parent/'real_research'/'real-research-pilot-v1.json'
    dataset=load_agent_dataset(root/'agent-eval-pilot-v1.json',source)
    assert len(dataset.tasks)==10 and dataset.source_sha256==digest(source)
    data=json.loads((root/'agent-eval-pilot-v1.json').read_text())
    data['tasks'][0]['expected_evidence'][0]['chunk_id']='fabricated'
    target=tmp_path/'bad.json';target.write_text(json.dumps(data))
    with pytest.raises(ValueError,match='exact_source_union'):
        load_agent_dataset(target,source)
