from __future__ import annotations

import json

import pytest
from sqlalchemy import func, select

from app.models.document import DocumentChunk, DocumentVersion
from app.models.entity import EntityMention
from app.models.index_job import IndexJob
from app.models.relation import Relation
from app.services.indexing.incremental_indexer import IncrementalIndexer
from app.services.indexing.version_chunks import version_chunks


pytestmark = pytest.mark.integration


def test_incremental_indexing_preserves_stable_chunks_and_reindexes_only_changes(integration_db, vector_store, rule_extractor, make_parsed_doc):

    indexer = IncrementalIndexer(vector_store=vector_store, graph_extractor=rule_extractor)
    original = make_parsed_doc(
        "integration:alpha",
        "Alpha Document",
        [
            ("scope", "Method Alpha TARGETS Task Omega. This section is stable and should keep its chunk id."),
            ("dataset", "Method Alpha EVALUATED_ON Dataset Beta. This section will be changed later."),
        ],
    )
    other = make_parsed_doc(
        "integration:other",
        "Other Document",
        [("metric", "Dataset Beta REPORTS Metric Gamma. Other document must remain unaffected.")],
    )

    first = indexer.import_parsed(integration_db, original)
    other_result = indexer.import_parsed(integration_db, other)
    assert first["index_action"] == "created"
    assert first["stats"]["chunk_count"] == 2
    assert first["stats"]["reembedded_chunk_count"] == 2
    assert first["stats"]["reextracted_chunk_count"] == 2
    assert first["stats"]["removed_chunk_count"] == 0
    assert other_result["index_action"] == "created"

    document_id = first["document_id"]
    chunks = integration_db.scalars(select(DocumentChunk).where(DocumentChunk.document_id == document_id).order_by(DocumentChunk.chunk_index)).all()
    stable_before = [chunk.stable_chunk_id for chunk in chunks]
    stale_chunk_id = chunks[1].id
    other_chunks_before = [row[0] for row in integration_db.execute(select(DocumentChunk.stable_chunk_id).where(DocumentChunk.document_id == other_result["document_id"])).all()]
    counts_before_duplicate = counts(integration_db, vector_store)

    duplicate = indexer.import_parsed(integration_db, original)
    assert duplicate["index_action"] == "unchanged"
    assert duplicate["stats"]["unchanged_chunk_count"] == 2
    assert duplicate["stats"]["added_chunk_count"] == 0
    assert duplicate["stats"]["removed_chunk_count"] == 0
    assert duplicate["stats"]["reembedded_chunk_count"] == 0
    assert duplicate["stats"]["reextracted_chunk_count"] == 0
    assert duplicate["stats"]["chunks_reembedded"] == 0
    assert duplicate["stats"]["chunks_graphed"] == 0
    assert counts(integration_db, vector_store) == counts_before_duplicate

    updated = make_parsed_doc(
        "integration:alpha",
        "Alpha Document",
        [
            ("scope", "Method Alpha TARGETS Task Omega. This section is stable and should keep its chunk id."),
            ("dataset", "Method Alpha EVALUATED_ON Dataset Beta. Dataset Beta REPORTS Metric Gamma after revision."),
        ],
    )
    changed = indexer.import_parsed(integration_db, updated)
    assert changed["index_action"] == "updated"
    assert changed["version"] == 2
    assert changed["stats"]["unchanged_chunk_count"] == 1
    assert changed["stats"]["added_chunk_count"] == 1
    assert changed["stats"]["removed_chunk_count"] == 1
    assert changed["stats"]["reembedded_chunk_count"] == 1
    assert changed["stats"]["reextracted_chunk_count"] == 1

    chunks_after = version_chunks(integration_db, document_id, 2)
    assert chunks_after[0].stable_chunk_id == stable_before[0]
    assert chunks_after[1].stable_chunk_id != stable_before[1]
    # Phase 2 retains historical SQL evidence; only current membership excludes it.
    assert integration_db.get(DocumentChunk, stale_chunk_id) is not None
    assert stale_chunk_id not in [chunk.id for chunk in chunks_after]
    assert not integration_db.scalars(select(Relation).where(Relation.evidence_chunk_id == stale_chunk_id)).all()
    assert not integration_db.scalars(select(EntityMention).where(EntityMention.chunk_id == stale_chunk_id)).all()
    assert vector_store.count() == 3
    assert integration_db.scalar(select(func.count(DocumentVersion.id)).where(DocumentVersion.document_id == document_id)) == 2
    assert [row[0] for row in integration_db.execute(select(DocumentChunk.stable_chunk_id).where(DocumentChunk.document_id == other_result["document_id"])).all()] == other_chunks_before

    last_job = integration_db.scalar(select(IndexJob).where(IndexJob.document_id == document_id).order_by(IndexJob.id.desc()))
    assert last_job and last_job.status == "succeeded"
    stats = json.loads(last_job.stats_json)
    assert stats["unchanged_chunk_count"] == 1
    assert stats["added_chunk_count"] == 1
    assert stats["removed_chunk_count"] == 1
    assert stats["reembedded_chunk_count"] == 1
    assert stats["reextracted_chunk_count"] == 1


def counts(db, vector_store):
    return {
        "versions": db.scalar(select(func.count(DocumentVersion.id))) or 0,
        "chunks": db.scalar(select(func.count(DocumentChunk.id))) or 0,
        "vectors": vector_store.count(),
        "mentions": db.scalar(select(func.count(EntityMention.id))) or 0,
        "relations": db.scalar(select(func.count(Relation.id))) or 0,
    }
