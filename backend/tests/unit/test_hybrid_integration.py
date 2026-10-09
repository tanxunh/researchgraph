from app.services.evaluation.hybrid_integration import complement,retention,metrics,paired,fuse

def case(**kw):
    return dict(query_id='q',query_type='cross_document',gold=['a','b','c'],bm25=['a','b'],dense=['b','c'],hybrid=['b','a','c'],reranked=['c'],**kw)

def test_complement_counts_query_gold_pairs():
    d=complement([case(),case()],20)
    assert d['counts']==dict(bm25_only=2,dense_only=2,both=2,neither=0)
    assert d['total']==6 and sum(d['ratios'].values())==1

def test_reranker_does_not_expand_candidate_recall():
    c=case();a=metrics([c],'hybrid');b=metrics([c],'hybrid',True)
    assert a['CR@20']==b['CR@20']==1
    assert b['R@10']==1/3

def test_retention_denominator_is_dense_gold_not_all_gold():
    c=case();c['hybrid']=['a','b']
    assert retention([c],20)==dict(retained=1,dense_top50_gold=2,ratio=.5)

def test_production_rrf_tie_order_and_dedup():
    assert fuse(['a','b'],['c','a'],{'a':1,'b':2,'c':3})==['a','c','b']

def test_pairwise_coverage_priority_over_top_rank():
    a=case();b=case();a['hybrid']=['a']+['x'+str(i) for i in range(49)];b['hybrid']=['x'+str(i) for i in range(48)]+['b','c']
    p=paired(a,b)
    assert p['classification']=='IMPROVED' and p['new_gold50']==['b','c'] and p['lost_gold50']==['a']
