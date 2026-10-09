from app.services.evaluation.fusion_optimization import weighted_rrf,replacement_gate,WEIGHTS,K_VALUES
from app.services.retrieval.fusion_ranker import FusionRanker


def test_equal_weight_reproduces_production_and_stable_dense_first_ties():
    d=['d','common'];b=['b','common'];occ={'d':1,'common':2,'b':3}
    expected=FusionRanker(60).rank([(occ[x],x,0) for x in d],[(occ[x],x,0) for x in b],[],100)
    assert weighted_rrf(d,b,occ)==[x.stable_chunk_id for x in expected]==['common','d','b']


def test_weighted_missing_route_and_one_indexed_rank():
    occ={'d':1,'b':2,'z':3}
    assert weighted_rrf(['d','z'],['b'],occ,1.5,20)==['b','d','z']
    assert weighted_rrf(['d','z'],['b'],occ,.5,20)==['d','z','b']


def test_occurrence_dedup_does_not_merge_distinct_occurrences():
    occ={'x':1,'alias':1,'y':2}
    assert weighted_rrf(['x'],['alias','y'],occ)==['x','y']
    occ['alias']=3
    assert weighted_rrf(['x'],['alias','y'],occ)==['x','alias','y']


def baseline():
    return {'metrics':{'CR@20':.7,'CR@30':.8,'CR@50':.9,'R@10':.5,'MRR@10':.4},'hit_counts':{'20':35,'10':25},'cross_document':{'CR@20':.5}}


def test_two_unit_gain_rejected_if_front_ranking_pathological():
    b=baseline();c=baseline();c['metrics']['CR@20']=.75;c['hit_counts']['20']=37;c['hit_counts']['10']=23
    assert replacement_gate(c,b)['front_ranking_flag'] and not replacement_gate(c,b)['pass']


def test_one_unit_gain_requires_secondary_non_regression():
    b=baseline();c=baseline();c['metrics']['CR@20']=.73;c['hit_counts']['20']=36
    assert replacement_gate(c,b)['pass']
    c['cross_document']['CR@20']=.49
    assert not replacement_gate(c,b)['pass']


def test_grid_is_exactly_25_with_baseline():
    assert WEIGHTS==(.5,.75,1.,1.25,1.5) and K_VALUES==(20,40,60,80,120)
    assert len(WEIGHTS)*len(K_VALUES)==25
