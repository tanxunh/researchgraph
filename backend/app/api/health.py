from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.document import Document, DocumentChunk
from app.models.entity import Entity
from app.models.index_job import IndexJob
from app.models.relation import Relation
from app.core.config import llm_configuration_status
from app.utils.response import success
from app.vectorstore.embeddings import embedding_status

router = APIRouter(prefix="/api/system", tags=["System Status"])


@router.get("/status")
def system_status(db: Session = Depends(get_db)):
    return success(
        {
            "document_count": db.scalar(select(func.count(Document.id))) or 0,
            "chunk_count": db.scalar(select(func.count(DocumentChunk.id))) or 0,
            "entity_count": db.scalar(select(func.count(Entity.id))) or 0,
            "relation_count": db.scalar(select(func.count(Relation.id))) or 0,
            "index_success_count": db.scalar(select(func.count(IndexJob.id)).where(IndexJob.status == "succeeded")) or 0,
            "index_failed_count": db.scalar(select(func.count(IndexJob.id)).where(IndexJob.status == "failed")) or 0,
            "recent_index_jobs": [
                {
                    "id": job.id,
                    "document_id": job.document_id,
                    "job_type": job.job_type,
                    "status": job.status,
                    "reason": job.reason,
                    "started_at": job.started_at,
                    "finished_at": job.finished_at,
                    "error_message": job.error_message,
                }
                for job in db.scalars(select(IndexJob).order_by(IndexJob.started_at.desc()).limit(10)).all()
            ],
            "embedding": embedding_status(),
            "llm": llm_configuration_status(),
        }
    )
