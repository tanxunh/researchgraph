from __future__ import annotations

import hashlib
import logging
import math
import re
import threading
import time
from typing import Protocol

from app.core.config import Settings, get_settings

logger = logging.getLogger(__name__)
TOKEN_PATTERN = re.compile(r"[\w\u4e00-\u9fff]+", re.UNICODE)


class EmbeddingProvider(Protocol):
    provider_name: str
    model_name: str
    version: str
    dimension: int

    @property
    def loaded(self) -> bool:
        ...

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        ...

    def embed_query(self, text: str) -> list[float]:
        ...


class EmbeddingProviderError(Exception):
    """Raised when an embedding provider cannot be initialized or used."""


class HashEmbedding:
    """Deterministic local embedding for explicit development mode only."""

    provider_name = "hash"
    model_name = "hash-token-v1"

    def __init__(self, dimension: int | None = None, version: str = "v1") -> None:
        settings = get_settings()
        self.dimension = dimension or settings.embedding_dimension
        self.version = version

    @property
    def loaded(self) -> bool:
        return True

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self.embed_query(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        vector = [0.0] * self.dimension
        tokens = self._tokenize(text)
        if not tokens:
            return vector
        for token in tokens:
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            index = int.from_bytes(digest[:4], "big") % self.dimension
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            vector[index] += sign
        return _normalize(vector)

    def _tokenize(self, text: str) -> list[str]:
        return [token.lower() for token in TOKEN_PATTERN.findall(text)]


class FakeEmbeddingProvider(HashEmbedding):
    """Small deterministic provider for automated tests; never use in production."""

    provider_name = "fake"
    model_name = "fake-embedding-v1"

    def __init__(self, dimension: int = 8, version: str = "test") -> None:
        super().__init__(dimension=dimension, version=version)


class BgeEmbeddingProvider:
    """Lazy SentenceTransformer provider for real local Chinese semantic retrieval."""

    provider_name = "bge"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.model_name = settings.embedding_model
        self.version = settings.embedding_version
        self.dimension = settings.embedding_dimension
        self._model = None
        self._lock = threading.Lock()
        self._load_error: str | None = None

    @property
    def loaded(self) -> bool:
        return self._model is not None

    @property
    def error(self) -> str | None:
        return self._load_error

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self._encode(texts)

    def embed_query(self, text: str) -> list[float]:
        return self._encode([text])[0]

    def _get_model(self):
        if self._model is not None:
            return self._model
        with self._lock:
            if self._model is not None:
                return self._model
            start = time.perf_counter()
            try:
                from sentence_transformers import SentenceTransformer

                model = SentenceTransformer(
                    self.settings.embedding_model,
                    device=self.settings.embedding_device,
                    cache_folder=self.settings.embedding_cache_dir,
                    local_files_only=self.settings.embedding_local_files_only,
                )
            except Exception as exc:
                self._load_error = str(exc)[:500]
                raise EmbeddingProviderError(f"BGE embedding model load failed: {self._load_error}") from exc
            self._model = model
            self._load_error = None
            logger.info(
                "Loaded BGE embedding model model=%s device=%s duration_ms=%.3f",
                self.settings.embedding_model,
                self.settings.embedding_device,
                (time.perf_counter() - start) * 1000,
            )
            return self._model

    def _encode(self, texts: list[str]) -> list[list[float]]:
        model = self._get_model()
        vectors = model.encode(
            texts,
            batch_size=self.settings.embedding_batch_size,
            normalize_embeddings=self.settings.embedding_normalize,
        )
        result = [vector.tolist() for vector in vectors]
        self._validate_dimensions(result)
        return result

    def _validate_dimensions(self, vectors: list[list[float]]) -> None:
        if not vectors:
            return
        actual = len(vectors[0])
        if self.dimension and actual != self.dimension:
            raise EmbeddingProviderError(
                f"Embedding dimension mismatch: configured={self.dimension}, actual={actual}. Reconfigure EMBEDDING_DIMENSION and rebuild index."
            )


_bge_providers: dict[tuple, BgeEmbeddingProvider] = {}
_provider_lock = threading.Lock()


def get_embedding_provider(settings: Settings | None = None) -> EmbeddingProvider:
    settings = settings or get_settings()
    provider = settings.embedding_provider.lower().strip()
    env = settings.app_env.lower().strip()
    if env == "test" and provider in {"", "hash"}:
        provider = "fake"
    if env == "production" and provider in {"hash", "fake"}:
        raise EmbeddingProviderError("Production requires EMBEDDING_PROVIDER=bge. hash/fake are disabled.")
    if provider == "fake":
        if env == "production":
            raise EmbeddingProviderError("FakeEmbeddingProvider is disabled in production.")
        return FakeEmbeddingProvider(dimension=settings.embedding_dimension, version=settings.embedding_version)
    if provider == "hash":
        logger.warning("HashEmbedding is enabled for development only; do not use it for production retrieval quality.")
        return HashEmbedding(dimension=settings.embedding_dimension, version=settings.embedding_version)
    if provider in {"bge", "sentence_transformer", "sentence-transformer"}:
        key = (settings.embedding_model, settings.embedding_version, settings.embedding_dimension,
               settings.embedding_device, settings.embedding_cache_dir, settings.embedding_local_files_only,
               settings.embedding_normalize, settings.embedding_batch_size)
        with _provider_lock:
            if key not in _bge_providers:
                _bge_providers[key] = BgeEmbeddingProvider(settings.model_copy(deep=True))
            return _bge_providers[key]
    raise EmbeddingProviderError(f"Unsupported EMBEDDING_PROVIDER: {settings.embedding_provider}")


def embedding_status(settings: Settings | None = None) -> dict:
    settings = settings or get_settings()
    try:
        provider = get_embedding_provider(settings)
        error = getattr(provider, "error", None)
        return {
            "configured_provider": settings.embedding_provider,
            "configured_model": settings.embedding_model,
            "loaded": provider.loaded,
            "ready": provider.loaded and error is None,
            "device": settings.embedding_device,
            "dimension": provider.dimension,
            "error": error,
        }
    except Exception as exc:
        return {
            "configured_provider": settings.embedding_provider,
            "configured_model": settings.embedding_model,
            "loaded": False,
            "ready": False,
            "device": settings.embedding_device,
            "dimension": settings.embedding_dimension,
            "error": str(exc),
        }


def _normalize(vector: list[float]) -> list[float]:
    norm = math.sqrt(sum(value * value for value in vector))
    if norm == 0:
        return vector
    return [value / norm for value in vector]