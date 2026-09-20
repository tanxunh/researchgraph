from __future__ import annotations

import re

from app.services.parsing.base import ParsedDocument, ParsedSection, ParserError


_WHITESPACE_RE = re.compile(r"\n{3,}")


class TextParser:
    source_type = "text"

    def parse(self, title: str, text: str, source_uri: str | None = None) -> ParsedDocument:
        normalized = self._normalize(text)
        if not normalized:
            raise ParserError("Text input is empty; indexing was stopped.")
        resolved_uri = source_uri or f"text:{title.strip() or 'untitled'}"
        sections = self._sections(normalized, resolved_uri)
        document = ParsedDocument(
            title=(title.strip() or "Untitled Text")[:255],
            source_type="text",
            source_uri=resolved_uri,
            text=normalized,
            sections=sections,
            metadata={"parser": "TextParser"},
        )
        document.validate()
        return document

    def _sections(self, text: str, source_uri: str) -> list[ParsedSection]:
        blocks = [block.strip() for block in re.split(r"\n\s*\n", text) if block.strip()]
        return [ParsedSection(text=block, order=index, source_uri=source_uri) for index, block in enumerate(blocks)]

    def _normalize(self, text: str) -> str:
        lines = [line.rstrip() for line in (text or "").splitlines()]
        compact = "\n".join(lines).strip()
        return _WHITESPACE_RE.sub("\n\n", compact)
