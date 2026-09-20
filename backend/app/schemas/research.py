from __future__ import annotations
from typing import Literal, TypedDict
from pydantic import BaseModel, ConfigDict, Field, model_validator
from app.schemas.evidence import Citation, Evidence

ResearchField = Literal['research_problem','system_scenario','method','optimization_objective',
    'optimization_variables','experimental_setting','baselines','main_findings']
DEFAULT_FIELDS = ['method','optimization_objective','optimization_variables','main_findings']


class Strict(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True, str_strip_whitespace=True)


class ResearchTaskRequest(Strict):
    question: str = Field(min_length=1,max_length=4000)
    document_ids: list[int] | None = Field(default=None,min_length=1,max_length=10)
    max_documents: int | None = Field(default=None,ge=1,le=10)
    retrieval_mode: Literal['hybrid','dense','bm25'] = 'hybrid'
    requested_fields: list[ResearchField] = Field(default_factory=lambda:list(DEFAULT_FIELDS),min_length=1,max_length=8)

    @model_validator(mode='after')
    def unique(self):
        if not self.question.strip() or len(set(self.requested_fields)) != len(self.requested_fields):
            raise ValueError('question and unique requested_fields required')
        if self.document_ids is not None and (any(x<=0 for x in self.document_ids) or len(set(self.document_ids))!=len(self.document_ids)):
            raise ValueError('document_ids must be distinct positive IDs')
        return self


class ResearchSubtask(Strict):
    subtask_id: str = Field(pattern=r'^S[1-8]$')
    question: str = Field(min_length=1,max_length=2000)
    target_field: ResearchField
    document_scope: list[int]
    status: Literal['pending','covered','missing'] = 'pending'


class ResearchPlan(Strict):
    subtasks: list[ResearchSubtask] = Field(min_length=1,max_length=8)


class EvidenceLocator(Strict):
    document_id: int = Field(gt=0)
    document_version_id: int = Field(gt=0)
    chunk_id: str = Field(min_length=1)

    @property
    def key(self):
        return f'{self.document_id}:{self.document_version_id}:{self.chunk_id}'


class FactClaim(Strict):
    field: ResearchField
    fact_status: Literal['SUPPORTED', 'INSUFFICIENT_EVIDENCE'] = Field(
        description='SUPPORTED means the requested field has a substantive answer in supplied evidence. '
        'Use INSUFFICIENT_EVIDENCE for unavailable, insufficient, unspecified, not provided, '
        'or unknown information; a locator alone does not make a field supported.')
    value: str = Field(min_length=1,max_length=3000)
    document_id: int = Field(gt=0)
    document_version_id: int = Field(gt=0)
    supporting_evidence_ids: list[str] = Field(min_length=1,max_length=10)


class FactBatch(Strict):
    facts: list[FactClaim] = Field(max_length=40)


class StructuredFact(FactClaim):
    evidence_locators: list[EvidenceLocator] = Field(min_length=1)


class BusinessValidationDiagnostic(Strict):
    run_id: str
    task_id: str
    stage: str
    validation_rule: str
    path: str
    reason: str
    expected_summary: str = Field(max_length=4000)
    actual_summary: str = Field(max_length=4000)
    invalid_reference_ids: list[str] = Field(default_factory=list)
    allowed_reference_ids: list[str] = Field(default_factory=list)


class CoverageCell(Strict):
    document_id: int | None
    field: ResearchField


class Coverage(Strict):
    covered: list[CoverageCell] = Field(default_factory=list)
    missing: list[CoverageCell] = Field(default_factory=list)


class ComparisonItem(Strict):
    document_id: int
    field: ResearchField
    value: str = Field(min_length=1,max_length=4000)
    status: Literal['supported','insufficient_evidence'] = 'supported'


class Synthesis(Strict):
    summary: str = Field(min_length=1,max_length=8000)
    comparison: list[ComparisonItem] = Field(max_length=80)
    limitations: list[str] = Field(default_factory=list,max_length=20)


class ComparisonDraft(ComparisonItem):
    value: str = Field(min_length=1, max_length=4000,
        description='Comparison content only, without citation markers. The system binds citations from validated cell Fact supports.')


class SynthesisDraft(Synthesis):
    comparison: list[ComparisonDraft] = Field(max_length=80)


class ResearchReport(Synthesis):
    citations: list[Citation] = Field(default_factory=list)


class ResearchResponse(Strict):
    run_id: str
    status: Literal['completed','partial','failed']
    report: ResearchReport | None = None
    citations: list[Citation] = Field(default_factory=list)
    coverage: Coverage = Field(default_factory=Coverage)
    retry_count: int = 0
    errors: list[str] = Field(default_factory=list)


class ResearchState(TypedDict):
    task_id: str
    question: str
    document_scope: list[int]
    requested_fields: list[ResearchField]
    plan: ResearchPlan | None
    current_step: str
    subtasks: list[ResearchSubtask]
    evidence_by_subtask: dict[str,list[Evidence]]
    extracted_facts: list[StructuredFact]
    coverage_status: Coverage
    retry_count: int
    final_report: ResearchReport | None
    citations: list[Citation]
    status: str
    errors: list[str]
