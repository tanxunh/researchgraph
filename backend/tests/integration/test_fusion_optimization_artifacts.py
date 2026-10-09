"""Offline checks of all25 saved configurations; no models or source retrieval."""
import hashlib,json,statistics
from pathlib import Path
from app.services.evaluation.fusion_optimization import replacement_gate,PRIORITY
ROOT=Path(__file__).resolve().parents[3]
read=lambda p:json.loads((ROOT/p).read_text())


def test_all25_saved_rankings_match_independent_weighted_formula_and_macro_recall():
    s=read('artifacts/evaluation_v2/d/summary.json');rankings=read('artifacts/evaluation_v2/d/fused_rankings.json');original=read('artifacts/evaluation_v2/c1/BASE_retrieval.json')['cases'];mapping=read('artifacts/evaluation_v2/c1r/mappings.json')['BASE']
    assert len(s['configs'])==len(rankings)==25
    for name,cfg in s['configs'].items():
        recalls={n:[] for n in (10,20,30,50)};counts={n:0 for n in recalls}
        for saved,source in zip(rankings[name],original):
            dr={sid:i+1 for i,sid in enumerate(source['dense'])};br={sid:i+1 for i,sid in enumerate(source['bm25'])};ids=list(dict.fromkeys(source['dense']+source['bm25']))
            k=cfg['rrf_k'];w=cfg['bm25_weight'];score=lambda sid:(1/(k+dr[sid]) if sid in dr else 0)+(w/(k+br[sid]) if sid in br else 0)
            expected=sorted(ids,key=score,reverse=True)[:100]
            assert saved['query_id']==source['query_id'] and saved['hybrid']==expected
            gs=[set(v) for a,v in mapping.items() if a.startswith(saved['query_id']+':')]
            for n in recalls:
                hits=sum(bool(set(expected[:n])&g) for g in gs);counts[n]+=hits;recalls[n].append(hits/len(gs))
        for n in recalls:
            metric=('R@' if n==10 else 'CR@')+str(n)
            assert abs(statistics.mean(recalls[n])-cfg['metrics'][metric])<1e-12
            assert counts[n]==cfg['hit_counts'][str(n)]


def test_frozen_winner_gate_and_upstream_identities():
    s=read('artifacts/evaluation_v2/d/summary.json');cfg=read('benchmarks/real_research/v2/final_fusion_config.json');b=s['configs'][s['baseline']];w=s['configs'][s['selected_candidate']]
    assert replacement_gate(w,b)['pass']
    assert (cfg['bm25_weight'],cfg['dense_weight'],cfg['rrf_k'])==(1.25,1.0,20)
    assert cfg['DEV_SELECTED'] and not cfg['TEST_VALIDATED'] and not cfg['PRODUCTION_DEFAULT']
    assert tuple(w['metrics'][x] for x in PRIORITY)==max(tuple(c['metrics'][x] for x in PRIORITY) for c in s['configs'].values())
    p=ROOT/'benchmarks/real_research/v2/final_fusion_config.json'
    assert hashlib.sha256(p.read_bytes()).hexdigest()==s['final_config_sha256']==p.with_suffix('.sha256').read_text().split()[0]
    for name,h in s['protected_hashes'].items():assert hashlib.sha256((ROOT/name).read_bytes()).hexdigest()==h
