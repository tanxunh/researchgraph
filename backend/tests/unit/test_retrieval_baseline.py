from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.services.indexing.bm25_index import BM25Index, tokenize
from app.services.retrieval.fusion_ranker import FusionRanker
from app.services.retrieval.retrieval_service import ResearchRetrievalService
from app.vectorstore.embeddings import EmbeddingProviderError


def test_rrf_stable_and_no_duplicate_candidate():
    dense = [(1, "A", .9), (2, "B", .8), (3, "C", .7)]
    bm25 = [(2, "B", 4), (4, "D", 3), (1, "A", 2)]
    result = FusionRanker(60).rank(dense, bm25, [], 10)
    assert [item.stable_chunk_id for item in result] == ["B", "A", "D", "C"]
    assert len({item.chunk_id for item in result}) == 4
    assert result[0].fusion_score == pytest.approx(1/62 + 1/61)


def test_bm25_ranking_and_tokenization():
    assert tokenize("BGE Redis 中文!") == ["bge", "redis", "中", "文"]
    db = Mock()
    db.scalars.return_value.all.return_value = [
        SimpleNamespace(id=1, stable_chunk_id="A", text="redis redis cache"),
        SimpleNamespace(id=2, stable_chunk_id="B", text="unrelated database"),
        SimpleNamespace(id=3, stable_chunk_id="C", text="redis cache database other words")]
    hits = BM25Index(db).search("redis", 5)
    assert [hit.chunk_id for hit in hits] == [1, 3]


def test_bm25_mode_never_calls_dense_or_graph(monkeypatch):
    service = ResearchRetrievalService(Mock())
    monkeypatch.setattr(service, "_dense_candidates", Mock(side_effect=AssertionError("dense called")))
    monkeypatch.setattr(service.graph_search, "expand", Mock(side_effect=AssertionError("graph called")))
    monkeypatch.setattr(BM25Index, "search", lambda *args: [])
    result = service.search("query", mode="bm25")
    assert result["results"] == [] and service._vector_store is None


def test_empty_current_embedding_index_requires_rebuild():
    db = Mock()
    db.scalar.return_value = 1
    store = Mock()
    store.search_documents.return_value = []
    store.count.return_value = 0
    service = ResearchRetrievalService(db, store)
    with pytest.raises(EmbeddingProviderError, match="rebuild index"):
        service.search("query", mode="dense")
