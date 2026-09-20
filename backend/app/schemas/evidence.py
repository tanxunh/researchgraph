"""Evidence identity is version-scoped; C# is only a response-local handle."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class Evidence(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")

    evidence_id: str = Field(pattern=r"^C[1-9][0-9]*$")
    document_id: int = Field(gt=0)
    document_version_id: int = Field(gt=0)
    document_version: int = Field(gt=0)
    chunk_id: str = Field(min_length=1)
    document_title: str
    page: int | None = Field(default=None, ge=1)
    section: str | None = None
    ordinal: int = Field(ge=0)
    content: str = Field(min_length=1)
    source_type: str = Field(min_length=1)
    source_reference: str
    source_snapshot_available: bool = False
    retrieval_source: str
    retrieval_score: float | None = Field(default=None, allow_inf_nan=False)

    @property
    def locator(self) -> tuple[int, str]:
        return self.document_version_id, self.chunk_id

    def context(self) -> str:
        return (f"[{self.evidence_id}]\nDocument: {self.document_title}\n"
                f"Version: {self.document_version_id}\nPage: {self.page}\n"
                f"Section: {self.section}\nContent: {self.content}")


class CitationValidation(BaseModel):
    valid: bool
    used_citation_ids: list[str] = Field(default_factory=list)
    invalid_citation_ids: list[str] = Field(default_factory=list)
    missing_citation: bool = False
    warnings: list[str] = Field(default_factory=list)
    reason: str | None = None


class Citation(BaseModel):
    citation_id: str
    document_id: int
    document_version_id: int
    chunk_id: str
    document_title: str
    page: int | None
    section: str | None
    ordinal: int
    snippet: str
    source_type: str
    source_reference: str
    source_snapshot_available: bool
    # Preserve the original nested API fields without exposing storage paths.
    document: dict
    location: dict


class QAResponse(BaseModel):
    status: Literal["answered", "insufficient_evidence"]
    answer: str
    citations: list[Citation]
    evidence_count: int
    retrieved_evidence_count: int
    citation_validation: CitationValidation
    search: dict
