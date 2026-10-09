"""Frozen B6 diagnostics. Candidate membership is separate from final ranking."""
import statistics
from app.services.evaluation.metrics import score_ranking
from app.services.retrieval.fusion_ranker import FusionRanker

BUDGETS = (20, 30, 50)

def fuse(bm25, dense, occurrence, budget=100):
    tup = lambda ids: [(occurrence[sid], sid, 0.0) for sid in ids]
    return [r.stable_chunk_id for r in FusionRanker(60).rank(tup(dense), tup(bm25), [], budget)]

def metrics(cases, path, reranked=False):
    result = {'n': len(cases)}
    for k in (5, 10):
        scores = [score_ranking(c['reranked'] if reranked else c[path], c['gold'], k) for c in cases]
        result[f'R@{k}'] = statistics.mean(s['Recall'] for s in scores)
        if k == 5: result['Hit@5'] = statistics.mean(s['HitRate'] for s in scores)
        if k == 10: result['MRR@10'] = statistics.mean(s['MRR'] for s in scores)
    for k in BUDGETS:
        result[f'CR@{k}'] = statistics.mean(score_ranking(c[path], c['gold'], k)['Recall'] for c in cases)
    return result

def complement(cases, k):
    counts = dict(bm25_only=0, dense_only=0, both=0, neither=0)
    for c in cases:
        b, d = set(c['bm25'][:k]), set(c['dense'][:k])
        for g in set(c['gold']):
            key = 'both' if g in b and g in d else 'bm25_only' if g in b else 'dense_only' if g in d else 'neither'
            counts[key] += 1
    total = sum(counts.values())
    return {'counts': counts, 'total': total, 'ratios': {k: v / total for k, v in counts.items()}}

def retention(cases, k):
    den = num = 0
    for c in cases:
        gold = set(c['dense'][:50]) & set(c['gold'])
        den += len(gold); num += len(gold & set(c['hybrid'][:k]))
    return {'retained': num, 'dense_top50_gold': den, 'ratio': num / den if den else None}

def paired(old, new):
    assert old['query_id'] == new['query_id'] and old['gold'] == new['gold']
    gold = set(old['gold']); row = {'query_id': old['query_id'], 'query_type': old['query_type']}
    for name, c in [('old', old), ('new', new)]:
        ranks = {g: c['hybrid'].index(g)+1 if g in c['hybrid'] else None for g in sorted(gold)}
        row[name+'_gold_ranks'] = ranks
        row[name+'_best_gold_rank'] = min((r for r in ranks.values() if r is not None), default=None)
        for k in BUDGETS: row[f'{name}_hits{k}'] = len(set(c['hybrid'][:k]) & gold)
    for k in BUDGETS:
        b = set(old['hybrid'][:k]) & gold; n = set(new['hybrid'][:k]) & gold
        row[f'new_gold{k}'] = sorted(n-b); row[f'lost_gold{k}'] = sorted(b-n)
    def key(c):
        return tuple(score_ranking(c['hybrid'], gold, k)['Recall'] for k in (50,30,20,10)) + (score_ranking(c['hybrid'], gold, 10)['MRR'],)
    a,b = key(old),key(new)
    row['classification'] = 'IMPROVED' if b>a else 'REGRESSED' if b<a else 'UNCHANGED'
    return row
