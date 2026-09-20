from app.services.retrieval.fusion_ranker import FusionRanker


def test_rrf_fusion_combines_channels_and_preserves_scores():
    ranked = FusionRanker(rrf_k=60).rank(
        dense=[(1, "chunk-1", 0.9), (2, "chunk-2", 0.8)],
        bm25=[(2, "chunk-2", 3.0)],
        graph=[(3, "chunk-3", 0.7, ["Method: ProtoNet"], [])],
        top_k=3,
    )
    assert {item.chunk_id for item in ranked} == {1, 2, 3}
    merged = next(item for item in ranked if item.chunk_id == 2)
    assert merged.dense_rank == 2
    assert merged.bm25_rank == 1
    assert merged.fusion_score > ranked[-1].fusion_score
