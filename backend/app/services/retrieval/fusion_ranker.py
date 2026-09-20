from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class RankedCandidate:
    chunk_id: int
    stable_chunk_id: str
    fusion_score: float
    dense_rank: int | None = None
    dense_score: float | None = None
    bm25_rank: int | None = None
    bm25_score: float | None = None
    graph_rank: int | None = None
    graph_score: float | None = None
    matched_entities: list[str] = field(default_factory=list)
    graph_paths: list[dict] = field(default_factory=list)


class FusionRanker:
    def __init__(self, rrf_k: int = 60, graph_weight: float = 0.5) -> None:
        self.rrf_k = rrf_k
        self.graph_weight = graph_weight

    def rank(
        self,
        dense: list[tuple[int, str, float]],
        bm25: list[tuple[int, str, float]],
        graph: list[tuple[int, str, float, list[str], list[dict]]],
        top_k: int,
    ) -> list[RankedCandidate]:
        candidates: dict[int, RankedCandidate] = {}
        for rank, (chunk_id, stable_id, score) in enumerate(dense, start=1):
            item = candidates.setdefault(chunk_id, RankedCandidate(chunk_id=chunk_id, stable_chunk_id=stable_id, fusion_score=0.0))
            item.dense_rank = rank
            item.dense_score = score
            item.fusion_score += 1.0 / (self.rrf_k + rank)
        for rank, (chunk_id, stable_id, score) in enumerate(bm25, start=1):
            item = candidates.setdefault(chunk_id, RankedCandidate(chunk_id=chunk_id, stable_chunk_id=stable_id, fusion_score=0.0))
            item.bm25_rank = rank
            item.bm25_score = score
            item.fusion_score += 1.0 / (self.rrf_k + rank)
        for rank, (chunk_id, stable_id, score, entities, paths) in enumerate(graph, start=1):
            item = candidates.setdefault(chunk_id, RankedCandidate(chunk_id=chunk_id, stable_chunk_id=stable_id, fusion_score=0.0))
            item.graph_rank = rank
            item.graph_score = score
            item.fusion_score += self.graph_weight / (self.rrf_k + rank)
            item.matched_entities = sorted(set(item.matched_entities + entities))
            item.graph_paths = item.graph_paths + paths
        return sorted(candidates.values(), key=lambda item: item.fusion_score, reverse=True)[:top_k]
