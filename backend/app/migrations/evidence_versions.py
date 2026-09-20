"""Forward-only, restartable Phase 1 -> Phase 2 migration for application MySQL.

MySQL DDL auto-commits. Each step is introspected before execution; rerunning
finishes an interrupted upgrade. Run with application writers stopped.
"""
from __future__ import annotations

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

from app.core.database import Base
from app.models import DocumentVersionChunk
from app.models.document import DocumentVersion

REVISION = "20260914_evidence_versions"


def upgrade(engine: Engine) -> dict:
    inspector = inspect(engine)
    if "documents" not in inspector.get_table_names():
        Base.metadata.create_all(engine)
        _record(engine)
        return {"revision": REVISION, "action": "created"}
    if engine.dialect.name != "mysql":
        raise RuntimeError("Existing-database migration requires MySQL; SQLite is test-only.")
    with engine.connect() as conn:
        if conn.scalar(text("SELECT GET_LOCK('lifeflow_evidence_migration', 30)")) != 1:
            raise RuntimeError("Another schema migration is running.")
        try:
            _add_column(conn, "documents", "pending_version", "INTEGER NULL")
            _add_column(conn, "document_chunks", "occurrence_index", "INTEGER NOT NULL DEFAULT 0")
            old = {"id", "document_id", "version", "content_hash", "parser_version", "created_at"}
            for column in DocumentVersion.__table__.columns:
                if column.name not in old:
                    _add_column(conn, "document_versions", column.name,
                                str(column.type.compile(dialect=engine.dialect)) + " NULL")
            _index(conn, "document_chunks", "uq_document_chunks_occurrence",
                   ["document_id", "chunk_hash", "occurrence_index"], unique=True)
            indexes = {row["name"] for row in inspect(conn).get_indexes("document_chunks")}
            if "uq_document_chunks_document_hash" in indexes:
                conn.execute(text("ALTER TABLE document_chunks DROP INDEX uq_document_chunks_document_hash"))
            _index(conn, "document_versions", "ix_document_versions_source_storage_key", ["source_storage_key"])
            _index(conn, "document_versions", "ix_document_versions_evidence_identity_hash", ["evidence_identity_hash"])
            DocumentVersionChunk.__table__.create(conn, checkfirst=True)
            conn.execute(text("""
                UPDATE document_versions v JOIN documents d ON d.id = v.document_id
                SET v.title = d.title, v.source_type = d.source_type, v.source_uri = d.source_uri
                WHERE v.source_type IS NULL
            """))
            # Preserve only surviving legacy evidence, without inventing deleted history.
            conn.execute(text("""
                INSERT INTO document_version_chunks
                    (document_version_id, chunk_id, ordinal, page_number, section_title)
                SELECT c.document_version_id, c.id, c.chunk_index, c.page_number, c.section_title
                FROM document_chunks c
                LEFT JOIN document_version_chunks m
                  ON m.document_version_id = c.document_version_id AND m.chunk_id = c.id
                WHERE m.id IS NULL
            """))
            conn.commit()
            _record(engine)
        finally:
            conn.execute(text("SELECT RELEASE_LOCK('lifeflow_evidence_migration')"))
            conn.commit()
    return {"revision": REVISION, "action": "upgraded", "legacy_raw_source": "unavailable"}


def _add_column(conn, table, name, definition):
    if name not in {row["name"] for row in inspect(conn).get_columns(table)}:
        conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {definition}"))


def _index(conn, table, name, columns, unique=False):
    if name not in {row["name"] for row in inspect(conn).get_indexes(table)}:
        kind = "UNIQUE " if unique else ""
        conn.execute(text(f"CREATE {kind}INDEX {name} ON {table} ({', '.join(columns)})"))


def _record(engine):
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE IF NOT EXISTS schema_migrations (revision VARCHAR(100) PRIMARY KEY)"))
        if not conn.scalar(text("SELECT revision FROM schema_migrations WHERE revision=:revision"), {"revision": REVISION}):
            conn.execute(text("INSERT INTO schema_migrations (revision) VALUES (:revision)"), {"revision": REVISION})
