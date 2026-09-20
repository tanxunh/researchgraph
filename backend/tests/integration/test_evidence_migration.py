"""Migration tests use disposable fixture schemas only."""
import os
from pathlib import Path

import pytest
from sqlalchemy import inspect, text, select
from sqlalchemy.orm import Session

from app.core.database import Base
from app.migrations.evidence_versions import upgrade, REVISION
from app.models.document import Document, DocumentChunk, DocumentVersion, DocumentVersionChunk
from app.services.indexing.ingestion import DocumentIngestion, RawSourceUnavailable
from app.services.indexing.incremental_indexer import IncrementalIndexer
from app.services.indexing.version_chunks import version_chunks
from app.services.retrieval.retrieval_service import ResearchRetrievalService

pytestmark = [pytest.mark.integration, pytest.mark.migration]


@pytest.fixture
def migration_engine(integration_db):
    engine = integration_db.get_bind()
    integration_db.close()
    Base.metadata.drop_all(engine)
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS schema_migrations"))
    try:
        yield engine
    finally:
        Base.metadata.drop_all(engine)
        with engine.begin() as conn:
            conn.execute(text("DROP TABLE IF EXISTS schema_migrations"))
        Base.metadata.create_all(engine)


def legacy_schema(engine):
    sql = (Path(__file__).parents[1] / "fixtures" / "phase1_schema.txt").read_text(encoding="utf-8-sig")
    with engine.begin() as conn:
        for statement in sql.split(";"):
            if statement.strip():
                conn.execute(text(statement))


def seed_legacy(engine):
    with engine.begin() as conn:
        conn.execute(text("""INSERT INTO documents
            (id,source_type,source_uri,title,content_hash,parser_version,current_version,status,created_at,updated_at)
            VALUES (1,'text','legacy:study','Legacy','hash','parser-v1',1,'ready',NOW(),NOW())"""))
        conn.execute(text("""INSERT INTO document_versions
            (id,document_id,version,content_hash,parser_version,created_at)
            VALUES (1,1,1,'hash','parser-v1',NOW())"""))
        conn.execute(text("""INSERT INTO document_chunks
            (id,stable_chunk_id,document_id,document_version_id,chunk_index,text,chunk_hash,page_number,
             section_title,token_count,embedding_version,graph_extractor_version,created_at)
            VALUES (1,'legacy-stable-id',1,1,0,'Legacy evidence.','chunk-hash',3,'Legacy section',10,
                    'embedding-v1','graph-extractor-v1',NOW())"""))


def test_empty_database_migration(migration_engine):
    result = upgrade(migration_engine)
    assert result["action"] == "created"
    assert "document_version_chunks" in inspect(migration_engine).get_table_names()
    with migration_engine.connect() as conn:
        assert conn.scalar(text("SELECT revision FROM schema_migrations")) == REVISION


@pytest.mark.skipif(os.environ.get("CONSISTENCY_REAL") != "1", reason="Existing application schema migration requires real MySQL")
def test_existing_phase1_schema_migration_is_restartable(migration_engine):
    legacy_schema(migration_engine)
    upgrade(migration_engine)
    upgrade(migration_engine)
    inspector = inspect(migration_engine)
    assert "pending_version" in {c["name"] for c in inspector.get_columns("documents")}
    assert "occurrence_index" in {c["name"] for c in inspector.get_columns("document_chunks")}
    assert "uq_document_chunks_document_hash" not in {i["name"] for i in inspector.get_indexes("document_chunks")}


@pytest.mark.skipif(os.environ.get("CONSISTENCY_REAL") != "1", reason="Legacy upgrade must be verified on real MySQL")
def test_legacy_rows_keep_ids_location_search_and_unavailable_source(migration_engine, vector_store, rule_extractor):
    legacy_schema(migration_engine)
    seed_legacy(migration_engine)
    upgrade(migration_engine)
    upgrade(migration_engine)
    with Session(migration_engine) as db:
        chunk = db.get(DocumentChunk, 1)
        version = db.get(DocumentVersion, 1)
        membership = db.scalar(select(DocumentVersionChunk))
        assert chunk.stable_chunk_id == "legacy-stable-id"
        assert membership.page_number == 3 and membership.section_title == "Legacy section"
        assert version.source_storage_key is None and version.source_checksum is None
        vector_store.upsert_document_chunks(version_chunks(db, 1, 1))
        hits = ResearchRetrievalService(db, vector_store).search("Legacy", mode="vector")["results"]
        assert len(hits) == 1 and hits[0]["location"]["page_number"] == 3
        with pytest.raises(RawSourceUnavailable, match="raw_source_unavailable"):
            DocumentIngestion(IncrementalIndexer(vector_store, rule_extractor)).reprocess(db, db.get(Document, 1))

@pytest.mark.skipif(os.environ.get("CONSISTENCY_REAL") != "1", reason="MySQL DDL interruption requires real MySQL")
def test_interrupted_migration_blocks_startup_and_can_resume(migration_engine, monkeypatch):
    import app.migrations.evidence_versions as migration
    import app.core.database as database
    legacy_schema(migration_engine)
    seed_legacy(migration_engine)
    original = migration._index
    def interrupted(*args, **kwargs):
        raise RuntimeError("injected DDL interruption")
    monkeypatch.setattr(migration, "_index", interrupted)
    with pytest.raises(RuntimeError, match="interruption"):
        upgrade(migration_engine)
    assert "pending_version" in {c["name"] for c in inspect(migration_engine).get_columns("documents")}
    monkeypatch.setattr(database, "engine", migration_engine)
    with pytest.raises(RuntimeError, match="migration required"):
        database.create_db_tables()
    monkeypatch.setattr(migration, "_index", original)
    upgrade(migration_engine)
    with pytest.raises(RuntimeError, match="Phase 7 migration required"):
        database.create_db_tables()
    from app.migrations.async_index_jobs import upgrade as upgrade_jobs
    upgrade_jobs(migration_engine)
    database.create_db_tables()
    with Session(migration_engine) as db:
        assert db.get(DocumentChunk, 1).text == "Legacy evidence."
        assert db.scalar(select(DocumentVersionChunk.chunk_id)) == 1
