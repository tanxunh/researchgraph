import json
from unittest.mock import Mock
from types import SimpleNamespace

import pytest

from app.services.evaluation.retrieval_evaluator import RetrievalEvaluator
from app.services.indexing.incremental_indexer import IncrementalIndexer
from app.services.indexing.version_chunks import version_chunks
from app.services.parsing.text_parser import TextParser
from app.services.retrieval.retrieval_service import ResearchRetrievalService
from app.vectorstore.chroma_store import ChromaStore
from app.vectorstore.embeddings import EmbeddingProviderError

pytestmark = pytest.mark.integration


def test_evaluator_invalid_gold_and_modes(integration_db, vector_store, rule_extractor, tmp_path, monkeypatch):
    result = IncrementalIndexer(vector_store, rule_extractor).import_parsed(
        integration_db, TextParser().parse("Fixture", "Method Alpha uses reliable evidence.", "test:metrics"))
    chunk = version_chunks(integration_db, result["document_id"], result["version"])[0]
    path = tmp_path / "cases.jsonl"
    cases = [{"id": "valid", "query": "Method Alpha", "query_type": "exact", "relevant_chunk_ids": [chunk.stable_chunk_id]},
             {"id": "empty", "query": "empty", "query_type": "invalid", "relevant_chunk_ids": []},
             {"id": "missing", "query": "missing", "relevant_chunk_ids": ["not-current"]}]
    path.write_text("\n".join(json.dumps(c) for c in cases), encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    retrieval = ResearchRetrievalService(integration_db, vector_store)
    report = RetrievalEvaluator(integration_db).run(str(path), top_k=1, modes=["bm25", "dense", "hybrid"],
                                                  dataset_kind="synthetic", retrieval=retrieval)
    assert report["valid_scored_cases"] == 1 and report["invalid_cases"] == 2
    assert report["evaluated_top_k"] == 10
    for values in report["modes"].values():
        assert values["Recall@5"] == 1
        assert values["category_metrics"]["invalid"]["Recall@5"] is None
    assert RetrievalEvaluator(integration_db).latest()["metric_version"] == "retrieval-macro-v2"
    assert retrieval.search("Method Alpha", "dense")["results"] == retrieval.search("Method Alpha", "vector")["results"]


def test_entire_empty_gold_dataset_is_unscored(integration_db, tmp_path, monkeypatch):
    path = tmp_path / "empty.jsonl"
    path.write_text(json.dumps({"id": "a", "query": "anything", "relevant_chunk_ids": []}), encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    retrieval = SimpleNamespace(search=Mock())
    report = RetrievalEvaluator(integration_db).run(str(path), modes=["bm25"], retrieval=retrieval)
    assert report["status"] == "unscored" and report["modes"]["bm25"]["MRR@10"] is None
    retrieval.search.assert_not_called()


def test_existing_collection_metadata_cannot_be_silently_relabelled(vector_store):
    metadata = vector_store.collection.metadata.copy()
    vector_store.collection.modify(metadata={**metadata, "embedding_model": "incompatible-model"})
    with pytest.raises(EmbeddingProviderError, match="rebuild"):
        ChromaStore(vector_store.embedding)
    existing = vector_store.client.get_collection(vector_store.collection_name, embedding_function=None)
    assert existing.metadata["embedding_model"] == "incompatible-model"
