import pytest
from app.services.evaluation.v2_candidates import construct_pool, summarize

def row(i):
    return dict(chunk_id=str(i),chunk_occurrence_id=i,scores={})

def test_protected_union_preserves_both_source_prefixes_and_fills_overlap():
    b=[row(i) for i in range(1,41)]
    d=[row(i) for i in range(6,46)]
    pool=construct_pool(b,d,'protected_union',20)
    assert len(pool)==20 and len({r['chunk_id'] for r in pool})==20
    assert {r['chunk_id'] for r in b[:10]+d[:10]} <= {r['chunk_id'] for r in pool}
    ranked=construct_pool(b,d,'rrf',80)
    assert [r['chunk_id'] for r in pool]==[r['chunk_id'] for r in ranked if r['chunk_id'] in {x['chunk_id'] for x in pool}]

def test_no_fabricated_candidates_for_small_pool():
    assert len(construct_pool([row(1)],[row(1)],'protected_union',50))==1

def test_protected_membership_can_rescue_single_source_top_candidate():
    b=[row(i) for i in range(1,101)]
    d=[row(i) for i in range(11,111)]
    assert '1' not in {r['chunk_id'] for r in construct_pool(b,d,'rrf',20)}
    assert '1' in {r['chunk_id'] for r in construct_pool(b,d,'protected_union',20)}

def test_rrf_depth_does_not_change_prefix():
    b=[row(i) for i in range(1,80)];d=[row(i) for i in range(20,100)]
    assert construct_pool(b,d,'rrf',20)[:10]==construct_pool(b,d,'rrf',50)[:10]

def test_fractional_recall_and_unavailable_larger_budget():
    case=dict(returned_ids=['1'],pool_ids=['1'],gold=['1','2'],actual_pool_size=1,retrieval_ms=1,reranker_ms=0,e2e_ms=1)
    m=summarize([case],20)
    assert m['candidate_recall']==.5 and m['CR@20']==.5 and m['CR@30'] is None

def test_deduplication_and_invalid_policy():
    assert len(construct_pool([row(1),row(1)],[],'bm25',20))==1
    with pytest.raises(ValueError):construct_pool([],[],'invalid',20)


def test_equal_budget_rejects_insufficient_single_source_depth():
    from app.services.evaluation.v2_candidates import validate_source_budget
    with pytest.raises(ValueError, match='source_depth_below_equal_budget'):
        validate_source_budget('bm25',40,100,50)
    with pytest.raises(ValueError, match='source_depth_below_equal_budget'):
        validate_source_budget('dense',100,20,30)
    validate_source_budget('protected_union',40,100,50)
    validate_source_budget('bm25',100,0,50)


def test_dense_overfetch_is_capped_before_experimental_fusion(monkeypatch):
    from types import SimpleNamespace
    from app.services.evaluation import v2_candidates as module
    active={i:(SimpleNamespace(id=i,stable_chunk_id=str(i)),SimpleNamespace(id=9)) for i in [1,2,3]}
    monkeypatch.setattr(module,'resolve_active',lambda db,ids:active)
    calls=[]
    def dense(query,depth,scope):
        calls.append((query,depth,scope))
        return [(i,str(i),1/i) for i in [1,2,3]]
    service=SimpleNamespace(db=None,candidate_limit=200,settings=SimpleNamespace(dense_top_k=8),
        _dense_candidates=dense,_serialize_candidate=lambda r,chunk,doc,names:row(r.chunk_id))
    result=module.retrieve_source(service,'question','dense',2,[9])
    assert calls==[('question',2,[9])]
    assert result['requested_depth']==8
    assert result['validated_before_cap']==3
    assert result['retained_depth']==2
    assert [r['chunk_id'] for r in result['rows']]==['1','2']
