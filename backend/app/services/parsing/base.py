from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from app.storage.base import SourceReference


SourceType = Literal["pdf", "docx", "url", "text"]


class ParserError(Exception):
    """Raised when a document cannot be parsed into usable text."""


@dataclass(frozen=True)
class ParsedSection:
    text: str
    order: int
    page_number: int | None = None
    section_title: str | None = None
    source_uri: str | None = None


@dataclass(frozen=True)
class ParsedDocument:
    title: str
    source_type: SourceType
    source_uri: str
    text: str
    sections: list[ParsedSection]
    metadata: dict[str, Any] = field(default_factory=dict)

    raw_source: SourceReference | None = None

    def validate(self) -> None:
        if not self.text.strip():
            raise ParserError("Parsed document text is empty; indexing was stopped.")
        if self.source_type not in {"pdf", "docx", "url", "text"}:
            raise ParserError(f"Unsupported source_type: {self.source_type}")
