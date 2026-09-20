from collections.abc import Generator

from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import get_settings

settings = get_settings()

engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,
    pool_recycle=3600,
)

SessionLocal = sessionmaker(
    bind=engine,
    autocommit=False,
    autoflush=False,
)


class Base(DeclarativeBase):
    pass


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def create_db_tables() -> None:
    from app.models import (  # noqa: F401
        Document,
        DocumentChunk,
        DocumentVersion,
        Entity,
        EntityAlias,
        EntityMention,
        EvaluationRun,
        IndexJob,
        Relation,
    )

    from sqlalchemy import text
    from app.migrations.evidence_versions import REVISION, upgrade

    inspector = inspect(engine)
    if not inspector.has_table("documents"):
        upgrade(engine)
        return
    if not inspector.has_table("schema_migrations"):
        raise RuntimeError("Phase 2 migration required: python -m scripts.migrate_evidence_versions")
    with engine.connect() as connection:
        revision = connection.scalar(text("SELECT revision FROM schema_migrations WHERE revision=:revision"),
                                     {"revision": REVISION})
    if not revision or not inspector.has_table("document_version_chunks"):
        raise RuntimeError("Phase 2 migration incomplete: python -m scripts.migrate_evidence_versions")
    Base.metadata.create_all(bind=engine)
    from app.migrations.async_index_jobs import require_schema
    require_schema(engine)

    from app.migrations.index_job_created_at import require_schema as require_job_created_at
    require_job_created_at(engine)
