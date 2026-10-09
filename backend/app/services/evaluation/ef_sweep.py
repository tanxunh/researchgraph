"""Evaluation-only same-graph EF sweep summaries; reuses frozen metric definitions."""
import statistics
from app.services.evaluation.ann_exactness import summarize

EFS=(10,20,40,80,120,200)
QUALITY=('Recall@10','MRR@10','CR@20','CR@50')


def round_order(round_number):
    offset=round_number%len(EFS)
    return EFS[offset:]+EFS[:offset]


def sweep_summary(cases):
    result=summarize(cases)
    result['mean_ms']=statistics.mean(t for c in cases for t in c['latency_ms'])
    for k in (10,20,50):
        result[f'exact_order_equal@{k}']=sum(c['ids'][:k]==c['exact'][:k] for c in cases)
        result[f'exact_set_equal@{k}']=sum(set(c['ids'][:k])==set(c['exact'][:k]) for c in cases)
    return result


def comparisons(current,baseline,exact):
    return {'delta_vs_ef10':{key:current[key]-baseline[key] for key in QUALITY},
            'gap_to_exact':{key:exact[key]-current[key] for key in QUALITY}}
