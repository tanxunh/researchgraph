"""Additive and restartable; run with application writers stopped."""
from sqlalchemy import inspect, text
from app.migrations.evidence_versions import _add_column

REVISION = '20260916_async_index_jobs'
COLUMNS = {'progress_stage':'VARCHAR(50) NULL', 'payload_json':'TEXT NULL',
           'source_data':'LONGBLOB NULL', 'attempts':'INTEGER NOT NULL DEFAULT 0',
           'pipeline_job_id':'INTEGER NULL'}


def upgrade(engine):
    if engine.dialect.name != 'mysql':
        raise RuntimeError('Existing-database migration requires MySQL.')
    with engine.connect() as conn:
        if conn.scalar(text("SELECT GET_LOCK('lifeflow_async_jobs_migration',30)")) != 1:
            raise RuntimeError('Another migration is running.')
        try:
            for name,definition in COLUMNS.items():
                _add_column(conn,'index_jobs',name,definition)
            conn.execute(text('CREATE TABLE IF NOT EXISTS schema_migrations (revision VARCHAR(100) PRIMARY KEY)'))
            conn.execute(text('INSERT IGNORE INTO schema_migrations(revision) VALUES (:revision)'),{'revision':REVISION})
            conn.commit()
        finally:
            conn.execute(text("SELECT RELEASE_LOCK('lifeflow_async_jobs_migration')"))
            conn.commit()
    return {'revision':REVISION,'status':'complete'}


def require_schema(engine):
    if not set(COLUMNS).issubset({c['name'] for c in inspect(engine).get_columns('index_jobs')}):
        raise RuntimeError('Phase 7 migration required: python -m scripts.migrate_async_index_jobs')
