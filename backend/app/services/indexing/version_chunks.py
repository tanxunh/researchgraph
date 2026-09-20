"""SQL queries for immutable memberships; shared by publication and retrieval."""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.document import Document, DocumentChunk, DocumentVersion, DocumentVersionChunk


@dataclass
class VersionChunk:
    chunk: DocumentChunk
    membership: DocumentVersionChunk
    version: DocumentVersion

    def __getattr__(self, name):
        return getattr(self.chunk, name)

    @property
    def document_version_id(self):
        return self.version.id

    @property
    def chunk_index(self):
        return self.membership.ordinal

    @property
    def page_number(self):
        return self.membership.page_number

    @property
    def section_title(self):
        return self.membership.section_title


def membership_query(*, pending: bool = False):
    target = func.coalesce(Document.pending_version, Document.current_version) if pending else Document.current_version
    return (select(DocumentChunk, DocumentVersionChunk, DocumentVersion, Document)
            .join(DocumentVersionChunk, DocumentVersionChunk.chunk_id == DocumentChunk.id)
            .join(DocumentVersion, DocumentVersion.id == DocumentVersionChunk.document_version_id)
            .join(Document, Document.id == DocumentVersion.document_id)
            .where(DocumentChunk.document_id == Document.id, DocumentVersion.version == target))


def version_chunks(db: Session, document_id: int, version_number: int) -> list[VersionChunk]:
    rows = db.execute(
        select(DocumentChunk, DocumentVersionChunk, DocumentVersion)
        .join(DocumentVersionChunk, DocumentVersionChunk.chunk_id == DocumentChunk.id)
        .join(DocumentVersion, DocumentVersion.id == DocumentVersionChunk.document_version_id)
        .where(DocumentVersion.document_id == document_id, DocumentVersion.version == version_number,
               DocumentChunk.document_id == document_id)
        .order_by(DocumentVersionChunk.ordinal)
        .execution_options(populate_existing=True)).all()
    return [VersionChunk(chunk, membership, version) for chunk, membership, version in rows]
