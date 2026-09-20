from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


class StorageError(Exception):
    pass


@dataclass(frozen=True)
class SourceReference:
    checksum: str
    storage_key: str
    content_type: str
    encoding: str | None = None


class SourceStorage(Protocol):
    def save(self, data: bytes, content_type: str, encoding: str | None = None) -> SourceReference: ...
    def load(self, storage_key: str) -> bytes: ...
    def exists(self, storage_key: str) -> bool: ...
    def delete(self, storage_key: str) -> None: ...
