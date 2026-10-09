"""Evaluation-only exhaustive reference and ANN fidelity; no production imports."""
import hashlib
import math
import statistics
import numpy as np
from app.services.evaluation.metrics import score_ranking


def vector_fingerprint(ids, vectors):
    x=np.asarray(vectors,dtype='<f4')
    if x.ndim!=2 or len(ids)!=len(x) or len(set(ids))!=len(ids) or not np.isfinite(x).all():
        raise ValueError('invalid_vector_mapping')
    digest=hashlib.sha256()
    for i in sorted(range(len(ids)),key=lambda j:ids[j]):
        digest.update(ids[i].encode());digest.update(b'\0');digest.update(x[i].tobytes())
    return digest.hexdigest()


def exact_order(ids, vectors, query, metric='dot'):
    x=np.asarray(vectors,dtype=np.float64);q=np.asarray(query,dtype=np.float64)
    if x.ndim!=2 or q.shape!=(x.shape[1],) or len(ids)!=len(x) or not np.isfinite(x).all() or not np.isfinite(q).all():
        raise ValueError('invalid_exact_input')
    scores=x@q
    if metric=='cosine':
        norms=np.linalg.norm(x,axis=1)*np.linalg.norm(q)
        if (norms==0).any():raise ValueError('zero_norm')
        scores=scores/norms
    elif metric!='dot':raise ValueError('unknown_metric')
    # Stable locator tie break. Preserve a deterministic exhaustive ranking.
    order=np.lexsort((np.asarray(ids),-scores))
    return [ids[i] for i in order]


def fidelity(ann,exact,k):
    if k<1 or len(exact)<k or len(set(ann[:k]))!=len(ann[:k]):raise ValueError('invalid_fidelity_input')
    return len(set(ann[:k])&set(exact[:k]))/k


def percentile(values,p):
    return sorted(values)[math.ceil(len(values)*p)-1]


def summarize(cases):
    if not cases:return {'n':0}
    out={'n':len(cases)}
    for k in (5,10,20,50):
        scores=[score_ranking(c['ids'],c['gold'],k) for c in cases]
        out[f'CR@{k}' if k>=20 else f'Recall@{k}']=statistics.mean(s['Recall'] for s in scores)
        if k==5:out['Hit@5']=statistics.mean(s['HitRate'] for s in scores)
        if k==10:out['MRR@10']=statistics.mean(s['MRR'] for s in scores)
    for k in (10,20,50,100):
        out[f'fidelity@{k}']=statistics.mean(fidelity(c['ids'],c['exact'],min(k,len(c['exact']))) for c in cases)
        out[f'overlap@{k}']=statistics.mean(len(set(c['ids'][:k])&set(c['exact'][:k])) for c in cases)
    samples=[ms for c in cases for ms in c['latency_ms']]
    out.update(p50=percentile(samples,.5),p95=percentile(samples,.95),timed_queries=len(samples))
    return out
