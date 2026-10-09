from app.services.evaluation.ef_sweep import EFS,round_order,sweep_summary,comparisons

def test_schedule_keeps_all_efs_once_per_round():
    for i in range(5):assert sorted(round_order(i))==list(EFS)
    assert round_order(0)!=round_order(1)

def test_overlap_does_not_mean_same_order_and_all_timings_used():
    exact=[str(i) for i in range(100)];ids=exact.copy();ids[0],ids[1]=ids[1],ids[0]
    r=sweep_summary([{'ids':ids,'exact':exact,'gold':['0','not-retrieved'],'latency_ms':[1,2,3,4,10]}])
    assert r['fidelity@10']==1 and r['exact_order_equal@10']==0 and r['exact_set_equal@10']==1
    assert r['CR@20']==.5 and r['MRR@10']==.5
    assert r['mean_ms']==4 and r['p50']==3 and r['p95']==10

def test_delta_and_exact_gap_directions():
    keys=['Recall@10','MRR@10','CR@20','CR@50']
    r=comparisons(dict.fromkeys(keys,.5),dict.fromkeys(keys,.25),dict.fromkeys(keys,.75))
    assert all(v==.25 for group in r.values() for v in group.values())
