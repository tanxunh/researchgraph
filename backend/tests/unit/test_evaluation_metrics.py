from app.services.evaluation.metrics import category_metrics, score_ranking, summarize


def row(kind="a", latency=10, returned=None, gold=None):
    return {"query_type": kind, "valid": True, "latency_ms": latency,
            "returned_chunk_ids": returned or ["X", "A", "Y", "B", "Z"],
            "relevant_chunk_ids": gold or ["A", "B"]}


def test_multi_gold_recall_and_hit_rate_are_distinct():
    result = score_ranking(["X", "A", "Y", "B", "Z"], ["A", "B"], 5)
    assert (result["HitRate"], result["Recall"], result["MRR"]) == (1, 1, 0.5)
    partial = score_ranking(["A", "X"], ["A", "B"], 5)
    assert partial["HitRate"] == 1 and partial["Recall"] == 0.5


def test_mrr_cutoff_at_rank_eleven():
    ranking = [str(i) for i in range(10)] + ["A"]
    assert score_ranking(ranking, ["A"], 10)["MRR"] == 0


def test_empty_gold_unscored_not_zero_or_one():
    result = score_ranking(["A"], [], 5)
    assert not result["valid"] and result["Recall"] is None
    invalid = {**row(), "valid": False, "relevant_chunk_ids": [], "latency_ms": None}
    report = summarize([row(), invalid])
    assert report["total_cases"] == 2 and report["valid_scored_cases"] == 1 and report["invalid_cases"] == 1
    assert report["Recall@5"] == 1
    assert summarize([invalid])["Recall@5"] is None


def test_categories_keep_their_own_metrics_and_latency():
    data = [row("a", 10), row("b", 200, ["X"]), row("a", 30)]
    metrics = category_metrics(data)
    assert metrics["a"]["count"] == 2 and metrics["a"]["Average Latency"] == 20
    assert metrics["b"]["Average Latency"] == 200 and metrics["b"]["MRR@10"] == 0
    assert metrics["a"]["Recall@5"] == 1


def test_duplicate_ranked_gold_does_not_inflate_recall():
    result = score_ranking(["A", "A", "A"], ["A", "A", "B"], 5)
    assert result["Recall"] == 0.5
