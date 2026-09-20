from sqlalchemy import select, tuple_
from sqlalchemy.orm import Session

from app.models.document import DocumentChunk, DocumentVersion, DocumentVersionChunk


def _query():
    return (select(DocumentVersion, DocumentVersionChunk, DocumentChunk)
            .join(DocumentVersionChunk, DocumentVersionChunk.document_version_id == DocumentVersion.id)
            .join(DocumentChunk, DocumentChunk.id == DocumentVersionChunk.chunk_id)
            .where(DocumentChunk.document_id == DocumentVersion.document_id))


def _serialize(row):
    version, membership, chunk = row
    return {
        "document": {"id": version.document_id, "title": version.title, "source_uri": version.source_uri},
        "version": {"id": version.id, "number": version.version, "parser_version": version.parser_version,
                    "chunking_config_hash": version.chunking_config_hash},
        "chunk_id": chunk.stable_chunk_id, "chunk_occurrence_id": chunk.id, "text": chunk.text,
        "location": {"ordinal": membership.ordinal, "page_number": membership.page_number,
                     "section_title": membership.section_title},
        "source": {"checksum": version.source_checksum, "storage_key": version.source_storage_key,
                   "content_type": version.source_content_type,
                   "original_url": version.source_uri if version.source_type == "url" else None},
    }


def resolve_version_chunk(db: Session, document_version_id: int, chunk_identity: str | int) -> dict | None:
    condition = DocumentChunk.id == chunk_identity if isinstance(chunk_identity, int) else DocumentChunk.stable_chunk_id == chunk_identity
    row = db.execute(_query().where(DocumentVersion.id == document_version_id, condition)).first()
    return _serialize(row) if row is not None else None


def resolve_version_chunks(db: Session, locators: list[tuple[int, str]]) -> dict[tuple[int, str], dict]:
    """Batch form of the same historical resolver, not a current-version lookup."""
    locators = list(dict.fromkeys(locators))
    resolved = {}
    for start in range(0, len(locators), 200):
        rows = db.execute(_query().where(
            tuple_(DocumentVersion.id, DocumentChunk.stable_chunk_id).in_(locators[start:start + 200]))).all()
        for row in rows:
            value = _serialize(row)
            resolved[(value["version"]["id"], value["chunk_id"])] = value
    return resolved
