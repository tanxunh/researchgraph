"""Phase 4 full path, using the existing isolated SQLite/MySQL + Chroma fixtures."""
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import event

from app.core.config import get_settings
from app.models.document import Document
from app.services.generation.citation_validator import CitationValidationError, CitationValidator
from app.services.generation.evidence_builder import EvidenceBuilder
from app.services.generation.grounded_answer_service import GroundedAnswerService
from app.services.indexing.evidence_resolver import resolve_version_chunk, resolve_version_chunks
from app.services.indexing.ingestion import DocumentIngestion
from app.services.indexing.incremental_indexer import IncrementalIndexer
from app.services.retrieval.retrieval_service import ResearchRetrievalService
from app.storage.local import LocalSourceStorage

pytestmark = pytest.mark.integration


@pytest.fixture
def qa_context(integration_db, vector_store, rule_extractor, tmp_path):
    get_settings().source_storage_root = str(tmp_path / "sources")
    storage = LocalSourceStorage()
    indexer = IncrementalIndexer(vector_store, rule_extractor)
    return SimpleNamespace(db=integration_db, store=vector_store, storage=storage, indexer=indexer,
                           ingestion=DocumentIngestion(indexer, storage),
                           retrieval=ResearchRetrievalService(integration_db, vector_store))


def ingest(ctx, text):
    return ctx.ingestion.import_text(ctx.db, "Study", text, "phase4:study")


@pytest.mark.asyncio
async def test_import_qa_update_and_historical_citation(qa_context):
    ctx = qa_context
    ingest(ctx, "Method Alpha uses Dataset Beta.\n\nOriginal historical evidence.")
    llm = SimpleNamespace(generate=AsyncMock(return_value="Dataset Beta [C1]."))
    result = await GroundedAnswerService(ctx.retrieval, llm).answer("Method Alpha", mode="hybrid", top_k=2)
    assert result["status"] == "answered" and result["citation_validation"]["valid"]
    assert len(result["citations"]) == 1 and result["evidence_count"] == 2
    citation = result["citations"][0]
    locator = (citation["document_version_id"], citation["chunk_id"])
    old = resolve_version_chunk(ctx.db, *locator)
    assert old["version"]["number"] == 1
    assert old["location"]["ordinal"] == citation["ordinal"]
    assert old["location"]["section_title"] == citation["section"]
    assert ctx.storage.load(old["source"]["storage_key"]).decode("utf-8").startswith("Method Alpha")
    assert old["source"]["storage_key"] not in str(result)
    assert str(get_settings().source_storage_root) not in str(result)
    old_evidence = EvidenceBuilder().build(result["search"])

    ingest(ctx, "Completely changed current evidence.")
    assert ctx.db.get(Document, citation["document_id"]).current_version == 2
    assert resolve_version_chunk(ctx.db, *locator) == old
    assert resolve_version_chunks(ctx.db, [locator])[locator] == old
    validator = CitationValidator(lambda locators: resolve_version_chunks(ctx.db, locators))
    assert validator.validate("Old reference [C1]", old_evidence).valid

    newer = await GroundedAnswerService(ctx.retrieval, llm).answer("evidence", mode="hybrid")
    assert newer["status"] == "answered"
    assert all(c["document_version_id"] != locator[0] for c in newer["citations"])
    assert all(c["document"]["version"] == 2 for c in newer["citations"])
    assert resolve_version_chunk(ctx.db, *locator) == old
    llm.generate.assert_awaited()


@pytest.mark.asyncio
async def test_current_qa_rejects_historical_vectors_and_nonready_documents(qa_context):
    from app.services.indexing.version_chunks import version_chunks
    ctx = qa_context
    imported = ingest(ctx, "Historical-only evidence.")
    old = version_chunks(ctx.db, imported["document_id"], 1)[0]
    ingest(ctx, "Current evidence only.")
    ctx.store.upsert_document_chunks([old])
    llm = SimpleNamespace(generate=AsyncMock(return_value="Current evidence [C1]."))
    service = GroundedAnswerService(ctx.retrieval, llm)
    result = await service.answer("Historical evidence", mode="hybrid")
    assert result["status"] == "answered"
    assert all(c["chunk_id"] != old.stable_chunk_id for c in result["citations"])
    assert all(c["document_version_id"] != old.document_version_id for c in result["citations"])
    assert "Historical-only evidence." not in llm.generate.call_args.args[0]
    document = ctx.db.get(Document, imported["document_id"])
    document.status = "publish_failed"
    ctx.db.commit()
    llm.generate.reset_mock()
    result = await service.answer("Current evidence", mode="hybrid")
    assert result["status"] == "insufficient_evidence" and result["evidence_count"] == 0
    llm.generate.assert_not_called()


@pytest.mark.asyncio
async def test_deleted_citation_fails_post_generation_resolution(qa_context):
    ctx = qa_context
    imported = ingest(ctx, "Evidence that will be deleted.")
    async def delete_then_answer(prompt):
        ctx.indexer.delete_document(ctx.db, ctx.db.get(Document, imported["document_id"]))
        return "Answer [C1]"
    llm = SimpleNamespace(generate=AsyncMock(side_effect=delete_then_answer))
    with pytest.raises(CitationValidationError) as error:
        await GroundedAnswerService(ctx.retrieval, llm).answer("Evidence", mode="hybrid")
    assert error.value.validation.invalid_citation_ids == ["C1"]


def test_batch_resolver_uses_one_select_and_rejects_wrong_locator(qa_context):
    ctx = qa_context
    ingest(ctx, "First evidence.\n\nSecond evidence.\n\nThird evidence.")
    rows = ctx.retrieval.search("evidence", mode="hybrid", top_k=3)["results"]
    locators = [(row["document_version_id"], row["chunk_id"]) for row in rows]
    selects = []
    def count_select(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith("SELECT"):
            selects.append(statement)
    event.listen(ctx.db.bind, "before_cursor_execute", count_select)
    try:
        result = resolve_version_chunks(ctx.db, locators + [(999999, locators[0][1])])
    finally:
        event.remove(ctx.db.bind, "before_cursor_execute", count_select)
    assert len(selects) == 1 and set(result) == set(locators)
