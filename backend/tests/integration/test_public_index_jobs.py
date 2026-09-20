from datetime import datetime, timedelta
from types import SimpleNamespace
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import event, text
from sqlalchemy.orm import Session
from app.api.index_jobs import router
from app.api.health import router as health_router
from app.core.database import get_db
from app.models.index_job import IndexJob
from app.models.document import Document
from app.services.indexing.async_jobs import enqueue

pytestmark = pytest.mark.integration


@pytest.fixture
def public_jobs(integration_db):
    db = integration_db
    doc = Document(title='Test paper', source_type='text', source_uri='test:jobs',
                   content_hash='a'*64, parser_version='test')
    db.add(doc); db.flush()
    jobs = []
    for i in range(16):
        job = IndexJob(job_type='async_import' if i % 2 == 0 else 'async_reprocess',
            document_id=doc.id if i % 2 else None,
            status=('queued','running','succeeded','failed')[i % 4],
            created_at=datetime(2026, 1, 1) + timedelta(days=i // 4),
            progress_stage='test', payload_json='{"private":"secret"}', source_data=b'private bytes')
        db.add(job); jobs.append(job)
    internal = IndexJob(job_type='new_document', status='running')
    db.add(internal); db.commit()
    # Simulates migrated NULLs, without invoking application insert defaults.
    db.execute(text('UPDATE index_jobs SET created_at=NULL WHERE id=:id'), {'id':jobs[-1].id})
    db.commit(); db.expire_all()
    engine = db.get_bind()
    app = FastAPI(); app.include_router(router); app.include_router(health_router)
    def session():
        with Session(engine) as connection: yield connection
    app.dependency_overrides[get_db] = session
    with TestClient(app) as client:
        yield SimpleNamespace(client=client, db=db, jobs=jobs, internal=internal, doc=doc)


def listing(ctx, **params):
    r = ctx.client.get('/api/index-jobs', params=params)
    assert r.status_code == 200 and r.json()['code'] == 0
    return r.json()['data']


def test_pagination_order_global_summary_and_privacy(public_jobs):
    c = public_jobs
    pages = [listing(c, page=i, page_size=5) for i in range(1,5)]
    rows = [r for p in pages for r in p['items']]
    expected = sorted(c.jobs[:-1], key=lambda j:(j.created_at, j.id), reverse=True) + [c.jobs[-1]]
    assert [r['job_id'] for r in rows] == [j.id for j in expected]
    assert len(set(r['job_id'] for r in rows)) == 16
    assert rows[-1]['created_at'] is None
    assert all(p['total']==16 and p['summary']==dict(queued=4,running=4,succeeded=4,failed=4) for p in pages)
    assert listing(c)['page_size']==20 and listing(c)['page']==1
    assert listing(c,page=50)['items']==[]
    assert any(r['document_id'] is None and r['status']=='queued' for r in rows)
    assert all('payload_json' not in r and 'source_data' not in r for r in rows)
    assert 'private' not in str(rows)


@pytest.mark.parametrize('params,count', [({'status':'queued'},4),
    ({'operation':'async_import'},8), ({'document_id':'DOC'},8),
    ({'status':'failed','operation':'async_reprocess','document_id':'DOC'},4)])
def test_filters_preserve_global_summary(public_jobs, params, count):
    c=public_jobs; params={k:c.doc.id if v=='DOC' else v for k,v in params.items()}
    r=listing(c,**params)
    assert r['total']==count and len(r['items'])==count
    for row in r['items']:
        for key,value in params.items(): assert row['job_type' if key=='operation' else key]==value
    assert r['summary']==dict(queued=4,running=4,succeeded=4,failed=4)


@pytest.mark.parametrize('params',[{'page':0},{'page':-1},{'page_size':0},{'page_size':101},
    {'page':'bad'},{'status':'publishing'},{'operation':'new_document'},{'document_id':0}])
def test_invalid_queries(public_jobs,params):
    assert public_jobs.client.get('/api/index-jobs',params=params).status_code==422


def test_new_timestamps_retry_and_current_association(public_jobs):
    c=public_jobs
    job=enqueue(c.db,{'source_type':'text','source_uri':'new'},b'text')
    created=job.created_at
    assert created is not None and c.internal.created_at is not None
    job.status='failed';c.db.commit()
    assert c.client.post(f'/api/index-jobs/{job.id}/retry').status_code==202
    # The HTTP request commits in a different session. End MySQL's old read snapshot.
    c.db.commit(); c.db.refresh(job)
    assert job.created_at==created and job.status=='queued'
    for state in ['queued','running','succeeded']:
        job.status=state;c.db.commit()
        assert c.client.post(f'/api/index-jobs/{job.id}/retry').status_code==409
    job.started_at=datetime(2027,1,1);job.document_id=c.doc.id;c.db.commit()
    response=c.client.get(f'/api/index-jobs/{job.id}').json()['data']
    assert response==next(r for r in listing(c)['items'] if r['job_id']==job.id)
    c.db.refresh(job); assert job.created_at==created and response['document_id']==c.doc.id
    assert c.client.get(f'/api/index-jobs/{c.internal.id}').status_code==404
    assert c.client.post(f'/api/index-jobs/{c.internal.id}/retry').status_code==409
    old=c.jobs[-1]; assert old.created_at is None
    assert c.client.post(f'/api/index-jobs/{old.id}/retry').status_code==202
    c.db.commit(); c.db.refresh(old); assert old.created_at is None


def test_system_status_unchanged_and_no_n_plus_one(public_jobs):
    c=public_jobs; statements=[]
    def capture(conn,cursor,statement,parameters,context,executemany): statements.append(statement)
    event.listen(c.db.get_bind(),'before_cursor_execute',capture)
    try: listing(c,page_size=100)
    finally: event.remove(c.db.get_bind(),'before_cursor_execute',capture)
    assert len(statements)==3
    assert not any('source_data' in s or 'payload_json' in s for s in statements)
    result=c.client.get('/api/system/status').json()['data']
    assert len(result['recent_index_jobs'])==10
    assert any(r['id']==c.internal.id for r in result['recent_index_jobs'])
    assert result['index_success_count']==4 and result['index_failed_count']==4


def test_mysql_migration_preserves_null_and_is_restartable(integration_db):
    from app.migrations.index_job_created_at import upgrade, require_schema
    engine=integration_db.get_bind()
    if engine.dialect.name!='mysql': pytest.skip('requires real MySQL DDL')
    with engine.begin() as conn:
        conn.execute(text('ALTER TABLE index_jobs DROP COLUMN created_at'))
        conn.execute(text("INSERT INTO index_jobs(job_type,status,reason,started_at) VALUES ('async_import','failed','historical','2025-01-01')"))
    with pytest.raises(RuntimeError,match='migration required'): require_schema(engine)
    upgrade(engine);upgrade(engine);require_schema(engine)
    with engine.connect() as conn:
        row=conn.execute(text('SELECT created_at,started_at FROM index_jobs')).one()
        assert row.created_at is None and row.started_at==datetime(2025,1,1)
    job=enqueue(integration_db,{'source_type':'text','source_uri':'after-migration'},b'text')
    assert job.created_at is not None
    upgrade(engine);integration_db.refresh(job)
    assert job.created_at is not None
