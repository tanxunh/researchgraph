"""G4: standard-library-only frozen review aggregation. No model or retriever imports."""
import collections,csv,hashlib,json,math,re,statistics
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];G=ROOT/'artifacts/evaluation_v2/g';B=ROOT/'benchmarks/real_research/v2'
LABELS=['COMPLETE','PARTIAL','INCORRECT'];TYPES=['factual','exact_term','semantic','relational','cross_document','multi_hop']
CAUSES=['WORKFLOW_TECHNICAL_FAILURE','RETRIEVAL_MISS','RERANKER_MISS','EVIDENCE_SELECTION_MISS','SYNTHESIS_ERROR','CITATION_ERROR','UNSUPPORTED_INFERENCE','OTHER']
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def read(p):return json.loads(p.read_text(encoding='utf-8'))
def lines(p):return [json.loads(x) for x in p.read_text(encoding='utf-8').splitlines() if x]
def write(p,d):p.write_text(json.dumps(d,ensure_ascii=False,sort_keys=True,indent=2)+'\n',encoding='utf-8')
def csvout(name,rows):
 with (B/name).open('w',encoding='utf-8',newline='') as f:
  w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader()
  for row in rows:w.writerow({k:json.dumps(v,ensure_ascii=False) if isinstance(v,(list,dict)) else v for k,v in row.items()})
def blocks(path):
 s=re.split(r'^## (R\d{3})\s*$',path.read_text(encoding='utf-8'),flags=re.M);return dict(zip(s[1::2],s[2::2]))
def pct(n,d):return n/d if d else None
def stats(values):
 x=sorted(values);position=(len(x)-1)*.95;lo=math.floor(position);hi=math.ceil(position)
 return dict(n=len(x),mean=statistics.mean(x),median=statistics.median(x),p95=x[lo]+(x[hi]-x[lo])*(position-lo),max=max(x))
def counts(rows,key,labels):return {v:sum(r[key]==v for r in rows) for v in labels}
def metrics(rows):
 n=len(rows);d=dict(n=n,**counts(rows,'answer_correctness',LABELS))
 d.update({k.lower()+'_rate':pct(d[k],n) for k in LABELS})
 d.update({'evidence_'+k:v for k,v in counts(rows,'evidence_sufficiency',['SUFFICIENT','PARTIAL','INSUFFICIENT']).items()})
 d.update({'citation_'+k:v for k,v in counts(rows,'citation_correctness',['ALL','PARTIAL','NONE']).items()})
 d.update(unsupported_claims=sum(x['unsupported_claims'] for x in rows),answers_with_unsupported_claims=sum(x['unsupported_claims']>0 for x in rows),correctly_cited_complete=sum(x['answer_correctness']=='COMPLETE' and x['citation_correctness']=='ALL' for x in rows))
 d['correctly_cited_complete_rate']=pct(d['correctly_cited_complete'],n)
 return d

def main():
 expected_hashes={'HUMAN_WORKFLOW_REVIEW_COMPLETED.md':'0d7e07c0e65301d8e3abf90737c8189800f8b522f43de1f629136cf219acef77','V2_G3_REVIEW_SUMMARY.json':'4959228e3c3f541492aa7382d98f87e4a965f1cb6fffed04c94d492bc34fc2fb'}
 for name,h in expected_hashes.items():assert sha(G/name)==h,'G3_REVIEW_CHECKSUM_FAIL: '+name
 review=read(G/'V2_G3_REVIEW_SUMMARY.json');judgments=review['judgments'];completed=blocks(G/'HUMAN_WORKFLOW_REVIEW_COMPLETED.md');template=blocks(G/'HUMAN_WORKFLOW_REVIEW.md')
 expected={'answer_correctness':{'COMPLETE':51,'PARTIAL':18,'INCORRECT':11},'evidence_sufficiency':{'SUFFICIENT':69,'PARTIAL':9,'INSUFFICIENT':2},'citation_correctness':{'ALL':58,'PARTIAL':4,'NONE':18}}
 assert len(judgments)==len(completed)==80,'G3_REVIEW_CHECKSUM_FAIL'
 for key,totals in expected.items():assert dict(collections.Counter(j[key] for j in judgments.values()))==totals,'G3_REVIEW_CHECKSUM_FAIL'
 assert sum(j['unsupported_claims'] for j in judgments.values())==7 and sum(j['unsupported_claims']>0 for j in judgments.values())==4
 for rid,j in judgments.items():
  for k in [*expected,'unsupported_claims']:
   val=re.search(r'^'+k+r':\s*(\w+)',completed[rid],re.M).group(1)
   assert val==str(j[k]),'G3_REVIEW_CHECKSUM_FAIL markdown/json '+rid
 tasks={t['query_id']:t for t in read(B/'v2_g_workflow_benchmark.json')['tasks']}
 outputs={'A':{r['query_id']:r for r in lines(G/'track_a_answers.jsonl')},'B-R':{r['query_id']:r for r in lines(G/'track_b_answers.jsonl')}}
 mapping=read(G/'review_item_mapping_private.json')['items'];reviews={};proof=[]
 for m in mapping:
  rid=m['review_item_id'];qid=m['query_id'];track='A' if m['track']=='A' else 'B-R';r=outputs[track][qid]
  payload=completed[rid].split('answer_correctness:')[0].strip()
  assert payload==template[rid].split('answer_correctness:')[0].strip(),'BLIND_TRACK_MAPPING_FAIL payload'
  assert re.search(r'^Query ID: (\S+)',payload,re.M).group(1)==qid
  assert ('Question: '+r['question']) in payload
  citations=json.loads(payload.split('### Citations')[1].split('```json\n')[1].split('```')[0]);assert citations==r['citations'],'BLIND_TRACK_MAPPING_FAIL citations'
  answer=payload.split('### Generated answer\n')[1].split('### Citations')[0].strip()
  if isinstance(r['answer'],str):assert answer==r['answer'],'BLIND_TRACK_MAPPING_FAIL answer'
  elif r['answer'] is None:assert answer=='No validated answer was returned.'
  else:
   a=r['answer'];parts=[a['summary'],'']+[f"- Document {c['document_id']} / {c['field']}: {c['value']}" for c in a['comparison']]+['','Limitations:']+['- '+v for v in a['limitations']]
   assert answer=='\n'.join(parts).strip(),'BLIND_TRACK_MAPPING_FAIL report'
  for e in r['provided_evidence']:assert e['content'] in payload,'BLIND_TRACK_MAPPING_FAIL evidence'
  assert (track,qid) not in reviews
  reviews[track,qid]={**judgments[rid],'review_item_id':rid,'query_id':qid,'track':track,'query_type':tasks[qid]['query_type']}
  proof.append(dict(review_item_id=rid,query_id=qid,track=track,review_payload_sha256=hashlib.sha256(payload.encode()).hexdigest(),answer_sha256=hashlib.sha256(answer.encode()).hexdigest(),citation_payload_sha256=hashlib.sha256(json.dumps(citations,sort_keys=True).encode()).hexdigest(),provided_evidence_section_sha256=hashlib.sha256(payload.split('### Provided evidence')[1].encode()).hexdigest()))
 assert set(reviews)=={(t,q) for t in outputs for q in tasks},'BLIND_TRACK_MAPPING_FAIL'
 assert all(len(lines(G/n))==40 for n in ['track_a_answers.jsonl','track_b_answers.jsonl','track_b_retrieval_trace.jsonl'])
 assert {q for q,r in outputs['B-R'].items() if r['status']=='failed'}=={'V2Q048','V2Q075'}
 protocol=read(G/'g2/protocol.json');protected={p.replace('\\','/'):h for p,h in protocol['hashes'].items()}
 protected.update({str((G/n).relative_to(ROOT)).replace('\\','/'):sha(G/n) for n in ['HUMAN_WORKFLOW_REVIEW_COMPLETED.md','V2_G3_REVIEW_SUMMARY.json','track_a_answers.jsonl','track_b_answers.jsonl','track_b_retrieval_trace.jsonl','generation_run_summary.json','HUMAN_WORKFLOW_REVIEW.md']})
 generation=read(G/'generation_run_summary.json')
 for n,h in generation['artifact_hashes'].items():assert sha(G/n)==h,n
 for p,h in protected.items():assert sha(ROOT/p)==h,p
 frozen=read(B/'final_retrieval_manifest.json');assert sha(ROOT/'artifacts/evaluation_v2/f/test_run.json')==frozen['test_run_sha256']
 f={r['query_id']:r for r in read(ROOT/'artifacts/evaluation_v2/f/test_run.json')['cases']};trace={r['query_id']:r for r in lines(G/'track_b_retrieval_trace.jsonl')}
 per=[];recovery=[];pairs=[];ceilings={};goldsets={};available={};globalavailable={};missingbefore={}
 for q,t in tasks.items():
  gold={(x['document_id'],x['document_version_id'],x['chunk_id']) for x in t['gold_evidence']};goldsets[q]=gold
  def ids_to_gold(ids):return {x for x in gold if x[2] in ids}
  top10=ids_to_gold(f[q]['reranked']);top20=ids_to_gold(f[q]['hybrid'][:20]);assert top10<=top20
  missing=gold-top10;missingbefore[q]=missing
  ceiling='ANSWERABLE_FROM_TOP10' if top10==gold else 'ANSWERABLE_FROM_TOP20' if top20==gold else 'NOT_ANSWERABLE_FROM_TOP20';ceilings[q]=ceiling
  calls=trace[q]['retrieval_calls'];admitted=set();glob=set();first={};returnedfirst={}
  for call in calls:
   phase=call.get('phase','unknown')
   for row in call['returned_results']:
    key=(row['document']['id'],row['document_version_id'],row['chunk_id']);glob.add(key);returnedfirst.setdefault(key,phase)
   for e in (call.get('admission') or {}).get('admitted',[]):
    key=(e['document_id'],e['document_version_id'],e['chunk_id']);admitted.add(key);first.setdefault(key,phase)
  available['A',q]=top10;available['B-R',q]=gold&admitted;globalavailable[q]=gold&glob
  recovered=missing&admitted
  row=dict(query_id=q,query_type=t['query_type'],required_gold=len(gold),ceiling=ceiling,all_gold_top10=top10==gold,all_gold_top20=top20==gold,
   missing_before=len(missing),missing_before_locators=sorted(missing),recovered_admitted=len(recovered),recovered_locators=sorted(recovered),
   recovered_initial=sum(first[x]=='initial' for x in recovered),recovered_supplemental=sum(first[x]=='supplemental' for x in recovered),
   recovered_global_returned=len(missing&glob),all_missing_recovered=bool(missing) and missing<=admitted,
   previously_missing_still_absent=len(missing-admitted),all_required_still_missing=len(gold-admitted),
   lost_initial_gold=sorted(top10-admitted),all_required_admitted=gold<=admitted,
   total_calls=len(calls),supplemental_calls=sum(c.get('phase')=='supplemental' for c in calls),
   unique_subqueries=len({c['actual_query'] for c in calls}),unique_returned_chunks=len(glob),unique_admitted_chunks=len(admitted),
   unique_returned_documents=len({x[0] for x in glob}),unique_admitted_documents=len({x[0] for x in admitted}))
  recovery.append(row)
  ra=reviews['A',q]['answer_correctness'];rb=reviews['B-R',q]['answer_correctness'];score={'COMPLETE':2,'PARTIAL':1,'INCORRECT':0}
  change='B_R_IMPROVED' if score[rb]>score[ra] else 'B_R_REGRESSED' if score[rb]<score[ra] else 'UNCHANGED'
  pairs.append(dict(query_id=q,query_type=t['query_type'],A=ra,B_R=rb,change=change,A_incomplete_B_complete=ra!='COMPLETE' and rb=='COMPLETE',A_complete_B_incomplete=ra=='COMPLETE' and rb!='COMPLETE',ORCHESTRATION_RECOVERY_SUCCESS=ra!='COMPLETE' and rb=='COMPLETE' and bool(recovered)))
 for track in outputs:
  per.append(dict(track=track,**metrics([reviews[track,q] for q in tasks])))
 categories=[]
 for track in outputs:
  for typ in TYPES:
   rows=[reviews[track,q] for q in tasks if tasks[q]['query_type']==typ];m=metrics(rows)
   categories.append(dict(track=track,query_type=typ,interpretation='LOW_SAMPLE_DESCRIPTIVE',**m,citation_ALL_rate=m['citation_ALL']/m['n']))
 # Attribution uses requested priority; retained notes support downstream subcategories, never new semantic labels.
 failures=[]
 for (track,q),j in reviews.items():
  if j['answer_correctness']=='COMPLETE':continue
  r=outputs[track][q];g=goldsets[q];used={(c['document_id'],c['document_version_id'],c['chunk_id']) for c in r['citations']};note=j['reviewer_notes']
  if track=='B-R' and r['status']=='failed':cause='WORKFLOW_TECHNICAL_FAILURE';reason='Preserved runtime failure: '+','.join(r['errors'])
  elif (track=='A' and ceilings[q]=='NOT_ANSWERABLE_FROM_TOP20') or (track=='B-R' and not g<=available[track,q]):cause='RETRIEVAL_MISS';reason='Frozen exact Gold unavailable at defined retrieval/admission boundary; proxy attribution, not proof that equivalent support is absent'
  elif track=='A' and ceilings[q]=='ANSWERABLE_FROM_TOP20':cause='RERANKER_MISS';reason='All exact Gold in Hybrid20 but not Final10'
  elif re.search(r'omit|misses|abstain|not enough|not explicit|absent|not sufficiently|not described',note,re.I) or (g-used):cause='EVIDENCE_SELECTION_MISS';reason='Available exact Gold not cited/used completely or frozen review explicitly reports omission: '+note
  elif j['unsupported_claims'] and re.search(r'reversed|mischaracter|incorrect|contradict',note,re.I):cause='SYNTHESIS_ERROR';reason='Frozen review reports reasoning/mischaracterization: '+note
  elif j['citation_correctness']!='ALL':cause='CITATION_ERROR';reason='Citation inadequacy recorded in frozen review: '+note
  elif j['unsupported_claims']:cause='UNSUPPORTED_INFERENCE';reason=note
  else:cause='OTHER';reason='Insufficient frozen diagnostic basis for a more specific attribution: '+note
  failures.append(dict(track=track,query_id=q,review_item_id=j['review_item_id'],semantic_status=j['answer_correctness'],primary_cause=cause,reason=reason,review_notes=note,unsupported_claims=j['unsupported_claims'],exact_gold_available=len(available[track,q]),required_gold=len(g),secondary_flags=['GOLD_ABSENCE_WITH_REVIEW_SUFFICIENT'] if j['evidence_sufficiency']=='SUFFICIENT' and not g<=available[track,q] else []))
 cross=[];multi=[]
 for typ,dest in [('cross_document',cross),('multi_hop',multi)]:
  for track in outputs:
   for q,t in tasks.items():
    if t['query_type']!=typ:continue
    j=reviews[track,q];r=outputs[track][q];docs={c['document_id'] for c in r['citations']};scope=set(t['document_scope'])
    full=j['answer_correctness']=='COMPLETE' and j['citation_correctness']=='ALL' and (scope<=docs if typ=='cross_document' else goldsets[q]<=available[track,q])
    outcome='FAIL' if j['answer_correctness']=='INCORRECT' or r['status']=='failed' else 'FULL' if full else 'PARTIAL'
    dest.append(dict(track=track,query_id=q,answer_correctness=j['answer_correctness'],citation_correctness=j['citation_correctness'],unsupported_claims=j['unsupported_claims'],required_documents=sorted(scope),cited_documents=sorted(docs),all_documents_used=scope<=docs,all_required_gold_available=goldsets[q]<=available[track,q],poc_result=outcome,low_sample='LOW_SAMPLE_DESCRIPTIVE'))
 funnel={};abstentions={};citationquality={};unsupported={}
 for track in outputs:
  qs=list(tasks);m=next(x for x in per if x['track']==track)
  stages=[('tasks',set(qs))]
  if track=='A':stages += [('all_gold_hybrid20',{q for q in qs if ceilings[q]!='NOT_ANSWERABLE_FROM_TOP20'}),('all_gold_final10',{q for q in qs if ceilings[q]=='ANSWERABLE_FROM_TOP10'})]
  else:stages += [('execution_succeeded',{q for q in qs if outputs[track][q]['status']!='failed'}),('all_gold_admitted_after_agent',{q for q in qs if goldsets[q]<=available[track,q]})]
  stages += [('review_evidence_sufficient',{q for q in qs if reviews[track,q]['evidence_sufficiency']=='SUFFICIENT'}),('semantic_complete',{q for q in qs if reviews[track,q]['answer_correctness']=='COMPLETE'}),('correctly_cited_complete',{q for q in qs if reviews[track,q]['answer_correctness']=='COMPLETE' and reviews[track,q]['citation_correctness']=='ALL'})]
  cumulative=set(qs);funnel[track]=[]
  for name,members in stages:
   cumulative &= members;funnel[track].append(dict(stage=name,count=len(members),rate=len(members)/40,cumulative_count=len(cumulative),cumulative_rate=len(cumulative)/40))
  abst=[]
  for q in qs:
   j=reviews[track,q];r=outputs[track][q]
   is_abst=r.get('abstention',False) if track=='A' else r['status']!='failed' and bool(r['insufficient_evidence_cells'])
   if is_abst:
    # Review is explicitly about supplied evidence; exact-Gold availability is a separate proxy.
    enough=j['evidence_sufficiency']=='SUFFICIENT' or goldsets[q]<=available[track,q]
    abst.append(dict(query_id=q,classification='MISSED_OPPORTUNITY_ABSTENTION' if enough else 'SAFE_ABSTENTION',review_evidence=j['evidence_sufficiency'],all_exact_gold_available=goldsets[q]<=available[track,q],semantic_status=j['answer_correctness']))
  abstentions[track]=dict(counts=dict(collections.Counter(x['classification'] for x in abst)),items=abst,definition='A: explicit whole-answer abstention; B-R: any system insufficient-evidence cell in a validated report. Sufficient review OR all exact Gold => missed opportunity; otherwise safe under the frozen evidence-sufficiency review. B fields exceed some questions; this is not a task failure count.')
  citationquality[track]=dict(ALL=m['citation_ALL'],PARTIAL=m['citation_PARTIAL'],NONE=m['citation_NONE'],complete_all=m['correctly_cited_complete'],complete_partial_or_none=m['COMPLETE']-m['correctly_cited_complete'],partial_all=sum(reviews[track,q]['answer_correctness']=='PARTIAL' and reviews[track,q]['citation_correctness']=='ALL' for q in qs))
  unsupported[track]=[dict(query_id=q,review_item_id=reviews[track,q]['review_item_id'],count=reviews[track,q]['unsupported_claims'],claim_review=reviews[track,q]['claim_review'],distinction='CONTRADICTED_OR_MISCHARACTERIZED_AS_RECORDED; no new per-claim relabeling') for q in qs if reviews[track,q]['unsupported_claims']]
 recmap={x['query_id']:x for x in recovery}
 recovered=[x['query_id'] for x in recovery if x['recovered_admitted']];allrec=[x['query_id'] for x in recovery if x['all_missing_recovered']]
 groups={}
 for used in [True,False]:
  qs=[q for q in tasks if bool(recmap[q]['supplemental_calls'])==used]
  groups['SUPPLEMENTAL_USED' if used else 'NO_SUPPLEMENTAL']=dict(metrics=metrics([reviews['B-R',q] for q in qs]),paired=dict(collections.Counter(p['change'] for p in pairs if p['query_id'] in qs)),causal_claim=False)
 assert sum(bool(x['supplemental_calls']) for x in recovery)==19 and sum(x['total_calls'] for x in recovery)==201
 summary=dict(status='COMPLETE',review_method='MODEL_ASSISTED_SEMANTIC_REVIEW',checksum=dict(review_items=80,**expected,unsupported_claims_total=7,items_with_unsupported_claims=4),track_metrics=per,
  paired_counts=dict(collections.Counter(p['change'] for p in pairs)),paired_matrix={a:{b:sum(p['A']==a and p['B_R']==b for p in pairs) for b in LABELS} for a in LABELS},
  A_incomplete_B_complete=sum(p['A_incomplete_B_complete'] for p in pairs),A_complete_B_incomplete=sum(p['A_complete_B_incomplete'] for p in pairs),
  workflow_semantic_crosstab={s:{lab:sum(outputs['B-R'][q]['status']==s and reviews['B-R',q]['answer_correctness']==lab for q in tasks) for lab in LABELS} for s in ['completed','partial','failed']},
  retrieval_ceiling=dict(collections.Counter(ceilings.values())),ceiling_semantic_crosstab={c:{lab:sum(ceilings[q]==c and reviews['A',q]['answer_correctness']==lab for q in tasks) for lab in LABELS} for c in sorted(set(ceilings.values()))},
  top10_answerable_A_incomplete=sum(ceilings[q]=='ANSWERABLE_FROM_TOP10' and reviews['A',q]['answer_correctness']!='COMPLETE' for q in tasks),
  recovery=dict(missing_units_before=sum(x['missing_before'] for x in recovery),units_recovered_admitted=sum(x['recovered_admitted'] for x in recovery),units_recovered_initial=sum(x['recovered_initial'] for x in recovery),units_recovered_supplemental=sum(x['recovered_supplemental'] for x in recovery),previously_missing_still_missing=sum(x['previously_missing_still_absent'] for x in recovery),queries_with_recovery=len(recovered),queries_all_missing_recovered=len(allrec),queries_still_retrieval_limited=sum(not x['all_required_admitted'] for x in recovery),recovered_semantics=counts([reviews['B-R',q] for q in recovered],'answer_correctness',LABELS),all_recovered_semantics=counts([reviews['B-R',q] for q in allrec],'answer_correctness',LABELS),ORCHESTRATION_RECOVERY_SUCCESS=sum(p['ORCHESTRATION_RECOVERY_SUCCESS'] for p in pairs),definition='Before=Track A final Top10. Recovery=first acquisition of previously missing exact locator into admitted Evidence; initial and supplemental mutually exclusive. Global-only return coverage is separately recorded. B does not inherit A context.'),
  intensity=dict(supplemental_tasks=19,total_retrieval_calls=201,calls_per_task=stats([x['total_calls'] for x in recovery]),unique_subqueries_per_task=stats([x['unique_subqueries'] for x in recovery]),subquery_invocations_per_task=stats([x['total_calls'] for x in recovery]),unique_returned_chunks=stats([x['unique_returned_chunks'] for x in recovery]),unique_admitted_chunks=stats([x['unique_admitted_chunks'] for x in recovery]),unique_returned_documents=stats([x['unique_returned_documents'] for x in recovery]),unique_admitted_documents=stats([x['unique_admitted_documents'] for x in recovery]),llm_calls=stats([r['llm_calls'] for r in outputs['B-R'].values()]),workflow_latency_ms=stats([r['execution_summary']['duration_ms'] for r in outputs['B-R'].values()]),percentile_method='linear interpolation at (n-1)*p'),
  supplemental_groups=groups,query_type_metrics=categories,failure_counts={t:{c:sum(x['track']==t and x['primary_cause']==c for x in failures) for c in CAUSES} for t in outputs},
  cross_document={t:dict(collections.Counter(x['poc_result'] for x in cross if x['track']==t)) for t in outputs},multi_hop={t:dict(collections.Counter(x['poc_result'] for x in multi if x['track']==t)) for t in outputs},abstention=abstentions,citation_quality=citationquality,unsupported_claims=unsupported,
  mapping_proof=proof,protected_hashes=protected,tests=dict(passed=0,failed=0))
 for name,rows in [('v2_g4_track_metrics.csv',per),('v2_g4_paired_comparison.csv',pairs),('v2_g4_query_type_metrics.csv',categories),('v2_g4_failure_attribution.csv',failures),('v2_g4_retrieval_recovery.csv',recovery),('v2_g4_cross_paper.csv',cross),('v2_g4_multi_hop.csv',multi)]:csvout(name,rows)
 write(G/'final_summary.json',summary);write(G/'workflow_funnel.json',dict(denominator=40,interpretation='count/rate are marginal stage diagnostics and may be non-monotonic because exact Gold is a proxy, not all semantically sufficient Evidence; cumulative_count/rate are nested intersections, not to be conflated.',tracks=funnel))
 for p,h in protected.items():assert sha(ROOT/p)==h,p
 print(json.dumps({k:summary[k] for k in ['track_metrics','paired_counts','retrieval_ceiling','recovery','failure_counts','cross_document','multi_hop']},ensure_ascii=True))
if __name__=='__main__':main()
