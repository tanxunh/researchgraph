"""Offline G4 artifact invariants; standard library only, no external services."""
import unittest,json,csv,re,hashlib
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3];G=ROOT/'artifacts/evaluation_v2/g';B=ROOT/'benchmarks/real_research/v2'
def read(p):return json.loads(p.read_text(encoding='utf-8'))
def rows(p):return [json.loads(x) for x in p.read_text(encoding='utf-8').splitlines()]
def csvrows(n):
 with (B/n).open(encoding='utf-8',newline='') as stream:return list(csv.DictReader(stream))
class G4Integrity(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.s=read(G/'final_summary.json');cls.j=read(G/'V2_G3_REVIEW_SUMMARY.json')['judgments'];cls.tasks=read(B/'v2_g_workflow_benchmark.json')['tasks']
 def test_review_file_hashes(self):
  expected={'HUMAN_WORKFLOW_REVIEW_COMPLETED.md':'0d7e07c0e65301d8e3abf90737c8189800f8b522f43de1f629136cf219acef77','V2_G3_REVIEW_SUMMARY.json':'4959228e3c3f541492aa7382d98f87e4a965f1cb6fffed04c94d492bc34fc2fb'}
  for n,h in expected.items():self.assertEqual(hashlib.sha256((G/n).read_bytes()).hexdigest(),h)
 def test_review_checksum(self):
  self.assertEqual(len(self.j),80)
  for k,exp in [('answer_correctness',{'COMPLETE':51,'PARTIAL':18,'INCORRECT':11}),('evidence_sufficiency',{'SUFFICIENT':69,'PARTIAL':9,'INSUFFICIENT':2}),('citation_correctness',{'ALL':58,'PARTIAL':4,'NONE':18})]:
   self.assertEqual({v:sum(j[k]==v for j in self.j.values()) for v in exp},exp)
  self.assertEqual(sum(j['unsupported_claims'] for j in self.j.values()),7)
  self.assertEqual(sum(j['unsupported_claims']>0 for j in self.j.values()),4)
 def test_mapping_bijection(self):
  proof=self.s['mapping_proof'];self.assertEqual(len(proof),80)
  self.assertEqual(len({x['review_item_id'] for x in proof}),80)
  self.assertEqual({(x['track'],x['query_id']) for x in proof},{(t,q['query_id']) for t in ['A','B-R'] for q in self.tasks})
 def test_frozen_payloads_match(self):
  def split(n):
   x=re.split(r'^## (R\d{3})\s*$',(G/n).read_text(encoding='utf-8'),flags=re.M);return dict(zip(x[1::2],x[2::2]))
  a=split('HUMAN_WORKFLOW_REVIEW.md');b=split('HUMAN_WORKFLOW_REVIEW_COMPLETED.md')
  for k in a:self.assertEqual(a[k].split('answer_correctness:')[0].strip(),b[k].split('answer_correctness:')[0].strip())
 def test_g2_unchanged_and_failures_preserved(self):
  old=read(G/'generation_run_summary.json')
  for n,h in old['artifact_hashes'].items():self.assertEqual(hashlib.sha256((G/n).read_bytes()).hexdigest(),h)
  self.assertEqual({r['query_id'] for r in rows(G/'track_b_answers.jsonl') if r['status']=='failed'},{'V2Q048','V2Q075'})
 def test_protected_hashes(self):
  for p,h in self.s['protected_hashes'].items():self.assertEqual(hashlib.sha256((ROOT/p).read_bytes()).hexdigest(),h,p)
 def test_denominators(self):
  for m in self.s['track_metrics']:
   self.assertEqual(m['n'],40);self.assertEqual(sum(m[k] for k in ['COMPLETE','PARTIAL','INCORRECT']),40)
   self.assertEqual(m['complete_rate'],m['COMPLETE']/40)
 def test_paired_matrix(self):
  ps=csvrows('v2_g4_paired_comparison.csv');self.assertEqual(len(ps),40)
  self.assertEqual(len({p['query_id'] for p in ps}),40)
  self.assertEqual(sum(sum(v.values()) for v in self.s['paired_matrix'].values()),40)
  self.assertEqual(sum(self.s['paired_counts'].values()),40)
 def test_category_sizes(self):
  expected={'factual':8,'exact_term':5,'semantic':8,'relational':5,'cross_document':8,'multi_hop':6}
  for x in self.s['query_type_metrics']:self.assertEqual(x['n'],expected[x['query_type']])
 def test_recovery_conservation(self):
  for x in csvrows('v2_g4_retrieval_recovery.csv'):
   self.assertEqual(int(x['missing_before']),int(x['recovered_admitted'])+int(x['previously_missing_still_absent']))
   self.assertEqual(int(x['recovered_admitted']),int(x['recovered_initial'])+int(x['recovered_supplemental']))
   self.assertEqual(len(json.loads(x['recovered_locators'])),int(x['recovered_admitted']))
 def test_recovery_from_real_admission(self):
  trace={x['query_id']:x for x in rows(G/'track_b_retrieval_trace.jsonl')}
  for x in csvrows('v2_g4_retrieval_recovery.csv'):
   admitted={(e['document_id'],e['document_version_id'],e['chunk_id']) for c in trace[x['query_id']]['retrieval_calls'] for e in (c.get('admission') or {}).get('admitted',[])}
   missing={tuple(v) for v in json.loads(x['missing_before_locators'])}
   self.assertEqual(missing & admitted,{tuple(v) for v in json.loads(x['recovered_locators'])})
 def test_intensity(self):
  trace=rows(G/'track_b_retrieval_trace.jsonl');self.assertEqual(sum(len(t['retrieval_calls']) for t in trace),201)
  self.assertEqual(sum(any(c.get('phase')=='supplemental' for c in t['retrieval_calls']) for t in trace),19)
 def test_failure_primary_exclusive(self):
  data=csvrows('v2_g4_failure_attribution.csv');self.assertEqual(len(data),29);self.assertEqual(len({(x['track'],x['query_id']) for x in data}),29)
  self.assertEqual(sum(x['track']=='A' for x in data),17);self.assertEqual(sum(x['track']=='B-R' for x in data),12)
 def test_strict_cross_and_hop(self):
  for name,per in [('v2_g4_cross_paper.csv',8),('v2_g4_multi_hop.csv',6)]:
   data=csvrows(name);self.assertEqual(len(data),2*per)
   for x in data:
    if x['poc_result']=='FULL':
     self.assertEqual(x['answer_correctness'],'COMPLETE');self.assertEqual(x['citation_correctness'],'ALL')
     self.assertEqual(x['all_documents_used'] if per==8 else x['all_required_gold_available'],'True')
 def test_funnel_cumulative_monotonic(self):
  for track,stages in read(G/'workflow_funnel.json')['tracks'].items():
   vals=[s['cumulative_count'] for s in stages];self.assertEqual(vals,sorted(vals,reverse=True))
   for s in stages:self.assertLessEqual(s['cumulative_count'],s['count']);self.assertEqual(s['rate'],s['count']/40)
 def test_provenance(self):
  p=read(G/'poc_closeout.json');self.assertEqual(p['review_method'],'MODEL_ASSISTED_SEMANTIC_REVIEW');self.assertFalse(p['historical_runtime_recovered']);self.assertTrue(p['no_llm_calls']);self.assertTrue(p['no_retrieval_calls'])
if __name__=='__main__':unittest.main(verbosity=2)
