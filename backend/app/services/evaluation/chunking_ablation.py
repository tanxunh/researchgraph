"""C1 evaluation-only chunk construction and pre-encoding portability gate."""
import hashlib
import json
import re

CONFIGS = {
    'BASE': dict(strategy='TextChunker', target=700, hard_max=700),
    'A': dict(strategy='TextChunker', target=450, hard_max=450),
    'B': dict(strategy='TextChunker', target=1000, hard_max=1000),
    'C': dict(strategy='sentence-boundary-aware character chunking', target=700, hard_max=700, preferred_min=600),
}
for config in CONFIGS.values():
    config.update(overlap=100, page_policy='page-contained', normalization_version='nfc-whitespace-v1')


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def sentence_windows(text):
    start = 0
    while start < len(text):
        end = min(start + 700, len(text))
        if end < len(text):
            boundaries = [start + m.end() for m in re.finditer(r'''[.?!]["'\u2019\u201d)\]]*(?=\s)''', text[start:end+1])
                          if 600 <= m.end() <= 700]
            if boundaries:
                end = boundaries[-1]
        raw = text[start:end]
        if raw.strip():
            offset = start + len(raw) - len(raw.lstrip())
            yield offset, raw.strip()
        if end == len(text):
            break
        start = end - 100


def score_portable(ranking, mapping, query_id):
    """Macro caller: one hit per original query-anchor, irrespective of multiplicity."""
    groups = [set(v) for a,v in mapping.items() if a.startswith(query_id + ':')]
    if not groups:
        raise ValueError('query has no portable Gold')
    ranks = [next((i+1 for i,s in enumerate(ranking) if s in g), None) for g in groups]
    result = {f'CR@{k}':sum(r is not None and r<=k for r in ranks)/len(groups) for k in (20,30,50)}
    result.update({f'R@{k}':sum(r is not None and r<=k for r in ranks)/len(groups) for k in (5,10)})
    best = min((r for r in ranks if r is not None), default=None)
    result.update({'Hit@5':int(best is not None and best<=5),'MRR@10':1/best if best is not None and best<=10 else 0})
    return result


def duplicate_equivalent(ranking, mapping, query_id, k):
    """Count distinct retrieved chunks adding no new Gold unit after an earlier match.

    A chunk matching both an old and a new anchor is not wasted. This avoids
    double-counting one retrieved chunk when several Gold anchors overlap.
    """
    seen=set();duplicates=0
    for sid in ranking[:k]:
        units={a for a,v in mapping.items() if a.startswith(query_id+':') and sid in v}
        if units and units.issubset(seen):duplicates+=1
        seen.update(units)
    return duplicates


def score_reranked_portable(reranked, hybrid, mapping, query_id):
    """Final-answer ranking metrics plus upstream pre-rerank candidate coverage.

    CR30/50 describe the Hybrid pool, not the reranker's actual Top20 input.
    """
    result = score_portable(reranked, mapping, query_id)
    candidates = score_portable(hybrid, mapping, query_id)
    for k in (20, 30, 50):
        result[f'CR@{k}'] = candidates[f'CR@{k}']
    return result
