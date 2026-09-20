"""Graph ablation attribution relative to the same Hybrid Top-K ranking."""


def graph_gain(hybrid_cases: list[dict], graph_cases: list[dict], k: int = 10) -> dict:
    baseline = {c["id"]: c for c in hybrid_cases if c["valid"]}
    rows = []
    for case in graph_cases:
        if not case["valid"] or case["id"] not in baseline:
            continue
        gold = set(case["relevant_chunk_ids"])
        returned = set(case["returned_chunk_ids"][:k])
        previous = set(baseline[case["id"]]["returned_chunk_ids"][:k])
        graph_hits = gold & returned & set(case.get("graph_returned_chunk_ids", []))
        additional = sorted((gold & returned) - previous)
        lost = sorted((gold & previous) - returned)
        rows.append({"id": case["id"], "additional_gold": additional, "lost_gold": lost,
                     "graph_expansion_hit": bool(graph_hits)})
    return {"valid_cases": len(rows), "Graph Expansion Hit@10": (
                sum(r["graph_expansion_hit"] for r in rows)/len(rows) if rows else None),
            "Graph-only Additional Gold@10": sum(len(r["additional_gold"]) for r in rows),
            "Additional Gold Cases@10": sum(bool(r["additional_gold"]) for r in rows),
            "Lost Gold@10": sum(len(r["lost_gold"]) for r in rows),
            "cases": rows}
