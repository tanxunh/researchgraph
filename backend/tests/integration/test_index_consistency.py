from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.document import Document, DocumentChunk
from app.models.index_job import IndexJob
from app.services.generation.grounded_answer_service import GroundedAnswerService
from app.services.indexing.incremental_indexer import IncrementalIndexer, IncrementalIndexError
from app.services.indexing.reconciliation import VectorReconciliationService
from app.services.retrieval.retrieval_service import ResearchRetrievalService

pytestmark = pytest.mark.integration


@pytest.fixture
def context(integration_db, vector_store, rule_extractor, make_parsed_doc):
    return SimpleNamespace(db=integration_db, store=vector_store, parse=make_parsed_doc,
                           indexer=IncrementalIndexer(vector_store, rule_extractor))


def parsed(ctx, uri="consistency:one", text="Method Alpha TARGETS Task Omega."):
    return ctx.parse(uri, uri, [("body", text)])


def import_one(ctx, **kwargs):
    result = ctx.indexer.import_parsed(ctx.db, parsed(ctx, **kwargs))
    return ctx.db.get(Document, result["document_id"])


def chunks(ctx):
    return list(ctx.db.scalars(select(DocumentChunk).order_by(DocumentChunk.id)).all())


def fail(*args, **kwargs):
    raise RuntimeError("injected failure")


def orphan(ctx, number=1, query="Method Alpha"):
    ids = [f"orphan-{i}" for i in range(number)]
    ctx.store.collection.upsert(
        ids=ids, embeddings=[ctx.store.embedding.embed_query(query)] * number,
        documents=[query] * number,
        metadatas=[{"document_id": 900000 + i, "document_chunk_id": 900000 + i,
                    "document_version_id": 900000 + i, "chunk_hash": "orphan"} for i in range(number)])
    return ids


def search(ctx, query="Method Alpha", top_k=5):
    return ResearchRetrievalService(ctx.db, ctx.store).search(query, mode="vector", top_k=top_k)


def test_graph_extraction_failure_never_publishes(context, monkeypatch):
    ctx = context
    monkeypatch.setattr(ctx.indexer.graph_extractor, "extract", fail)
    with pytest.raises(IncrementalIndexError):
        import_one(ctx)
    assert ctx.db.scalar(select(func.count(Document.id))) == 0
    assert not chunks(ctx)
    assert ctx.store.count() == 0
    assert ctx.db.scalar(select(IndexJob)).status == "failed"


def test_graph_sql_failure_rolls_back_without_touching_vectors(context, monkeypatch):
    from app.services.graph.graph_builder import GraphBuilder
    ctx = context
    doc = import_one(ctx)
    old_ids = [c.stable_chunk_id for c in chunks(ctx)]
    monkeypatch.setattr(GraphBuilder, "apply_extraction", fail)
    with pytest.raises(IncrementalIndexError):
        ctx.indexer.import_parsed(ctx.db, parsed(ctx, text="Method Alpha USES Dataset Beta after change."))
    ctx.db.refresh(doc)
    assert doc.current_version == 1 and doc.status == "ready"
    assert [c.stable_chunk_id for c in chunks(ctx)] == old_ids
    assert ctx.store.count() == 1


def test_upsert_failure_preserves_committed_state_and_retry(context, monkeypatch):
    ctx = context
    original = ctx.store.upsert_document_chunks
    def check_committed_then_fail(batch):
        with Session(ctx.db.get_bind()) as observer:
            assert observer.scalar(select(func.count(DocumentChunk.id))) == 1
            assert observer.scalar(select(Document.status)) == "publishing"
        raise RuntimeError("Chroma unavailable")
    monkeypatch.setattr(ctx.store, "upsert_document_chunks", check_committed_then_fail)
    with pytest.raises(IncrementalIndexError):
        import_one(ctx)
    doc = ctx.db.scalar(select(Document))
    assert doc.status == "publish_failed" and len(chunks(ctx)) == 1
    assert not search(ctx)["results"]
    monkeypatch.setattr(ctx.store, "upsert_document_chunks", original)
    retried = ctx.indexer.import_parsed(ctx.db, parsed(ctx))
    assert retried["status"] == "ready" and retried["version"] == 1
    assert ctx.store.count() == 1


def test_activation_commit_failure_is_not_retrievable_and_retry_is_idempotent(context, monkeypatch):
    ctx = context
    commit = ctx.db.commit
    failed = False
    def commit_fail_once():
        nonlocal failed
        if not failed and any(isinstance(obj, Document) and obj.status == "ready" for obj in ctx.db.identity_map.values()):
            failed = True
            raise RuntimeError("commit failed before activation")
        commit()
    monkeypatch.setattr(ctx.db, "commit", commit_fail_once)
    with pytest.raises(IncrementalIndexError):
        import_one(ctx)
    assert failed and ctx.store.count() == 1
    assert ctx.db.scalar(select(Document.status)) == "publish_failed"
    assert not search(ctx)["results"]
    assert ctx.indexer.import_parsed(ctx.db, parsed(ctx))["status"] == "ready"
    assert ctx.store.count() == 1


def test_update_cleanup_failure_removes_sql_before_chroma(context, monkeypatch):
    ctx = context
    import_one(ctx)
    old_id = chunks(ctx)[0].stable_chunk_id
    def check_removed_then_fail(ids):
        with Session(ctx.db.get_bind()) as observer:
            from app.services.indexing.version_chunks import membership_query
            # The old SQL row is retained for citations but is no longer expected/current.
            assert observer.scalar(select(DocumentChunk.id).where(DocumentChunk.stable_chunk_id == old_id)) is not None
            assert observer.scalar(membership_query(pending=True).with_only_columns(DocumentChunk.id)
                                   .where(DocumentChunk.stable_chunk_id == old_id)) is None
        raise RuntimeError("delete failed")
    monkeypatch.setattr(ctx.store, "delete_chunk_ids", check_removed_then_fail)
    result = ctx.indexer.import_parsed(ctx.db, parsed(ctx, text="Method Alpha REPORTS Metric Gamma after revision."))
    assert result["status"] == "ready" and result["stats"]["cleanup_pending"]
    assert ctx.store.count() == 2
    assert old_id not in [row["chunk_id"] for row in search(ctx)["results"]]
    assert ctx.db.scalar(select(IndexJob).order_by(IndexJob.id.desc())).status == "cleanup_failed"


@pytest.mark.asyncio
async def test_injected_orphan_filtered_and_qa_uses_only_complete_evidence(context):
    ctx = context
    import_one(ctx)
    orphan(ctx)
    llm = SimpleNamespace(generate=AsyncMock(return_value="Grounded answer [C1]."))
    result = await GroundedAnswerService(ResearchRetrievalService(ctx.db, ctx.store), llm).answer("Method Alpha")
    assert len(result["citations"]) == 1 and result["status"] == "answered"
    assert all(row["chunk_id"] != "orphan-0" for row in result["search"]["results"])
    assert "orphan" not in llm.generate.call_args.args[0]


def test_top_five_with_two_orphans_is_refilled(context):
    ctx = context
    for i in range(5):
        import_one(ctx, uri=f"consistency:{i}", text=f"Method Alpha TARGETS Task Omega in study {i}.")
    orphan(ctx, 2)
    initial = ctx.store.search_documents("Method Alpha", 5)
    assert sum(hit.chunk_id.startswith("orphan-") for hit in initial) == 2
    results = search(ctx)["results"]
    assert len(results) == 5 and all(not row["chunk_id"].startswith("orphan-") for row in results)


def test_refill_retries_and_has_a_hard_bound(context, monkeypatch):
    ctx = context
    for i in range(5):
        import_one(ctx, uri=f"consistency:{i}", text=f"Method Alpha TARGETS Task Omega in study {i}.")
    orphan(ctx, 12)
    original = ctx.store.search_documents
    calls = []
    def observe(query, count):
        calls.append(count)
        return original(query, count)
    monkeypatch.setattr(ctx.store, "search_documents", observe)
    assert len(search(ctx)["results"]) == 5
    assert len(calls) == 2 and calls == [10, 20]
    orphan(ctx, 210)
    calls.clear()
    assert len(search(ctx)["results"]) == 0
    assert len(calls) <= 3 and max(calls) <= 200


def test_dry_run_detects_missing_vector_without_mutation(context):
    ctx = context
    import_one(ctx)
    key = chunks(ctx)[0].stable_chunk_id
    ctx.store.delete_chunk_ids([key])
    report = VectorReconciliationService(ctx.db, ctx.store).run()
    assert report["dry_run"] and report["missing_vector_ids"] == [key]
    assert report["missing_count"] == 1 and report["upserted_count"] == 0
    assert ctx.store.count() == 0


def test_repair_missing_vector(context):
    ctx = context
    import_one(ctx)
    ctx.store.delete_chunk_ids([chunks(ctx)[0].stable_chunk_id])
    report = VectorReconciliationService(ctx.db, ctx.store).run(repair=True)
    assert report["upserted_count"] == 1 and ctx.store.count() == 1
    assert len(search(ctx)["results"]) == 1


def test_repair_orphans_uses_pagination_without_skipping(context):
    ctx = context
    import_one(ctx)
    orphan(ctx, 7)
    report = VectorReconciliationService(ctx.db, ctx.store, batch_size=2).run(repair=True)
    assert report["orphan_count"] == 7 and report["deleted_count"] == 7
    assert ctx.store.count() == 1


def test_repair_is_idempotent(context):
    ctx = context
    import_one(ctx)
    ctx.store.delete_chunk_ids([chunks(ctx)[0].stable_chunk_id])
    orphan(ctx, 3)
    service = VectorReconciliationService(ctx.db, ctx.store, batch_size=2)
    first = service.run(repair=True)
    second = service.run(repair=True)
    assert first["deleted_count"] == 3 and first["upserted_count"] == 1
    assert second["deleted_count"] == second["upserted_count"] == 0
    assert second["orphan_count"] == second["missing_count"] == second["stale_count"] == 0


def test_delete_failure_keeps_authoritative_deletion_and_reconcile_recovers(context, monkeypatch):
    ctx = context
    doc = import_one(ctx)
    original = ctx.store.delete_chunk_ids
    monkeypatch.setattr(ctx.store, "delete_chunk_ids", fail)
    result = ctx.indexer.delete_document(ctx.db, doc)
    assert result["cleanup_pending"]
    assert ctx.db.scalar(select(func.count(Document.id))) == 0 and not chunks(ctx)
    assert ctx.store.count() == 1 and not search(ctx)["results"]
    monkeypatch.setattr(ctx.store, "delete_chunk_ids", original)
    assert VectorReconciliationService(ctx.db, ctx.store).run(repair=True)["deleted_count"] == 1


def test_partial_embedding_rebuild_never_reports_success(context, monkeypatch):
    ctx = context
    document = ctx.parse("consistency:many", "many", [("one", "Method Alpha TARGETS Task Omega."),
                                                         ("two", "Dataset Beta REPORTS Metric Gamma.")])
    result = ctx.indexer.import_parsed(ctx.db, document)
    doc = ctx.db.get(Document, result["document_id"])
    monkeypatch.setattr(ctx.store, "batch_size", 1)
    original = ctx.store.upsert_document_chunks
    calls = 0
    def partially_publish(batch):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("second vector batch failed")
        return original(batch)
    monkeypatch.setattr(ctx.store, "upsert_document_chunks", partially_publish)
    with pytest.raises(IncrementalIndexError):
        ctx.indexer.reindex(ctx.db, doc, "embedding_only")
    assert ctx.db.scalar(select(Document.status)) == "publish_failed"
    assert not search(ctx)["results"]
    assert ctx.db.scalar(select(IndexJob).order_by(IndexJob.id.desc())).status == "failed"
    monkeypatch.setattr(ctx.store, "upsert_document_chunks", original)
    assert ctx.indexer.reindex(ctx.db, doc, "embedding_only")["status"] == "ready"
    assert ctx.store.count() == 2


def test_graph_only_requires_verified_vectors(context):
    ctx = context
    doc = import_one(ctx)
    ctx.store.delete_chunk_ids([chunks(ctx)[0].stable_chunk_id])
    with pytest.raises(IncrementalIndexError):
        ctx.indexer.reindex(ctx.db, doc, "graph_only")
    assert ctx.db.scalar(select(Document.status)) == "publish_failed"
    assert VectorReconciliationService(ctx.db, ctx.store).run(repair=True)["upserted_count"] == 1
    # Reconciliation repairs bytes; only the publication flow may activate.
    assert ctx.db.scalar(select(Document.status)) == "publish_failed"
    assert ctx.indexer.reindex(ctx.db, doc, "embedding_only")["status"] == "ready"


def test_stale_vector_metadata_is_filtered_then_repaired(context):
    ctx = context
    import_one(ctx)
    key = chunks(ctx)[0].stable_chunk_id
    ctx.store.collection.update(ids=[key], metadatas=[{"document_version_id": 99999}])
    assert not search(ctx)["results"]
    service = VectorReconciliationService(ctx.db, ctx.store)
    assert service.run()["stale_vector_ids"] == [key]
    assert service.run(repair=True)["upserted_count"] == 1
    assert len(search(ctx)["results"]) == 1


def test_unchanged_import_recovers_missing_publication(context):
    ctx = context
    doc = import_one(ctx)
    ctx.store.delete_chunk_ids([chunks(ctx)[0].stable_chunk_id])
    result = ctx.indexer.import_parsed(ctx.db, parsed(ctx))
    assert result["index_action"] == "reindexed" and result["version"] == doc.current_version == 1
    assert ctx.store.count() == 1

def test_chroma_client_initialization_failure_does_not_block_sql_delete(context, monkeypatch):
    import app.services.indexing.incremental_indexer as module
    ctx = context
    doc = import_one(ctx)
    monkeypatch.setattr(module, "ChromaStore", fail)
    result = IncrementalIndexer(graph_extractor=ctx.indexer.graph_extractor).delete_document(ctx.db, doc)
    assert result["index_action"] == "deleted" and result["cleanup_pending"]
    assert ctx.db.scalar(select(func.count(Document.id))) == 0
    assert ctx.store.count() == 1


def test_authoritative_commit_failure_never_publishes_vectors(context, monkeypatch):
    ctx = context
    commit = ctx.db.commit
    def fail_preparation_commit():
        if any(isinstance(obj, Document) and obj.status == "publishing" for obj in ctx.db.identity_map.values()):
            raise RuntimeError("authoritative commit failed")
        commit()
    monkeypatch.setattr(ctx.db, "commit", fail_preparation_commit)
    with pytest.raises(IncrementalIndexError):
        import_one(ctx)
    assert ctx.db.scalar(select(func.count(Document.id))) == 0
    assert ctx.store.count() == 0


def test_failed_status_write_leaves_durable_nonready_state(context, monkeypatch):
    ctx = context
    commit = ctx.db.commit
    failures = 0
    def fail_final_and_error_commit():
        nonlocal failures
        objects = list(ctx.db.identity_map.values())
        if any(isinstance(obj, Document) and obj.status in {"ready", "publish_failed"} for obj in objects):
            failures += 1
            raise RuntimeError("database unavailable after publication")
        commit()
    monkeypatch.setattr(ctx.db, "commit", fail_final_and_error_commit)
    with pytest.raises(IncrementalIndexError):
        import_one(ctx)
    assert failures == 2 and ctx.store.count() == 1
    assert ctx.db.scalar(select(Document.status)) == "publishing"
    assert not search(ctx)["results"]
    monkeypatch.setattr(ctx.db, "commit", commit)
    assert ctx.indexer.import_parsed(ctx.db, parsed(ctx))["status"] == "ready"


def test_candidate_resolution_and_serialization_use_batched_sql(context):
    from sqlalchemy import event
    ctx = context
    for i in range(5):
        import_one(ctx, uri=f"batch:{i}", text=f"Method Alpha TARGETS Task Omega study {i}.")
    statements = []
    def capture(conn, cursor, statement, parameters, execution_context, executemany):
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(statement)
    engine = ctx.db.get_bind()
    event.listen(engine, "before_cursor_execute", capture)
    try:
        assert len(search(ctx)["results"]) == 5
    finally:
        event.remove(engine, "before_cursor_execute", capture)
    # One batch for dense resolution, one final batch, one batch for entity labels.
    assert len(statements) == 3


def test_chroma_connection_failure_during_import_retains_committed_chunks(context, monkeypatch):
    import app.services.indexing.incremental_indexer as module
    ctx = context
    monkeypatch.setattr(module, "ChromaStore", fail)
    with pytest.raises(IncrementalIndexError):
        IncrementalIndexer(graph_extractor=ctx.indexer.graph_extractor).import_parsed(ctx.db, parsed(ctx))
    assert len(chunks(ctx)) == 1
    assert ctx.db.scalar(select(Document.status)) == "publish_failed"

def test_missing_collection_dry_run_does_not_create_index(context):
    from app.vectorstore.chroma_store import ChromaStore
    ctx = context
    import_one(ctx)
    ctx.store.client.delete_collection(ctx.store.collection_name)
    empty_store = ChromaStore(ctx.store.embedding, create_collection=False)
    assert empty_store.collection is None
    service = VectorReconciliationService(ctx.db, empty_store)
    assert service.run()["missing_count"] == 1
    assert all(item.name != ctx.store.collection_name for item in ctx.store.client.list_collections())
    assert service.run(repair=True)["upserted_count"] == 1
    assert empty_store.count() == 1
