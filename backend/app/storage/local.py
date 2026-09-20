from __future__ import annotations

import hashlib
import os
import re
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path

from app.core.config import get_settings
from app.storage.base import SourceReference, StorageError

_KEY = re.compile(r"sources/([0-9a-f]{2})/([0-9a-f]{2})/([0-9a-f]{64})\.blob")


class LocalSourceStorage:
    """Content-addressed bytes. Filenames never participate in storage paths."""

    def __init__(self, root: str | Path | None = None):
        self.root = Path(root or get_settings().source_storage_root).resolve()

    def _path(self, key: str) -> Path:
        match = _KEY.fullmatch(key)
        if not match or match[1] != match[3][:2] or match[2] != match[3][2:4]:
            raise StorageError("Invalid source storage key.")
        path = (self.root / key).resolve()
        if not path.is_relative_to(self.root):
            raise StorageError("Source path escapes the storage root.")
        return path

    def save(self, data: bytes, content_type: str, encoding: str | None = None) -> SourceReference:
        checksum = hashlib.sha256(data).hexdigest()
        key = f"sources/{checksum[:2]}/{checksum[2:4]}/{checksum}.blob"
        path = self._path(key)
        try:
            if path.exists():
                self.load(key)  # Detect a corrupt existing blob instead of trusting its name.
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                temporary = None
                try:
                    with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".source-", delete=False) as stream:
                        temporary = Path(stream.name)
                        stream.write(data)
                        stream.flush()
                        os.fsync(stream.fileno())
                    os.replace(temporary, path)
                finally:
                    if temporary is not None:
                        temporary.unlink(missing_ok=True)
        except OSError as exc:
            raise StorageError("Raw source could not be saved.") from exc
        return SourceReference(checksum, key, content_type[:128], encoding)

    def load(self, storage_key: str) -> bytes:
        path = self._path(storage_key)
        try:
            data = path.read_bytes()
        except OSError as exc:
            raise StorageError("Raw source is unavailable.") from exc
        checksum = hashlib.sha256(data).hexdigest()
        if path.stem != checksum:
            raise StorageError("Raw source checksum verification failed.")
        return data

    def exists(self, storage_key: str) -> bool:
        return self._path(storage_key).is_file()

    def delete(self, storage_key: str) -> None:
        try:
            self._path(storage_key).unlink(missing_ok=True)
        except OSError as exc:
            raise StorageError("Raw source cleanup failed; retry source GC.") from exc

    def iter_keys(self):
        directory = self.root / "sources"
        if directory.exists():
            for path in directory.glob("*/*/*.blob"):
                key = path.relative_to(self.root).as_posix()
                self._path(key)  # Reject symlink escapes too.
                yield key

    @contextmanager
    def mutation_lock(self):
        """Serialize import references and GC across local processes.

        The lock covers save -> SQL publication and SQL deletion -> source cleanup.
        It deliberately favors correctness over concurrent import throughput.
        """
        try:
            self.root.mkdir(parents=True, exist_ok=True)
            lock_stream = (self.root / ".source-lifecycle.lock").open("a+b")
        except OSError as exc:
            raise StorageError("Source storage is unavailable; check its configured directory.") from exc
        with lock_stream as stream:
            if os.name == "nt":
                import msvcrt
                if stream.tell() == 0:
                    stream.write(b"0")
                    stream.flush()
                while True:
                    try:
                        stream.seek(0)
                        msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                        break
                    except OSError:
                        time.sleep(0.05)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                if os.name == "nt":
                    stream.seek(0)
                    msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
