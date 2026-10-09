from app.services.evaluation.chunking_ablation import sentence_windows, CONFIGS, fingerprint, score_portable, duplicate_equivalent


def test_sentence_boundary_quotes_and_last_match():
    text='x'*605+'. '+ 'y'*40+'!\") '+ 'z'*400
    chunks=list(sentence_windows(text))
    assert len(chunks[0][1])==650
    assert chunks[1][0]==550
    for offset,raw in chunks:assert text[offset:offset+len(raw)]==raw and len(raw)<=700


def test_fallback_and_short_tail():
    text='a'*1500
    assert [(s,len(t)) for s,t in sentence_windows(text)]==[(0,700),(600,700),(1200,300)]
    assert list(sentence_windows('a'*700))==[(0,'a'*700)]


def test_identity_contains_contract():
    assert len({fingerprint(c) for c in CONFIGS.values()})==4
    cfg=CONFIGS['C']; assert fingerprint(cfg)!=fingerprint(dict(cfg,page_policy='other'))


def test_portable_metrics_multiple_chunks_and_multiple_anchors():
    mapping={'q:G1':['a','b'],'q:G2':['b','c'],'other:G1':['x']}
    m=score_portable(['z','a','b','c'],mapping,'q')
    assert m['R@5']==1 and m['MRR@10']==.5 and m['CR@50']==1
    assert duplicate_equivalent(['a','b','c'],mapping,'q',20)==1
    assert duplicate_equivalent(['b','a','c'],mapping,'q',20)==2



def test_reranker_candidate_coverage_comes_from_hybrid_not_final_ten():
    from app.services.evaluation.chunking_ablation import score_reranked_portable
    mapping={'q:G1':['a'],'q:G2':['b'],'q:G3':['c']}
    hybrid=['a']+['x']*23+['b']+['x']*19+['c']
    result=score_reranked_portable(['x']*10,hybrid,mapping,'q')
    assert result['R@10']==0 and result['MRR@10']==0
    assert result['CR@20']==1/3 and result['CR@30']==2/3 and result['CR@50']==1
    changed=score_reranked_portable(['a'],hybrid,mapping,'q')
    assert changed['R@10']==1/3
    assert all(result[f'CR@{k}']==changed[f'CR@{k}'] for k in (20,30,50))
