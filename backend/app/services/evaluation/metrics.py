"""Deterministic macro-averaged retrieval metrics; empty gold is unscored."""
from __future__ import annotations

import math
import statistics


def score_ranking(returned: list[str], gold: list[str], k: int) -> dict:
    if k < 1:
        raise ValueError("k must be positive")
    relevant = set(gold)
    if not relevant:
        return {"valid": False, "reason": "empty_gold", "HitRate": None, "Recall": None, "MRR": None}
    hits = relevant.intersection(returned[:k])
    first = next((rank for rank, key in enumerate(returned[:k], 1) if key in relevant), None)
    return {"valid": True, "reason": None, "HitRate": float(bool(hits)),
            "Recall": len(hits) / len(relevant), "MRR": 1 / first if first else 0.0}


def summarize(cases: list[dict]) -> dict:
    valid = [case for case in cases if case["valid"]]
    result = {"count": len(cases), "total_cases": len(cases),
              "valid_scored_cases": len(valid), "invalid_cases": len(cases) - len(valid)}
    for k in (5, 10):
        scores = [score_ranking(c["returned_chunk_ids"], c["relevant_chunk_ids"], k) for c in valid]
        for metric in ("HitRate", "Recall", "MRR"):
            result[f"{metric}@{k}"] = round(statistics.mean(s[metric] for s in scores), 4) if scores else None
    latencies = sorted(c["latency_ms"] for c in valid if c.get("latency_ms") is not None)
    result["Average Latency"] = round(statistics.mean(latencies), 3) if latencies else None
    # Nearest-rank percentiles; every timed query is used, without best-run selection.
    for name, p in (("P50 Latency", 0.5), ("P95 Latency", 0.95)):
        result[name] = round(latencies[math.ceil(len(latencies) * p) - 1], 3) if latencies else None
    result["Source Hit Rate"] = (round(statistics.mean(bool(set(c["returned_chunk_ids"]) &
                                                           set(c["relevant_chunk_ids"])) for c in valid), 4)
                                 if valid else None)
    cross = [c for c in valid if c.get("cross_document")]
    result["Cross-document Recall@5"] = (round(statistics.mean(
        score_ranking(c["returned_chunk_ids"], c["relevant_chunk_ids"], 5)["Recall"] for c in cross), 4)
        if cross else None)
    result["Complete Evidence Recall"] = (round(statistics.mean(
        set(c["relevant_chunk_ids"]).issubset(c["returned_chunk_ids"]) for c in cross), 4) if cross else None)
    return result


def category_metrics(cases: list[dict]) -> dict:
    return {category: summarize([c for c in cases if c["query_type"] == category])
            for category in sorted({c["query_type"] for c in cases})}
