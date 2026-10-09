"""Evaluation-only instruction ablation; no production configuration changes."""
import hashlib
import json
import statistics

from app.services.evaluation.metrics import score_ranking
from app.services.evaluation.ann_exactness import percentile

MODEL = "BAAI/bge-small-zh-v1.5"
REVISION = "7999e1d3359715c523056ef9478215996d62a620"
INSTRUCTION = "为这个句子生成表示以用于检索相关文章："
STRATEGIES = ("raw", "official_instruction")
SOURCE = f"https://huggingface.co/{MODEL}/blob/{REVISION}/README.md"


def encoded_text(query, strategy):
    if strategy not in STRATEGIES:
        raise ValueError("unknown_query_strategy")
    return query if strategy == "raw" else INSTRUCTION + query


def fingerprint(config):
    return hashlib.sha256(json.dumps(config, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def summary(cases):
    result = {"n": len(cases)}
    for k in (5, 10, 20, 50):
        scores = [score_ranking(c["ids"], c["gold"], k) for c in cases]
        result[f"CR@{k}" if k >= 20 else f"Recall@{k}"] = statistics.mean(s["Recall"] for s in scores)
        if k == 5:
            result["Hit@5"] = statistics.mean(s["HitRate"] for s in scores)
        if k == 10:
            result["MRR@10"] = statistics.mean(s["MRR"] for s in scores)
    samples = [ms for c in cases for ms in c["latency_ms"]]
    result.update(p50=percentile(samples, .5), p95=percentile(samples, .95))
    return result


def paired_case(query, baseline, instruction):
    gold = [g["chunk_id"] for g in query["gold_evidence"]]
    assert len(set(gold)) == len(gold)
    ranks = lambda ids: {g: ids.index(g) + 1 if g in ids else None for g in gold}
    br, ir = ranks(baseline), ranks(instruction)
    best = lambda values: min((r for r in values if r is not None), default=None)
    row = {"query_id": query["query_id"], "query_type": query["query_type"],
           "query_text": query["query"], "baseline_gold_ranks": br, "instruction_gold_ranks": ir,
           "baseline_best_gold_rank": best(br.values()), "instruction_best_gold_rank": best(ir.values())}
    for k in (20, 50):
        b, i = set(gold) & set(baseline[:k]), set(gold) & set(instruction[:k])
        row[f"baseline_hits{k}"] = len(b)
        row[f"instruction_hits{k}"] = len(i)
        row[f"delta_hits{k}"] = len(i) - len(b)
        row[f"new_gold{k}"] = sorted(i-b)
        row[f"lost_gold{k}"] = sorted(b-i)
    # Predeclared lexicographic rule follows the task's quality priorities.
    def quality(ids):
        return tuple(score_ranking(ids, gold, k)["Recall"] for k in (50, 20, 10)) + (score_ranking(ids, gold, 10)["MRR"],)
    bq, iq = quality(baseline), quality(instruction)
    row["classification"] = "IMPROVED" if iq > bq else "REGRESSED" if iq < bq else "UNCHANGED"
    row["quality_delta"] = [i-b for b,i in zip(bq,iq)]
    return row

