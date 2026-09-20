"""Offline tests never inherit runtime database, Chroma or LLM credentials.
SQLite here is test infrastructure, not the application database.
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
for path in (BACKEND_ROOT.parent, BACKEND_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

os.environ.update({
    "APP_ENV": "test",
    "DATABASE_URL": "sqlite://",
    "EMBEDDING_PROVIDER": "fake",
    "EMBEDDING_DIMENSION": "8",
    "GRAPH_EXTRACTOR_MODE": "mock",
    # Existing Graph regression fixtures explicitly opt into enrichment.
    "GRAPH_EXTRACTION_ENABLED": "true",
    "CHROMA_HOST": "",
    "SOURCE_STORAGE_ROOT": tempfile.mkdtemp(prefix="lifeflow-sources-tests-"),
    "CHROMA_PERSIST_DIR": tempfile.mkdtemp(prefix="lifeflow-tests-"),
    "ANONYMIZED_TELEMETRY": "FALSE",
    "LLM_API_KEY": "",
    "LLM_BASE_URL": "http://127.0.0.1:1/v1",
})


@pytest.fixture(autouse=True)
def isolated_settings():
    # Restore isolation after tests that mutate the cached Settings object.
    from app.core.config import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
