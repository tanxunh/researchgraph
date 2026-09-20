from __future__ import annotations

from itertools import islice

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.document import DocumentVersion
from app.storage.local import LocalSourceStorage


class SourceGarbageCollector:
    def __init__(self, db: Session, storage: LocalSourceStorage | None = None):
        self.db = db
        self.storage = storage or LocalSourceStorage()

    def delete_unreferenced(self, keys: list[str]) -> int:
        references = set(self.db.scalars(select(DocumentVersion.source_storage_key).where(
            DocumentVersion.source_storage_key.in_(keys))).all())
        deleted = 0
        for key in set(keys) - references:
            self.storage.delete(key)
            deleted += 1
        return deleted

    def run(self, repair: bool = False, on_issue=None) -> dict:
        if self.db.new or self.db.dirty or self.db.deleted:
            raise ValueError("Source GC requires a clean dedicated session.")
        report = dict(dry_run=not repair, orphan_count=0, deleted_count=0, orphan_source_keys=[], ids_truncated=False)
        with self.storage.mutation_lock():
            self.db.rollback()
            keys = iter(self.storage.iter_keys())
            while batch := list(islice(keys, 128)):
                references = set(self.db.scalars(select(DocumentVersion.source_storage_key).where(
                    DocumentVersion.source_storage_key.in_(batch))).all())
                orphan = [key for key in batch if key not in references]
                report["orphan_count"] += len(orphan)
                report["orphan_source_keys"].extend(orphan[:max(0, 1000-len(report["orphan_source_keys"]))])
                if on_issue:
                    for key in orphan:
                        on_issue({"source_storage_key": key})
                if repair:
                    report["deleted_count"] += self.delete_unreferenced(orphan)
        report["ids_truncated"] = report["orphan_count"] > 1000
        return report
