from __future__ import annotations

import hashlib
from dataclasses import replace

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.document import Document, DocumentVersion
from app.services.indexing.incremental_indexer import IncrementalIndexer, IncrementalIndexError
from app.services.parsing.docx_parser import DocxParser
from app.services.parsing.pdf_parser import PdfParser
from app.services.parsing.text_parser import TextParser
from app.services.parsing.url_parser import UrlParser
from app.storage.base import SourceReference, StorageError
from app.storage.local import LocalSourceStorage


class RawSourceUnavailable(IncrementalIndexError):
    pass


class DocumentIngestion:
    def __init__(self, indexer: IncrementalIndexer | None = None, storage: LocalSourceStorage | None = None):
        self.indexer = indexer or IncrementalIndexer()
        self.storage = storage or LocalSourceStorage()

    def import_text(self, db: Session, title: str, text: str, source_uri: str | None = None) -> dict:
        return self.import_bytes(db, text.encode("utf-8"), "text", source_uri or f"text:{title.strip()}",
                                 title, "text/plain; charset=utf-8", "utf-8")

    def import_url(self, db: Session, url: str, title: str | None = None) -> dict:
        snapshot = UrlParser().fetch_snapshot(url)
        return self.import_bytes(db, snapshot["data"], "url", url, title,
                                 snapshot["content_type"], snapshot["encoding"])

    def import_bytes(self, db: Session, data: bytes, source_type: str, source_uri: str,
                     title: str | None = None, content_type: str = "application/octet-stream",
                     encoding: str | None = None) -> dict:
        with self.storage.mutation_lock():
            source = self.storage.save(data, content_type, encoding)
            self.indexer.on_progress("parsing")
            parsed = self._parse(data, source_type, source_uri, title, encoding)
            return self.indexer.import_parsed(db, replace(parsed, raw_source=source))

    def _parse(self, data: bytes, source_type: str, source_uri: str, title: str | None, encoding: str | None):
        if source_type == "pdf":
            parsed = PdfParser().parse(source_uri, data)
        elif source_type == "docx":
            parsed = DocxParser().parse(source_uri, data)
        elif source_type == "url":
            parsed = UrlParser().parse_html(source_uri, data.decode(encoding or "utf-8", errors="replace"), title)
        else:
            parsed = TextParser().parse(title or source_uri, data.decode("utf-8-sig"), source_uri)
        return replace(parsed, title=(title or parsed.title)[:255], source_uri=source_uri)

    def reprocess(self, db: Session, document: Document, source_version_id: int | None = None) -> dict:
        version = (db.get(DocumentVersion, source_version_id) if source_version_id else db.scalar(
            select(DocumentVersion).where(DocumentVersion.document_id == document.id,
                                          DocumentVersion.version == document.current_version)))
        if version is None or version.document_id != document.id:
            raise IncrementalIndexError("Source version does not belong to this document.")
        if not version.source_storage_key:
            raise RawSourceUnavailable("raw_source_unavailable: upload the original source before reprocessing.")
        with self.storage.mutation_lock():
            try:
                data = self.storage.load(version.source_storage_key)
            except StorageError as exc:
                raise RawSourceUnavailable("raw_source_unavailable: restore or upload the original source.") from exc
            if hashlib.sha256(data).hexdigest() != version.source_checksum:
                raise RawSourceUnavailable("raw_source_unavailable: source reference checksum does not match the stored bytes.")
            source = SourceReference(version.source_checksum, version.source_storage_key,
                                     version.source_content_type or "application/octet-stream", version.source_encoding)
            self.indexer.on_progress("parsing")
            parsed = self._parse(data, version.source_type or document.source_type,
                                 document.source_uri, version.title or document.title, version.source_encoding)
            return self.indexer.import_parsed(db, replace(parsed, raw_source=source))
