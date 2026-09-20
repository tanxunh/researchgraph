from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from sqlalchemy import event, select

from app.models.document import Document
from app.models.entity import Entity, EntityAlias
from app.models.relation import Relation
from app.services.graph.extraction_schema import ChunkGraphExtraction
from app.services.graph.graph_search import GraphSearch
from app.services.generation.evidence_builder import EvidenceBuilder
from app.services.indexing.incremental_indexer import IncrementalIndexer
from app.services.indexing.version_chunks import version_chunks
from app.services.indexing.hash_service import normalize_entity_name
from app.services.retrieval.retrieval_service import ResearchRetrievalService

pytestmark = pytest.mark.integration


@pytest.fixture
def graph_ctx(integration_db, vector_store, make_parsed_doc):
    db = integration_db
    extractor = SimpleNamespace(extract=lambda text: ChunkGraphExtraction())
    indexer = IncrementalIndexer(vector_store, extractor)
    result = indexer.import_parsed(db, make_parsed_doc("phase5:graph", "Graph fixture", [
        ("ab", "Proximal Policy Optimization uses Dataset Beta."),
        ("bc", "Dataset Beta reports Metric Gamma."),
        ("ca", "Metric Gamma relates to Proximal Policy Optimization.")]))
    chunks = version_chunks(db, result["document_id"], result["version"])
    entities = []
    for name in ("Proximal Policy Optimization", "Dataset Beta", "Metric Gamma"):
        entity = Entity(entity_type="Concept", canonical_name=name, normalized_name=normalize_entity_name(name))
        db.add(entity)
        entities.append(entity)
    db.flush()
    db.add(EntityAlias(entity_id=entities[0].id, alias="PPO", normalized_alias="ppo"))
    edges = []
    for source, target, chunk in [(0, 1, chunks[0]), (1, 2, chunks[1])]:
        edge = Relation(source_entity_id=entities[source].id, target_entity_id=entities[target].id,
                        relation_type="USES", evidence_chunk_id=chunk.id, confidence=.9, extractor_version="test")
        db.add(edge)
        edges.append(edge)
    db.commit()
    graph = GraphSearch(db)
    return SimpleNamespace(db=db, store=vector_store, graph=graph, chunks=chunks, entities=entities,
                           edges=edges, document_id=result["document_id"])


@pytest.mark.parametrize("query", ["Proximal Policy Optimization", "PPO", "使用 PPO？"])
def test_canonical_alias_linking(graph_ctx, query):
    ctx = graph_ctx
    assert [e.id for e in ctx.graph.find_query_entities(query)] == [ctx.entities[0].id]


def test_real_two_hops_score_and_version_trace(graph_ctx):
    ctx = graph_ctx
    hits = ctx.graph.expand("PPO", [])
    assert [h.chunk_id for h in hits] == [ctx.chunks[0].id, ctx.chunks[1].id]
    assert [h.graph_paths[0].hop_count for h in hits] == [1, 2]
    assert hits[0].score > hits[1].score
    path = hits[1].graph_paths[0]
    assert len(path.relations) == 2 and len(path.entities) == 3
    assert all(edge["document_version_id"] == ctx.chunks[0].document_version_id for edge in path.relations)


def test_one_hop_cannot_emit_two_hop(graph_ctx):
    ctx = graph_ctx
    ctx.graph.settings.graph_max_hops = 1
    assert [h.chunk_id for h in ctx.graph.expand("PPO", [])] == [ctx.chunks[0].id]


def test_cycle_terminates_and_deduplicates_relations(graph_ctx):
    ctx = graph_ctx
    ctx.db.add(Relation(source_entity_id=ctx.entities[2].id, target_entity_id=ctx.entities[0].id,
                        relation_type="RELATED_TO", evidence_chunk_id=ctx.chunks[2].id,
                        confidence=.9, extractor_version="test"))
    ctx.db.commit()
    hits = ctx.graph.expand("PPO", [])
    assert len(hits) <= 3
    assert ctx.graph.last_stats["visited_entities"] == 3
    ids = [edge["relation_id"] for h in hits for edge in h.graph_paths[0].relations]
    assert len(set(ids)) <= 3 and all(h.graph_paths[0].hop_count <= 2 for h in hits)


@pytest.mark.parametrize("limit,value", [("graph_max_expanded_entities", 1), ("graph_max_paths", 1)])
def test_strict_caps(graph_ctx, limit, value):
    ctx = graph_ctx
    setattr(ctx.graph.settings, limit, value)
    hits = ctx.graph.expand("PPO", [])
    if limit == "graph_max_expanded_entities":
        assert not hits and ctx.graph.last_stats["visited_entities"] <= 1
    else:
        assert len(hits) <= 1 and ctx.graph.last_stats["path_count"] <= 1


def test_missing_evidence_relation_is_excluded(graph_ctx, monkeypatch):
    ctx = graph_ctx
    rows = ctx.graph._edges([ctx.entities[0].id], set(), 20)
    relation, source, target, chunk, version = rows[0]
    monkeypatch.setattr(ctx.graph, "_edges", lambda *args: [(relation, source, target, None, version)])
    assert ctx.graph.expand("PPO", []) == []


def test_nonready_evidence_cannot_be_traversed(graph_ctx):
    ctx = graph_ctx
    ctx.db.get(Document, ctx.document_id).status = "publish_failed"
    ctx.db.commit()
    assert ctx.graph.expand("PPO", []) == []


def test_same_chunk_multiple_paths_only_one_candidate(graph_ctx):
    ctx = graph_ctx
    ctx.edges[1].evidence_chunk_id = ctx.chunks[0].id
    ctx.db.commit()
    hits = ctx.graph.expand("PPO", [])
    assert len(hits) == 1 and hits[0].graph_paths[0].hop_count == 1


def test_graph_queries_batched_with_sql_limits(graph_ctx):
    ctx = graph_ctx
    statements = []
    connection = ctx.db.get_bind()
    def record(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(statement)
    event.listen(connection, "before_cursor_execute", record)
    try:
        ctx.graph.expand("PPO", [])
    finally:
        event.remove(connection, "before_cursor_execute", record)
    assert len(statements) == 3  # One linking statement plus two joined BFS batches.
    assert all("LIMIT" in sql.upper() for sql in statements)


@pytest.mark.parametrize("mode,query,expected", [
    ("auto", "PPO 的全称是什么？", False),
    ("auto", "哪些方法使用 PPO？", True),
    ("hybrid", "哪些方法使用 PPO？", False),
    ("graph_enhanced", "PPO", True),
])
def test_routing_calls_graph_only_when_requested(graph_ctx, monkeypatch, mode, query, expected):
    ctx = graph_ctx
    service = ResearchRetrievalService(ctx.db, ctx.store)
    spy = Mock(wraps=service.graph_search.expand)
    monkeypatch.setattr(service.graph_search, "expand", spy)
    result = service.search(query, mode=mode)
    assert spy.called == expected
    assert result["routing"]["graph_enabled"] == expected


def test_graph_candidate_converts_to_phase4_evidence(graph_ctx, monkeypatch):
    ctx = graph_ctx
    service = ResearchRetrievalService(ctx.db, ctx.store)
    monkeypatch.setattr(service, "_dense_candidates", lambda *args: [])
    from app.services.indexing.bm25_index import BM25Index
    monkeypatch.setattr(BM25Index, "search", lambda *args: [])
    result = service.search("PPO", mode="graph_enhanced")
    evidence = EvidenceBuilder().build(result)
    assert len(evidence) == 2
    assert evidence[1].document_version_id == ctx.chunks[1].document_version_id
    assert evidence[1].chunk_id == ctx.chunks[1].stable_chunk_id
