"""Fixed internal read-only tools, with no dynamic registration or dispatch."""
from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Annotated, Callable, Literal

from pydantic import BaseModel, ConfigDict, Field, RootModel

from app.schemas.evidence import Evidence
from app.schemas.research import EvidenceLocator
from app.services.generation.evidence_builder import EvidenceBuilder
from app.services.runtime.contracts import AgentRuntimeError


class SearchInput(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    query: str = Field(min_length=1, max_length=4000)
    document_scope: list[Annotated[int, Field(gt=0)]] | None = Field(default=None, max_length=10)
    top_k: int = Field(ge=1, le=200)
    retrieval_mode: Literal['dense', 'bm25', 'hybrid'] = 'hybrid'


class SearchOutput(RootModel[list[Evidence]]):
    pass


class ResolveInput(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    locators: list[EvidenceLocator] = Field(max_length=80)


class ResolvedDocument(BaseModel):
    model_config = ConfigDict(strict=True)
    id: int = Field(gt=0)
    title: str | None = None
    source_uri: str | None = None


class ResolvedVersion(BaseModel):
    model_config = ConfigDict(strict=True)
    id: int = Field(gt=0)
    number: int | None = None
    parser_version: str | None = None
    chunking_config_hash: str | None = None


class ResolvedLocation(BaseModel):
    model_config = ConfigDict(strict=True)
    ordinal: int = Field(ge=0)
    page_number: int | None = None
    section_title: str | None = None


class ResolvedSource(BaseModel):
    model_config = ConfigDict(strict=True)
    checksum: str | None = None
    storage_key: str | None = None
    content_type: str | None = None
    original_url: str | None = None


class ResolvedEvidence(BaseModel):
    model_config = ConfigDict(strict=True, extra='forbid')
    document: ResolvedDocument
    version: ResolvedVersion
    chunk_id: str = Field(min_length=1)
    chunk_occurrence_id: int | None = None
    text: str = Field(min_length=1)
    location: ResolvedLocation
    source: ResolvedSource | None = None


class ResolveOutput(RootModel[list[ResolvedEvidence]]):
    pass


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    description: str
    input_schema: type[BaseModel]
    output_schema: type[BaseModel]
    handler: Callable


class ToolRegistry:
    """Dependencies are injected services, never names supplied by a model."""
    def __init__(self, retrieval, resolver: Callable, *, max_evidence: int = 5):
        builder = EvidenceBuilder(max_count=max_evidence)

        def search(data: SearchInput) -> list[Evidence]:
            kwargs = {'mode': data.retrieval_mode, 'top_k': data.top_k, 'rerank': False}
            if data.document_scope is not None:
                kwargs['document_ids'] = data.document_scope
            result = builder.build(retrieval.search(data.query, **kwargs))
            if data.document_scope is not None and any(e.document_id not in data.document_scope for e in result):
                raise AgentRuntimeError('tool_business_error')
            return result

        def resolve(data: ResolveInput) -> list[dict]:
            wanted = {(e.document_id, e.document_version_id, e.chunk_id) for e in data.locators}
            keys = list(dict.fromkeys((e.document_version_id, e.chunk_id) for e in data.locators))
            rows = resolver(keys)
            result = []
            for key, row in rows.items():
                # A resolver may omit unavailable evidence; it must never substitute current.
                value = ResolvedEvidence.model_validate(row)
                identity = (value.document.id, value.version.id, value.chunk_id)
                if identity not in wanted or key != (value.version.id, value.chunk_id):
                    raise AgentRuntimeError('tool_output_invalid')
                result.append(row)
            return result

        self._definitions = MappingProxyType({
            'search_evidence': ToolDefinition('search_evidence', 'Retrieve current-ready scoped evidence.',
                                               SearchInput, SearchOutput, search),
            'resolve_evidence': ToolDefinition('resolve_evidence', 'Resolve exact historical immutable locators.',
                                               ResolveInput, ResolveOutput, resolve),
        })

    def get(self, name: str) -> ToolDefinition:
        if name not in self._definitions:
            raise AgentRuntimeError('tool_not_found')
        return self._definitions[name]
