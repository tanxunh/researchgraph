from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, HttpUrl, model_validator

SourceType = Literal["pdf", "docx", "url", "text"]


class DocumentImportRequest(BaseModel):
    source_type: Literal["url", "text"] = "text"
    title: str = Field(min_length=1, max_length=255)
    text: str | None = None
    url: HttpUrl | None = None
    source_uri: str | None = None

    @model_validator(mode="after")
    def validate_payload(self):
        if self.source_type == "text" and not (self.text and self.text.strip()):
            raise ValueError("text is required when source_type=text")
        if self.source_type == "url" and not self.url:
            raise ValueError("url is required when source_type=url")
        return self


class ReindexRequest(BaseModel):
    mode: Literal["full", "embedding_only", "graph_only"] = "full"


class ReprocessRequest(BaseModel):
    source_version_id: int | None = Field(default=None, ge=1)
