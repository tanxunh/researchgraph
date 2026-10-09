from app.services.evaluation.query_instruction import encoded_text, INSTRUCTION, fingerprint, paired_case, summary
import pytest

def test_exact_prefix_preserves_original_query():
    q = "  How does NOMA work?\n"
    assert encoded_text(q, "raw") == q
    assert encoded_text(q, "official_instruction") == INSTRUCTION + q
    assert fingerprint({"strategy": "raw"}) != fingerprint({"strategy": "official_instruction"})
    with pytest.raises(ValueError):
        encoded_text(q, "rewrite")

def test_paired_gain_loss_and_priority_over_mrr():
    q = {"query_id": "Q", "query_type": "cross_document", "query": "Compare", "gold_evidence": [{"chunk_id": g} for g in ["a","b"]]}
    base = ["a"] + [str(i) for i in range(60)]
    instr = [str(i) for i in range(25)] + ["a","b"]
    r = paired_case(q, base, instr)
    assert r["classification"] == "IMPROVED"
    assert r["lost_gold20"] == ["a"] and r["new_gold50"] == ["b"]
    assert r["baseline_best_gold_rank"] == 1 and r["instruction_best_gold_rank"] == 26
    assert paired_case(q, instr, base)["classification"] == "REGRESSED"
    assert paired_case(q, base, base)["classification"] == "UNCHANGED"

def test_macro_multi_gold_recall_and_latency():
    m = summary([{"ids":["a"],"gold":["a","b"],"latency_ms":[1,2]},
                 {"ids":["c"],"gold":["c"],"latency_ms":[3,4]}])
    assert m["CR@20"] == .75 and m["Hit@5"] == 1
    assert m["p50"] == 2 and m["p95"] == 4

