"""Offline completeness and blind review assembly; never semantic scoring."""
import collections,json
from run_v2_g_generation import ROOT,B,G,RUN,read,write,sha,load_lines,verify

def finalize():
 protocol=verify();a=load_lines(G/'track_a_answers.jsonl');b=load_lines(G/'track_b_answers.jsonl')
 expected=protocol['query_order']
 complete=len(a)==len(b)==40
 for rows in [a,b]:
  assert len(rows)==len({r['query_id'] for r in rows})
  assert [r['query_id'] for r in rows]==expected[:len(rows)]
 trace=load_lines(G/'track_b_retrieval_trace.jsonl')
 assert [r['query_id'] for r in trace]==[r['query_id'] for r in b]
 counts=collections.Counter(r['status'] for r in b)
 summary=dict(status='GENERATION_COMPLETE' if complete else 'GENERATION_INCOMPLETE',
  runtime_type='RECONSTRUCTED_EVALUATION_RUNTIME',semantic_scoring_performed=False,
  track_a=dict(records=len(a),generated=sum(r['status']!='failed' for r in a),failed=sum(r['status']=='failed' for r in a),
   abstentions=sum(r.get('abstention',False) for r in a),technical_retries=sum(r['technical_retry_count'] for r in a)),
  track_b=dict(records=len(b),generated=sum(r['status']!='failed' for r in b),failed=counts['failed'],complete=counts['completed'],partial=counts['partial'],
   supplemental_triggered=sum(r['supplemental_rounds']>0 for r in b),total_retrieval_calls=sum(r['total_retrieval_calls'] for r in trace),
   supplemental_retrieval_calls=sum(r['supplemental_retrieval_calls'] for r in trace),technical_retries=sum(r['technical_retry_count'] for r in b)),
  llm_calls=sum(r['llm_calls'] for r in a+b),token_usage=None,
  citation_validation=dict(track_a=collections.Counter('PASS' if r.get('citation_validation',{}).get('valid') else 'FAILED_OR_UNAVAILABLE' for r in a),
   track_b=collections.Counter('PASS' if r['citation_validation']['structural_pass'] else 'FAILED_OR_NOT_REACHED' for r in b)),
  unsupported_cells_emitted=sum(len(r['unsupported_cells_emitted']) for r in b),
  allowed_cell_gating=('PASS' if not any(r['unsupported_cells_emitted'] for r in b) else 'FAIL') if b else 'NOT_RUN',
  frozen_configs_unchanged=True,benchmark_unchanged=True,TEST_unchanged=True,frozen_retrieval_unchanged=True,
  generation_config_unchanged=True,review_items=0,ready_for_human_review=False,
  failed_record_note='A failed execution is preserved as one result record with no trusted answer; never regenerated.',
  blind_order='Pre-existing private item mapping reused unchanged; no new shuffle; original seed not recorded in that artifact.')
 if complete:
  mapping=read(G/'review_item_mapping_private.json')['items'];assert len(mapping)==80
  lookup={('A',r['query_id']):r for r in a};lookup.update({('B',r['query_id']):r for r in b})
  assert len({(m['track'],m['query_id']) for m in mapping})==80
  output=['# Human Workflow Review','', 'STATUS: READY FOR HUMAN REVIEW. Semantic labels remain PENDING.',
   'Items follow the pre-existing blinded order. No Gold hits, retrieval scores, track labels or runtime histories are shown.',
   'If no validated answer was returned, this is stated without substituting rejected model content.','']
  for item in mapping:
   row=lookup[(item['track'],item['query_id'])]
   output += ['## '+item['review_item_id'],'','Query ID: '+row['query_id'],'','Question: '+row['question'],'','### Generated answer','']
   answer=row['answer']
   if isinstance(answer,dict):
    output += [answer['summary'],'']
    for cell in answer['comparison']:output.append(f"- Document {cell['document_id']} / {cell['field']}: {cell['value']}")
    output += ['','Limitations:']+['- '+s for s in answer.get('limitations',[])]
   else:output.append(answer if answer else 'No validated answer was returned.')
   output += ['','### Citations','','```json',json.dumps(row['citations'],ensure_ascii=False,indent=2),'```','','### Provided evidence','']
   final={(e['document_id'],e['document_version_id'],e['chunk_id']):e for e in row.get('final_admitted_evidence',row['provided_evidence'])}
   for e in row['provided_evidence']:
    key=(e['document_id'],e['document_version_id'],e['chunk_id']);handle=final.get(key,{}).get('evidence_id','No final citation handle')
    output += [f"**{handle} | document {key[0]} | version {key[1]} | {key[2]}**",f"Page: {e.get('page')} | Section: {e.get('section')}",'',e['content'],'']
   output += ['answer_correctness: PENDING (COMPLETE / PARTIAL / INCORRECT)',
    'evidence_sufficiency: PENDING (SUFFICIENT / PARTIAL / INSUFFICIENT)',
    'citation_correctness: PENDING (ALL / PARTIAL / NONE)',
    'unsupported_claims: PENDING (integer)','reviewer_notes:',
    'Claim review: claim_id | exact answer span | cited chunks/documents | SUPPORTED / PARTIALLY_SUPPORTED / UNSUPPORTED / CONTRADICTED | citation supports claim YES/NO','']
  (ROOT/G/'HUMAN_WORKFLOW_REVIEW.md').write_text('\n'.join(output)+'\n',encoding='utf-8')
  summary.update(review_items=80,ready_for_human_review=True)
 write(G/'generation_run_summary.json',summary)
 print(json.dumps(summary,sort_keys=True))

if __name__=='__main__':finalize()
