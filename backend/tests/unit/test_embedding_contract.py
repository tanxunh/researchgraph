import sys
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import Mock
import numpy as np
import pytest

from app.core.config import Settings
from app.vectorstore import embeddings
from app.vectorstore.chroma_store import ChromaStore


def settings(**kwargs):
    return Settings(_env_file=None, EMBEDDING_PROVIDER="bge", EMBEDDING_DIMENSION=512,
                    EMBEDDING_MODEL="BAAI/bge-small-zh-v1.5", **kwargs)


def test_default_config_is_semantic_and_tests_are_explicit_fake(monkeypatch):
    monkeypatch.delenv("EMBEDDING_PROVIDER", raising=False)
    assert Settings(_env_file=None).embedding_provider == "bge"
    assert embeddings.get_embedding_provider(Settings(_env_file=None, EMBEDDING_PROVIDER="fake")).provider_name == "fake"


def test_bge_lazy_provider_and_model_reused_across_queries(monkeypatch):
    embeddings._bge_providers.clear()
    model = Mock()
    model.encode.side_effect = lambda texts, **kw: np.ones((len(texts), 512))
    constructor = Mock(return_value=model)
    monkeypatch.setitem(sys.modules, "sentence_transformers", SimpleNamespace(SentenceTransformer=constructor))
    config = settings()
    provider = embeddings.get_embedding_provider(config)
    assert not provider.loaded and not embeddings.embedding_status(config)["ready"]
    with ThreadPoolExecutor(max_workers=4) as pool:
        vectors = list(pool.map(lambda _: embeddings.get_embedding_provider(config).embed_query("query"), range(4)))
    assert constructor.call_count == 1 and all(len(vector) == 512 for vector in vectors)
    assert embeddings.get_embedding_provider(config) is provider
    assert embeddings.embedding_status(config)["ready"]
    changed = config.model_copy(update={"embedding_model": "different-model"})
    assert embeddings.get_embedding_provider(changed) is not provider
    assert embeddings.get_embedding_provider(config) is provider
    embeddings._bge_providers.clear()


def test_bge_bad_dimension_is_explicit(monkeypatch):
    model = Mock()
    model.encode.return_value = np.ones((1, 7))
    monkeypatch.setitem(sys.modules, "sentence_transformers",
                        SimpleNamespace(SentenceTransformer=Mock(return_value=model)))
    with pytest.raises(embeddings.EmbeddingProviderError, match="dimension mismatch"):
        embeddings.BgeEmbeddingProvider(settings()).embed_query("query")


def test_load_failure_has_no_fake_fallback(monkeypatch):
    monkeypatch.setitem(sys.modules, "sentence_transformers",
                        SimpleNamespace(SentenceTransformer=Mock(side_effect=OSError("offline"))))
    provider = embeddings.BgeEmbeddingProvider(settings())
    with pytest.raises(embeddings.EmbeddingProviderError, match="load failed"):
        provider.embed_query("query")
    assert not provider.loaded and provider.error


def test_collection_identity_and_metadata_guard():
    store = object.__new__(ChromaStore)
    store.embedding = embeddings.FakeEmbeddingProvider()
    first = store._collection_name(store.embedding)
    other = embeddings.FakeEmbeddingProvider(dimension=16)
    assert first != store._collection_name(other)
    other.model_name = "other-model"
    assert first != store._collection_name(other)
    metadata = dict(embedding_provider="fake", embedding_model="fake-embedding-v1",
                    embedding_dimension=8, embedding_version="test")
    assert store._validate_collection(SimpleNamespace(metadata=metadata))
    for key, value in [("embedding_provider", "bge"), ("embedding_model", "wrong"), ("embedding_dimension", 9)]:
        with pytest.raises(embeddings.EmbeddingProviderError, match="rebuild"):
            store._validate_collection(SimpleNamespace(metadata={**metadata, key: value}))
