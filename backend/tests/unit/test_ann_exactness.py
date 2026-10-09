import numpy as np
import pytest
from app.services.evaluation.ann_exactness import exact_order,fidelity,vector_fingerprint,summarize

def test_exact_matches_known_neighbors_and_cosine():
    ids=['c','a','b'];x=np.array([[0.,1.],[1.,0.],[.6,.8]])
    assert exact_order(ids,x,[1.,0.])==['a','b','c']
    assert exact_order(ids,x,[1.,0.],'cosine')==['a','b','c']

def test_fidelity_is_not_gold_recall():
    assert fidelity(['a','z'],['a','b'],2)==.5
    with pytest.raises(ValueError):fidelity(['a','a'],['a','b'],2)

def test_vector_fingerprint_binds_locator_and_bytes_not_row_order():
    x=[[1.,0.],[0.,1.]]
    assert vector_fingerprint(['a','b'],x)==vector_fingerprint(['b','a'],x[::-1])
    assert vector_fingerprint(['a','b'],x)!=vector_fingerprint(['b','a'],x)

def test_recall_multi_gold_and_all_timing_samples():
    ids=[str(i) for i in range(100)]
    c={'ids':ids,'exact':ids,'gold':['0','200'],'latency_ms':[1.,2.,9.]}
    s=summarize([c]);assert s['CR@20']==.5 and s['fidelity@20']==1
    assert s['p50']==2 and s['p95']==9

def test_invalid_mapping_and_zero_norm_rejected():
    with pytest.raises(ValueError):vector_fingerprint(['a','a'],[[1],[2]])
    with pytest.raises(ValueError):exact_order(['a'],[[0.,0.]],[1.,0.],'cosine')
