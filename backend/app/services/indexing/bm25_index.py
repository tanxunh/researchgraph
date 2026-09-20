from __future__ import annotations

from collections import Counter
import math
import re
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.document import Document, DocumentChunk
from app.services.indexing.version_chunks import membership_query

_TOKEN_RE = re.compile(r"[A-Za-z0-9_]+|[\u4e00-\u9fff]", re.UNICODE)


@dataclass(frozen=True)
class BM25Hit:
    chunk_id: int
    stable_chunk_id: str
    score: float
    rank: int


class BM25Index:
    """Small deterministic BM25 over persisted chunks; rebuilt from MySQL at query time."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def search(self, query: str, top_k: int, document_ids: list[int] | None = None) -> list[BM25Hit]:
        query_rows = membership_query().with_only_columns(DocumentChunk).where(Document.status == "ready")
        if document_ids is not None:
            query_rows = query_rows.where(Document.id.in_(document_ids))
        chunks = self.db.scalars(query_rows).all()
        if not chunks:
            return []
        query_terms = tokenize(query)
        if not query_terms:
            return []
        tokenized = [tokenize(chunk.text) for chunk in chunks]
        avg_len = sum(len(tokens) for tokens in tokenized) / max(len(tokenized), 1)
        doc_freq = Counter(term for tokens in tokenized for term in set(tokens))
        scored: list[tuple[DocumentChunk, float]] = []
        for chunk, tokens in zip(chunks, tokenized, strict=False):
            tf = Counter(tokens)
            score = 0.0
            for term in query_terms:
                if term not in tf:
                    continue
                idf = math.log(1 + (len(chunks) - doc_freq[term] + 0.5) / (doc_freq[term] + 0.5))
                freq = tf[term]
                denom = freq + 1.5 * (1 - 0.75 + 0.75 * len(tokens) / max(avg_len, 1))
                score += idf * (freq * 2.5) / max(denom, 1e-9)
            if score > 0:
                scored.append((chunk, score))
        ranked = sorted(scored, key=lambda item: item[1], reverse=True)[:top_k]
        return [BM25Hit(chunk_id=chunk.id, stable_chunk_id=chunk.stable_chunk_id, score=round(score, 4), rank=i + 1) for i, (chunk, score) in enumerate(ranked)]


def tokenize(text: str) -> list[str]:
    return [token.lower() for token in _TOKEN_RE.findall(text or "")]
