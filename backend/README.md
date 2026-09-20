# ResearchGraph backend

Run from the repository root using [deployment instructions](../docs/deployment.md).
FastAPI serves documents, persistent index jobs, scoped search, grounded QA,
Research and evaluation APIs. MySQL is authoritative; Chroma is derived.

For local development, create a virtual environment here, install requirements.txt
and requirements-dev.txt, and copy .env.example to .env. Install requirements-bge.txt
for real embeddings. Configure MySQL and Chroma before starting:

```sh
python -m scripts.migrate_all
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Offline validation (Fake Embedding, mocked LLM, disposable test storage):

```sh
python tests/smoke_import.py
python -m pytest -p no:cacheprovider
```

Production still requires MySQL. SQLite in tests is isolated test infrastructure.
Safe frozen query fixtures are copied into the Docker test image at its expected
paths; the public repository does not bundle papers or real model outputs.

Operational recovery tools default to dry-run: scripts.reconcile_vectors and
scripts.source_gc. Repairs require an explicit --repair and a quiet writer period.
Use [migration guidance](migrations/README.md) and back up MySQL plus raw sources.
No automatic cleanup should delete user data to force a successful validation.
