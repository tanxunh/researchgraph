import hashlib

import pytest

from app.storage.base import StorageError
from app.storage.local import LocalSourceStorage


def test_content_addressed_roundtrip_and_deduplication(tmp_path):
    store = LocalSourceStorage(tmp_path)
    raw = "Original UTF-8 bytes: 中文\r\n".encode("utf-8")
    first = store.save(raw, "text/plain", "utf-8")
    second = store.save(raw, "text/markdown", "utf-8")
    assert first.storage_key == second.storage_key
    assert first.checksum == hashlib.sha256(raw).hexdigest()
    assert store.load(first.storage_key) == raw
    assert len(list(store.iter_keys())) == 1


@pytest.mark.parametrize("key", ["../../secret.pdf", "/etc/passwd", "C:/secret", "sources/aa/bb/not-a-hash.blob"])
def test_untrusted_storage_keys_are_rejected(tmp_path, key):
    store = LocalSourceStorage(tmp_path)
    for operation in (store.load, store.exists, store.delete):
        with pytest.raises(StorageError):
            operation(key)


def test_corruption_is_not_trusted_on_load_or_dedup(tmp_path):
    store = LocalSourceStorage(tmp_path)
    source = store.save(b"original", "application/octet-stream")
    (tmp_path / source.storage_key).write_bytes(b"corrupt")
    with pytest.raises(StorageError, match="checksum"):
        store.load(source.storage_key)
    with pytest.raises(StorageError, match="checksum"):
        store.save(b"original", "application/octet-stream")
