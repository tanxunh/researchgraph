from typing import Literal
from fastapi import APIRouter, Depends, File, Form, UploadFile, Query
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError
from app.core.database import get_db
from app.models.index_job import IndexJob
from app.schemas.document import DocumentImportRequest, ReprocessRequest
from app.services.indexing.async_jobs import enqueue, enqueue_reprocess, retry, serialize, KINDS, MAX_SOURCE_BYTES
from app.utils.response import success, fail
from app.services.indexing.job_queries import list_jobs

router = APIRouter(tags=['Index Jobs'])


def accepted(job):
    return JSONResponse(status_code=202, content=success({'job_id':job.id,'status':job.status}))


@router.post('/api/documents/import/async', status_code=202)
def import_async(payload: DocumentImportRequest, db: Session = Depends(get_db)):
    try:
        source_uri = str(payload.url) if payload.source_type == 'url' else payload.source_uri or f'text:{payload.title.strip()}'
        job = enqueue(db, dict(source_type=payload.source_type, source_uri=source_uri,
            title=payload.title, content_type='text/plain; charset=utf-8', encoding='utf-8'),
            payload.text.encode('utf-8') if payload.source_type == 'text' else None)
        return accepted(job)
    except ValueError as exc:
        return JSONResponse(status_code=400, content=fail(str(exc)))
    except SQLAlchemyError:
        db.rollback()
        return JSONResponse(status_code=503,content=fail('Job storage unavailable; retry the request.'))


@router.post('/api/documents/import/file/async', status_code=202)
def file_async(file: UploadFile = File(...), source_uri: str | None = Form(None), db: Session = Depends(get_db)):
    name = file.filename or 'uploaded-file'
    kind = {'pdf':'pdf','docx':'docx','txt':'text','md':'text','markdown':'text'}.get(name.lower().rsplit('.',1)[-1])
    if not kind:
        return JSONResponse(status_code=400,content=fail('Only PDF, DOCX, TXT, and Markdown files are supported.'))
    try:
        return accepted(enqueue(db,dict(source_type=kind,source_uri=source_uri or name,
            content_type=file.content_type or 'application/octet-stream',encoding='utf-8' if kind=='text' else None),
            file.file.read(MAX_SOURCE_BYTES+1)))
    except ValueError as exc:
        return JSONResponse(status_code=400,content=fail(str(exc)))
    except SQLAlchemyError:
        db.rollback()
        return JSONResponse(status_code=503,content=fail('Job storage unavailable; retry the request.'))


@router.post('/api/documents/{document_id}/reprocess/async', status_code=202)
def reprocess_async(document_id:int,payload:ReprocessRequest,db:Session=Depends(get_db)):
    try:
        return accepted(enqueue_reprocess(db,document_id,payload.source_version_id))
    except ValueError as exc:
        return JSONResponse(status_code=400,content=fail(str(exc)))
    except SQLAlchemyError:
        db.rollback()
        return JSONResponse(status_code=503,content=fail('Job storage unavailable; retry the request.'))


@router.get('/api/index-jobs')
def list_index_jobs(page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
                   status: Literal['queued', 'running', 'succeeded', 'failed'] | None = None,
                   operation: Literal['async_import', 'async_reprocess'] | None = None,
                   document_id: int | None = Query(None, ge=1), db: Session = Depends(get_db)):
    """List async jobs; summary ignores ALL filters and pagination.

    Newest created_at first, historical NULL last; id DESC breaks ties.
    Historical jobs created before migration may have created_at=null.
    """
    try:
        return success(list_jobs(db, page=page, page_size=page_size, status=status,
                                 operation=operation, document_id=document_id))
    except SQLAlchemyError:
        db.rollback()
        return JSONResponse(status_code=503, content=fail('Job storage unavailable; retry the request.'))


@router.get('/api/index-jobs/{job_id}')
def get_job(job_id:int,db:Session=Depends(get_db)):
    try:
        job=db.get(IndexJob,job_id)
    except SQLAlchemyError:
        db.rollback()
        return JSONResponse(status_code=503,content=fail('Job storage unavailable; retry the request.'))
    if not job or job.job_type not in KINDS:
        return JSONResponse(status_code=404,content=fail('Async job not found.'))
    return success(serialize(job))


@router.post('/api/index-jobs/{job_id}/retry', status_code=202)
def retry_job(job_id:int,db:Session=Depends(get_db)):
    try:
        return accepted(retry(db,job_id))
    except ValueError as exc:
        return JSONResponse(status_code=409,content=fail(str(exc)))
    except SQLAlchemyError:
        db.rollback()
        return JSONResponse(status_code=503,content=fail('Job storage unavailable; retry the request.'))
