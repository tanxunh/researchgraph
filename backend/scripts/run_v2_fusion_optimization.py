"""V2-D predeclared25-point fusion sweep over immutable saved route rankings."""
import csv,hashlib,json,statistics,sys,time,types
from pathlib import Path
R=Path(__file__).resolve().parents[2];A=R/'artifacts/evaluation_v2';B=R/'benchmarks/real_research/v2';O=A/'d'
sys.path.insert(0,str(R/'backend'));pkg=types.ModuleType('app.services.evaluation');pkg.__path__=[str(R/'backend/app/services/evaluation')];sys.modules['app.services.evaluation']=pkg
from app.services.evaluation.fusion_optimization import WEIGHTS,K_VALUES,PRIORITY,weighted_rrf,replacement_gate
from app.services.evaluation.chunking_ablation import score_portable,duplicate_equivalent
from app.services.evaluation.evidence_span_repair import fully_contains

def read(p):return json.loads(p.read_text(encoding='utf-8-sig'))
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def save(p,v):p.write_text(json.dumps(v,sort_keys=True,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
def csvsave(p,rows):
    keys=list(dict.fromkeys(k for row in rows for k in row))
    with p.open('w',encoding='utf-8',newline='') as f:w=csv.DictWriter(f,fieldnames=keys);w.writeheader();w.writerows(rows)
def pct(v,p):
    a=sorted(v);x=(len(a)-1)*p/100;i=int(x);return a[i]+(a[min(i+1,len(a)-1)]-a[i])*(x-i)

def main():
    assert not (O/'summary.json').exists(),'Completed sweep must not be overwritten'
    O.mkdir(exist_ok=True)
    frozen=read(B/'final_chunking_config.json');assert sha(B/'final_chunking_config.json')=='008845cdc4c45d8921173138d8b8591fa06d85e44082a5d73627801be3887079'
    c2=read(A/'c2/freeze_validation.json');assert c2['status']=='COMPLETE'
    for p,h in c2['protected_hashes'].items():assert sha(R/p)==h,p
    protected=dict(c2['protected_hashes']);protected['benchmarks/real_research/v2/final_chunking_config.json']=sha(B/'final_chunking_config.json')
    # Predeclare all25 points and selection/gates before calculating any new fusion ranks.
    protocol=dict(phase='V2-D',weights=list(WEIGHTS),rrf_k=list(K_VALUES),dense_weight=1.0,bm25_depth=200,dense_depth=200,fused_top_k=100,priority=list(PRIORITY)+['gain_loss','cross_document','duplicate_waste','simplicity'],tie_details='Net units20/30/50, fewer losses20/30/50; cross-document CR20/30/50,R10,MRR10; fewer redundant20/50; prefer baseline, then smaller abs(weight-1),abs(k-60), then declared grid order. Measured timing is not a noisy tie-break.',replacement='Net>=2 units at20, or net=1 with macro CR30,CR50,R10 nondecreasing and crossdoc CR20 nondecreasing. Requires positive macroCR20 gain.',front_safety='Exclude CR20 gain with >=2 unit hits lost at10 or MRR drop>0.05; no exceptions in this run.',gold_equivalence='100% exact containment of human-approved C1R spans',tie_break='Stable dense-first insertion, occurrence-ID dedup, same as production',bootstrap='NOT RUN: no existing V2 bootstrap utility found; no dependency added',timing='Offline fusion arithmetic only;35-query warmup then3 rounds/config; excludes source retrieval, models and scoring.',protected_hashes=protected)
    if (O/'protocol.json').exists():assert read(O/'protocol.json')==protocol
    else:save(O/'protocol.json',protocol)
    annotation=read(B/'dev_gold_evidence_spans_v2.json');assert sha(B/'dev_gold_evidence_spans_v2.json')==frozen['reviewed_evidence_sha256']
    units=annotation['units'];assert len(units)==55 and all(u['reviewed_by_human'] and u['review_status']=='APPROVED' for u in units)
    co=read(A/'c1/BASE_corpus.json');assert sha(A/'c1/BASE_corpus.json')==frozen['base_corpus_sha256']
    mapping={u['gold_id']:[c['chunk_id'] for c in co['chunks'] if fully_contains(u,c)] for u in units}
    assert mapping==read(A/'c1r/mappings.json')['BASE']
    cases=read(A/'c1/BASE_retrieval.json')['cases'];assert len(cases)==35
    qids=[c['query_id'] for c in cases];assert qids==[json.loads(x)['query_id'] for x in (B/'queries_dev.jsonl').read_text(encoding='utf-8').splitlines() if x.strip()]
    authority=read(A/'b4/corpus.json');auth={sid:row for sid,row in zip(authority['ids'],authority['rows'])};occ={sid:row['metadata']['document_chunk_id'] for sid,row in auth.items()}
    assert len(occ)==len(set(occ.values()))==3837
    for c in co['chunks']:
        m=auth[c['chunk_id']]['metadata'];assert auth[c['chunk_id']]['document']==c['text'] and m['document_id']==c['document_id'] and m['document_version_id']==c['document_version_id'] and m['page_number']==c['page']
    for c in cases:
        for route in ('bm25','dense'):assert len(c[route])==200 and len(set(c[route]))==200 and set(c[route])<=set(occ)
    def hit(q,rank,k):return {a for a,v in mapping.items() if a.startswith(q+':') and set(v)&set(rank[:k])}
    def metrics(cs,path):
        rows=[score_portable(c[path],mapping,c['query_id']) for c in cs]
        return {key:statistics.mean(r[key] for r in rows) for key in rows[0]}
    def allhits(cs,path,k):return set().union(*(hit(c['query_id'],c[path],k) for c in cs))
    for c in cases:assert weighted_rrf(c['dense'],c['bm25'],occ)==c['hybrid'],'BASELINE_REPRODUCTION_FAIL:ranking'
    bm=metrics(cases,'hybrid');expected=read(A/'c1r/summary.json')['configs']['BASE']['metrics']['hybrid']
    if any(abs(bm[k]-expected[k])>1e-12 for k in bm):
        save(O/'baseline_reproduction.json',dict(status='BASELINE_REPRODUCTION_FAIL',observed=bm,expected=expected));raise ValueError('BASELINE_REPRODUCTION_FAIL')
    save(O/'baseline_reproduction.json',dict(status='PASS',metrics=bm,all35_rankings_identical=True))
    route_diag={p:metrics(cases,p) for p in ('bm25','dense')};complement={}
    for k in (20,30,50,200):
        bh=allhits(cases,'bm25',k);dh=allhits(cases,'dense',k)
        union_macro=statistics.mean(len(hit(c['query_id'],c['bm25'],k)|hit(c['query_id'],c['dense'],k))/sum(a.startswith(c['query_id']+':') for a in mapping) for c in cases)
        complement[str(k)]=dict(bm25_only=sorted(bh-dh),dense_only=sorted(dh-bh),both=sorted(bh&dh),neither=sorted(set(mapping)-(bh|dh)),union_units=len(bh|dh),union_unit_coverage=len(bh|dh)/55,union_macro_coverage=union_macro,max_candidate_budget=2*k)
    binput=allhits(cases,'bm25',200);dinput=allhits(cases,'dense',200);groups={'bm25_only':binput-dinput,'dense_only':dinput-binput,'both':binput&dinput}
    outputs={};retentions={};gainrows=[];pairrows=[];gridrows=[];crossrows=[];rankings={}
    for weight in WEIGHTS:
        for k in K_VALUES:
            name=f'bm25-{weight:.2f}_k-{k}';cs=[dict(c,hybrid=weighted_rrf(c['dense'],c['bm25'],occ,weight,k)) for c in cases];rankings[name]=[dict(query_id=c['query_id'],hybrid=c['hybrid']) for c in cs]
            met=metrics(cs,'hybrid');cross=metrics([c for c in cs if c['query_type']=='cross_document'],'hybrid')
            out=dict(bm25_weight=weight,dense_weight=1.0,rrf_k=k,metrics=met,cross_document=dict(n=7,**cross),hit_counts={str(n):len(allhits(cs,'hybrid',n)) for n in (5,10,20,30,50,100)},gain_loss={},duplicates={})
            retentions[name]={}
            for n in (20,30,50):
                nh=allhits(cs,'hybrid',n);bh=allhits(cases,'hybrid',n);recovered=nh-bh;lost=bh-nh
                out['gain_loss'][str(n)]=dict(recovered=sorted(recovered),lost=sorted(lost),net=len(recovered)-len(lost))
                for status,ids in [('RECOVERED',recovered),('LOST',lost)]:
                    for aid in sorted(ids):gainrows.append(dict(config=name,depth=n,change=status,query_id=aid.split(':')[0],gold_id=aid))
                retentions[name][str(n)]=dict(bm25_input_gold=len(binput),dense_input_gold=len(dinput),union_input_gold=len(binput|dinput),fused_gold=len(nh),bm25_gold_retained=len(nh&binput),dense_gold_retained=len(nh&dinput),union_gold_retained=len(nh&(binput|dinput)),route_specific={g:dict(available=len(ids),retained=len(ids&nh),retained_ids=sorted(ids&nh)) for g,ids in groups.items()})
            for n in (20,50):
                redundant=sum(duplicate_equivalent(c['hybrid'],mapping,c['query_id'],n) for c in cs)
                nq=sum(any(len(set(c['hybrid'][:n])&set(v))>1 for a,v in mapping.items() if a.startswith(c['query_id']+':')) for c in cs)
                out['duplicates'][str(n)]=dict(queries=nq,redundant_chunks=redundant,wasted_slots=redundant,candidate_slots=35*n,waste_pct=100*redundant/(35*n))
            paired={'IMPROVED':0,'UNCHANGED':0,'REGRESSED':0}
            for c,b in zip(cs,cases):
                sm=score_portable(c['hybrid'],mapping,c['query_id']);old=score_portable(b['hybrid'],mapping,b['query_id']);nk=tuple(sm[x] for x in PRIORITY);ok=tuple(old[x] for x in PRIORITY);label='IMPROVED' if nk>ok else 'REGRESSED' if nk<ok else 'UNCHANGED';paired[label]+=1
                row=dict(config=name,query_id=c['query_id'],classification=label)
                for n in (20,30,50):row[f'baseline_hits{n}']=len(hit(c['query_id'],b['hybrid'],n));row[f'new_hits{n}']=len(hit(c['query_id'],c['hybrid'],n))
                pairrows.append(row)
            out['paired_queries']=paired
            out['CR@100_diagnostic']=statistics.mean(len(hit(c['query_id'],c['hybrid'],100))/sum(a.startswith(c['query_id']+':') for a in mapping) for c in cs)
            # Arithmetic warmup and timings only; no retrieval or model inference.
            for c in cases:weighted_rrf(c['dense'],c['bm25'],occ,weight,k)
            samples=[]
            for repeat in range(3):
                for c,want in zip(cases,cs):
                    t=time.perf_counter_ns();got=weighted_rrf(c['dense'],c['bm25'],occ,weight,k);samples.append((time.perf_counter_ns()-t)/1e6);assert got==want['hybrid']
            out['fusion_ms']=dict(mean=statistics.mean(samples),p50=pct(samples,50),p95=pct(samples,95),samples=len(samples))
            outputs[name]=out
    base_name='bm25-1.00_k-60';base=outputs[base_name]
    for name,out in outputs.items():
        out['replacement_gate']=replacement_gate(out,base)
        gridrows.append(dict(config=name,bm25_weight=out['bm25_weight'],dense_weight=1.0,rrf_k=out['rrf_k'],**out['metrics'],**{f'hits@{n}':v for n,v in out['hit_counts'].items()},**{f'net@{n}':out['gain_loss'][str(n)]['net'] for n in (20,30,50)},front_ranking_flag=out['replacement_gate']['front_ranking_flag'],replacement_gate=out['replacement_gate']['pass'],**{f'fusion_{k}_ms':out['fusion_ms'][k] for k in ('mean','p50','p95')},**{f'duplicate{n}_{k}':out['duplicates'][str(n)][k] for n in (20,50) for k in ('queries','redundant_chunks','waste_pct')}))
        crossrows.append(dict(config=name,**out['cross_document']))
    def selection_key(name):
        x=outputs[name]
        return tuple(x['metrics'][m] for m in PRIORITY)+tuple(x['gain_loss'][str(n)]['net'] for n in (20,30,50))+tuple(-len(x['gain_loss'][str(n)]['lost']) for n in (20,30,50))+tuple(x['cross_document'][m] for m in PRIORITY)+tuple(-x['duplicates'][str(n)]['redundant_chunks'] for n in (20,50))+(name==base_name,-abs(x['bm25_weight']-1),-abs(x['rrf_k']-60))
    leader=max(outputs,key=selection_key);selected=leader if outputs[leader]['replacement_gate']['pass'] else base_name
    conclusion='MATERIAL' if selected!=base_name else 'MINOR' if outputs[leader]['metrics']['CR@20']>base['metrics']['CR@20'] else 'NOT SUPPORTED'
    summary=dict(status='SWEEP_COMPLETE_PENDING_VALIDATION',protocol_sha256=sha(O/'protocol.json'),baseline=base_name,route_metrics=route_diag,route_complementarity=complement,configs=outputs,lexicographic_leader=leader,selected_candidate=selected,fusion_bottleneck=conclusion,retention_input_budget=200,original_gold_units=55,DEV_queries=35,metric_definition='Recall is35-query macro average; hit_counts are integer Query-Gold units; one unit is1/55=1.818pp only in micro coverage, not necessarily macro Recall. Replacement and front safety unit tests use integer counts.',bootstrap=protocol['bootstrap'],protected_hashes=protected,retrieval_run=False,model_inference=False,TEST_evaluated=False)
    for p,h in protected.items():assert sha(R/p)==h,p
    save(O/'summary.json',summary);save(O/'fusion_retention.json',retentions);save(O/'fused_rankings.json',rankings)
    csvsave(B/'v2_d_fusion_grid.csv',gridrows);csvsave(B/'v2_d_gain_loss.csv',gainrows);csvsave(B/'v2_d_cross_document.csv',crossrows);csvsave(B/'v2_d_paired_queries.csv',pairrows)
    print(json.dumps({'baseline':base,'leader_name':leader,'leader':outputs[leader],'selected':selected,'conclusion':conclusion,'route_metrics':route_diag,'retention':retentions[leader]},indent=2))
if __name__=='__main__':main()
