from __future__ import annotations

import json

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from fastapi.responses import JSONResponse

from app.services.parsing.base import ParserError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.document import Document, DocumentChunk, DocumentVersion, DocumentVersionChunk
from app.models.entity import EntityMention
from app.models.index_job import IndexJob
from app.models.relation import Relation
from app.schemas.document import DocumentImportRequest, ReindexRequest, ReprocessRequest
from app.services.indexing.incremental_indexer import IncrementalIndexer, IncrementalIndexError
from app.utils.response import fail, success
from app.services.indexing.ingestion import DocumentIngestion, RawSourceUnavailable
from app.services.indexing.version_chunks import version_chunks
from app.storage.base import StorageError

router = APIRouter(prefix="/api/documents", tags=["Documents"])


@router.post("/import")
def import_document(payload: DocumentImportRequest, db: Session = Depends(get_db)):
    try:
        if payload.source_type == "url":
            result = DocumentIngestion().import_url(db, str(payload.url), payload.title)
        else:
            result = DocumentIngestion().import_text(db, payload.title, payload.text or "", payload.source_uri)
    except ParserError:
        return JSONResponse(status_code=400, content=fail("Document could not be parsed or contains no usable text."))
    except (IncrementalIndexError, StorageError, ValueError) as exc:
        return fail(str(exc))
    return success(result)


@router.post("/import/file")
async def import_file(file: UploadFile = File(...), source_uri: str | None = Form(None),
                      db: Session = Depends(get_db)):
    data = await file.read()
    filename = file.filename or "uploaded-file"
    suffix = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""
    source_type = {"pdf": "pdf", "docx": "docx", "txt": "text", "md": "text", "markdown": "text"}.get(suffix)
    if source_type is None:
        return fail("Only PDF, DOCX, TXT, and Markdown files are supported.")
    try:
        result = DocumentIngestion().import_bytes(
            db, data, source_type, source_uri or filename, content_type=file.content_type or "application/octet-stream",
            encoding="utf-8" if source_type == "text" else None)
    except (ParserError, UnicodeError):
        return JSONResponse(status_code=400, content=fail("Document could not be parsed or contains no usable text."))
    except (IncrementalIndexError, StorageError) as exc:
        return fail(str(exc))
    return success(result)


@router.get("")
def list_documents(db: Session = Depends(get_db)):
    documents = db.scalars(select(Document).order_by(Document.updated_at.desc())).all()
    return success([_serialize_document(db, document) for document in documents])


@router.get("/{document_id}")
def get_document(document_id: int, db: Session = Depends(get_db)):
    document = db.get(Document, document_id)
    if not document:
        return fail("Document not found.")
    return success(_serialize_document(db, document, include_chunks=True))


@router.post("/{document_id}/reindex")
def reindex_document(document_id: int, payload: ReindexRequest, db: Session = Depends(get_db)):
    document = db.get(Document, document_id)
    if not document:
        return fail("Document not found.")
    try:
        result = IncrementalIndexer().reindex(db, document, payload.mode)
    except IncrementalIndexError as exc:
        return fail(str(exc))
    return success(result)


@router.get("/{document_id}/versions")
def list_versions(document_id: int, limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0),
                  db: Session = Depends(get_db)):
    document = db.get(Document, document_id)
    if not document:
        return fail("Document not found.")
    rows = db.scalars(select(DocumentVersion).where(DocumentVersion.document_id == document_id)
                      .order_by(DocumentVersion.version.desc()).offset(offset).limit(limit)).all()
    return success([{
        "id": version.id, "version": version.version, "is_current": version.version == document.current_version,
        "is_pending": version.version == document.pending_version, "created_at": version.created_at,
        "source_checksum": version.source_checksum, "raw_source_available": bool(version.source_storage_key),
        "parser_version": version.parser_version, "chunker_version": version.chunker_version,
        "chunking_config_hash": version.chunking_config_hash,
    } for version in rows])


@router.post("/{document_id}/reprocess")
def reprocess_document(document_id: int, payload: ReprocessRequest, db: Session = Depends(get_db)):
    document = db.get(Document, document_id)
    if not document:
        return fail("Document not found.")
    try:
        return success(DocumentIngestion().reprocess(db, document, payload.source_version_id))
    except RawSourceUnavailable as exc:
        return fail(str(exc), {"error_type": "raw_source_unavailable"})
    except (ParserError, UnicodeError):
        return JSONResponse(status_code=400, content=fail("Stored source could not be parsed."))
    except (IncrementalIndexError, StorageError) as exc:
        return fail(str(exc))


@router.delete("/{document_id}")
def delete_document(document_id: int, db: Session = Depends(get_db)):
    document = db.get(Document, document_id)
    if not document:
        return fail("Document not found.")
    try:
        result = IncrementalIndexer().delete_document(db, document)
    except IncrementalIndexError as exc:
        return fail(str(exc))
    return success(result)


def _serialize_document(db: Session, document: Document, include_chunks: bool = False) -> dict:
    chunks = version_chunks(db, document.id, document.current_version)
    chunk_count = len(chunks)
    chunk_ids = [chunk.id for chunk in chunks]
    entity_count = db.scalar(select(func.count(EntityMention.id)).where(EntityMention.chunk_id.in_(chunk_ids))) if chunk_ids else 0
    relation_count = db.scalar(select(func.count(Relation.id)).where(Relation.evidence_chunk_id.in_(chunk_ids))) if chunk_ids else 0
    latest_job = db.scalar(select(IndexJob).where(IndexJob.document_id == document.id).order_by(IndexJob.started_at.desc()).limit(1))
    data = {
        "id": document.id,
        "source_type": document.source_type,
        "source_uri": document.source_uri,
        "title": document.title,
        "content_hash": document.content_hash,
        "parser_version": document.parser_version,
        "current_version": document.current_version,
        "pending_version": document.pending_version,
        "status": document.status,
        "error_message": document.error_message,
        "created_at": document.created_at,
        "updated_at": document.updated_at,
        "indexed_at": document.indexed_at,
        "chunk_count": chunk_count,
        "entity_count": entity_count or 0,
        "relation_count": relation_count or 0,
        "latest_index_job": _serialize_job(latest_job) if latest_job else None,
    }
    if include_chunks:
        data["chunks"] = [
            {
                "id": chunk.id,
                "stable_chunk_id": chunk.stable_chunk_id,
                "chunk_index": chunk.chunk_index,
                "document_version_id": chunk.document_version_id,
                "occurrence_index": chunk.occurrence_index,
                "text": chunk.text,
                "page_number": chunk.page_number,
                "section_title": chunk.section_title,
                "chunk_hash": chunk.chunk_hash,
            }
            for chunk in chunks
        ]
    return data


def _serialize_job(job: IndexJob) -> dict:
    stats = None
    if job.stats_json:
        try:
            stats = json.loads(job.stats_json)
        except json.JSONDecodeError:
            stats = None
    return {
        "id": job.id,
        "job_type": job.job_type,
        "progress_stage": job.progress_stage,
        "attempts": job.attempts,
        "pipeline_job_id": job.pipeline_job_id,
        "status": job.status,
        "reason": job.reason,
        "started_at": job.started_at,
        "finished_at": job.finished_at,
        "error_message": job.error_message,
        "stats": stats,
    }
