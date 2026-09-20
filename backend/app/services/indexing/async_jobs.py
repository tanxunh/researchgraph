"""Durable single-machine jobs. SQL owns state; one OS-locked worker consumes it."""
from __future__ import annotations
import json
import logging
import threading
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.models.document import Document, DocumentVersion
from app.models.index_job import IndexJob
from app.services.indexing.ingestion import DocumentIngestion
from app.services.indexing.incremental_indexer import IncrementalIndexer
from app.services.parsing.url_parser import UrlParser
from app.storage.local import LocalSourceStorage

KINDS = ('async_import', 'async_reprocess')
MAX_SOURCE_BYTES = 8 * 1024 * 1024
logger = logging.getLogger(__name__)


def now():
    return datetime.now(timezone.utc)


def enqueue(db: Session, payload: dict, data: bytes | None = None, document_id=None) -> IndexJob:
    if data is not None and len(data) > MAX_SOURCE_BYTES:
        raise ValueError('Async source exceeds 8 MiB limit.')
    if len(payload.get('source_uri', '')) > 700:
        raise ValueError('source_uri exceeds 700 characters.')
    job = IndexJob(job_type='async_reprocess' if document_id is not None else 'async_import',
                   document_id=document_id, status='queued', progress_stage='queued',
                   payload_json=json.dumps(payload), source_data=data, reason='async request')
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def enqueue_reprocess(db, document_id, source_version_id=None):
    document = db.get(Document, document_id)
    if document is None:
        raise ValueError('Document not found.')
    source = db.get(DocumentVersion, source_version_id) if source_version_id else db.scalar(
        select(DocumentVersion).where(DocumentVersion.document_id == document_id,
                                      DocumentVersion.version == document.current_version))
    if not source or source.document_id != document_id:
        raise ValueError('Source version does not belong to this document.')
    # Pin source identity at enqueue, not whichever version happens to be current later.
    return enqueue(db, {'source_version_id': source.id}, document_id=document_id)


def retry(db, job_id):
    job = db.scalar(select(IndexJob).where(IndexJob.id == job_id).with_for_update())
    if not job or job.job_type not in KINDS:
        raise ValueError('Async job not found.')
    if job.status != 'failed':
        raise ValueError('Only failed jobs can be retried.')
    job.status, job.progress_stage = 'queued', 'queued'
    job.error_message = job.error_type = job.finished_at = None
    db.commit()
    db.refresh(job)
    return job


def serialize(job):
    return dict(job_id=job.id, document_id=job.document_id, job_type=job.job_type,
        status=job.status, progress_stage=job.progress_stage, attempts=job.attempts,
        pipeline_job_id=job.pipeline_job_id, error_type=job.error_type, error=job.error_message,
        created_at=job.created_at, started_at=job.started_at, finished_at=job.finished_at,
        result=json.loads(job.stats_json) if job.stats_json else None)


class IndexWorker:
    def __init__(self, engine, *, ingestion_factory=None, lock_root=None, poll_seconds=0.5):
        self.engine = engine
        self.ingestion_factory = ingestion_factory or DocumentIngestion
        self.lock_root = Path(lock_root or LocalSourceStorage().root) / '.index-worker'
        self.poll_seconds = poll_seconds
        self.stop_event = threading.Event()
        self.thread = None

    def start(self):
        self.thread = threading.Thread(target=self.run, name='index-worker', daemon=True)
        self.thread.start()

    def stop(self):
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=5)
        # A live job retains the lock until completion or process exit. Never mark it
        # stale merely because shutdown timed out; only the next lock owner recovers.

    def recover_interrupted(self):
        # Only call while holding the exclusive worker lock, before consuming jobs.
        with Session(self.engine) as db:
            db.execute(update(IndexJob).where(IndexJob.job_type.in_(KINDS), IndexJob.status == 'running')
                .values(status='failed', error_type='process_interrupted',
                        error_message='Worker process interrupted; inspect the document and manually retry.',
                        finished_at=now()))
            db.commit()

    def run(self):
        while not self.stop_event.is_set():
            try:
                # Separate from the source lifecycle lock acquired by ingestion.
                # OS releases this lock on process death; no unsafe timeout takeover.
                with LocalSourceStorage(self.lock_root).mutation_lock():
                    if self.stop_event.is_set():
                        return
                    self.recover_interrupted()
                    while not self.stop_event.is_set():
                        if not self.run_one():
                            self.stop_event.wait(self.poll_seconds)
            except Exception:
                logger.exception('index_worker_cycle_failed')
                self.stop_event.wait(self.poll_seconds)

    def run_one(self):
        # Caller must hold worker lock (tests may call synchronously with no other workers).
        with Session(self.engine) as db:
            job = db.scalar(select(IndexJob).where(IndexJob.job_type.in_(KINDS), IndexJob.status == 'queued')
                            .order_by(IndexJob.id).limit(1).with_for_update())
            if not job:
                return False
            job.status, job.progress_stage = 'running', 'starting'
            job.attempts += 1
            job.started_at = now()
            job_id = job.id
            db.commit()
        try:
            result = self.execute(job_id)
            with Session(self.engine) as db:
                job = db.get(IndexJob, job_id)
                job.status, job.progress_stage = 'succeeded', 'completed'
                job.finished_at = now()
                job.document_id = result.get('document_id')
                job.stats_json = json.dumps(result)
                db.commit()
        except Exception as exc:
            with Session(self.engine) as db:
                job = db.get(IndexJob, job_id)
                job.status, job.finished_at = 'failed', now()
                job.error_type = type(exc).__name__
                job.error_message = 'Indexing failed; inspect stage/pipeline job, restore dependencies and retry.'
                db.commit()
            logger.warning('async_index_job_failed job_id=%s error_type=%s', job_id, type(exc).__name__)
        return True

    def execute(self, job_id):
        def progress(stage):
            with Session(self.engine) as observer:
                task = observer.get(IndexJob, job_id)
                task.progress_stage = stage
                if task.pipeline_job_id:
                    child = observer.get(IndexJob, task.pipeline_job_id)
                    if child and child.document_id:
                        task.document_id = child.document_id
                        if stage == 'publishing':
                            doc = observer.get(Document, child.document_id)
                            payload = json.loads(task.payload_json)
                            payload['target_version'] = doc.pending_version or doc.current_version
                            task.payload_json = json.dumps(payload)
                observer.commit()

        def started(child_id):
            with Session(self.engine) as observer:
                task = observer.get(IndexJob, job_id)
                task.pipeline_job_id = child_id
                observer.commit()

        with Session(self.engine) as db:
            task = db.get(IndexJob, job_id)
            payload, data = json.loads(task.payload_json), task.source_data
            if task.pipeline_job_id:
                child = db.get(IndexJob, task.pipeline_job_id)
                if child and child.status in ('succeeded','cleanup_failed'):
                    # Crash after pipeline commit but before outer-job acknowledgement:
                    # acknowledge durable success instead of replaying old input.
                    return dict(document_id=child.document_id, index_job_id=child.id,
                                recovered_completion=True, stats=json.loads(child.stats_json or '{}'))
                if child and child.document_id:
                    newer_success = db.scalar(select(IndexJob.id).where(
                        IndexJob.document_id == child.document_id, IndexJob.id > child.id,
                        IndexJob.job_type.not_in(KINDS), IndexJob.status.in_(('succeeded','cleanup_failed'))).limit(1))
                    if newer_success:
                        raise ValueError('A newer document operation succeeded; old retry is superseded.')
                if child and child.status == 'publishing' and child.document_id is None:
                    raise ValueError('Prepared document was deleted; old retry is superseded.')
            if 'target_version' in payload:
                doc = db.get(Document, task.document_id)
                if not doc or (doc.pending_version or doc.current_version) != payload['target_version']:
                    raise ValueError('Document was deleted or superseded; do not replay an old job.')
            ingestion = self.ingestion_factory()
            ingestion.indexer.on_progress = progress
            ingestion.indexer.on_job_started = started
            if task.job_type == 'async_reprocess':
                doc = db.get(Document, task.document_id)
                if not doc:
                    raise ValueError('Document no longer exists.')
                return ingestion.reprocess(db, doc, payload['source_version_id'])
            if payload['source_type'] == 'url' and data is None:
                progress('fetching')
                snapshot = UrlParser().fetch_snapshot(payload['source_uri'])
                data = snapshot['data']
                if len(data) > MAX_SOURCE_BYTES:
                    raise ValueError('Async source exceeds 8 MiB limit.')
                payload.update(content_type=snapshot['content_type'], encoding=snapshot['encoding'])
                task.source_data, task.payload_json = data, json.dumps(payload)
                db.commit()  # Retry uses these exact bytes, never refetches a changed URL.
            return ingestion.import_bytes(db, data, payload['source_type'], payload['source_uri'],
                payload.get('title'), payload.get('content_type','application/octet-stream'), payload.get('encoding'))
