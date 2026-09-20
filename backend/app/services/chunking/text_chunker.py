from __future__ import annotations

from dataclasses import dataclass

from app.core.config import get_settings
from app.services.indexing.hash_service import hash_text
from app.services.parsing.base import ParsedDocument, ParsedSection


@dataclass(frozen=True)
class ChunkCandidate:
    chunk_index: int
    text: str
    chunk_hash: str
    page_number: int | None
    section_title: str | None
    token_count: int


class TextChunker:
    def __init__(self, chunk_size: int | None = None, chunk_overlap: int | None = None) -> None:
        settings = get_settings()
        self.chunk_size = chunk_size or settings.chunk_size
        self.chunk_overlap = settings.chunk_overlap if chunk_overlap is None else chunk_overlap
        if self.chunk_overlap >= self.chunk_size:
            raise ValueError("chunk_overlap must be smaller than chunk_size")

    def chunk(self, parsed: ParsedDocument) -> list[ChunkCandidate]:
        candidates: list[ChunkCandidate] = []
        for section in parsed.sections or [ParsedSection(text=parsed.text, order=0, source_uri=parsed.source_uri)]:
            for text in self._windows(section.text):
                clean = text.strip()
                if not clean:
                    continue
                candidates.append(
                    ChunkCandidate(
                        chunk_index=len(candidates),
                        text=clean,
                        chunk_hash=hash_text(clean),
                        page_number=section.page_number,
                        section_title=section.section_title,
                        token_count=self._token_count(clean),
                    )
                )
        return candidates

    def _windows(self, text: str) -> list[str]:
        paragraphs = [part.strip() for part in text.split("\n\n") if part.strip()]
        chunks: list[str] = []
        buffer = ""
        for paragraph in paragraphs or [text]:
            if len(paragraph) > self.chunk_size:
                if buffer:
                    chunks.append(buffer.strip())
                    buffer = ""
                chunks.extend(self._hard_windows(paragraph))
                continue
            candidate = f"{buffer}\n\n{paragraph}".strip() if buffer else paragraph
            if len(candidate) <= self.chunk_size:
                buffer = candidate
            else:
                if buffer:
                    chunks.append(buffer.strip())
                prefix = chunks[-1][-self.chunk_overlap :] if chunks and self.chunk_overlap else ""
                buffer = f"{prefix}{paragraph}" if prefix else paragraph
        if buffer.strip():
            chunks.append(buffer.strip())
        return chunks

    def _hard_windows(self, text: str) -> list[str]:
        windows: list[str] = []
        start = 0
        while start < len(text):
            end = min(start + self.chunk_size, len(text))
            windows.append(text[start:end].strip())
            if end >= len(text):
                break
            start = end - self.chunk_overlap
        return [window for window in windows if window]

    def _token_count(self, text: str) -> int:
        return max(1, len(text) // 2)
