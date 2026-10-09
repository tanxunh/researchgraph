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

## Public and private suites

Default pytest excludes the registered evaluation_private marker. CI also passes
`-m "not evaluation_private"` explicitly. Five artifact-dependent modules are
marked at collection in tests/conftest.py; synthetic evaluation tests remain public.
Deselected tests are not counted as passes. CI uses no PDFs, Gold spans, Chroma
snapshot or real LLM credentials.

Private artifact checks are explicitly opt-in from backend/:

```sh
python -m pytest -p no:cacheprovider -m evaluation_private
```

This requires the original private artifacts. Missing inputs fail explicitly; they
are never fabricated or downloaded. G4 also retains its standalone stdlib command:
`python backend/tests/unit/test_v2_g4_integrity.py` from the root, with private inputs.

The public chunking contract is also packaged byte-for-byte in tests/fixtures for
the backend-only Docker build context. Its expected hash remains checked; no Gold
text is packaged. Real-storage MySQL/Chroma integration remains separately opt-in.

Release checks must distinguish actual executed results from configured hosted CI.
See [V2 methodology](evaluation_v2.md) and [data policy](evaluation_data_policy.md).

## V2.0 release hardening validation

The official Docker test target and a separate public-files-only mirror both ran
501 passing tests, with 5 explicitly skipped real-MySQL DDL cases and 31 private
artifact checks deselected. The mirror was mounted read-only with container network
disabled; it contained neither private corpus nor raw evaluation traces. This is
local clean-clone-equivalent validation, not a claim of hosted GitHub Actions execution.

Frontend: 134 tests passed; production build passed with a bundle-size warning.
Offline import/index smoke passed with Fake Embedding, temporary SQLite and zero
external LLM calls. Separately, the existing private G4 integrity runner passed all
16 checks. No retrieval, answer generation or quality evaluation was rerun.

An initial full-suite failure exposed evaluation-runner import-time environment
leakage. The test fixture now restores its mock-only environment before every test;
production runner and retrieval behavior were not changed. Dependency deprecation
warnings and the opt-in real-MySQL test coverage remain explicit limitations.
