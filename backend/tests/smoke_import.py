"""Offline API import smoke. Not a MySQL or real-model acceptance test."""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
runtime_dir = Path(tempfile.mkdtemp(prefix="lifeflow-import-smoke-"))
os.environ.update({
    "SOURCE_STORAGE_ROOT": tempfile.mkdtemp(prefix="lifeflow-smoke-sources-"),
    "APP_ENV": "test",
    "DATABASE_URL": f"sqlite:///{runtime_dir / 'smoke.db'}",
    "CHROMA_HOST": "",
    "CHROMA_PERSIST_DIR": str(runtime_dir / "chroma"),
    "EMBEDDING_PROVIDER": "fake",
    "EMBEDDING_DIMENSION": "8",
    "GRAPH_EXTRACTOR_MODE": "mock",
    "LLM_API_KEY": "",
    "LLM_BASE_URL": "http://127.0.0.1:1/v1",
    "ANONYMIZED_TELEMETRY": "FALSE",
})

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from app.core.database import SessionLocal
from app.main import app
from app.models import Document, DocumentChunk, IndexJob
from app.vectorstore.chroma_store import ChromaStore

with TestClient(app) as client:
    assert client.get("/health").status_code == 200
    response = client.post("/api/documents/import", json={
        "source_type": "text",
        "title": "Phase 0 synthetic smoke",
        "source_uri": "test:phase0:smoke",
        "text": "ProtoNet is evaluated on miniImageNet and reports Accuracy.",
    })
    body = response.json()
    assert response.status_code == 200 and body["code"] == 0, body
    assert body["data"]["index_action"] == "created", body
    document_id = body["data"]["document_id"]
    detail = client.get(f"/api/documents/{document_id}").json()
    assert detail["code"] == 0 and detail["data"]["chunk_count"] == 1, detail

with SessionLocal() as db:
    counts = {
        "documents": db.scalar(select(func.count(Document.id))),
        "chunks": db.scalar(select(func.count(DocumentChunk.id))),
        "succeeded_jobs": db.scalar(select(func.count(IndexJob.id)).where(IndexJob.status == "succeeded")),
        "vectors": ChromaStore().count(),
    }
    assert all(value == 1 for value in counts.values()), counts
print(json.dumps({
    "status": "passed",
    "api_import": "created",
    "counts": counts,
    "database": "temporary SQLite",
    "embedding": "fake",
    "extraction": "mock",
    "external_llm_calls": 0,
}))
