from types import SimpleNamespace
from threading import Event
import json
import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select, func
from sqlalchemy.orm import Session

from app.api.index_jobs import router
from app.core.database import get_db
from app.models.document import Document, DocumentChunk, DocumentVersion
from app.models.index_job import IndexJob
from app.services.indexing.async_jobs import IndexWorker, enqueue, enqueue_reprocess, retry, MAX_SOURCE_BYTES
from app.services.indexing.ingestion import DocumentIngestion
from app.services.indexing.incremental_indexer import IncrementalIndexer

pytestmark = pytest.mark.integration


@pytest.fixture
def jobs(integration_db, vector_store, rule_extractor, tmp_path):
    engine=integration_db.get_bind()
    def factory():
        return DocumentIngestion(IncrementalIndexer(vector_store,rule_extractor))
    worker=IndexWorker(engine,ingestion_factory=factory,lock_root=tmp_path,poll_seconds=.02)
    app=FastAPI(); app.include_router(router)
    def session():
        with Session(engine) as db: yield db
    app.dependency_overrides[get_db]=session
    return SimpleNamespace(engine=engine,store=vector_store,worker=worker,client=TestClient(app),factory=factory)


def submit(ctx,text='Method Alpha TARGETS Task Omega.',uri='async:one'):
    response=ctx.client.post('/api/documents/import/async',json={'title':'Async paper','text':text,'source_uri':uri})
    assert response.status_code==202
    return response.json()['data']['job_id']


def state(ctx,job_id):
    response=ctx.client.get(f'/api/index-jobs/{job_id}')
    assert response.status_code==200
    return response.json()['data']


def counts(ctx):
    with Session(ctx.engine) as db:
        return tuple(db.scalar(select(func.count(m.id))) for m in (Document,DocumentVersion,DocumentChunk))+(ctx.store.count(),)


def wait_state(ctx,job_id,status):
    deadline=time.monotonic()+15
    while time.monotonic()<deadline:
        value=state(ctx,job_id)
        if value['status']==status: return value
        time.sleep(.02)
    pytest.fail(f'job did not become {status}: {value}')


def test_http_returns_queued_before_pipeline_and_worker_persists_stages(jobs):
    ctx=jobs; entered=Event(); release=Event(); stages=[]
    original=ctx.worker.ingestion_factory
    def factory():
        obj=original(); parse=obj._parse
        def blocked(*a,**kw):
            entered.set(); assert release.wait(10)
            return parse(*a,**kw)
        obj._parse=blocked
        return obj
    ctx.worker.ingestion_factory=factory
    job_id=submit(ctx)
    assert state(ctx,job_id)['status']=='queued'
    assert counts(ctx)==(0,0,0,0)
    ctx.worker.start()
    try:
        assert entered.wait(10)
        running=state(ctx,job_id)
        assert running['status']=='running' and running['progress_stage']=='parsing'
        release.set()
        result=wait_state(ctx,job_id,'succeeded')
        assert result['progress_stage']=='completed' and result['attempts']==1
        assert result['pipeline_job_id'] and result['document_id']
        with Session(ctx.engine) as db:
            assert db.get(IndexJob, job_id).document_id == result['document_id']
            assert db.get(Document, result['document_id']).status == 'ready'
        assert counts(ctx)==(1,1,1,1)
    finally:
        release.set();ctx.worker.stop()


def test_publication_failure_manual_retry_is_idempotent(jobs,monkeypatch):
    ctx=jobs; real=ctx.store.publish_document_chunks
    def broken(*a,**kw): raise RuntimeError('private infrastructure detail')
    monkeypatch.setattr(ctx.store,'publish_document_chunks',broken)
    job_id=submit(ctx);ctx.worker.run_one()
    assert state(ctx,job_id)['status']=='failed'
    assert state(ctx,job_id)['progress_stage']=='publishing'
    assert 'private' not in state(ctx,job_id)['error']
    with Session(ctx.engine) as db: assert db.scalar(select(Document.status))=='publish_failed'
    monkeypatch.setattr(ctx.store,'publish_document_chunks',real)
    assert ctx.client.post(f'/api/index-jobs/{job_id}/retry').status_code==202
    assert ctx.client.post(f'/api/index-jobs/{job_id}/retry').status_code==409
    ctx.worker.run_one()
    assert state(ctx,job_id)['status']=='succeeded' and state(ctx,job_id)['attempts']==2
    assert counts(ctx)==(1,1,1,1)
    second=submit(ctx);ctx.worker.run_one()
    assert state(ctx,second)['result']['index_action']=='unchanged'
    assert counts(ctx)==(1,1,1,1)


def test_interruption_after_commit_acknowledges_without_replaying(jobs):
    ctx=jobs;job_id=submit(ctx);ctx.worker.run_one()
    with Session(ctx.engine) as db:
        job=db.get(IndexJob,job_id);job.status='running';job.stats_json=None;db.commit()
    ctx.worker.recover_interrupted()
    assert state(ctx,job_id)['error_type']=='process_interrupted'
    assert ctx.client.post(f'/api/index-jobs/{job_id}/retry').status_code==202
    ctx.worker.run_one()
    assert state(ctx,job_id)['result']['recovered_completion'] is True
    assert counts(ctx)==(1,1,1,1)


def test_stale_running_requires_manual_retry_queued_resumes(jobs):
    ctx=jobs;a=submit(ctx);b=submit(ctx,uri='async:two')
    with Session(ctx.engine) as db:
        task=db.get(IndexJob,a);task.status='running';task.progress_stage='parsing';db.commit()
    ctx.worker.start()
    try:
        wait_state(ctx,b,'succeeded')
        assert state(ctx,a)['status']=='failed'
        assert state(ctx,a)['error_type']=='process_interrupted'
    finally:ctx.worker.stop()


def test_reprocess_pins_source_and_does_not_duplicate(jobs):
    ctx=jobs;job_id=submit(ctx);ctx.worker.run_one()
    doc_id=state(ctx,job_id)['document_id']
    response=ctx.client.post(f'/api/documents/{doc_id}/reprocess/async',json={})
    assert response.status_code==202
    task=response.json()['data']['job_id'];ctx.worker.run_one()
    assert state(ctx,task)['status']=='succeeded'
    assert counts(ctx)==(1,1,1,1)


def test_parser_failure_creates_no_ready_document_and_file_upload(jobs):
    ctx=jobs
    response=ctx.client.post('/api/documents/import/file/async',files={'file':('empty.txt',b'', 'text/plain')})
    assert response.status_code==202
    task=response.json()['data']['job_id'];ctx.worker.run_one()
    assert state(ctx,task)['status']=='failed'
    assert state(ctx,task)['progress_stage']=='parsing'
    assert counts(ctx)==(0,0,0,0)


def test_two_workers_same_source_are_serialized(jobs,tmp_path):
    ctx=jobs
    other=IndexWorker(ctx.engine,ingestion_factory=ctx.factory,lock_root=tmp_path,poll_seconds=.02)
    a=submit(ctx);b=submit(ctx)
    ctx.worker.start();other.start()
    try:
        wait_state(ctx,a,'succeeded');wait_state(ctx,b,'succeeded')
        assert counts(ctx)==(1,1,1,1)
        assert state(ctx,a)['attempts']==state(ctx,b)['attempts']==1
    finally:
        ctx.worker.stop();other.stop()


def test_url_retry_uses_frozen_download(jobs,monkeypatch):
    from app.services.parsing.url_parser import UrlParser
    ctx=jobs;calls=[]
    def fetch(self,url):
        calls.append(url)
        return {'data':b'<html><body><p>Method Alpha TARGETS Task Omega.</p></body></html>', 'content_type':'text/html','encoding':'utf-8'}
    monkeypatch.setattr(UrlParser,'fetch_snapshot',fetch)
    real=ctx.store.publish_document_chunks
    monkeypatch.setattr(ctx.store,'publish_document_chunks',lambda *a,**kw: (_ for _ in ()).throw(RuntimeError()))
    response=ctx.client.post('/api/documents/import/async',json={'source_type':'url','title':'URL','url':'https://example.invalid/paper'})
    task=response.json()['data']['job_id'];ctx.worker.run_one()
    assert state(ctx,task)['status']=='failed'
    monkeypatch.setattr(ctx.store,'publish_document_chunks',real)
    ctx.client.post(f'/api/index-jobs/{task}/retry');ctx.worker.run_one()
    assert state(ctx,task)['status']=='succeeded' and len(calls)==1
    assert counts(ctx)==(1,1,1,1)


def test_size_limit_and_invalid_job_do_not_enqueue(jobs):
    ctx=jobs
    with Session(ctx.engine) as db:
        with pytest.raises(ValueError):enqueue(db,{'source_type':'text'},b'x'*(MAX_SOURCE_BYTES+1))
    assert ctx.client.get('/api/index-jobs/999999').status_code==404
    assert ctx.client.post('/api/documents/999999/reprocess/async',json={}).status_code==400


def test_old_failed_job_does_not_replay_over_newer_success(jobs,monkeypatch):
    ctx=jobs;real=ctx.store.publish_document_chunks
    monkeypatch.setattr(ctx.store,'publish_document_chunks',lambda *a,**kw: (_ for _ in ()).throw(RuntimeError()))
    old=submit(ctx);ctx.worker.run_one()
    assert state(ctx,old)['status']=='failed'
    monkeypatch.setattr(ctx.store,'publish_document_chunks',real)
    newer=submit(ctx,text='Method Alpha USES Dataset Beta. New authoritative source.')
    ctx.worker.run_one();assert state(ctx,newer)['status']=='succeeded'
    before=counts(ctx)
    ctx.client.post(f'/api/index-jobs/{old}/retry');ctx.worker.run_one()
    assert state(ctx,old)['status']=='failed' and counts(ctx)==before
    with Session(ctx.engine) as db:assert db.scalar(select(Document.current_version))==2


def test_mysql_async_migration_restartable_preserves_existing_job(integration_db):
    from sqlalchemy import inspect,text
    from app.migrations.async_index_jobs import upgrade,COLUMNS
    engine=integration_db.get_bind()
    if engine.dialect.name!='mysql':
        pytest.skip('real MySQL DDL migration test')
    with engine.begin() as conn:
        for name in COLUMNS:
            conn.execute(text(f'ALTER TABLE index_jobs DROP COLUMN {name}'))
        conn.execute(text("INSERT INTO index_jobs(job_type,status,reason,started_at,stats_json) VALUES ('new_document','succeeded','legacy',CURRENT_TIMESTAMP,'{}')"))
    upgrade(engine);upgrade(engine)
    assert set(COLUMNS).issubset({c['name'] for c in inspect(engine).get_columns('index_jobs')})
    with Session(engine) as db:
        job=db.scalar(select(IndexJob))
        assert job.reason=='legacy' and job.status=='succeeded' and job.attempts==0


def test_actual_process_exit_releases_worker_lock_and_is_recoverable(jobs,tmp_path):
    import subprocess,sys
    ctx=jobs;task=submit(ctx)
    script = """
import os,sys
from sqlalchemy import create_engine
from app.services.indexing.async_jobs import IndexWorker
from app.services.indexing.ingestion import DocumentIngestion
DocumentIngestion._parse=lambda *a,**kw: os._exit(17)
IndexWorker(create_engine(sys.argv[1]),lock_root=sys.argv[2]).run()
"""
    completed=subprocess.run([sys.executable,'-c',script,
        ctx.engine.url.render_as_string(hide_password=False),str(tmp_path)],timeout=30,capture_output=True)
    assert completed.returncode==17,completed.stderr.decode(errors='replace')
    assert state(ctx,task)['status']=='running'
    ctx.worker.start()
    try:
        value=wait_state(ctx,task,'failed')
        assert value['error_type']=='process_interrupted'
        assert ctx.client.post(f'/api/index-jobs/{task}/retry').status_code==202
        wait_state(ctx,task,'succeeded')
        assert counts(ctx)==(1,1,1,1)
    finally:ctx.worker.stop()


def test_database_enqueue_failure_is_not_accepted(jobs,monkeypatch):
    from sqlalchemy.exc import OperationalError
    def broken(self):raise OperationalError('private SQL',{},RuntimeError('secret'))
    monkeypatch.setattr(Session,'commit',broken)
    response=jobs.client.post('/api/documents/import/async',json={'title':'test','text':'text'})
    assert response.status_code==503 and response.json()['code']==1
    assert 'secret' not in response.text and 'private SQL' not in response.text
