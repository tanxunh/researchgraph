from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Document(Base):
    __tablename__ = "documents"
    __table_args__ = (
        UniqueConstraint("source_type", "source_uri", name="uq_documents_source"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    source_type: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    source_uri: Mapped[str] = mapped_column(String(700), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    parser_version: Mapped[str] = mapped_column(String(50), nullable=False)
    current_version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    pending_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="pending", index=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)
    indexed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    versions: Mapped[list[DocumentVersion]] = relationship(
        "DocumentVersion",
        back_populates="document",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    chunks: Mapped[list[DocumentChunk]] = relationship(
        "DocumentChunk",
        back_populates="document",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class DocumentVersion(Base):
    __tablename__ = "document_versions"
    __table_args__ = (
        UniqueConstraint("document_id", "version", name="uq_document_versions_document_version"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    parser_version: Mapped[str] = mapped_column(String(50), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

    source_checksum: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source_storage_key: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    source_content_type: Mapped[str | None] = mapped_column(String(128), nullable=True)
    source_encoding: Mapped[str | None] = mapped_column(String(40), nullable=True)
    source_type: Mapped[str | None] = mapped_column(String(20), nullable=True)
    source_uri: Mapped[str | None] = mapped_column(String(700), nullable=True)
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    chunker_version: Mapped[str | None] = mapped_column(String(50), nullable=True)
    chunk_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    chunk_overlap: Mapped[int | None] = mapped_column(Integer, nullable=True)
    chunking_config_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    evidence_identity_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)

    document: Mapped[Document] = relationship("Document", back_populates="versions")


class DocumentChunk(Base):
    __tablename__ = "document_chunks"
    __table_args__ = (
        UniqueConstraint("document_id", "chunk_hash", "occurrence_index", name="uq_document_chunks_occurrence"),
        UniqueConstraint("stable_chunk_id", name="uq_document_chunks_stable_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    stable_chunk_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True)
    document_version_id: Mapped[int] = mapped_column(
        ForeignKey("document_versions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Legacy version/location columns are immutable creation provenance only.
    occurrence_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    chunk_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    page_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    section_title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    token_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    embedding_version: Mapped[str] = mapped_column(String(50), nullable=False)
    graph_extractor_version: Mapped[str] = mapped_column(String(50), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    indexed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    document: Mapped[Document] = relationship("Document", back_populates="chunks")



class DocumentVersionChunk(Base):
    """Immutable evidence membership and location; never repoint a Chunk."""
    __tablename__ = "document_version_chunks"
    __table_args__ = (
        UniqueConstraint("document_version_id", "chunk_id", name="uq_version_chunks_membership"),
        UniqueConstraint("document_version_id", "ordinal", name="uq_version_chunks_ordinal"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    document_version_id: Mapped[int] = mapped_column(
        ForeignKey("document_versions.id", ondelete="CASCADE"), nullable=False, index=True)
    chunk_id: Mapped[int] = mapped_column(
        ForeignKey("document_chunks.id", ondelete="CASCADE"), nullable=False, index=True)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    page_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    section_title: Mapped[str | None] = mapped_column(String(255), nullable=True)


# Service-layer writes cannot silently mutate a cited layout. Explicit SQL
# migrations/deletion are separate operator actions; this is not an ACL system.
from sqlalchemy import event, inspect


@event.listens_for(DocumentVersion, "before_update")
@event.listens_for(DocumentVersionChunk, "before_update")
def _immutable_evidence(mapper, connection, target):
    if any(attribute.history.has_changes() for attribute in inspect(target).attrs):
        raise ValueError("Evidence versions and memberships are immutable; create a new version.")


@event.listens_for(DocumentChunk, "before_update")
def _immutable_chunk_content(mapper, connection, target):
    fields = ("document_id", "document_version_id", "stable_chunk_id", "chunk_hash", "text",
              "occurrence_index", "chunk_index", "page_number", "section_title", "token_count")
    if any(inspect(target).attrs[name].history.has_changes() for name in fields):
        raise ValueError("Chunk identity/content is immutable; create another occurrence.")
