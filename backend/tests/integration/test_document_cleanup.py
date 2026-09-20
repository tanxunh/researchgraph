from __future__ import annotations

import pytest
from sqlalchemy import func, select

from app.models.document import Document, DocumentChunk
from app.models.entity import Entity, EntityMention
from app.models.relation import Relation
from app.services.indexing.bm25_index import BM25Index
from app.services.indexing.incremental_indexer import IncrementalIndexer


pytestmark = pytest.mark.integration


def test_document_cleanup_removes_vectors_graph_rows_and_bm25_corpus(integration_db, vector_store, rule_extractor, make_parsed_doc):

    indexer = IncrementalIndexer(vector_store=vector_store, graph_extractor=rule_extractor)
    delete_result = indexer.import_parsed(
        integration_db,
        make_parsed_doc(
            "integration:cleanup:delete-me",
            "Cleanup Target",
            [
                ("alpha", "Paper Alpha USES Method Alpha. Method Alpha TARGETS Task Omega. cleanup_unique_alpha_token."),
                ("beta", "Method Alpha EVALUATED_ON Dataset Beta. Dataset Beta REPORTS Metric Gamma. cleanup_unique_beta_token."),
            ],
        ),
    )
    keep_result = indexer.import_parsed(
        integration_db,
        make_parsed_doc("integration:cleanup:keep-me", "Cleanup Keeper", [("keep", "Paper Other USES Concept Bridge. keep_unique_token remains searchable.")]),
    )

    target_doc = integration_db.get(Document, delete_result["document_id"])
    target_chunks = integration_db.scalars(select(DocumentChunk).where(DocumentChunk.document_id == target_doc.id)).all()
    target_stable_ids = {chunk.stable_chunk_id for chunk in target_chunks}
    target_chunk_ids = {chunk.id for chunk in target_chunks}
    before = counts(integration_db, vector_store)
    assert before["documents"] == 2
    assert before["chunks"] == 3
    assert before["vectors"] == 3
    assert BM25Index(integration_db).search("cleanup_unique_alpha_token", top_k=5)

    deleted = indexer.delete_document(integration_db, target_doc)
    assert deleted["index_action"] == "deleted"

    assert integration_db.get(Document, delete_result["document_id"]) is None
    assert not integration_db.scalars(select(DocumentChunk).where(DocumentChunk.id.in_(target_chunk_ids))).all()
    assert not integration_db.scalars(select(EntityMention).where(EntityMention.chunk_id.in_(target_chunk_ids))).all()
    assert not integration_db.scalars(select(Relation).where(Relation.evidence_chunk_id.in_(target_chunk_ids))).all()
    assert vector_store.count() == 1
    assert all(hit.stable_chunk_id not in target_stable_ids for hit in BM25Index(integration_db).search("cleanup_unique_alpha_token", top_k=5))
    assert BM25Index(integration_db).search("keep_unique_token", top_k=5)

    keep_doc = integration_db.get(Document, keep_result["document_id"])
    assert keep_doc is not None
    assert integration_db.scalars(select(DocumentChunk).where(DocumentChunk.document_id == keep_doc.id)).all()
    remaining_entities = {row[0] for row in integration_db.execute(select(Entity.canonical_name)).all()}
    assert "Concept Bridge" in remaining_entities
    assert "Paper Other" in remaining_entities
    assert "Task Omega" not in remaining_entities


def counts(db, vector_store):
    return {
        "documents": db.scalar(select(func.count(Document.id))) or 0,
        "chunks": db.scalar(select(func.count(DocumentChunk.id))) or 0,
        "vectors": vector_store.count(),
        "mentions": db.scalar(select(func.count(EntityMention.id))) or 0,
        "relations": db.scalar(select(func.count(Relation.id))) or 0,
    }
