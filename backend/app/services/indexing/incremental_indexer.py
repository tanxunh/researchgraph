from __future__ import annotations

import json
import logging
from collections import Counter
from contextlib import ExitStack
from datetime import datetime, timezone
from typing import Literal

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.document import Document, DocumentChunk, DocumentVersion, DocumentVersionChunk
from app.models.entity import EntityMention
from app.models.index_job import IndexJob
from app.models.relation import Relation
from app.services.chunking.text_chunker import ChunkCandidate, TextChunker
from app.services.graph.graph_builder import GraphBuilder
from app.services.graph.extraction_schema import ChunkGraphExtraction
from app.services.indexing.hash_service import chunking_config_hash, evidence_identity, hash_text, stable_chunk_id
from app.services.indexing.version_chunks import VersionChunk, version_chunks
from app.services.indexing.source_gc import SourceGarbageCollector
from app.storage.local import LocalSourceStorage
from app.storage.base import StorageError
from app.services.parsing.base import ParsedDocument, ParserError
from app.vectorstore.chroma_store import ChromaStore

ReindexMode = Literal["full", "embedding_only", "graph_only"]


class IncrementalIndexError(Exception):
    pass


logger = logging.getLogger(__name__)


class IncrementalIndexer:
    """SQL authority -> verified vector publication -> activation.

    Graph extraction runs outside write transactions. Document row locks serialize
    mutations/publication; a job token fences publishers between the two commits.
    """

    def __init__(self, vector_store: ChromaStore | None = None, graph_extractor: object | None = None, *,
                 on_progress=None, on_job_started=None) -> None:
        self.settings = get_settings()
        self._vector_store = vector_store
        self.graph_extractor = graph_extractor
        self.on_progress = on_progress or (lambda stage: None)
        self.on_job_started = on_job_started or (lambda job_id: None)

    @property
    def vector_store(self) -> ChromaStore:
        if self._vector_store is None:
            self._vector_store = ChromaStore()
        return self._vector_store

    def import_parsed(self, db: Session, parsed: ParsedDocument) -> dict:
        parsed.validate()
        content_hash = hash_text(parsed.text)
        identity = evidence_identity(parsed, self.settings)
        document = self._find_document(db, parsed, content_hash)
        target = self._target_version(document) if document else None
        previous = db.scalar(select(DocumentVersion).where(
            DocumentVersion.document_id == document.id, DocumentVersion.version == target)) if document else None
        if previous and previous.evidence_identity_hash == identity:
            if document.status != "ready":
                return self.reindex(db, document, "embedding_only" if document.status in {"publishing", "publish_failed"} else "full")
            chunks = self._chunks(db, document.id)
            try:
                verified = self.vector_store.verify_document_chunks(chunks)
            except Exception as exc:
                raise IncrementalIndexError("Cannot verify existing vectors; restore Chroma and retry.") from exc
            if not verified:
                return self.reindex(db, document, "embedding_only")
            job = self._start_job(db, document.id, "new_document", "content unchanged")
            count = len(chunks)
            stats = dict(index_action="unchanged", chunk_count=count, unchanged_chunk_count=count,
                         added_chunk_count=0, removed_chunk_count=0, reembedded_chunk_count=0,
                         reextracted_chunk_count=0, chunks_reembedded=0, chunks_graphed=0)
            self._finish_job(db, job, "succeeded", stats)
            db.commit()
            return self._result(document, job, "unchanged", stats)

        document_id = document.id if document else None
        expected_head = (document.current_version, document.pending_version) if document else None
        old_chunks = self._chunks(db, document_id) if document else []
        old_keys = {(c.chunk_hash, c.occurrence_index) for c in old_chunks}
        job_type = "content_changed" if document else "new_document"
        job = self._start_job(db, document_id, job_type, "import document")
        job_id = job.id
        db.commit()
        try:
            self.on_progress("chunking")
            candidates = TextChunker().chunk(parsed)
            if not candidates:
                raise ParserError("Chunking produced no chunks; indexing was stopped.")
            self.on_progress("indexing")
            builder = self._graph_builder(db) if self.settings.graph_extraction_enabled else None
            counts = Counter()
            extractions = {}
            for candidate in candidates:
                key = (candidate.chunk_hash, counts[candidate.chunk_hash])
                counts[candidate.chunk_hash] += 1
                if builder is not None and key not in old_keys and candidate.chunk_hash not in extractions:
                    extractions[candidate.chunk_hash] = builder.extractor.extract(candidate.text)
            if document_id:
                document = self._lock_document(db, document_id)
                if document is None or (document.current_version, document.pending_version) != expected_head:
                    raise IncrementalIndexError("Document changed during preparation; retry import.")
            else:
                document = Document(source_type=parsed.source_type, source_uri=parsed.source_uri,
                                    title=parsed.title, content_hash=content_hash,
                                    parser_version=self.settings.parser_version, current_version=0, status="indexing")
                db.add(document)
                db.flush()
            document.title = parsed.title
            document.content_hash = content_hash
            document.parser_version = self.settings.parser_version
            document.metadata_json = json.dumps(parsed.metadata, ensure_ascii=False)
            document.error_message = None
            version = self._create_version(db, document, parsed, identity)
            chunks = self._sync_chunks(db, document, version, candidates, old_keys)
            graph_stats = self._apply_graph(builder, chunks["changed_chunks"], extractions) if builder else {"status": "disabled"}
            job = db.get(IndexJob, job_id)
            job.document_id = document.id
            stats = dict(index_action="created" if job_type == "new_document" else "updated",
                         chunk_count=len(chunks["current_chunks"]),
                         unchanged_chunk_count=len(chunks["current_chunks"]) - len(chunks["changed_chunks"]),
                         added_chunk_count=len(chunks["changed_chunks"]),
                         removed_chunk_count=chunks["stale_deleted"],
                         stale_chunks_deleted=chunks["stale_deleted"],
                         reembedded_chunk_count=len(chunks["changed_chunks"]),
                         reextracted_chunk_count=len(chunks["changed_chunks"]) if builder else 0,
                         chunks_reembedded=len(chunks["changed_chunks"]),
                         chunks_graphed=len(chunks["changed_chunks"]) if builder else 0, graph=graph_stats)
            changed_ids = {c.stable_chunk_id for c in chunks["changed_chunks"]}
            document.status = job.status = "publishing"
            job.stats_json = json.dumps(stats)
            document_id, expected_version = document.id, version.version
            db.commit()
        except Exception as exc:
            self._record_failure(db, job_id, exc)
            raise IncrementalIndexError("Document preparation failed; inspect index job and retry.") from exc
        self.on_progress("publishing")
        return self._publish(db, document_id, expected_version, job_id, stats, changed_ids=changed_ids)

    def reindex(self, db: Session, document: Document, mode: ReindexMode) -> dict:
        if mode == "graph_only" and not self.settings.graph_extraction_enabled:
            raise IncrementalIndexError("Graph extraction is disabled; enable GRAPH_EXTRACTION_ENABLED for graph_only reindex.")
        document_id, version = document.id, self._target_version(document)
        if mode == "embedding_only" and document.status not in {"ready", "publishing", "publish_failed"}:
            raise IncrementalIndexError("Graph preparation is incomplete; retry with mode=full.")
        snapshots = [(c.chunk_hash, c.text) for c in self._chunks(db, document_id)]
        job_type = {"full": "manual_reindex", "embedding_only": "embedding_changed",
                    "graph_only": "graph_extractor_changed"}[mode]
        job = self._start_job(db, document_id, job_type, f"manual {mode}")
        job_id = job.id
        db.commit()
        try:
            self.on_progress("indexing")
            enrich = self.settings.graph_extraction_enabled and mode != "embedding_only"
            builder = self._graph_builder(db) if enrich else None
            extractions = {key: builder.extractor.extract(text) for key, text in snapshots} if enrich else {}
            document = self._lock_document(db, document_id)
            if document is None or self._target_version(document) != version:
                raise IncrementalIndexError("Document changed during preparation; retry reindex.")
            chunks = self._chunks(db, document_id)
            graph_stats = self._apply_graph(builder, [c.chunk for c in chunks], extractions) if enrich else {"status": "disabled" if not self.settings.graph_extraction_enabled else "unchanged"}
            stats = dict(index_action="reindexed", mode=mode, chunk_count=len(chunks), graph=graph_stats)
            document.status = "publishing"
            job = db.get(IndexJob, job_id)
            job.status = "publishing"
            job.stats_json = json.dumps(stats)
            db.commit()
        except Exception as exc:
            self._record_failure(db, job_id, exc)
            raise IncrementalIndexError("Reindex preparation failed; inspect index job and retry.") from exc
        self.on_progress("publishing")
        # graph_only verifies existing publication, never silently repairs/re-embeds it.
        return self._publish(db, document_id, version, job_id, stats, verify_only=mode == "graph_only")

    def _publish(self, db: Session, document_id: int, version: int, job_id: int, stats: dict,
                 changed_ids: set[str] | None = None, stale_ids: list[str] | tuple = (),
                 verify_only: bool = False) -> dict:
        try:
            document = self._lock_document(db, document_id)
            owner = db.scalar(select(IndexJob.id).where(
                IndexJob.document_id == document_id, IndexJob.status == "publishing"
            ).order_by(IndexJob.id.desc()).limit(1))
            if document is None or self._target_version(document) != version or owner != job_id:
                raise IncrementalIndexError("Publication superseded; retry the current document.")
            chunks = self._chunks(db, document_id)
            if not chunks:
                raise IncrementalIndexError("Cannot activate an empty document.")
            if not verify_only:
                reembedded = self.vector_store.publish_document_chunks(chunks, changed_ids)
                stats["reembedded_chunk_count"] = stats["chunks_reembedded"] = reembedded
            if not self.vector_store.verify_document_chunks(chunks):
                raise IncrementalIndexError("Vector publication verification failed; retry embedding rebuild.")
            active_ids = {chunk.id for chunk in chunks}
            stale_ids = list(db.scalars(select(DocumentChunk.stable_chunk_id).where(
                DocumentChunk.document_id == document_id, DocumentChunk.id.not_in(active_ids))).all())
            cleanup_error = self._cleanup_vectors(stale_ids)
            for chunk in chunks:
                chunk.chunk.indexed_at = datetime.now(timezone.utc)
                chunk.chunk.embedding_version = self.vector_store.embedding.version
            document.current_version = version
            document.pending_version = None
            document.status = "ready"
            document.indexed_at = datetime.now(timezone.utc)
            document.error_message = None
            stats["cleanup_pending"] = cleanup_error is not None
            job = db.get(IndexJob, job_id)
            self._finish_job(db, job, "cleanup_failed" if cleanup_error else "succeeded", stats, cleanup_error)
            db.commit()  # C: publication was verified; activation and job complete atomically.
            return self._result(document, job, stats["index_action"], stats)
        except Exception as exc:
            logger.error("vector_publish_failure", extra={"document_id": document_id, "index_job_id": job_id})
            self._record_failure(db, job_id, exc, document_id, version)
            raise IncrementalIndexError("Vector publication failed; authoritative data is retained. Retry reindex.") from exc

    def delete_document(self, db: Session, document: Document) -> dict:
        storage = LocalSourceStorage()
        with ExitStack() as stack:
            try:
                stack.enter_context(storage.mutation_lock())
            except (OSError, StorageError):
                # Source outage must not prevent authoritative logical deletion.
                return self._delete_document(db, document, storage, source_cleanup=False)
            return self._delete_document(db, document, storage)

    def _delete_document(self, db: Session, document: Document, storage: LocalSourceStorage,
                         source_cleanup: bool = True) -> dict:
        document_id = document.id
        job = self._start_job(db, document_id, "delete_cleanup", "delete document")
        job_id = job.id
        try:
            document = self._lock_document(db, document_id)
            if document is None:
                raise IncrementalIndexError("Document already deleted.")
            chunks = list(db.scalars(select(DocumentChunk).where(DocumentChunk.document_id == document_id)).all())
            source_keys = list(db.scalars(select(DocumentVersion.source_storage_key).where(
                DocumentVersion.document_id == document_id, DocumentVersion.source_storage_key.is_not(None))).all())
            version_ids = select(DocumentVersion.id).where(DocumentVersion.document_id == document_id)
            db.execute(delete(DocumentVersionChunk).where(DocumentVersionChunk.document_version_id.in_(version_ids)))
            stable_ids, chunk_ids = [c.stable_chunk_id for c in chunks], [c.id for c in chunks]
            if chunk_ids:
                db.execute(delete(Relation).where(Relation.evidence_chunk_id.in_(chunk_ids)))
                db.execute(delete(EntityMention).where(EntityMention.chunk_id.in_(chunk_ids)))
                db.execute(delete(DocumentChunk).where(DocumentChunk.id.in_(chunk_ids)))
            db.execute(delete(DocumentVersion).where(DocumentVersion.document_id == document_id))
            # Explicit for SQLite tests too; MySQL also has ON DELETE SET NULL.
            db.query(IndexJob).filter(IndexJob.document_id == document_id).update({IndexJob.document_id: None})
            db.delete(document)
            db.flush()
            orphan_count = self._graph_builder(db).cleanup_orphan_entities()
            stats = dict(index_action="deleted", document_id=document_id, chunks_deleted=len(chunk_ids),
                         orphan_entities_deleted=orphan_count, cleanup_pending=True)
            job = db.get(IndexJob, job_id)
            job.status = "cleanup_pending"
            job.stats_json = json.dumps(stats)
            db.commit()  # Deletion is authoritative even if Chroma is unavailable.
        except Exception as exc:
            self._record_failure(db, job_id, exc)
            raise IncrementalIndexError("Document deletion failed; inspect index job.") from exc
        cleanup_error = self._cleanup_vectors(stable_ids)
        source_cleanup_error = None
        try:
            if not source_cleanup:
                raise StorageError("Source lock unavailable; defer cleanup to source GC.")
            stats["source_blobs_deleted"] = SourceGarbageCollector(db, storage).delete_unreferenced(source_keys)
        except Exception as exc:
            source_cleanup_error = exc
            logger.error("source_delete_failure", extra={"document_id": document_id})
        cleanup_error = cleanup_error or source_cleanup_error
        stats["cleanup_pending"] = cleanup_error is not None
        try:
            self._finish_job(db, db.get(IndexJob, job_id), "cleanup_failed" if cleanup_error else "succeeded", stats, cleanup_error)
            db.commit()
        except Exception as exc:
            db.rollback()
            raise IncrementalIndexError("Document deleted; cleanup status could not be saved. Run reconciliation.") from exc
        return dict(document_id=document_id, index_job_id=job_id, index_action="deleted",
                    cleanup_pending=stats["cleanup_pending"])

    def _cleanup_vectors(self, stable_ids: list[str] | tuple) -> Exception | None:
        try:
            self.vector_store.delete_chunk_ids(stable_ids)
        except Exception as exc:
            logger.error("vector_delete_failure", extra={"vector_count": len(stable_ids)})
            return exc
        return None

    def _lock_document(self, db: Session, document_id: int) -> Document | None:
        return db.scalar(select(Document).where(Document.id == document_id)
                         .with_for_update().execution_options(populate_existing=True))

    @staticmethod
    def _target_version(document: Document) -> int:
        return document.pending_version if document.pending_version is not None else document.current_version

    def _chunks(self, db: Session, document_id: int) -> list[VersionChunk]:
        document = db.get(Document, document_id)
        return version_chunks(db, document_id, self._target_version(document)) if document else []

    def _apply_graph(self, builder: GraphBuilder, chunks: list[DocumentChunk],
                     extractions: dict[str, ChunkGraphExtraction]) -> dict:
        stats = dict(chunks=len(chunks), entities=0, mentions=0, relations=0)
        for chunk in chunks:
            builder.cleanup_chunk(chunk.id)
            result = builder.apply_extraction(chunk, extractions[chunk.chunk_hash])
            chunk.graph_extractor_version = self.settings.graph_extractor_version
            for key in result:
                stats[key] += result[key]
        return stats

    def _graph_builder(self, db: Session) -> GraphBuilder:
        if self.graph_extractor is not None:
            return GraphBuilder(db, extractor=self.graph_extractor)
        return GraphBuilder(db)

    def _find_document(self, db: Session, parsed: ParsedDocument, content_hash: str) -> Document | None:
        # Source equality defines logical identity; content equality only deduplicates blobs.
        return db.scalar(select(Document).where(Document.source_type == parsed.source_type,
                                                Document.source_uri == parsed.source_uri))

    def _create_version(self, db: Session, document: Document, parsed: ParsedDocument, identity: str) -> DocumentVersion:
        number = (db.scalar(select(func.max(DocumentVersion.version)).where(
            DocumentVersion.document_id == document.id)) or 0) + 1
        source = parsed.raw_source
        version = DocumentVersion(
            document_id=document.id, version=number, content_hash=hash_text(parsed.text),
            parser_version=self.settings.parser_version, title=parsed.title,
            source_type=parsed.source_type, source_uri=parsed.source_uri,
            source_checksum=source.checksum if source else None,
            source_storage_key=source.storage_key if source else None,
            source_content_type=source.content_type if source else None,
            source_encoding=source.encoding if source else None,
            chunker_version=self.settings.chunker_version, chunk_size=self.settings.chunk_size,
            chunk_overlap=self.settings.chunk_overlap, chunking_config_hash=chunking_config_hash(self.settings),
            evidence_identity_hash=identity)
        db.add(version)
        db.flush()
        document.pending_version = number
        return version

    def _sync_chunks(self, db: Session, document: Document, version: DocumentVersion,
                     candidates: list[ChunkCandidate], old_keys: set[tuple[str, int]]) -> dict:
        occurrences = {(c.chunk_hash, c.occurrence_index): c for c in db.scalars(
            select(DocumentChunk).where(
                DocumentChunk.document_id == document.id,
                DocumentChunk.chunk_hash.in_({c.chunk_hash for c in candidates} | {key[0] for key in old_keys})
            )).all()}
        counts = Counter()
        changed, current = [], []
        for candidate in candidates:
            occurrence = counts[candidate.chunk_hash]
            counts[candidate.chunk_hash] += 1
            key = candidate.chunk_hash, occurrence
            chunk = occurrences.get(key)
            if chunk is None:
                chunk = DocumentChunk(
                    stable_chunk_id=stable_chunk_id(document.id, candidate.chunk_hash, occurrence),
                    document_id=document.id, document_version_id=version.id,
                    occurrence_index=occurrence, chunk_index=candidate.chunk_index,
                    text=candidate.text, chunk_hash=candidate.chunk_hash,
                    page_number=candidate.page_number, section_title=candidate.section_title,
                    token_count=candidate.token_count, embedding_version=self.settings.embedding_version,
                    graph_extractor_version=self.settings.graph_extractor_version if self.settings.graph_extraction_enabled else "not-extracted")
                db.add(chunk)
                db.flush()
                occurrences[key] = chunk
            db.add(DocumentVersionChunk(document_version_id=version.id, chunk_id=chunk.id,
                                        ordinal=candidate.chunk_index, page_number=candidate.page_number,
                                        section_title=candidate.section_title))
            current.append(chunk)
            if key not in old_keys:
                changed.append(chunk)
        current_ids = {c.id for c in current}
        stale = [c for key, c in occurrences.items() if key in old_keys and c.id not in current_ids]
        if stale:
            ids = [c.id for c in stale]
            # Graph is current-only. Historical text/membership never depends on it.
            db.execute(delete(Relation).where(Relation.evidence_chunk_id.in_(ids)))
            db.execute(delete(EntityMention).where(EntityMention.chunk_id.in_(ids)))
            self._graph_builder(db).cleanup_orphan_entities()
        db.flush()
        return {"changed_chunks": changed, "current_chunks": current, "stale_deleted": len(stale)}

    def _start_job(self, db: Session, document_id: int | None, job_type: str, reason: str) -> IndexJob:
        job = IndexJob(document_id=document_id, job_type=job_type, status="running", reason=reason)
        db.add(job)
        db.commit()
        db.refresh(job)
        self.on_job_started(job.id)
        return job

    def _finish_job(self, db: Session, job: IndexJob, status: str, stats: dict, exc: Exception | None = None) -> None:
        job.status = status
        job.finished_at = datetime.now(timezone.utc)
        job.stats_json = json.dumps(stats, ensure_ascii=False)
        if exc:
            job.error_type = exc.__class__.__name__
            job.error_message = f"{exc.__class__.__name__}: operation failed; retry or reconcile."
        db.add(job)
        db.flush()

    def _record_failure(self, db: Session, job_id: int, exc: Exception,
                        document_id: int | None = None, version: int | None = None) -> None:
        db.rollback()
        try:
            if document_id is not None:
                document = self._lock_document(db, document_id)
                owner = db.scalar(select(IndexJob.id).where(
                    IndexJob.document_id == document_id, IndexJob.status == "publishing"
                ).order_by(IndexJob.id.desc()).limit(1))
                if document and self._target_version(document) == version and owner == job_id:
                    document.status = "publish_failed"
                    document.error_message = "Vector publication failed; retry reindex."
            job = db.get(IndexJob, job_id)
            if job:
                self._finish_job(db, job, "failed", {"index_action": "failed", "retryable": True}, exc)
            db.commit()
        except Exception:
            db.rollback()
            # Durable publishing/non-ready state remains safe if DB is unavailable.
            logger.error("index_failure_status_write_failed", extra={"index_job_id": job_id})

    def _result(self, document: Document, job: IndexJob, action: str, stats: dict | None = None) -> dict:
        return {
            "document_id": document.id,
            "status": document.status,
            "content_hash": document.content_hash,
            "version": document.current_version,
            "index_job_id": job.id,
            "index_action": action,
            "stats": stats or {},
        }
