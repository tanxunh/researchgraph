from __future__ import annotations

import logging
import time
from dataclasses import asdict

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.document import Document, DocumentChunk
from app.models.entity import Entity, EntityMention
from app.services.graph.graph_search import GraphSearch
from app.services.graph.query_analyzer import analyze_query
from app.services.indexing.bm25_index import BM25Index
from app.services.retrieval.active_candidates import matches_candidate, resolve_active
from app.services.retrieval.fusion_ranker import FusionRanker
from app.vectorstore.chroma_store import ChromaStore

logger = logging.getLogger(__name__)


class GraphUnavailableError(ValueError):
    pass


class ResearchRetrievalService:
    # Chroma query has no cursor. Repeat with a doubled prefix, at most 3 queries.
    # Twofold overfetch covers modest orphan rates; 200 bounds SQL and vector work.
    candidate_limit = 200
    max_dense_rounds = 3

    def __init__(self, db: Session, vector_store: ChromaStore | None = None) -> None:
        self.db = db
        self.settings = get_settings()
        self._vector_store = vector_store
        self.graph_search = GraphSearch(db)

    @property
    def vector_store(self):
        if self._vector_store is None:
            self._vector_store = ChromaStore()
        return self._vector_store

    def search(self, query: str, mode: str = "auto", top_k: int = 10, *, rerank: bool | None = None,
               document_ids: list[int] | None = None) -> dict:
        if mode not in {"auto", "vector", "dense", "bm25", "hybrid", "graph_enhanced"}:
            raise ValueError("Unsupported retrieval mode")
        use_reranker = self.settings.reranker_enabled if rerank is None else rerank
        if use_reranker:
            from app.services.retrieval.reranker import get_reranker, rerank_candidates
            result = self.search(query, mode, self.settings.reranker_candidate_n, rerank=False, document_ids=document_ids)
            started = time.perf_counter()
            rows, metadata = rerank_candidates(query, result["results"], get_reranker(self.settings))
            result["results"] = rows[:min(top_k, self.settings.reranker_final_k)]
            result["reranker"] = metadata
            result["timing"]["reranker_ms"] = round(elapsed_ms(started), 3)
            result["timing"]["total_ms"] += result["timing"]["reranker_ms"]
            return result
        if document_ids is not None and mode in {"auto", "graph_enhanced"}:
            raise ValueError("Scoped retrieval supports dense/bm25/hybrid only.")
        requested_mode = mode
        analysis = analyze_query(query)
        if mode == "auto":
            mode = "graph_enhanced" if analysis.use_graph else "hybrid"
        routing_reason = analysis.reason if requested_mode == "auto" else "explicit_mode"
        if mode == "graph_enhanced" and not self.graph_search.is_available():
            if requested_mode != "auto":
                raise GraphUnavailableError("Graph index unavailable for current-ready evidence. Use hybrid retrieval.")
            mode = "hybrid"
            routing_reason = "graph_unavailable_hybrid_fallback"
        start_total = time.perf_counter()
        timing = {}
        dense_start = time.perf_counter()
        dense_rows = (self._dense_candidates(query, top_k, document_ids) if document_ids is not None else self._dense_candidates(query, top_k)) if mode != "bm25" else []
        timing["dense_ms"] = elapsed_ms(dense_start)

        bm25_start = time.perf_counter()
        bm25_rows = []
        if mode in {"bm25", "hybrid", "graph_enhanced"}:
            bm25 = BM25Index(self.db)
            hits = (bm25.search(query, self.candidate_limit, document_ids) if document_ids is not None
                    else bm25.search(query, self.candidate_limit))
            active = resolve_active(self.db, [hit.chunk_id for hit in hits])
            bm25_rows = [(h.chunk_id, h.stable_chunk_id, h.score) for h in hits
                         if matches_candidate(active.get(h.chunk_id), h.chunk_id, h.stable_chunk_id)]
        timing["bm25_ms"] = elapsed_ms(bm25_start)

        graph_start = time.perf_counter()
        graph_rows = []
        if mode == "graph_enhanced":
            expansions = self.graph_search.expand(query, [row[0] for row in dense_rows + bm25_rows])
            active = resolve_active(self.db, [item.chunk_id for item in expansions])
            for item in expansions:
                if not matches_candidate(active.get(item.chunk_id), item.chunk_id, item.stable_chunk_id):
                    continue
                paths = [asdict(path) for path in item.graph_paths
                         if path.evidence_chunk_id == item.chunk_id
                         and path.evidence_stable_chunk_id == item.stable_chunk_id]
                if not paths:
                    continue
                graph_rows.append((item.chunk_id, item.stable_chunk_id, item.score, item.matched_entities, paths))
        timing["graph_ms"] = elapsed_ms(graph_start)

        fusion_start = time.perf_counter()
        ranked = FusionRanker(self.settings.rrf_k, self.settings.graph_rrf_weight).rank(
            dense_rows, bm25_rows, graph_rows, self.candidate_limit * 3)
        active = resolve_active(self.db, [item.chunk_id for item in ranked])
        if document_ids is not None:
            active = {key: value for key, value in active.items() if value[1].id in document_ids}
        ranked = [item for item in ranked if matches_candidate(
            active.get(item.chunk_id), item.chunk_id, item.stable_chunk_id)][:top_k]
        names = self._entity_names([item.chunk_id for item in ranked])
        results = [self._serialize_candidate(item, *active[item.chunk_id], names.get(item.chunk_id, [])) for item in ranked]
        timing["fusion_ms"] = elapsed_ms(fusion_start)
        timing["total_ms"] = elapsed_ms(start_total)
        return {"query": query, "mode": requested_mode, "results": results,
                "routing": {"query_type": analysis.query_type, "effective_mode": mode,
                            "graph_enabled": mode == "graph_enhanced",
                            "reason": routing_reason},
                "timing": {key: round(value, 3) for key, value in timing.items()}}

    def _dense_candidates(self, query, top_k, document_ids=None):
        count = min(self.candidate_limit, max(top_k * 2, self.settings.dense_top_k))
        invalid_ids = set()
        rows = []
        for _ in range(self.max_dense_rounds):
            hits = (self.vector_store.search_documents(query, count, document_ids=document_ids)
                    if document_ids is not None else self.vector_store.search_documents(query, count))
            if not hits and self.vector_store.count() == 0:
                ready = self.db.scalar(select(Document.id).where(Document.status == "ready").limit(1))
                if ready is not None:
                    from app.vectorstore.embeddings import EmbeddingProviderError
                    raise EmbeddingProviderError("Current embedding index is empty; rebuild index with the configured provider/model.")
            active = resolve_active(self.db, [h.document_chunk_id for h in hits if h.document_chunk_id])
            rows = []
            for hit in hits:
                pair = active.get(hit.document_chunk_id)
                if not matches_candidate(pair, hit.document_chunk_id, hit.chunk_id):
                    invalid_ids.add(hit.chunk_id)
                    continue
                chunk, document = pair
                if (hit.document_id != document.id or hit.document_version_id != chunk.document_version_id
                        or hit.chunk_hash != chunk.chunk_hash):
                    invalid_ids.add(hit.chunk_id)
                    continue
                rows.append((chunk.id, chunk.stable_chunk_id, hit.score))
            if len(rows) >= top_k or len(hits) < count or count == self.candidate_limit:
                break
            count = min(self.candidate_limit, count * 2)
        if invalid_ids:
            logger.warning("orphan_candidate_filtered_count=%s", len(invalid_ids),
                           extra={"orphan_candidate_filtered_count": len(invalid_ids),
                                  "orphan_candidate_ids": sorted(str(x) for x in invalid_ids)})
        return rows

    def _entity_names(self, ids):
        names = {}
        if ids:
            rows = self.db.execute(select(EntityMention.chunk_id, Entity.entity_type, Entity.canonical_name)
                                   .join(Entity, Entity.id == EntityMention.entity_id)
                                   .where(EntityMention.chunk_id.in_(ids))).all()
            for chunk_id, entity_type, name in rows:
                names.setdefault(chunk_id, []).append(f"{entity_type}: {name}")
        return names

    def status(self) -> dict:
        return {"document_count": self.db.query(Document).count(),
                "chunk_count": self.db.query(DocumentChunk).count()}

    def _serialize_candidate(self, candidate, chunk, document, names) -> dict:
        return {
            "chunk_id": chunk.stable_chunk_id,
            "text": chunk.text,
            "document": {"id": document.id, "title": chunk.version.title if chunk.version.title is not None else document.title,
                         "source_uri": chunk.version.source_uri if chunk.version.source_uri is not None else document.source_uri, "version": document.current_version,
                         "version_id": chunk.document_version_id},
            "document_version_id": chunk.document_version_id,
            "source_type": chunk.version.source_type or document.source_type,
            "source_snapshot_available": bool(chunk.version.source_storage_key),
            "chunk_occurrence_id": chunk.id,
            "location": {"page_number": chunk.page_number, "section_title": chunk.section_title,
                         "ordinal": chunk.chunk_index},
            "scores": {
                "dense_rank": candidate.dense_rank, "dense_score": candidate.dense_score,
                "bm25_rank": candidate.bm25_rank, "bm25_score": candidate.bm25_score,
                "graph_rank": candidate.graph_rank, "graph_score": candidate.graph_score,
                "fusion_score": round(candidate.fusion_score, 6),
            },
            "matched_entities": sorted(set(candidate.matched_entities + names)),
            "graph_paths": candidate.graph_paths,
        }


def elapsed_ms(start: float) -> float:
    return (time.perf_counter() - start) * 1000
