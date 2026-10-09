"""Controlled reranker experiment contracts, independent of model weights."""
import importlib.util,sys
from pathlib import Path
import pytest
P=Path(__file__).resolve().parents[2]/'scripts/run_v2_reranker_optimization.py'
spec=importlib.util.spec_from_file_location('v2e_contract',P);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

def test_rank_blend_ties_preserve_fusion_identity():
    ids=[f'id{i}' for i in range(20)]
    assert m.blend(ids,[1.]*20,1.)==ids
    scores=list(range(20))
    assert m.blend(ids,scores,1.)==list(reversed(ids))
    for alpha in (1.,.75,.5):
        rr={cid:20-i for i,cid in enumerate(ids)}
        expected=sorted(ids,key=lambda cid:-(alpha/(10+rr[cid])+(1-alpha)/(11+ids.index(cid))))
        assert m.blend(ids,scores,alpha)==expected
        assert set(expected)==set(ids)

@pytest.mark.parametrize('bad',[float('nan'),float('inf')])
def test_invalid_scores_fail_closed(bad):
    with pytest.raises(AssertionError):m.blend(list(range(20)),[bad]+[0.]*19,1.)

def test_budget_and_alpha_cannot_expand():
    with pytest.raises(AssertionError):m.blend(list(range(30)),[0.]*30,1.)
    with pytest.raises(AssertionError):m.blend(list(range(20)),[0.]*20,.25)

@pytest.mark.parametrize('c,o,f,expected',[(False,False,False,'NOT_IN_TOP20'),(True,False,True,'PROMOTED_INTO_TOP10'),(True,True,True,'STAYED_IN_TOP10'),(True,True,False,'DEMOTED_OUT_OF_TOP10'),(True,False,False,'CANDIDATE_PRESENT_BUT_STILL_MISSED')])
def test_gold_categories(c,o,f,expected):assert m.classify(c,o,f)==expected

def test_paired_recall_not_rr_controls_classification():
    a={'q':{'R@10':.5,'MRR@10':1.}};b={'q':{'R@10':.5,'MRR@10':.1}}
    assert m.paired(a,b)=={'improved':0,'unchanged':1,'regressed':0}

def fixture():return {'metrics':{'R@10':.5,'MRR@10':.3,'R@5':.4},'cross':{'R@10':.4},'demotions':1,'hits5':20,'net':0}

def test_net_two_requires_macro_improvement_and_front_safety():
    b=fixture();c=fixture();c['net']=2
    assert not m.gate(c,b)['pass']
    c['metrics']['R@10']=.6;assert m.gate(c,b)['pass']
    c['metrics']['MRR@10']=.24;assert not m.gate(c,b)['pass']
    c['metrics']['MRR@10']=.3;c['hits5']=18;assert not m.gate(c,b)['pass']

def test_net_one_requires_all_secondary_guards():
    b=fixture();c=fixture();c['net']=1;c['metrics']['R@10']=.6
    assert m.gate(c,b)['gate_B']
    c['cross']['R@10']=.39;assert not m.gate(c,b)['pass']
    c['cross']['R@10']=.4;c['demotions']=2;assert not m.gate(c,b)['pass']

def test_duplicate_equivalent_gold_is_counted_once_and_no_final_cr():
    mapping={'q:G1':['a','b'],'q:G2':['c']}
    mm,per=m.metrics({'q':['a','b']},mapping,[{'query_id':'q'}])
    assert mm['R@10']==.5 and set(mm)==set(m.METRICS)
    assert m.hits({'q':['a','b']},mapping)=={'q:G1'}
