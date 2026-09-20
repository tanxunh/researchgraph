from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Any, Iterable


from app.core.config import get_settings
from app.vectorstore.embeddings import EmbeddingProvider, EmbeddingProviderError, get_embedding_provider
from app.vectorstore.splitter import TextChunk


@dataclass
class RetrievedChunk:
    resource_id: int = 0
    title: str = ""
    content: str = ""
    score: float = 0.0
    chunk_id: str | None = None
    chunk_index: int | None = None
    document_id: int | None = None
    document_version_id: int | None = None
    document_chunk_id: int | None = None
    page_number: int | None = None
    section_title: str | None = None
    chunk_hash: str | None = None


class ChromaStore:
    """Thin Chroma adapter for stable ResearchGraph chunk vectors."""

    def __init__(self, embedding: EmbeddingProvider | None = None, *, create_collection: bool = True) -> None:
        settings = get_settings()
        self.embedding = embedding or get_embedding_provider()
        try:
            import chromadb
        except Exception as exc:
            raise EmbeddingProviderError(f"ChromaDB is unavailable: {exc}") from exc
        if settings.chroma_host:
            self.client = chromadb.HttpClient(
                host=settings.chroma_host,
                port=settings.chroma_port,
                ssl=settings.chroma_ssl,
            )
        else:
            self.client = chromadb.PersistentClient(path=settings.chroma_persist_dir)
        self.collection_name = self._collection_name(self.embedding)
        self.collection = None
        if create_collection:
            self.collection = self._create_collection()
        else:
            from chromadb.errors import InvalidCollectionException, NotFoundError
            try:
                self.collection = self._validate_collection(self.client.get_collection(name=self.collection_name, embedding_function=None))
            except (InvalidCollectionException, NotFoundError):
                pass  # Dry-run may inspect a completely missing index without creating it.

    def _validate_collection(self, collection):
        expected = {
            "embedding_provider": self.embedding.provider_name,
            "embedding_model": self.embedding.model_name,
            "embedding_dimension": self.embedding.dimension,
            "embedding_version": self.embedding.version,
        }
        metadata = collection.metadata or {}
        if any(metadata.get(key) != value for key, value in expected.items()):
            raise EmbeddingProviderError("Incompatible embedding collection metadata; rebuild index with matching provider/model/dimension.")
        return collection

    def _create_collection(self):
        from chromadb.errors import InvalidCollectionException, NotFoundError
        try:
            # Never overwrite old metadata before checking model compatibility.
            collection = self.client.get_collection(name=self.collection_name, embedding_function=None)
        except (InvalidCollectionException, NotFoundError):
            collection = self.client.get_or_create_collection(
                name=self.collection_name, embedding_function=None,
                metadata={"project": "lifeflow_researchgraph",
                          "embedding_provider": self.embedding.provider_name,
                          "embedding_model": self.embedding.model_name,
                          "embedding_dimension": self.embedding.dimension,
                          "embedding_version": self.embedding.version})
        return self._validate_collection(collection)

    def upsert_document_chunks(self, chunks: Iterable[Any]) -> int:
        normalized = list(chunks)
        if not normalized:
            return 0
        if self.collection is None:
            self.collection = self._create_collection()
        ids = [str(chunk.stable_chunk_id) for chunk in normalized]
        documents = [str(chunk.text) for chunk in normalized]
        embeddings = self.embedding.embed_documents(documents)
        self._validate_dimensions(embeddings)
        metadatas = self.chunk_metadata(normalized)
        self.collection.upsert(ids=ids, documents=documents, embeddings=embeddings, metadatas=metadatas)
        return len(normalized)

    batch_size = 128

    def chunk_metadata(self, chunks: Iterable[Any]) -> list[dict]:
        return [
            {
                "document_id": int(chunk.document_id),
                "document_version_id": int(chunk.document_version_id),
                "document_chunk_id": int(chunk.id),
                "chunk_index": int(chunk.chunk_index),
                "page_number": int(chunk.page_number) if chunk.page_number is not None else 0,
                "section_title": chunk.section_title or "",
                "chunk_hash": chunk.chunk_hash,
                "embedding_provider": self.embedding.provider_name,
                "embedding_model": self.embedding.model_name,
                "embedding_dimension": self.embedding.dimension,
                "embedding_version": self.embedding.version,
            }
            for chunk in chunks
        ]

    def metadata_for_ids(self, ids: Iterable[str]) -> dict[str, dict]:
        if self.collection is None:
            return {}
        values = list(ids)
        found = {}
        for start in range(0, len(values), self.batch_size):
            result = self.collection.get(ids=values[start:start + self.batch_size], include=["metadatas"])
            found.update(zip(result["ids"], result["metadatas"]))
        return found

    def iter_id_batches(self, batch_size: int = 128):
        if batch_size < 1:
            raise ValueError("batch_size must be positive.")
        if self.collection is None:
            return
        offset = 0
        while True:
            ids = self.collection.get(limit=batch_size, offset=offset, include=[])["ids"]
            if not ids:
                break
            yield ids
            offset += len(ids)

    def publish_document_chunks(self, chunks: Iterable[Any], changed_ids: set[str] | None = None) -> int:
        """Retry re-embeds all; incremental publication refreshes retained metadata."""
        chunks = list(chunks)
        reembedded = 0
        for start in range(0, len(chunks), self.batch_size):
            batch = chunks[start:start + self.batch_size]
            present = self.metadata_for_ids(c.stable_chunk_id for c in batch)
            changed = [c for c in batch if changed_ids is None or c.stable_chunk_id in changed_ids
                       or c.stable_chunk_id not in present]
            retained = [c for c in batch if c not in changed]
            reembedded += self.upsert_document_chunks(changed)
            if retained:
                self.collection.update(ids=[c.stable_chunk_id for c in retained],
                                       metadatas=self.chunk_metadata(retained))
        return reembedded

    @staticmethod
    def metadata_matches(actual: dict | None, expected: dict) -> bool:
        return actual is not None and all(actual.get(key) == value for key, value in expected.items())

    def verify_document_chunks(self, chunks: Iterable[Any]) -> bool:
        chunks = list(chunks)
        for start in range(0, len(chunks), self.batch_size):
            batch = chunks[start:start + self.batch_size]
            found = self.metadata_for_ids(c.stable_chunk_id for c in batch)
            for chunk, expected in zip(batch, self.chunk_metadata(batch)):
                if not self.metadata_matches(found.get(chunk.stable_chunk_id), expected):
                    return False
        return bool(chunks)

    def delete_document_chunks(self, document_id: int) -> None:
        self.collection.delete(where={"document_id": int(document_id)})

    def delete_chunk_ids(self, stable_chunk_ids: Iterable[str]) -> None:
        if self.collection is None:
            return
        ids = [str(item) for item in stable_chunk_ids]
        for start in range(0, len(ids), self.batch_size):
            self.collection.delete(ids=ids[start:start + self.batch_size])

    def search_documents(self, query: str, top_k: int, document_ids: list[int] | None = None) -> list[RetrievedChunk]:
        return self.search(question=query, top_k=top_k, document_ids=document_ids)

    def count(self) -> int:
        return int(self.collection.count()) if self.collection is not None else 0

    def add_resource_chunks(self, resource_id: int, title: str, chunks: list[str] | list[TextChunk]) -> int:
        """Deprecated Resource compatibility API; unused by document import."""
        if not chunks:
            return 0
        normalized = [
            chunk
            if isinstance(chunk, TextChunk)
            else TextChunk(
                chunk_id=f"resource-{resource_id}-legacy-{index}",
                content=str(chunk),
                chunk_index=index,
                content_hash="legacy",
            )
            for index, chunk in enumerate(chunks)
        ]
        ids = [chunk.chunk_id for chunk in normalized]
        documents = [chunk.content for chunk in normalized]
        embeddings = self.embedding.embed_documents(documents)
        self._validate_dimensions(embeddings)
        metadatas = [
            {
                "resource_id": resource_id,
                "title": title,
                "chunk_index": chunk.chunk_index,
                "content_hash": chunk.content_hash,
                "embedding_provider": self.embedding.provider_name,
                "embedding_model": self.embedding.model_name,
                "embedding_dimension": self.embedding.dimension,
                "embedding_version": self.embedding.version,
            }
            for chunk in normalized
        ]
        self.collection.upsert(ids=ids, documents=documents, embeddings=embeddings, metadatas=metadatas)
        return len(normalized)

    def delete_resource_chunks(self, resource_id: int) -> None:
        """Deprecated Resource compatibility API; unused by document deletion."""
        self.collection.delete(where={"resource_id": int(resource_id)})

    def search(self, question: str, top_k: int, resource_ids: list[int] | None = None, *, document_ids: list[int] | None = None) -> list[RetrievedChunk]:
        if document_ids == [] or self.collection.count() == 0:
            return []
        query_embedding = self.embedding.embed_query(question)
        self._validate_dimensions([query_embedding])
        query_args: dict[str, Any] = {
            "query_embeddings": [query_embedding],
            "n_results": max(1, min(top_k, self.count())),
            "include": ["documents", "metadatas", "distances"],
        }
        where = self._resource_where(resource_ids)
        if document_ids is not None:
            scope = {"document_id": {"$in": document_ids}}
            where = {"$and": [where, scope]} if where else scope
        if where:
            query_args["where"] = where
        result = self.collection.query(**query_args)
        ids = result.get("ids", [[]])[0]
        documents = result.get("documents", [[]])[0]
        metadatas = result.get("metadatas", [[]])[0]
        distances = result.get("distances", [[]])[0]

        chunks: list[RetrievedChunk] = []
        for chunk_id, document, metadata, distance in zip(ids, documents, metadatas, distances, strict=False):
            metadata = metadata or {}
            score = max(0.0, 1.0 - float(distance))
            chunks.append(
                RetrievedChunk(
                    resource_id=_int_or_none(metadata.get("resource_id")) or _int_or_none(metadata.get("document_id")) or 0,
                    title=str(metadata.get("title", "")),
                    content=str(document),
                    score=round(score, 4),
                    chunk_id=str(chunk_id),
                    chunk_index=_int_or_none(metadata.get("chunk_index")) or 0,
                    document_id=_int_or_none(metadata.get("document_id")),
                    document_version_id=_int_or_none(metadata.get("document_version_id")),
                    document_chunk_id=_int_or_none(metadata.get("document_chunk_id")),
                    page_number=_int_or_none(metadata.get("page_number")),
                    section_title=str(metadata.get("section_title") or "") or None,
                    chunk_hash=str(metadata.get("chunk_hash") or "") or None,
                )
            )
        return chunks

    def _resource_where(self, resource_ids: list[int] | None) -> dict[str, Any] | None:
        ids = [int(item) for item in resource_ids or []]
        if not ids:
            return None
        if len(ids) == 1:
            return {"resource_id": ids[0]}
        return {"resource_id": {"$in": ids}}

    def _validate_dimensions(self, embeddings: list[list[float]]) -> None:
        if not embeddings:
            return
        actual = len(embeddings[0])
        expected = self.embedding.dimension
        if expected and actual != expected:
            raise EmbeddingProviderError(
                f"Embedding dimension mismatch for collection {self.collection_name}: expected={expected}, actual={actual}. Rebuild index with matching provider/model."
            )

    def _collection_name(self, embedding: EmbeddingProvider) -> str:
        model_hash = hashlib.sha256(embedding.model_name.encode("utf-8")).hexdigest()[:10]
        raw = f"lifeflow_rg_{embedding.provider_name}_{model_hash}_{embedding.dimension}_{embedding.version}"
        return re.sub(r"[^a-zA-Z0-9_-]", "_", raw)[:63]


def _int_or_none(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None
