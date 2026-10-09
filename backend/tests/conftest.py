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

TEST_ENVIRONMENT = {
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
}
os.environ.update(TEST_ENVIRONMENT)


@pytest.fixture(autouse=True)
def isolated_settings(monkeypatch):
    # Restore isolation after tests that mutate the cached Settings object.
    from app.core.config import get_settings

    # Evaluation runner imports may mutate os.environ during collection.
    # Reestablish the mock-only test contract before every test.
    for key, value in TEST_ENVIRONMENT.items():
        monkeypatch.setenv(key, value)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


PRIVATE_EVALUATION_MODULES = ('integration/test_chunking_freeze_corpus.py', 'integration/test_final_retrieval_artifacts.py', 'integration/test_fusion_optimization_artifacts.py', 'integration/test_reranker_optimization_artifacts.py', 'unit/test_v2_g4_integrity.py')

def pytest_collection_modifyitems(items):
    """Artifact checks are opt-in; ordinary CI must not need private papers."""
    tests_root = Path(__file__).resolve().parent
    for item in items:
        relative = Path(item.path).relative_to(tests_root).as_posix()
        if relative in PRIVATE_EVALUATION_MODULES:
            item.add_marker(pytest.mark.evaluation_private)
