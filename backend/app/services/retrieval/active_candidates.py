"""The shared authoritative boundary for evidence candidates."""
from sqlalchemy.orm import Session

from app.models.document import Document, DocumentChunk
from app.services.indexing.version_chunks import VersionChunk, membership_query


def resolve_active(db: Session, chunk_ids: list[int]) -> dict[int, tuple[VersionChunk, Document]]:
    resolved = {}
    ids = list(set(chunk_ids))
    for start in range(0, len(ids), 200):
        rows = db.execute(membership_query().where(
            DocumentChunk.id.in_(ids[start:start + 200]), Document.status == "ready")
            .execution_options(populate_existing=True)).all()
        resolved.update({chunk.id: (VersionChunk(chunk, membership, version), document)
                         for chunk, membership, version, document in rows})
    return resolved


def matches_candidate(row, chunk_id, stable_id) -> bool:
    return row is not None and row[0].id == chunk_id and row[0].stable_chunk_id == stable_id
