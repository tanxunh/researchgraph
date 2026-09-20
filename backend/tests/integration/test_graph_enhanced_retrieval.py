from __future__ import annotations

import pytest
from sqlalchemy import select

from app.models.document import DocumentChunk
from app.models.relation import Relation
from app.services.graph.graph_search import GraphSearch
from app.services.indexing.incremental_indexer import IncrementalIndexer
from app.services.retrieval.retrieval_service import ResearchRetrievalService


pytestmark = pytest.mark.integration


def test_graph_enhanced_retrieval_expands_seed_candidates_and_returns_valid_paths(integration_db, vector_store, rule_extractor, make_parsed_doc):

    indexer = IncrementalIndexer(vector_store=vector_store, graph_extractor=rule_extractor)
    doc1 = indexer.import_parsed(
        integration_db,
        make_parsed_doc("integration:graph:method", "Method Alpha Paper", [("alpha", "Paper Alpha USES Method Alpha. Method Alpha TARGETS Task Omega. Method Alpha Method Alpha overview for alpha task search.")]),
    )
    doc2 = indexer.import_parsed(
        integration_db,
        make_parsed_doc("integration:graph:dataset", "Dataset Beta Paper", [("beta", "Method Alpha EVALUATED_ON Dataset Beta. Dataset Beta is the evaluation dataset for the alpha method.")]),
    )
    doc3 = indexer.import_parsed(
        integration_db,
        make_parsed_doc("integration:graph:metric", "Metric Gamma Paper", [("gamma", "Dataset Beta REPORTS Metric Gamma. Metric Gamma measures beta dataset quality.")]),
    )
    assert {doc1["index_action"], doc2["index_action"], doc3["index_action"]} == {"created"}

    service = ResearchRetrievalService(integration_db, vector_store=vector_store)
    vector_result = service.search("Method Alpha overview task omega", mode="vector", top_k=1)
    assert len(vector_result["results"]) == 1
    initial_doc_ids = {item["document"]["id"] for item in vector_result["results"]}
    assert doc1["document_id"] in initial_doc_ids
    assert doc2["document_id"] not in initial_doc_ids

    graph_result = service.search("Method Alpha overview task omega", mode="graph_enhanced", top_k=5)
    result_doc_ids = {item["document"]["id"] for item in graph_result["results"]}
    assert doc2["document_id"] in result_doc_ids
    expanded = [item for item in graph_result["results"] if item["document"]["id"] == doc2["document_id"]]
    assert expanded
    assert any(item["scores"]["graph_rank"] is not None for item in expanded)
    assert any(item["graph_paths"] for item in expanded)

    for item in expanded:
        for path in item["graph_paths"]:
            relation = relation_for_path(integration_db, path)
            assert relation is not None
            evidence = integration_db.get(DocumentChunk, path["evidence_chunk_id"])
            assert evidence is not None
            assert path["evidence_stable_chunk_id"] == evidence.stable_chunk_id
            assert "Dataset Beta" in evidence.text or "Method Alpha" in evidence.text

    graph_search = GraphSearch(integration_db)
    seed_chunk_id = integration_db.scalar(select(DocumentChunk.id).where(DocumentChunk.document_id == doc1["document_id"]))
    graph_search.settings.graph_max_paths = 1
    graph_search.settings.graph_max_neighbors = 1
    graph_search.settings.graph_max_hops = 1
    limited = graph_search.expand("Method Alpha", [seed_chunk_id])
    assert len(limited) <= 1
    if limited:
        assert len(limited[0].graph_paths) <= 1


def relation_for_path(db, path):
    from app.models.entity import Entity

    source = db.scalar(select(Entity).where(Entity.canonical_name == path["source_entity"]))
    target = db.scalar(select(Entity).where(Entity.canonical_name == path["target_entity"]))
    if not source or not target:
        return None
    return db.scalar(
        select(Relation).where(
            Relation.source_entity_id == source.id,
            Relation.target_entity_id == target.id,
            Relation.relation_type == path["relation_type"],
            Relation.evidence_chunk_id == path["evidence_chunk_id"],
        )
    )
