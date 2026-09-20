"""Bounded SQL/Chroma reconciliation. Repair never activates a document."""
from __future__ import annotations

import json
import logging
import tempfile
from collections.abc import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.document import Document, DocumentChunk, DocumentVersion
from app.vectorstore.chroma_store import ChromaStore
from app.services.indexing.version_chunks import VersionChunk, membership_query

logger = logging.getLogger(__name__)


class VectorReconciliationService:
    def __init__(self, db: Session, vector_store: ChromaStore | None = None, batch_size: int = 128):
        if not 1 <= batch_size <= 1000:
            raise ValueError("batch_size must be between 1 and 1000.")
        self.db = db
        self.store = vector_store or ChromaStore(create_collection=False)
        self.batch_size = batch_size

    def _expected(self):
        # Pending committed membership is recoverable but never user evidence.
        return membership_query(pending=True)

    def run(self, repair: bool = False, on_issue: Callable[[dict], None] | None = None) -> dict:
        if self.db.new or self.db.dirty or self.db.deleted:
            raise ValueError("Reconciliation requires a dedicated session without pending changes.")
        report = dict(dry_run=not repair, collection=self.store.collection_name,
                      orphan_vector_ids=[], missing_vector_ids=[], stale_vector_ids=[],
                      orphan_count=0, missing_count=0, stale_count=0,
                      deleted_count=0, upserted_count=0, id_sample_limit=1000)
        def record(kind, ids):
            report[f"{kind}_count"] += len(ids)
            sample = report[f"{kind}_vector_ids"]
            sample.extend(ids[:max(0, 1000 - len(sample))])
            if on_issue:
                for vector_id in ids:
                    on_issue({"kind": kind, "vector_id": vector_id})

        # Complete offset scan BEFORE mutations: deleting during pagination skips IDs.
        # Spool orphan IDs to disk, not an unbounded Python list.
        with tempfile.TemporaryFile(mode="w+t", encoding="utf-8") as orphan_spool:
            for ids in self.store.iter_id_batches(self.batch_size):
                expected = set(self.db.scalars(self._expected().with_only_columns(
                    DocumentChunk.stable_chunk_id).where(DocumentChunk.stable_chunk_id.in_(ids))).all())
                orphans = [key for key in ids if key not in expected]
                record("orphan", orphans)
                if repair and orphans:
                    orphan_spool.write(json.dumps(orphans) + "\n")
            if repair:
                orphan_spool.seek(0)
                for line in orphan_spool:
                    ids = json.loads(line)
                    # Recheck against latest committed SQL before destructive cleanup.
                    self.db.rollback()
                    expected = set(self.db.scalars(self._expected().with_only_columns(
                        DocumentChunk.stable_chunk_id).where(DocumentChunk.stable_chunk_id.in_(ids))).all())
                    ids = [key for key in ids if key not in expected]
                    try:
                        self.store.delete_chunk_ids(ids)
                    except Exception:
                        logger.error("vector_delete_failure", extra={"vector_count": len(ids)})
                        raise
                    report["deleted_count"] += len(ids)

        after_id = 0
        while True:
            self.db.rollback()  # Dedicated service session; fresh snapshot per page.
            rows = self.db.execute(self._expected().where(DocumentChunk.id > after_id)
                                   .order_by(DocumentChunk.id).limit(self.batch_size)).all()
            chunks = [VersionChunk(chunk, membership, version) for chunk, membership, version, document in rows]
            if not chunks:
                break
            after_id = chunks[-1].id
            metadata = self.store.metadata_for_ids(c.stable_chunk_id for c in chunks)
            missing = [c for c in chunks if c.stable_chunk_id not in metadata]
            stale = [c for c, expected in zip(chunks, self.store.chunk_metadata(chunks))
                     if c.stable_chunk_id in metadata and not self.store.metadata_matches(metadata[c.stable_chunk_id], expected)]
            record("missing", [c.stable_chunk_id for c in missing])
            record("stale", [c.stable_chunk_id for c in stale])
            if repair and (missing or stale):
                try:
                    self.store.upsert_document_chunks(missing + stale)
                    if not self.store.verify_document_chunks(missing + stale):
                        raise RuntimeError("Reconciliation publication verification failed.")
                except Exception:
                    logger.error("vector_publish_failure")
                    raise
                report["upserted_count"] += len(missing) + len(stale)
        logger.info("reconciliation_orphan_count=%s reconciliation_missing_count=%s",
                    report["orphan_count"], report["missing_count"],
                    extra={"reconciliation_orphan_count": report["orphan_count"],
                           "reconciliation_missing_count": report["missing_count"]})
        report["ids_truncated"] = any(report[f"{kind}_count"] > 1000 for kind in ("orphan", "missing", "stale"))
        return report
