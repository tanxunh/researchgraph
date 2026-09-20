from __future__ import annotations

import sys

from app.vectorstore.embeddings import EmbeddingProviderError, get_embedding_provider


def main() -> int:
    try:
        provider = get_embedding_provider()
        vector = provider.embed_query("Redis 是常见的缓存和消息队列组件。")
        if not vector:
            raise EmbeddingProviderError("Embedding vector is empty.")
        print(
            f"Embedding warmup succeeded: provider={provider.provider_name}, model={provider.model_name}, dimension={len(vector)}"
        )
        return 0
    except Exception as exc:
        print(f"Embedding warmup failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())