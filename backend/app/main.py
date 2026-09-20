from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.index_jobs import router as index_jobs_router
from app.services.indexing.async_jobs import IndexWorker
from app.api.research import router as research_router
from app.api.documents import router as documents_router
from app.api.evaluations import router as evaluations_router
from app.api.health import router as system_router
from app.api.qa import router as qa_router
from app.api.search import router as search_router
from app.core.config import get_settings, llm_configuration_status, log_runtime_configuration
from app.core.database import create_db_tables, engine
from app.utils.response import success

settings = get_settings()

app = FastAPI(
    title=settings.app_name,
    description="LifeFlow ResearchGraph backend API",
    version="0.2.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def on_startup() -> None:
    create_db_tables()
    log_runtime_configuration(settings)
    if settings.app_env != "test":
        app.state.index_worker = IndexWorker(engine)
        app.state.index_worker.start()


@app.on_event("shutdown")
def on_shutdown() -> None:
    worker = getattr(app.state, "index_worker", None)
    if worker:
        worker.stop()


@app.get("/health", tags=["Health"])
async def health_check():
    return success({"status": "ok", "service": settings.app_name, "llm": llm_configuration_status(settings)})


app.include_router(research_router)
app.include_router(system_router)
app.include_router(index_jobs_router)
app.include_router(documents_router)
app.include_router(search_router)
app.include_router(qa_router)
app.include_router(evaluations_router)
