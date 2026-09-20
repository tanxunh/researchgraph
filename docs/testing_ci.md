# Testing and CI

Automated regression is separate from model-quality evaluation. Tests use Fake
Embedding, mocked LLM/extraction and isolated temporary storage. They do not
inherit business credentials or require external model calls.

## Offline tests

From a configured repository root:

```sh
docker compose --profile test run --build --rm --no-deps backend-tests
docker compose --profile test run --rm --no-deps backend-tests python tests/smoke_import.py
```

Local backend alternative: install requirements.txt and requirements-dev.txt, then
run `python -m pytest -p no:cacheprovider` and `python tests/smoke_import.py`.
Docker and CI use Python 3.11. Docker test packaging includes the safe query/locator
fixtures and release-preflight helper required by regression.

Frontend, from frontend/:

```sh
npm ci
npm test -- --run
npm run build
```

## Real-storage integration

```sh
docker compose --profile consistency run --build --rm backend-consistency-tests
docker compose --profile consistency stop mysql-consistency chroma-consistency
```

This opt-in profile uses disposable MySQL/Chroma services with tmpfs storage,
no business volumes and no real LLM. Tests create/drop only the dedicated test
schema. Never point tests at a business database. SQLite tests do not establish
MySQL migration correctness. MySQL-specific cases skip when services are absent.

Coverage includes indexing failure/recovery, immutable versions, historical
Evidence, citation validation, document scopes, persistent jobs, Research ownership,
Harness budgets, retrieval/evaluation contracts and frontend workspace behavior.
Model quality and semantic support require separate evaluation and human review;
see [evaluation](evaluation.md). No real benchmark is automatically rerun by CI.

Export validation: 254 backend unit tests and 134 frontend tests passed; offline
import smoke and frontend build passed. This does not claim a new full integration
or real-model run. CI configuration is included; hosted CI execution is not claimed.
