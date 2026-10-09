"""Experiment-only candidate construction; production routes never import this module."""
from __future__ import annotations
import statistics
import time
from app.services.evaluation.metrics import score_ranking
from app.services.evaluation.v2_benchmark import percentile
from app.services.indexing.bm25_index import BM25Index
from app.services.retrieval.active_candidates import matches_candidate, resolve_active
from app.services.retrieval.fusion_ranker import FusionRanker

DEPTHS = (20, 40, 60, 100, 200)
BUDGETS = (20, 30, 40, 50)


def validate_source_budget(policy, bm25_k, dense_k, budget):
    if (policy == "bm25" and bm25_k < budget) or (policy == "dense" and dense_k < budget):
        raise ValueError("source_depth_below_equal_budget")


def unique(rows):
    result = {}
    for row in rows:
        result.setdefault(row['chunk_id'], row)
    return list(result.values())


def rrf_order(bm25, dense):
    """Use the unchanged production RRF including its stable tie order."""
    by_id = {r['chunk_occurrence_id']: r for r in dense + bm25}
    tup = lambda rows: [(r['chunk_occurrence_id'], r['chunk_id'], 0.0) for r in rows]
    ranked = FusionRanker(60).rank(tup(dense), tup(bm25), [], len(by_id))
    return [{**by_id[r.chunk_id], 'scores': {
        **by_id[r.chunk_id]['scores'], 'fusion_score': r.fusion_score,
        'bm25_rank': r.bm25_rank, 'dense_rank': r.dense_rank,
    }} for r in ranked]


def construct_pool(bm25, dense, policy, budget):
    if budget < 1:
        raise ValueError('positive_candidate_budget_required')
    if policy == 'bm25':
        return unique(bm25)[:budget]
    if policy == 'dense':
        return unique(dense)[:budget]
    ranked = rrf_order(unique(bm25), unique(dense))
    if policy == 'rrf':
        return ranked[:budget]
    if policy != 'protected_union':
        raise ValueError('unknown_experimental_policy')
    quota = budget // 2
    protected = unique(unique(bm25)[:quota] + unique(dense)[:quota])
    chosen = {r['chunk_id'] for r in protected}
    for row in ranked:
        if len(chosen) >= budget:
            break
        chosen.add(row['chunk_id'])
    # Membership protection, not a new ranking/weight scheme.
    return [row for row in ranked if row['chunk_id'] in chosen][:budget]


def retrieve_source(service, query, source, depth, document_ids=None):
    started = time.perf_counter()
    if source == 'bm25':
        hits = BM25Index(service.db).search(query, depth, document_ids)
        active = resolve_active(service.db, [h.chunk_id for h in hits])
        tuples = [(h.chunk_id, h.stable_chunk_id, h.score) for h in hits
                  if matches_candidate(active.get(h.chunk_id), h.chunk_id, h.stable_chunk_id)]
        requested = depth
    elif source == 'dense':
        tuples = service._dense_candidates(query, depth, document_ids)
        requested = min(service.candidate_limit, max(2 * depth, service.settings.dense_top_k))
    else:
        raise ValueError('unsupported_source')
    validated_before_cap = len(tuples)
    tuples = tuples[:depth]  # explicit experimental PRE-fusion depth
    ranked = FusionRanker(60).rank(tuples if source == 'dense' else [],
                                  tuples if source == 'bm25' else [], [], depth)
    active = resolve_active(service.db, [r.chunk_id for r in ranked])
    rows = []
    for r in ranked:
        pair = active.get(r.chunk_id)
        if not matches_candidate(pair, r.chunk_id, r.stable_chunk_id):
            continue
        if document_ids is not None and pair[1].id not in document_ids:
            continue
        rows.append(service._serialize_candidate(r, *pair, []))
    return dict(rows=rows, latency_ms=(time.perf_counter()-started)*1000,
                requested_depth=requested, validated_before_cap=validated_before_cap,
                retained_depth=len(rows))


def make_case(query, bm25, dense, policy, budget):
    started = time.perf_counter()
    pool = construct_pool(bm25['rows'], dense['rows'], policy, budget)
    construction_ms = (time.perf_counter()-started)*1000
    source_ms = ((bm25['latency_ms'] if policy != 'dense' else 0)
                 + (dense['latency_ms'] if policy != 'bm25' else 0))
    gold = sorted({g['chunk_id'] for g in query['gold_evidence']})
    return dict(query_id=query['query_id'], query=query['query'], query_type=query['query_type'],
                gold=gold, pool=pool, pool_ids=[r['chunk_id'] for r in pool],
                returned_ids=[r['chunk_id'] for r in pool[:10]], actual_pool_size=len(pool),
                retrieval_ms=source_ms+construction_ms, reranker_ms=0.0,
                construction_ms=construction_ms, e2e_ms=source_ms+construction_ms,
                source_depths=dict(bm25={k:v for k,v in bm25.items() if k!='rows'},
                                   dense={k:v for k,v in dense.items() if k!='rows'}))


def summarize(cases, budget):
    result = {'n':len(cases)}
    if not cases:
        return result
    for k in (5,10):
        scores = [score_ranking(c['returned_ids'],c['gold'],k) for c in cases]
        for key in ('HitRate','Recall','MRR'):
            result[f'{key}@{k}']=round(statistics.mean(s[key] for s in scores),6)
    # A smaller pool cannot honestly report recall at a larger candidate budget.
    for k in (20,30,40,50):
        result[f'CR@{k}']=(round(statistics.mean(score_ranking(c['pool_ids'],c['gold'],k)['Recall'] for c in cases),6)
                          if k<=budget else None)
    result['candidate_recall']=round(statistics.mean(score_ranking(c['pool_ids'],c['gold'],max(1,len(c['pool_ids'])))['Recall'] for c in cases),6)
    result['pool_size']={'min':min(c['actual_pool_size'] for c in cases),'max':max(c['actual_pool_size'] for c in cases),'mean':statistics.mean(c['actual_pool_size'] for c in cases)}
    for name in ('retrieval','reranker','e2e'):
        result[name+'_p50']=percentile([c[name+'_ms'] for c in cases],.50)
        result[name+'_p95']=percentile([c[name+'_ms'] for c in cases],.95)
    return result


def metrics(cases,budget):
    return {'overall':summarize(cases,budget),
            'cross_document':summarize([c for c in cases if c['query_type']=='cross_document'],budget),
            'by_type':{t:summarize([c for c in cases if c['query_type']==t],budget) for t in sorted({c['query_type'] for c in cases})}}
