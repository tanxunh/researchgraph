"""Versioned, human-reviewable research annotations. No automatic gold generation."""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field

QUERY_TYPES = ('factual', 'exact_term', 'semantic', 'relational', 'cross_document', 'multi_hop')


class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True, str_strip_whitespace=True)


class GoldEvidence(StrictModel):
    document_id: int = Field(gt=0)
    document_version_id: int = Field(gt=0)
    chunk_id: str = Field(min_length=1)
    page: int | None = Field(ge=1)
    section: str | None


class ResearchQuery(StrictModel):
    query_id: str = Field(min_length=1)
    question: str = Field(min_length=1)
    query_type: Literal['factual', 'exact_term', 'semantic', 'relational', 'cross_document', 'multi_hop']
    language: Literal['zh', 'en', 'mixed']
    gold_document_ids: list[int]
    gold_evidence: list[GoldEvidence]
    annotation_status: Literal['pending', 'human_reviewed']
    annotator: str
    annotation_notes: str


class CorpusDocument(StrictModel):
    document_id: int = Field(gt=0)
    document_version_id: int = Field(gt=0)
    title: str = Field(min_length=1)
    source_reference: str = Field(min_length=1)
    path: str = Field(min_length=1)
    sha256: str = Field(pattern=r'^[a-f0-9]{64}$')


class ResearchManifest(StrictModel):
    benchmark_version: str = Field(min_length=1)
    corpus_kind: Literal['real_papers']
    documents: list[CorpusDocument]
    queries_path: str
