"""Optional post-fusion scoring. Scorers see text pairs, never candidate identities."""
from __future__ import annotations

import logging
import math
import threading
import time
from functools import lru_cache
from typing import Protocol

logger = logging.getLogger(__name__)


class Reranker(Protocol):
    def score(self, query: str, texts: list[str]) -> list[float]: ...


class CrossEncoderReranker:
    def __init__(self, model, revision, device, cache_dir, local_files_only):
        self.config = dict(model=model, revision=revision, device=device,
                           cache_dir=cache_dir, local_files_only=local_files_only)
        self.model = None
        self.load_error = None
        self.cold_load_ms = None
        self.lock = threading.Lock()

    def load(self):
        with self.lock:
            if self.load_error:
                raise RuntimeError(self.load_error)
            if self.model is None:
                started = time.perf_counter()
                try:
                    from sentence_transformers import CrossEncoder
                    self.model = CrossEncoder(
                        self.config['model'], revision=self.config['revision'],
                        device=self.config['device'], cache_dir=self.config['cache_dir'],
                        local_files_only=self.config['local_files_only'], max_length=512,
                        trust_remote_code=False)
                except Exception as exc:
                    self.load_error = type(exc).__name__
                    raise RuntimeError(self.load_error) from exc
                finally:
                    self.cold_load_ms = (time.perf_counter() - started) * 1000
        return self.model

    def score(self, query, texts):
        model = self.load()
        return model.predict([(query, text) for text in texts], batch_size=8,
                             show_progress_bar=False).tolist()


@lru_cache(maxsize=2)
def _cached(model, revision, device, cache_dir, local_files_only):
    return CrossEncoderReranker(model, revision, device, cache_dir, local_files_only)


def get_reranker(settings):
    return _cached(settings.reranker_model, settings.reranker_revision,
                   settings.reranker_device, settings.embedding_cache_dir,
                   settings.embedding_local_files_only)


def rerank_candidates(query: str, candidates: list[dict], scorer: Reranker):
    metadata = {'reranker_failed': False, 'failure_reason': None, 'candidate_count': len(candidates)}
    if not candidates:
        return [], metadata
    try:
        scores = [float(value) for value in scorer.score(query, [c['text'] for c in candidates])]
        if len(scores) != len(candidates) or not all(math.isfinite(s) for s in scores):
            raise ValueError('invalid_score_vector')
    except Exception as exc:
        metadata.update(reranker_failed=True, failure_reason=type(exc).__name__)
        logger.warning('reranker_failed=true reason=%s', type(exc).__name__)
        return list(candidates), metadata
    order = sorted(range(len(candidates)), key=lambda i: (-scores[i], i))
    rows = []
    for rank, index in enumerate(order, 1):
        original = candidates[index]
        rows.append({**original, 'scores': {**original['scores'],
                     'original_retrieval_rank': index + 1,
                     'original_retrieval_score': original['scores'].get('fusion_score'),
                     'reranker_score': scores[index], 'reranked_rank': rank}})
    return rows, metadata
