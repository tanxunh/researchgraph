"""Offline Phase 10 evaluation contracts, separate from production APIs."""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.research import EvidenceLocator, ResearchField, ResearchResponse, StructuredFact
from app.schemas.evidence import Evidence, CitationValidation
from app.services.runtime.contracts import ExecutionSummary, TraceEvent

TaskType = Literal['single_paper', 'cross_document', 'relational', 'multi_hop']
FailureCategory = Literal['planning_failure', 'retrieval_miss', 'evidence_partial',
    'extraction_failure', 'coverage_failure', 'retry_ineffective', 'synthesis_failure',
    'citation_failure', 'budget_exhausted', 'tool_failure', 'model_failure',
    'semantic_unsupported', 'unknown']


class GoldEvidence(EvidenceLocator):
    benchmark_document_id: str
    page: int | None
    section: str | None


class AgentTask(BaseModel):
    model_config = ConfigDict(extra='forbid')
    task_id: str = Field(pattern=r'^A\d{3}$')
    question: str = Field(min_length=1, max_length=4000)
    task_type: TaskType
    document_scope: list[int] = Field(min_length=1, max_length=5)
    required_fields: list[ResearchField] = Field(min_length=1, max_length=8)
    source_query_ids: list[str] = Field(min_length=2, max_length=4)
    expected_evidence: list[GoldEvidence] = Field(min_length=1)
    notes: str

    @model_validator(mode='after')
    def unique(self):
        for values in [self.document_scope, self.required_fields, self.source_query_ids]:
            if len(values) != len(set(values)):
                raise ValueError('duplicate task values')
        if set(self.document_scope) != {e.document_id for e in self.expected_evidence}:
            raise ValueError('scope must equal approved source evidence scope')
        if len({e.key for e in self.expected_evidence}) != len(self.expected_evidence):
            raise ValueError('duplicate expected evidence')
        return self


class AgentDataset(BaseModel):
    model_config = ConfigDict(extra='forbid')
    dataset_id: Literal['agent-eval-pilot-v1']
    dataset_version: int
    source_benchmark: str
    source_sha256: str
    gold_source: Literal['HUMAN_CURATED']
    task_review_status: Literal['CANDIDATE_REVIEW_PENDING']
    semantic_review_status: Literal['SEMANTIC_REVIEW_PENDING']
    corpus_papers: int
    language: str
    tasks: list[AgentTask] = Field(min_length=10, max_length=10)


class TaskMetrics(BaseModel):
    completion: Literal['completed', 'partial', 'failed']
    required_field_count: int
    covered_field_count: int
    field_coverage: float
    required_cell_count: int
    covered_cell_count: int
    document_field_coverage: float
    total_facts: int
    grounded_facts: int
    grounded_fact_rate: float | None
    citation_validation: CitationValidation | None
    valid_cited_evidence: int
    invalid_citations: int
    missing_citation: bool
    expected_count: int
    retrieved_expected_count: int
    cited_expected_count: int
    retrieved_expected_evidence_coverage: float
    cited_expected_evidence_coverage: float
    successful_tool_calls: int
    executed_tool_calls: int
    tool_success_rate: float | None
    workflow_retries: int
    model_transient_retries: int
    tool_transient_retries: int
    honest_partial_eligible: bool
    honest_partial: bool
    correctness_flags: list[str] = Field(default_factory=list)


class AgentRunRecord(BaseModel):
    task_id: str
    run_id: str
    task_type: TaskType
    response: ResearchResponse
    retrieved_evidence: list[Evidence]
    facts: list[StructuredFact]
    final_citation_ids: list[str]
    execution: ExecutionSummary
    trace: list[TraceEvent]
    metrics: TaskMetrics
    failure_category: FailureCategory | None
    root_cause: str | None
    semantic_review_status: Literal['SEMANTIC_REVIEW_PENDING'] = 'SEMANTIC_REVIEW_PENDING'


class BadCase(BaseModel):
    task_id: str
    question: str
    task_type: TaskType
    failure_category: FailureCategory
    expected_fields: list[ResearchField]
    covered_fields: list[ResearchField]
    expected_evidence: list[GoldEvidence]
    retrieved_evidence: list[EvidenceLocator]
    cited_evidence: list[EvidenceLocator]
    trace_summary: ExecutionSummary
    root_cause: str
    regression_test_status: str = 'RECORDED_NOT_FIXED'
