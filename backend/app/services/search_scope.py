"""Resolve public Search scope before candidate retrieval, using MySQL state."""
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.document import Document, DocumentVersion


def resolve_search_scope(db: Session, document_ids: list[int] | None) -> dict:
    if document_ids is None:
        return {"mode": "global"}
    requested = list(dict.fromkeys(document_ids))
    rows = db.execute(
        select(Document.id, Document.status, DocumentVersion.id)
        .outerjoin(DocumentVersion, (DocumentVersion.document_id == Document.id)
                   & (DocumentVersion.version == Document.current_version))
        .where(Document.id.in_(requested))
    ).all() if requested else []
    existing = {document_id: (status, version_id) for document_id, status, version_id in rows}
    eligible, excluded = [], []
    for document_id in requested:
        state = existing.get(document_id)
        if state is not None and state[0] == "ready" and state[1] is not None:
            eligible.append(document_id)
        else:
            excluded.append({"document_id": document_id,
                             "reason": "not_found" if state is None else "not_ready"})
    return {"mode": "explicit", "requested_document_ids": requested,
            "eligible_document_ids": eligible, "excluded_documents": excluded}
