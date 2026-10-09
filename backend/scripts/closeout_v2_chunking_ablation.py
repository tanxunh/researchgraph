"""Offline C1 closeout: existing artifacts only; no retrieval or model imports."""
import csv,hashlib,io,json,sys,types
from pathlib import Path
R=Path(__file__).resolve().parents[2];O=R/'artifacts/evaluation_v2/c1';B=R/'benchmarks/real_research/v2'
sys.path.insert(0,str(R/'backend'));pkg=types.ModuleType('app.services.evaluation');pkg.__path__=[str(R/'backend/app/services/evaluation')];sys.modules['app.services.evaluation']=pkg
from app.services.evaluation.chunking_ablation import score_reranked_portable

def read(p):return json.loads(p.read_text(encoding='utf-8-sig'))
def save(p,v):p.write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
protected=dict(read(O/'protocol.json')['protected_hashes'])
for pattern in ('*_retrieval.json','*_reranked.json','*_corpus.json','*_vectors.npz'):
    for p in O.glob(pattern):protected[p.relative_to(R).as_posix()]=sha(p)
for p,h in protected.items():assert sha(R/p)==h,p
s=read(O/'summary.json')
if not (O/'summary_before_closeout.json').exists():save(O/'summary_before_closeout.json',s)
co=read(O/'B_corpus.json');chunks={c['chunk_id']:c for c in co['chunks']};anchors={a['anchor_id']:a for a in read(B/'dev_gold_portable_anchors.json')['anchors']};cases={c['query_id']:c for c in read(O/'B_retrieval.json')['cases']}
queries={q['query_id']:q for q in map(json.loads,(B/'queries_dev.jsonl').read_text(encoding='utf-8').splitlines())}
source={d['document_id']:d for d in read(R/'artifacts/evaluation_v2/c0/source_reconstruction.json')['documents']}
notes={
'V2Q049:G1':('VALID_SUPPORT_AT_RANK_2_BUT_EXTRA_FALSE_EQUIVALENT','Rank2 explicitly preserves the eavesdropping-versus-energy/time conflict and the MOP rationale. Rank21 lacks that conflict but also qualifies geometrically.'),
'V2Q050:G2':('FULL_ANCHOR_RECOVERED','Rank41 contains the complete reviewed anchor: local/OBS offloading and welfare-energy/revenue optimization.'),
'V2Q056:G2':('FULL_ANCHOR_RECOVERED','Rank23 contains the complete anchor including JTRAOP maximizing time-average utility.'),
'V2Q067:G1':('FULL_ANCHOR_RECOVERED','Rank21 contains the full anchor and adds the deterministic mixed-traffic scheduling antecedent before DDQN routing.'),
'V2Q068:G1':('CORE_USAGE_SUPPORTED_NOT_FULL_ANCHOR','Rank7 explicitly contains hybrid NOMA/OMA, statistical-delay QoS, access selection and power allocation. User-pairing details from the rest of the anchor are absent; its entire original evidence content is not recovered by that single chunk.'),
'V2Q072:G1':('JOINT_TOP50_SUPPORT_ONLY_ANY_CHUNK_RULE_FAILS','Rank16 preserves local-versus-offloaded task partition but lacks the stated weighted-energy objective, joint variables and computation-bit constraint. Rank21 preserves objective/variables/constraint and alternating solution, but lacks the explicit local-versus-offloaded partition. Together they preserve the anchor at Top50; neither alone is equivalent. Top20 counts rank16 although the complement is rank21.')}

def audit(aid):
    a=anchors[aid];q=a['query_id'];rows=[]
    for sid in co['mapping'][aid]:
        c=chunks[sid];lo=max(a['document_char_start'],c['document_char_start']);hi=min(a['document_char_end'],c['document_char_end']);n=max(0,hi-lo);length=a['document_char_end']-a['document_char_start']
        assert source[c['document_id']]['text'][c['document_char_start']:c['document_char_end']]==c['text']
        assert c['source_text_hash']==a['source_text_hash'] and c['document_version_id']==a['document_version_id']
        rank=cases[q]['hybrid'].index(sid)+1 if sid in cases[q]['hybrid'] else None
        rows.append(dict(query_id=q,gold_id=aid,anchor_length=length,chunk_id=sid,chunk_length=len(c['text']),covered_characters=n,coverage_ratio=n/length,contains_full_anchor=n==length,hybrid_rank=rank,document_id=c['document_id'],document_version_id=c['document_version_id'],page=c['page'],section=c['section'],document_char_start=c['document_char_start'],document_char_end=c['document_char_end'],anchor_overlap_start=lo-a['document_char_start'],anchor_overlap_end=hi-a['document_char_start'],raw_text=c['text']))
    return dict(gold_id=aid,query_id=q,question=queries[q]['query'],anchor_text=a['anchor_text'],matches=rows)
recovered=[]
for aid,(verdict,reason) in notes.items():
    row=audit(aid);row.update(verdict=verdict,reason=reason);recovered.append(row)
assert set(notes)==set(s['configs']['B']['miss_recovery']['50']['recovered'])
doubles=[audit(aid) for aid,ids in co['mapping'].items() if len(ids)==2];assert len(doubles)==31
assert all(not c['contains_full_anchor'] for a in doubles for c in a['matches'])
# Text-inspection findings; NOT human benchmark labels or a semantic scoring model.
findings=[dict(gold_id='V2Q072:G1',reason=notes['V2Q072:G1'][1]),dict(gold_id='V2Q034:G1',reason='Second mapped chunk (7a6b8fd0c1d416adb531cdca) contains optimization/solver/results but does not state the two queried UAV roles: computing unit and relay. Its 400/700 overlap still qualifies.'),dict(gold_id='V2Q074:G1',reason='First chunk preserves the multi-UAV architecture/3-D positioning but no objective/constraints; second preserves objective/constraints but omits the dynamic multi-UAV 3-D architecture. Neither preserves all necessary anchor facts alone.')]
decision=dict(status='STOPPED_PORTABILITY_ROBUSTNESS',portability_robustness='FAIL',reranker_metric_schema_corrected=True,selected_candidate='BASE',chunking_bottleneck='NOT SUPPORTED',ready_for_c2=False,interpretation='NOT SUPPORTED means the MATERIAL conclusion is not validated under the current portability rule; it does not establish absence of real chunking benefits. Retain BASE; B remains only the observed proxy-metric leader.')
report=dict(decision=decision,review_method='Exact raw-span arithmetic for all31 double mappings; offline assistant text inspection of six recoveries and explicit counterexamples. No external LLM, benchmark rerun, new human labels, threshold or Gold changes.',recovered_gold_audit=recovered,double_mapping_audit=doubles,double_mapping_count=31,both_partial_count=31,semantic_counterexamples=findings,scope_note='All31 were screened geometrically and full texts saved. Counterexamples suffice to fail the gate; no assertion that all remaining mapped chunks were semantically approved.')
for key,cfg in s['configs'].items():
    rr=read(O/f'{key}_reranked.json');mapping=read(O/f'{key}_corpus.json')['mapping'];rows=[score_reranked_portable(c['reranked'],c['hybrid'],mapping,c['query_id']) for c in rr['cases']]
    old=dict(cfg['reranked'])
    for k in (20,30,50):
        value=cfg['metrics']['hybrid'][f'CR@{k}'];assert abs(sum(x[f'CR@{k}'] for x in rows)/len(rows)-value)<1e-12;cfg['reranked'][f'CR@{k}']=value
    assert all(cfg['reranked'][k]==old[k] for k in ('R@10','MRR@10','Hit@5','R@5'))
    cfg['reranked_metric_provenance']={'CR@20/30/50':'metrics.hybrid (pre-rerank pool)','reranker_input_depth':20,'final_output_depth':10,'CR30/50_scope':'Upstream Hybrid pool, not actual reranker input'}
base=s['configs']['BASE'];best=s['configs']['B']
assert base['audit']['chunk_count']==3837 and best['audit']['chunk_count']==2627
assert base['cost']['index_size_bytes']==44722875 and best['cost']['index_size_bytes']==41172948
assert round(best['cost']['chunk_encode_sec'],2)==4463.59 and round(base['cost']['historical_base_encode_sec'],2)==5746.11
report['cost_review']=dict(B_chunks=2627,BASE_chunks=3837,B_index_bytes=41172948,BASE_index_bytes=44722875,B_encode_sec=best['cost']['chunk_encode_sec'],BASE_historical_encode_sec=base['cost']['historical_base_encode_sec'],conclusion='No structural cost explosion; fewer chunks and smaller index. Query timing variation, including unchanged M3 query encoding, precludes a causal algorithm-speedup claim.')
s.update(status=decision['status'],decision='RETAIN_BASE_PORTABILITY_AUDIT_FAILED',closeout=decision)
s['limitations'].append('Closeout found geometric false equivalences. Alternative portable metrics remain recorded proxy measurements, not validated semantic evidence-recall improvements.')
save(O/'summary.json',s);save(O/'closeout_robustness.json',report)
# Existing 88 historical rows are untouched semantically. C1 rows record observed metrics and failed selection gate.
p=B/'experiments.csv';prior=list(csv.DictReader(p.open(encoding='utf-8-sig',newline='')));history=[x for x in prior if x.get('phase')!='V2-C1'];rows=read(O/'ledger_rows.json')
for row in rows:
    key=row['experiment_id'].removeprefix('V2-C1-');row.update(portability_robustness='FAIL' if key=='B' else 'NOT_APPROVED_BY_THIS_CLOSEOUT',decision='RETAIN_BASE_PORTABILITY_AUDIT_FAILED',metric_basis='UNCHANGED_GEOMETRIC_PORTABILITY_PROXY',reranker_candidate_recall_source='PRE_RERANK_HYBRID')
    for k in (20,30,50):row[f'reranked_cr{k}']=s['configs'][key]['metrics']['hybrid'][f'CR@{k}']
save(O/'ledger_rows.json',rows)
fields=list(dict.fromkeys(k for row in history+rows for k in row))
with p.open('w',encoding='utf-8',newline='') as f:
    w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(history+rows)
new=list(csv.DictReader(p.open(encoding='utf-8',newline='')))
canonical=lambda rows:[{k:v for k,v in row.items() if v not in ('',None)} for row in rows]
assert canonical(new[:len(history)])==canonical(history)
md=['# C1 Portability Robustness Closeout','', 'Status: FAIL — retain BASE; do not enter C2.','',report['review_method'],'', 'The six Top50 recoveries are not all fictitious: three contain full anchors, Q049 has a complete rationale at rank2, and Q068 preserves the core access-mode use. Q072 is jointly supported at Top50 but is incorrectly credited at Top20 with only its first fragment. No revised metric is computed.','']
for row in recovered:
    md += ['## '+row['gold_id'], '',row['question'],'',row['verdict']+': '+row['reason'],'','| Chunk | Doc/version/page | Anchor chars | Chunk chars | Covered | Ratio | Full anchor | Hybrid rank |','|---|---|---:|---:|---:|---:|---|---:|']
    for c in row['matches']:md.append(f"| {c['chunk_id']} | {c['document_id']}/{c['document_version_id']}/{c['page']} | {c['anchor_length']} | {c['chunk_length']} | {c['covered_characters']} | {c['coverage_ratio']:.6f} | {c['contains_full_anchor']} | {c['hybrid_rank']} |")
    for c in row['matches']:md += ['',c['chunk_id']+f"; immutable source offsets [{c['document_char_start']}, {c['document_char_end']}); section={c['section']}",'','```text',c['raw_text'],'```']
md += ['','## All 31 double mappings','', 'Both matches partially overlap the anchor in all31 cases. This alone is not semantic failure; the documented missing-fact counterexamples establish failure. Complete raw texts follow for review, without approving the other cases.','']
for row in doubles:
    md += ['### '+row['gold_id'],'',row['question'],'','Original anchor:','```text',row['anchor_text'],'```']
    for c in row['matches']:md += ['',f"{c['chunk_id']} — doc/version/page {c['document_id']}/{c['document_version_id']}/{c['page']}; rank {c['hybrid_rank']}; coverage {c['covered_characters']}/{c['anchor_length']} ({c['coverage_ratio']:.6f}); full={c['contains_full_anchor']}",'```text',c['raw_text'],'```']
(O/'closeout_robustness.md').write_text('\n'.join(md)+'\n',encoding='utf-8')
for p,h in protected.items():assert sha(R/p)==h,p
save(O/'closeout_integrity.json',dict(protected_hashes=protected,all_unchanged=True,original_ledger_rows_preserved=len(history),retrieval_not_run=True,encoding_not_run=True,tests='PENDING'))
print('ROBUSTNESS FAIL; reranker schema corrected; raw rankings and frozen inputs unchanged')
