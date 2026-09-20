from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator

from app.schemas.evidence import QAResponse


class QASuccessEnvelope(BaseModel):
    code: Literal[0]
    message: str
    data: QAResponse


class QAErrorEnvelope(BaseModel):
    code: Literal[1]
    message: str
    data: dict

SearchMode = Literal["auto", "vector", "hybrid", "graph_enhanced"]


class DocumentScopeRequest(BaseModel):
    document_ids: list[int] | None = Field(default=None, description="Omitted/null: global. Empty: no documents. Scoped auto uses hybrid; scoped graph is unsupported.")

    @model_validator(mode="after")
    def validate_scope(self):
        if self.document_ids is not None and self.mode == "graph_enhanced":
            raise ValueError("Document scope supports vector/hybrid; graph_enhanced is not supported.")
        return self

    @property
    def retrieval_mode(self):
        return "hybrid" if self.document_ids is not None and self.mode == "auto" else self.mode


class SearchRequest(DocumentScopeRequest):
    query: str = Field(min_length=1)
    mode: SearchMode = "auto"
    top_k: int = Field(default=10, ge=1, le=50)


class QARequest(DocumentScopeRequest):
    question: str = Field(min_length=1)
    mode: SearchMode = "auto"
    top_k: int = Field(default=5, ge=1, le=20)
