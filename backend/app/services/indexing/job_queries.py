"""Public listing with global counts and no per-row document lookup."""
from sqlalchemy import func, select
from sqlalchemy.orm import defer
from app.models.index_job import IndexJob
from app.services.indexing.async_jobs import KINDS, serialize


def list_jobs(db, *, page=1, page_size=20, status=None, operation=None, document_id=None):
    filters = [IndexJob.job_type.in_(KINDS)]
    if status is not None:
        filters.append(IndexJob.status == status)
    if operation is not None:
        filters.append(IndexJob.job_type == operation)
    if document_id is not None:
        filters.append(IndexJob.document_id == document_id)
    total = db.scalar(select(func.count(IndexJob.id)).where(*filters))
    rows = db.scalars(select(IndexJob).options(defer(IndexJob.source_data), defer(IndexJob.payload_json))
        .where(*filters).order_by(IndexJob.created_at.is_(None), IndexJob.created_at.desc(), IndexJob.id.desc())
        .offset((page - 1) * page_size).limit(page_size)).all()
    summary = dict.fromkeys(('queued', 'running', 'succeeded', 'failed'), 0)
    counts = db.execute(select(IndexJob.status, func.count(IndexJob.id))
        .where(IndexJob.job_type.in_(KINDS)).group_by(IndexJob.status))
    for state, count in counts:
        if state in summary:
            summary[state] = count
    return dict(items=[serialize(job) for job in rows], page=page, page_size=page_size,
                total=total, summary=summary)
