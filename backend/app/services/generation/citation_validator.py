"""Deterministic structural/reference validation; never semantic entailment."""
from __future__ import annotations

import re
from collections.abc import Callable

from app.schemas.evidence import CitationValidation, Evidence

INSUFFICIENT_ANSWER = "无法从提供的资料确认答案。"
_CITATION = re.compile(r"\[C[1-9][0-9]*\]")
# After removing canonical citations, any citation-like notation is malformed.
_MALFORMED = re.compile(r"[\[［]\s*[Cc]|\b[Cc]\s*\d+\s*[\]］]")


class CitationValidator:
    def __init__(self, resolver: Callable):
        self.resolver = resolver

    def validate(self, answer: str, evidence: list[Evidence]) -> CitationValidation:
        available = {item.evidence_id: item for item in evidence}
        matches = list(_CITATION.finditer(answer))
        handles = [match.group()[1:-1] for match in matches]
        used = list(dict.fromkeys(handles))
        invalid = [handle for handle in used if handle not in available]
        warnings = []
        if len(handles) != len(used):
            warnings.append("repeated_citation")
        remaining = _CITATION.sub("", answer)
        malformed = bool(_MALFORMED.search(remaining)) or any(
            (match.start() > 0 and answer[match.start() - 1] in "[［")
            or (match.end() < len(answer) and answer[match.end()] in "]］")
            for match in matches)
        missing = not used and answer.strip() != INSUFFICIENT_ANSWER
        if malformed:
            warnings.append("malformed_citation")
        cited = [available[handle] for handle in used if handle in available]
        resolved = self.resolver([item.locator for item in cited]) if cited else {}
        for item in cited:
            row = resolved.get(item.locator)
            if not self._matches(item, row):
                invalid.append(item.evidence_id)
                warnings.append("unresolved_or_mismatched_evidence")
        valid = not (invalid or missing or malformed)
        if any(not item.source_snapshot_available for item in cited):
            warnings.append("raw_source_unavailable")
        return CitationValidation(
            valid=valid, used_citation_ids=used, invalid_citation_ids=list(dict.fromkeys(invalid)),
            missing_citation=missing, warnings=list(dict.fromkeys(warnings)),
            reason=None if valid else "citation_validation_failed",
        )

    @staticmethod
    def _matches(item: Evidence, row: dict | None) -> bool:
        if not row:
            return False
        return (row["document"]["id"] == item.document_id
                and row["version"]["id"] == item.document_version_id
                and row["chunk_id"] == item.chunk_id
                and row["text"] == item.content
                and row["location"] == {"ordinal": item.ordinal, "page_number": item.page,
                                        "section_title": item.section})


class CitationValidationError(Exception):
    def __init__(self, validation: CitationValidation):
        super().__init__("Answer citation validation failed.")
        self.validation = validation
