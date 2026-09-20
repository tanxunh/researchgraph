"""Add creation time without inventing timestamps for historical jobs."""
from sqlalchemy import inspect, text
from app.migrations.evidence_versions import _add_column

REVISION = '20260918_index_job_created_at'


def upgrade(engine):
    if engine.dialect.name != 'mysql':
        raise RuntimeError('Existing-database migration requires MySQL.')
    with engine.connect() as conn:
        if conn.scalar(text("SELECT GET_LOCK('lifeflow_job_created_at_migration',30)")) != 1:
            raise RuntimeError('Another migration is running.')
        try:
            # No SQL default/backfill: existing rows must remain NULL.
            _add_column(conn, 'index_jobs', 'created_at', 'DATETIME NULL')
            conn.execute(text('CREATE TABLE IF NOT EXISTS schema_migrations (revision VARCHAR(100) PRIMARY KEY)'))
            conn.execute(text('INSERT IGNORE INTO schema_migrations(revision) VALUES (:revision)'), {'revision': REVISION})
            conn.commit()
        finally:
            conn.execute(text("SELECT RELEASE_LOCK('lifeflow_job_created_at_migration')"))
            conn.commit()
    return {'revision': REVISION, 'status': 'complete'}


def require_schema(engine):
    if 'created_at' not in {c['name'] for c in inspect(engine).get_columns('index_jobs')}:
        raise RuntimeError('IndexJob creation-time migration required: python -m scripts.migrate_index_job_created_at')
