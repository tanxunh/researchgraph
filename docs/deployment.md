# Local deployment

## Quick Start

Requires Git, Docker Desktop in Linux-container mode and Docker Compose v2. Clone this repository using its GitHub Clone URL, then open a terminal in the cloned repository root. Do not overwrite an existing `.env`.

```powershell
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
# Edit .env: choose MYSQL_ROOT_PASSWORD and MYSQL_PASSWORD.
# LLM_API_KEY is optional until using Ask/Research; use your own key if needed.
docker compose config --quiet
docker compose build
# One ordered migration command; dependencies start and become healthy first.
docker compose run --rm backend python -m scripts.migrate_all
docker compose up -d
docker compose ps
Invoke-RestMethod http://127.0.0.1:5173/health
```

Open **http://127.0.0.1:5173**. Frontend serves a production build through nginx; `/api` and `/health` proxy to backend inside Compose. Backend runs one Uvicorn process without reload. Sidebar Backend Online reflects `/health`; it does not assert that a model is already loaded. API/Swagger: http://127.0.0.1:8000/docs. MySQL host port: 3307; Chroma host port: 8001. Services bind to the local loopback interface; this is a single-user local deployment, not an authenticated public hosting setup.

Change `FRONTEND_PORT`, `BACKEND_PORT`, `MYSQL_PUBLISHED_PORT`, `CHROMA_PUBLISHED_PORT` if existing development services occupy these ports. Container-to-container addresses remain `mysql:3306` and `chroma:8000`. Keep `VITE_API_BASE_URL=/` for the recommended same-origin proxy; this is a build-time value, so rebuild frontend after changing it. No Docker hostname is sent to the browser. CORS lists explicit development origins on 5173/5174; cross-origin hosting must specify its actual origin, never wildcard with credentials.

### Configuration and first model use

Root `.env` configures Compose. `backend/.env` is only for local Python development; files are not synchronized or copied into images. LLM provider is selected through the existing OpenAI-compatible `LLM_BASE_URL` and `LLM_MODEL=deepseek-chat`; there is no separate `LLM_PROVIDER` setting. Leave `LLM_API_KEY=` empty for Library, indexing and Search. Ask/Research need a valid key and otherwise return the existing configuration failure. Do not call them merely to check startup.

Keep `GRAPH_EXTRACTION_ENABLED=false`: Library/Search/QA/Research do not require Graph extraction. Production embedding remains `bge`, `BAAI/bge-small-zh-v1.5`, 512 dimensions, CPU; reranker stays off. Compose installs BGE and CPU Torch dependencies, but does not bake model weights into the image. First indexing/search lazily downloads/loads weights and may take longer. Network access to Hugging Face is required for an empty cache; the model-cache volume persists downloads across restarts. Model files are not committed. `/api/system/status` exposes loaded/ready/error without forcing eager loading.

### Existing databases and storage

Before upgrading, back up MySQL and raw sources together and stop all application writers (including any local Uvicorn process). Retain your existing database credentials and Compose project name; changing passwords in `.env` does not change accounts in an initialized MySQL volume. Add the new Compose variables from `.env.example` without replacing your secrets.

```powershell
docker compose stop backend frontend
docker compose build
docker compose run --rm backend python -m scripts.migrate_all
docker compose up -d
```

The runner applies evidence-version, async-job and job-created-at migrations in that order, using their existing restartable implementations. Fresh schema and existing compatible schema are supported. Migration failure stops the command; do not start writers until it is resolved. No destructive downgrade or schema recreation is performed. See [migration details](../backend/migrations/README.md).

MySQL and Chroma retain the existing named volume keys. Raw sources now live in `researchgraph_raw` mounted at `/app/backend/storage`; model caches use `researchgraph_models` at `/app/backend/data`. For upgrades from the old repository bind mount, **copy the existing raw-source directory before starting the new backend**. With writers stopped, and only if `backend/storage` is your actual old storage path:

```powershell
docker compose run --rm --no-deps --volume "${PWD}/backend/storage:/legacy-raw:ro" backend python -c "import shutil; shutil.copytree('/legacy-raw','/app/backend/storage',dirs_exist_ok=True)"
```

If the old `SOURCE_STORAGE_ROOT` was different, mount that actual directory read-only instead. Keep the original backup. Do not point an existing database at an empty raw volume. Compose project-scoped volume names mean changing `-p` opens separate data. `docker compose down` retains named volumes; **`docker compose down -v` deletes the project's local database, vectors, raw sources and model cache** and must not be used to troubleshoot ordinary startup errors.

### Troubleshooting and development

```powershell
docker compose logs -f backend
docker compose logs -f frontend
docker compose ps
```

Health waiting usually means inspecting MySQL/Chroma logs or the migration error. Image/package/model downloads require network connectivity. The synchronous Research API and single-process indexing worker are retained.

For host development, see [backend commands](../backend/README.md). Install `requirements-bge.txt` for production embeddings, configure `backend/.env` with `127.0.0.1:3307` for MySQL and `127.0.0.1:8001` for Chroma, then start Uvicorn. Frontend: `cd frontend`, `npm ci`, `npm run dev`; default client target is http://127.0.0.1:8000. Explicit 5173/5174 origins are documented in the environment example.
