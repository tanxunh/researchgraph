import pytest
from app.services.graph.query_analyzer import analyze_query
from app.services.graph.graph_search import linking_terms
from app.services.retrieval.fusion_ranker import FusionRanker
from app.schemas.search import SearchRequest, QARequest


@pytest.mark.parametrize("query,kind,graph", [
    ("MAPPO 的全称是什么？", "factual", False),
    ("有哪些方法可以降低边缘推理时延？", "semantic", False),
    ("MiniImageNet", "exact_term", False),
    ("哪些方法使用 MiniImageNet？", "relational", True),
    ("比较论文 A 和论文 B 使用的数据集", "cross_document", True),
    ("What is PPO?", "factual", False),
    ("Which methods are evaluated on MiniImageNet?", "relational", True),
    ("Compare paper A and paper B", "cross_document", True),
])
def test_fixed_routing_cases(query, kind, graph):
    result = analyze_query(query)
    assert (result.query_type, result.use_graph) == (kind, graph)


def test_linking_normalization_is_bounded_and_deterministic():
    assert "proximal policy optimization" in linking_terms("What uses Proximal Policy Optimization?")
    assert "ppo" in linking_terms("哪些方法使用 PPO？")
    assert "边缘推理" in linking_terms("边缘推理")
    assert linking_terms(" PPO ") == linking_terms("ppo")
    assert len(linking_terms("字" * 10000)) <= 512


def test_graph_is_a_supplementary_rrf_channel():
    ranked = FusionRanker(60, graph_weight=0.5).rank(
        [(1, "a", .9)], [(1, "a", 1)], [(2, "b", 1, [], [])], 5)
    assert ranked[0].chunk_id == 1
    assert ranked[1].fusion_score == pytest.approx(.5/61)


def test_auto_schema_additive_defaults():
    assert SearchRequest(query="PPO").mode == "auto"
    assert QARequest(question="PPO").mode == "auto"
    for mode in ("vector", "hybrid", "graph_enhanced"):
        assert SearchRequest(query="PPO", mode=mode).mode == mode


def test_ablation_gain_is_relative_to_hybrid_not_dense():
    from app.services.evaluation.graph_ablation import graph_gain
    base = [{"id": "x", "valid": True, "returned_chunk_ids": ["A"], "relevant_chunk_ids": ["A", "B"]}]
    graph = [{**base[0], "returned_chunk_ids": ["A", "B"], "graph_returned_chunk_ids": ["A", "B"]}]
    result = graph_gain(base, graph)
    assert result["Graph-only Additional Gold@10"] == 1
    assert result["cases"][0]["additional_gold"] == ["B"]
    assert result["Graph Expansion Hit@10"] == 1
    assert graph_gain(base, [])['Graph Expansion Hit@10'] is None
