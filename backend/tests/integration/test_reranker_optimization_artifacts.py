"""Independent offline checks; never load TEST records or run inference."""
import hashlib,json,statistics
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3]
def read(p):return json.loads((ROOT/p).read_text(encoding='utf-8'))
B='benchmarks/real_research/v2/';E='artifacts/evaluation_v2/e/'

def test_all_seven_saved_final_rankings_and_metrics():
    s=read(E+'summary.json');r=read(E+'final_rankings.json');mp=read('artifacts/evaluation_v2/c1r/mappings.json')['BASE'];fusion=read('artifacts/evaluation_v2/d/fused_rankings.json')['bm25-1.25_k-20'];pools={x['query_id']:x['hybrid'][:20] for x in fusion}
    assert len(s['configs'])==len(r)==7
    for name,c in s['configs'].items():
        allm=[];cross=[];h10=0;h5=0
        for q,ids in r[name].items():
            assert len(ids)==len(set(ids))==10 and set(ids)<=set(pools[q])
            gs=[set(v) for g,v in mp.items() if g.startswith(q+':')]
            positions=[next((i+1 for i,cid in enumerate(ids) if cid in g),None) for g in gs]
            first=min((i for i in positions if i is not None),default=None)
            metrics={'R@10':sum(i is not None for i in positions)/len(gs),'R@5':sum(i is not None and i<=5 for i in positions)/len(gs),'Hit@5':int(first is not None and first<=5),'MRR@10':1/first if first else 0}
            allm.append(metrics);h10+=sum(i is not None for i in positions);h5+=sum(i is not None and i<=5 for i in positions)
        for k in metrics:assert abs(statistics.mean(x[k] for x in allm)-c['metrics'][k])<1e-12
        assert c['hit_count10']==h10 and c['hits5']==h5
        assert sum(c['error_counts'].values())==55 and sum(c['paired'].values())==35
        assert not any(k.startswith('CR') for k in c['metrics'])
        if name=='NO_RERANK':
            assert all(ids==pools[q][:10] for q,ids in r[name].items());continue
        cached=read(E+c['model']+'_scores.json')
        for row in cached['cases']:
            pool=row['candidate_ids'];order=sorted(range(20),key=lambda i:(-row['scores'][i],i));rank={i:p for p,i in enumerate(order,1)};alpha=c['alpha']
            expected=sorted(range(20),key=lambda i:(-(alpha/(10+rank[i])+(1-alpha)/(11+i)),i))
            assert r[name][row['query_id']]==[pool[i] for i in expected[:10]]

def test_frozen_config_and_all_input_hashes():
    s=read(E+'summary.json');cfg=read(B+'final_reranker_config.json')
    assert cfg['candidate_depth']==20 and cfg['final_top_k']==10 and cfg['rank_blend_k']==10
    assert cfg['DEV_SELECTED'] and not cfg['TEST_VALIDATED'] and not cfg['PRODUCTION_DEFAULT']
    assert not s['TEST_evaluated'] and not s['production_changed']
    raw=(ROOT/(B+'final_reranker_config.json')).read_bytes();assert hashlib.sha256(raw).hexdigest()==s['final_config_sha256']
    for name,h in {**s['protected_hashes'],**s['outputs_sha256']}.items():assert hashlib.sha256((ROOT/name).read_bytes()).hexdigest()==h,name

def test_gain_loss_and_baseline_diagnostics():
    s=read(E+'summary.json');rr=read(E+'final_rankings.json');mp=read('artifacts/evaluation_v2/c1r/mappings.json')['BASE']
    hits=lambda n:{g for g,v in mp.items() if set(v)&set(rr[n][g.split(':')[0]])}
    baseline=hits(s['current']);original=hits('NO_RERANK')
    for n,c in s['configs'].items():
        assert set(c['recovered'])==hits(n)-baseline and set(c['lost'])==baseline-hits(n)
        assert c['net']==len(c['recovered'])-len(c['lost'])
        assert set(c['demoted_ids'])==original-hits(n)
    assert abs(s['candidate_CR@20']-.7785714285714286)<1e-12

def test_audit_pair_counts_and_cross_subset():
    s=read(E+'summary.json');qs=[json.loads(x) for x in (ROOT/(B+'queries_dev.jsonl')).read_text().splitlines()];cross={q['query_id'] for q in qs if q['query_type']=='cross_document'};assert len(cross)==7
    for c in s['configs'].values():
        for metric in ('R@10','MRR@10'):assert abs(c['cross'][metric]-statistics.mean(c['per_query'][q][metric] for q in cross))<1e-12
    for key in ('base','m3'):
        data=read(E+key+'_scores.json');a=data['audit']
        assert a['status']=='PASS' and a['pairs']==700 and len(a['pairs_detail'])==700
        assert a['truncated_pairs']==sum(p['raw_token_length']>512 for p in a['pairs_detail'])
        assert len(data['cases'])==35 and all(len(c['scores'])==len(c['candidate_ids'])==20 for c in data['cases'])
        assert abs(data['latency']['mean_ms']-statistics.mean(c['latency_ms'] for c in data['cases']))<1e-9


def test_selected_configuration_obeys_gate_and_predeclared_objective():
    s=read(E+'summary.json');b=s['configs'][s['current']];eligible=[]
    for name,c in s['configs'].items():
        if name=='NO_RERANK':continue
        m=c['metrics'];bm=b['metrics']
        a=c['net']>=2 and m['R@10']>bm['R@10']
        bb=c['net']==1 and m['R@10']>bm['R@10'] and m['MRR@10']>=bm['MRR@10'] and m['R@5']>=bm['R@5'] and c['cross']['R@10']>=b['cross']['R@10'] and c['demotions']<=b['demotions']
        flag=(m['R@10']>bm['R@10'] and bm['MRR@10']-m['MRR@10']>.05) or b['hits5']-c['hits5']>=2
        assert c['gate']['pass']==((a or bb) and not flag)
        if c['gate']['pass']:eligible.append(name)
    if eligible:
        best=s['configs'][s['selected']];assert s['selected'] in eligible
        obj=lambda c:tuple(c['metrics'][k] for k in ('R@10','MRR@10','R@5','Hit@5'))
        assert obj(best)==max(obj(s['configs'][n]) for n in eligible)
    else:assert s['selected']==s['current']
    before=read(E+'current_baseline_audit.json')
    assert before['metrics']==b['metrics'] and before['counts']==b['error_counts']


def test_current_baseline_retains_b6_model_and_runtime_contract():
    old=read('artifacts/evaluation_v2/b6/protocol.json');new=read(E+'protocol.json');audit=read(E+'base_scores.json')['audit']
    assert audit['model']==old['reranker_model'] and audit['revision']==old['reranker_revision']
    assert audit['max_length']==old['rerank_max_length']==new['max_length']
    assert audit['batch_size']==old['rerank_batch']==new['batch_size']
    assert new['candidate_depth']==old['rerank_depth']==20 and new['final_top_k']==old['final_k']==10
    assert new['torch_threads']==old['torch_threads']
    path='backend/app/services/retrieval/reranker.py'
    assert hashlib.sha256((ROOT/path).read_bytes()).hexdigest()==old['protected_hashes'][path]
