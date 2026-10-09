"""V2-D offline weighted RRF; production retrieval remains unchanged."""
WEIGHTS=(0.50,0.75,1.00,1.25,1.50)
K_VALUES=(20,40,60,80,120)
PRIORITY=('CR@20','CR@30','CR@50','R@10','MRR@10')


def weighted_rrf(dense,bm25,occurrence,bm25_weight=1.0,rrf_k=60,top_k=100):
    """1-indexed ranks; zero missing contribution; dense-first stable ties."""
    candidates={}
    for route,weight in ((dense,1.0),(bm25,bm25_weight)):
        for rank,sid in enumerate(route,1):
            row=candidates.setdefault(occurrence[sid],{'id':sid,'score':0.0})
            row['score']+=weight/(rrf_k+rank)
    return [row['id'] for row in sorted(candidates.values(),key=lambda row:row['score'],reverse=True)[:top_k]]


def replacement_gate(candidate,baseline):
    m,b=candidate['metrics'],baseline['metrics']
    net=candidate['hit_counts']['20']-baseline['hit_counts']['20']
    safety=(m['CR@20']>b['CR@20'] and (candidate['hit_counts']['10']-baseline['hit_counts']['10']<=-2 or b['MRR@10']-m['MRR@10']>0.05))
    rule_a=net>=2
    rule_b=(net==1 and all(m[k]>=b[k] for k in ('CR@30','CR@50','R@10')) and candidate['cross_document']['CR@20']>=baseline['cross_document']['CR@20'])
    return {'net20':net,'rule_a':rule_a,'rule_b':rule_b,'front_ranking_flag':safety,'pass':m['CR@20']>b['CR@20'] and (rule_a or rule_b) and not safety}
