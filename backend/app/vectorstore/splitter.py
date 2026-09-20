"""Deprecated Resource compatibility splitter.

Active documents use services.chunking.text_chunker. TextChunk is still
imported by ChromaStore compatibility methods, so this module is retained.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

from app.core.config import get_settings

_BOUNDARY_PATTERN = re.compile(r"(\n#{1,6}\s+[^\n]+\n|\n\n+|[。！？!?；;]\s*)")


@dataclass(frozen=True)
class TextChunk:
    chunk_id: str
    content: str
    chunk_index: int
    content_hash: str


def split_text(text: str, chunk_size: int | None = None, chunk_overlap: int | None = None) -> list[str]:
    """Backward-compatible helper returning only chunk contents."""

    settings = get_settings()
    size = chunk_size or settings.rag_chunk_size
    overlap = settings.rag_chunk_overlap if chunk_overlap is None else chunk_overlap
    return [chunk.content for chunk in split_text_with_metadata(text, resource_id=0, chunk_size=size, chunk_overlap=overlap)]


def split_text_with_metadata(
    text: str,
    resource_id: int,
    chunk_size: int | None = None,
    chunk_overlap: int | None = None,
) -> list[TextChunk]:
    settings = get_settings()
    size = chunk_size or settings.rag_chunk_size
    overlap = settings.rag_chunk_overlap if chunk_overlap is None else chunk_overlap
    _validate_window(size, overlap)

    cleaned = text.strip()
    if not cleaned:
        return []

    segments = _semantic_segments(cleaned)
    chunks = _pack_segments(segments, size, overlap)
    content_hash = hash_text(cleaned)
    return [
        TextChunk(
            chunk_id=stable_chunk_id(resource_id=resource_id, content_hash=content_hash, chunk_index=index),
            content=chunk,
            chunk_index=index,
            content_hash=content_hash,
        )
        for index, chunk in enumerate(chunks)
    ]


def hash_text(text: str) -> str:
    return hashlib.sha256(text.strip().encode("utf-8")).hexdigest()


def stable_chunk_id(resource_id: int, content_hash: str, chunk_index: int) -> str:
    return f"resource-{resource_id}-{content_hash[:16]}-{chunk_index}"


def _validate_window(chunk_size: int, chunk_overlap: int) -> None:
    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive.")
    if chunk_overlap < 0 or chunk_overlap >= chunk_size:
        raise ValueError("chunk_overlap must be smaller than chunk_size.")


def _semantic_segments(text: str) -> list[str]:
    parts = _BOUNDARY_PATTERN.split(text)
    segments: list[str] = []
    current = ""
    for part in parts:
        if not part:
            continue
        current += part
        if _BOUNDARY_PATTERN.fullmatch(part):
            value = current.strip()
            if value:
                segments.append(value)
            current = ""
    if current.strip():
        segments.append(current.strip())
    if not segments:
        return [text]
    return segments


def _pack_segments(segments: list[str], chunk_size: int, chunk_overlap: int) -> list[str]:
    chunks: list[str] = []
    buffer = ""

    for segment in segments:
        if len(segment) > chunk_size:
            if buffer.strip():
                chunks.append(buffer.strip())
                buffer = ""
            chunks.extend(_char_windows(segment, chunk_size, chunk_overlap))
            continue

        candidate = f"{buffer}\n{segment}".strip() if buffer else segment
        if len(candidate) <= chunk_size:
            buffer = candidate
            continue

        if buffer.strip():
            chunks.append(buffer.strip())
        prefix = chunks[-1][-chunk_overlap:] if chunk_overlap and chunks else ""
        buffer = f"{prefix}{segment}" if prefix else segment
        if len(buffer) > chunk_size:
            chunks.extend(_char_windows(buffer, chunk_size, chunk_overlap))
            buffer = ""

    if buffer.strip():
        chunks.append(buffer.strip())
    return chunks


def _char_windows(text: str, chunk_size: int, chunk_overlap: int) -> list[str]:
    windows: list[str] = []
    start = 0
    while start < len(text):
        end = min(start + chunk_size, len(text))
        chunk = text[start:end].strip()
        if chunk:
            windows.append(chunk)
        if end >= len(text):
            break
        start = end - chunk_overlap
    return windows