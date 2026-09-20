import logging
from functools import lru_cache

from pydantic import AliasChoices, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)


class Settings(BaseSettings):
    """Application settings for LifeFlow ResearchGraph."""

    app_name: str = Field(default="LifeFlow ResearchGraph", alias="RESEARCHGRAPH_APP_NAME")
    app_env: str = "development"
    api_prefix: str = "/api"

    llm_api_key: str = Field(default="", alias="LLM_API_KEY")
    llm_base_url: str = Field(default="https://api.deepseek.com/v1", alias="LLM_BASE_URL")
    llm_model: str = Field(default="deepseek-chat", validation_alias=AliasChoices("LLM_MODEL", "LLM_MODEL_ID"))
    llm_timeout_seconds: float = Field(default=60.0, alias="LLM_TIMEOUT_SECONDS")

    database_url: str = Field(
        default="mysql+pymysql://lifeflow:lifeflow_password@127.0.0.1:3306/lifeflow_researchgraph?charset=utf8mb4",
        alias="DATABASE_URL",
    )
    chroma_host: str = Field(default="", alias="CHROMA_HOST")
    chroma_port: int = Field(default=8000, alias="CHROMA_PORT")
    chroma_ssl: bool = Field(default=False, alias="CHROMA_SSL")
    chroma_persist_dir: str = Field(default="./chroma_db", alias="CHROMA_PERSIST_DIR")

    embedding_dimension: int = Field(default=512, alias="EMBEDDING_DIMENSION")
    embedding_provider: str = Field(default="bge", alias="EMBEDDING_PROVIDER")
    embedding_model: str = Field(default="BAAI/bge-small-zh-v1.5", alias="EMBEDDING_MODEL")
    embedding_device: str = Field(default="cpu", alias="EMBEDDING_DEVICE")
    embedding_cache_dir: str = Field(default="./data/model_cache", alias="EMBEDDING_CACHE_DIR")
    embedding_batch_size: int = Field(default=32, alias="EMBEDDING_BATCH_SIZE")
    embedding_normalize: bool = Field(default=True, alias="EMBEDDING_NORMALIZE")
    embedding_local_files_only: bool = Field(default=False, alias="EMBEDDING_LOCAL_FILES_ONLY")
    embedding_version: str = Field(default="embedding-v1", alias="EMBEDDING_VERSION")

    source_storage_root: str = Field(default="./storage", alias="SOURCE_STORAGE_ROOT")
    chunker_version: str = Field(default="text-chunker-v1", alias="CHUNKER_VERSION")

    parser_version: str = Field(default="parser-v1", alias="PARSER_VERSION")
    graph_extractor_version: str = Field(default="graph-extractor-v1", alias="GRAPH_EXTRACTOR_VERSION")
    graph_extraction_enabled: bool = Field(default=False, alias="GRAPH_EXTRACTION_ENABLED")
    graph_extractor_mode: str = Field(default="llm", alias="GRAPH_EXTRACTOR_MODE")
    chunk_size: int = Field(default=700, alias="CHUNK_SIZE")
    chunk_overlap: int = Field(default=100, alias="CHUNK_OVERLAP")

    dense_top_k: int = Field(default=8, alias="DENSE_TOP_K")
    bm25_top_k: int = Field(default=8, alias="BM25_TOP_K")
    graph_max_hops: int = Field(default=2, ge=1, le=2, alias="GRAPH_MAX_HOPS")
    graph_max_neighbors: int = Field(default=12, ge=1, le=64, alias="GRAPH_MAX_NEIGHBORS")
    graph_max_paths: int = Field(default=20, ge=1, le=200, alias="GRAPH_MAX_PATHS")
    graph_max_expanded_entities: int = Field(default=32, ge=1, le=200, alias="GRAPH_MAX_EXPANDED_ENTITIES")
    graph_hop_decay: float = Field(default=0.7, gt=0, lt=1, alias="GRAPH_HOP_DECAY")
    graph_rrf_weight: float = Field(default=0.5, ge=0, le=1, alias="GRAPH_RRF_WEIGHT")
    rrf_k: int = Field(default=60, alias="RRF_K")
    graph_min_relation_confidence: float = Field(default=0.45, alias="GRAPH_MIN_RELATION_CONFIDENCE")

    reranker_enabled: bool = Field(default=False, alias="RERANKER_ENABLED")
    reranker_model: str = Field(default="BAAI/bge-reranker-base", alias="RERANKER_MODEL")
    reranker_revision: str = Field(default="465b4b7ddf2be0a020c8ad6e525b9bb1dbb708ae", alias="RERANKER_REVISION")
    reranker_device: str = Field(default="cpu", alias="RERANKER_DEVICE")
    reranker_candidate_n: int = Field(default=20, ge=20, le=20, alias="RERANKER_CANDIDATE_N")
    reranker_final_k: int = Field(default=10, ge=5, le=10, alias="RERANKER_FINAL_K")

    research_max_subtasks: int = Field(default=8, ge=1, le=8, alias="RESEARCH_MAX_SUBTASKS")
    research_top_k: int = Field(default=5, ge=1, le=10, alias="RESEARCH_TOP_K")
    research_max_retries: int = Field(default=1, ge=0, le=1, alias="RESEARCH_MAX_RETRIES")
    research_max_documents: int = Field(default=5, ge=1, le=10, alias="RESEARCH_MAX_DOCUMENTS")
    research_max_evidence: int = Field(default=40, ge=1, le=80, alias="RESEARCH_MAX_EVIDENCE")

    research_max_model_calls: int = Field(default=36, ge=1, le=100, alias="RESEARCH_MAX_MODEL_CALLS")
    research_max_tool_calls: int = Field(default=40, ge=1, le=100, alias="RESEARCH_MAX_TOOL_CALLS")
    research_max_retrieval_calls: int = Field(default=34, ge=1, le=100, alias="RESEARCH_MAX_RETRIEVAL_CALLS")
    research_max_runtime_seconds: float = Field(default=300, gt=0, le=3600, alias="RESEARCH_MAX_RUNTIME_SECONDS")
    research_tool_timeout_seconds: float = Field(default=60, gt=0, le=300, alias="RESEARCH_TOOL_TIMEOUT_SECONDS")

    cors_origins: str = Field(
        default="http://localhost:5173,http://127.0.0.1:5173",
        alias="CORS_ORIGINS",
    )

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    @model_validator(mode="after")
    def validate_researchgraph_settings(self):
        self.app_name = "LifeFlow ResearchGraph"
        env = self.app_env.lower().strip()
        provider = self.embedding_provider.lower().strip()
        if env == "production" and provider in {"hash", "fake"}:
            raise ValueError("Production requires EMBEDDING_PROVIDER=bge. hash/fake are disabled.")
        if provider not in {"bge", "hash", "fake", "sentence_transformer", "sentence-transformer"}:
            raise ValueError(f"Unsupported EMBEDDING_PROVIDER: {self.embedding_provider}")
        extractor_mode = self.graph_extractor_mode.lower().strip()
        self.graph_extractor_mode = extractor_mode
        if extractor_mode not in {"llm", "mock"}:
            raise ValueError("GRAPH_EXTRACTOR_MODE must be llm or mock.")
        if extractor_mode == "mock" and env != "test":
            raise ValueError("GRAPH_EXTRACTOR_MODE=mock is only allowed when APP_ENV=test.")
        if self.graph_max_hops > 2:
            raise ValueError("GRAPH_MAX_HOPS must be <= 2 for bounded graph search.")
        if self.chunk_overlap >= self.chunk_size:
            raise ValueError("CHUNK_OVERLAP must be smaller than CHUNK_SIZE.")
        return self

    @property
    def mysql_url(self) -> str:
        return self.database_url

    @property
    def llm_model_id(self) -> str:
        return self.llm_model

    @property
    def rag_chunk_size(self) -> int:
        return self.chunk_size

    @property
    def rag_chunk_overlap(self) -> int:
        return self.chunk_overlap

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()





def llm_configuration_status(settings: Settings | None = None) -> dict:
    settings = settings or get_settings()
    configured = bool(settings.llm_api_key.strip())
    error = None
    if settings.graph_extraction_enabled and settings.graph_extractor_mode == "llm" and not configured:
        error = "LLM_API_KEY is not configured while GRAPH_EXTRACTOR_MODE=llm. Formal graph extraction will fail until an OpenAI-compatible API key is provided."
    return {
        "llm_api_key_configured": configured,
        "llm_base_url": settings.llm_base_url,
        "llm_model": settings.llm_model,
        "graph_extractor_mode": settings.graph_extractor_mode,
        "graph_extraction_enabled": settings.graph_extraction_enabled,
        "error": error,
    }


def log_runtime_configuration(settings: Settings | None = None) -> None:
    status = llm_configuration_status(settings)
    logger.info("LLM_API_KEY configured: %s", status["llm_api_key_configured"])
    logger.info("LLM_BASE_URL: %s", status["llm_base_url"])
    logger.info("LLM_MODEL: %s", status["llm_model"])
    logger.info("GRAPH_EXTRACTOR_MODE: %s", status["graph_extractor_mode"])
    if status["error"]:
        logger.error(status["error"])