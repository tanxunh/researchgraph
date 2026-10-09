"""V2-F TEST: structural preflight, immutable pre-lock, one-shot execution."""
from run_v2_final_retrieval import *

def validate_gold(qs,cc,rows,docs):
 from app.services.indexing.hash_service import hash_text
 assert len(qs)==40 and len({q['query_id'] for q in qs})==40,'expected 40 unique TEST queries'
 mapping={};units=[]
 for q in qs:
  assert q['query'].strip() and q['human_verified'] is True and q['gold_evidence'],'unreviewed or empty query'
  assert q['query_type'] in ('factual','exact_term','semantic','relational','cross_document','multi_hop')
  seen=set()
  for i,g in enumerate(q['gold_evidence'],1):
   cid=g['chunk_id'];assert cid in cc and cid in rows,'missing chunk: '+cid
   assert cid not in seen,'duplicate Gold unit';seen.add(cid);c=cc[cid];meta=rows[cid]['metadata']
   for k in ('document_id','document_version_id'):
    assert g[k]==c[k]==meta[k],f'locator mismatch: {cid} {k}'
   doc=docs[(c['document_id'],c['document_version_id'])]
   assert g['paper_id']==doc['paper_id'] and c['document_id'] in q['document_scope'],'document scope or paper mismatch'
   assert c['text']==rows[cid]['document'] and hash_text(c['text'])==meta['chunk_hash'],'raw text/hash mismatch'
   assert cid.startswith('doc-'+str(c['document_id'])+'-chunk-'+meta['chunk_hash'][:24]),'stable chunk ID mismatch'
   assert g.get('page')==c['page'] and g.get('section')==c['section'],'page/section mismatch'
   assert doc['text_hash']==c['source_text_hash'] and doc['text'][c['document_char_start']:c['document_char_end']]==c['text'],'source offset/text identity mismatch'
   gid=q['query_id']+':G'+str(i);mapping[gid]=[cid];units.append({'gold_id':gid,'query_id':q['query_id'],**g,'raw_text_sha256':hashlib.sha256(c['text'].encode()).hexdigest(),'source_text_hash':c['source_text_hash']})
 return mapping,units

def preflight():
 p=verify();dev=read(F/'dev_reproduction.json');assert dev['status']=='PASS','FINAL_DEV_REPRODUCTION_FAIL'
 assert not (ROOT/F/'pre_test_lock.json').exists(),'pre-test lock already exists'
 try:
  qs=queries('test');cc=corpus();src=read('artifacts/evaluation_v2/b4/corpus.json');rows=dict(zip(src['ids'],src['rows']));docs={(d['document_id'],d['document_version_id']):d for d in read('artifacts/evaluation_v2/c0/source_reconstruction.json')['documents']}
  mapping,units=validate_gold(qs,cc,rows,docs)
  split=read(B/'split_manifest.json');assert split['test_human_verified']==40 and split['test_pending_human_review']==0 and split['test_gold_frozen']
  assert {q['query_id'] for q in qs}.isdisjoint({q['query_id'] for q in queries('dev')})
  assert dict(collections.Counter(q['query_type'] for q in qs))==split['query_type_distribution']['test']
 except Exception as exc:
  write(F/'test_gold_validation.json',{'status':'TEST_GOLD_VALIDATION_FAIL','error':type(exc).__name__,'detail':str(exc),'scoring_started':False});raise
 gold_projection=[{'query_id':q['query_id'],'gold_evidence':q['gold_evidence']} for q in qs]
 write(F/'test_gold_validation.json',{'status':'PASS','queries':40,'Gold_units':len(units),'rule':'frozen exact BASE chunk locators; no remap or annotation','mapping':mapping,'units':units,'embedded_gold_source':str(B/'queries_test.jsonl'),'embedded_gold_file_sha256':sha(B/'queries_test.jsonl'),'canonical_gold_sha256':canonical_hash(gold_projection),'retrieval_inspected':False,'created_at':now()})
 dense=read(B/'final_dense_config.json');rerank=read(B/'final_reranker_config.json');chunk=read(B/'final_chunking_config.json')
 manifest={'schema_version':'researchgraph.retrieval-freeze.v1','created_from':'V2-B5 + V2-C2 + V2-D + V2-E','DEV_SELECTED':True,'TEST_VALIDATED':False,'PRODUCTION_DEFAULT':False,'dense_model':dense['model'],'dense_revision':dense['revision'],'dense_fingerprint':dense['embedding_fingerprint'],'bm25_depth':200,'bm25_implementation_sha256':sha('backend/app/services/indexing/bm25_index.py'),'bm25_index_identity':p['bm25_index_identity'],'dense_index_files':p['dense_index_files'],'dense_index_identity':canonical_hash(p['dense_index_files']),'dense_document_vector_fingerprint':dense['document_vector_fingerprint'],'reranker_model':rerank['model'],'reranker_revision':rerank['revision'],'reranker_candidate_depth':20,'final_top_k':10,'corpus_hash':chunk['corpus_hash'],'chunk_id_hash':chunk['chunk_id_hash'],'chunk_text_hash':chunk['chunk_text_hash'],'DEV_query_path':str(B/'queries_dev.jsonl'),'DEV_query_sha256':sha(B/'queries_dev.jsonl'),'TEST_query_path':str(B/'queries_test.jsonl'),'TEST_query_sha256':sha(B/'queries_test.jsonl'),'DEV_Gold_path':str(B/'dev_gold_evidence_spans_v2.json'),'DEV_Gold_sha256':sha(B/'dev_gold_evidence_spans_v2.json'),'TEST_Gold_path':str(B/'queries_test.jsonl'),'TEST_Gold_sha256':sha(B/'queries_test.jsonl'),'TEST_Gold_canonical_sha256':canonical_hash(gold_projection),'gold_hash_note':'TEST Gold embedded in frozen queries_test.jsonl: whole-file SHA plus canonical query_id/gold_evidence projection; DEV uses reviewed span layer','DEV_reproduction_sha256':sha(F/'dev_reproduction.json'),'protocol_sha256':sha(F/'protocol.json'),'query_scope':'global','created_at':now()}
 for component in ('chunking','dense','fusion','reranker'):
  path=B/f'final_{component}_config.json';manifest[component+'_config_path']=str(path);manifest[component+'_config_sha256']=sha(path)
 write(B/'final_retrieval_manifest.json',manifest);write(F/'pre_test_manifest.json',manifest);mh=sha(B/'final_retrieval_manifest.json');assert sha(F/'pre_test_manifest.json')==mh
 protected=p['protected_hashes'].copy()
 for path in [str(B/'final_retrieval_manifest.json'),str(F/'pre_test_manifest.json'),str(F/'dev_reproduction.json'),str(F/'test_gold_validation.json'),'backend/scripts/run_v2_final_test.py']:
  protected[path]=sha(path)
 lock={'status':'PASS','created_at':now(),'pre_test_manifest_sha256':mh,'protected_hashes':protected,'TEST_queries':40,'TEST_Gold_units':len(units),'execution_count_at_lock':0,'TEST_not_evaluated':True}
 write(F/'pre_test_lock.json',lock);print('TEST_GOLD_VALIDATION = PASS; Gold units =',len(units),flush=True);print('PRE_TEST_LOCK = PASS',mh,flush=True)

def verify_lock():
 lock=read(F/'pre_test_lock.json');assert lock['status']=='PASS'
 for p,h in lock['protected_hashes'].items():assert sha(p)==h,p
 return lock

def test():
 lock=verify_lock();qs=queries('test');validation=read(F/'test_gold_validation.json');assert validation['status']=='PASS'
 exclusive_lock(F/'test_execution_lock.json',{'attempt':1,'started_at':now(),'pre_test_manifest_sha256':lock['pre_test_manifest_sha256'],'query_ids':[q['query_id'] for q in qs],'policy':'one execution; no automatic retry, resume, overwrite, or retuning'})
 out={'status':'RUNNING','started_at':now(),'pre_test_manifest_sha256':lock['pre_test_manifest_sha256'],'cases':[],'attempt':1}
 try:
  pipe=Pipeline();out['runtime_audit']=pipe.audit
  # Warm-up uses an already-seen DEV query, never TEST; no measurement or scoring.
  pipe.run(queries('dev')[0])
  for q in qs:
   journal=F/'query_execution_journal.jsonl'
   with (ROOT/journal).open('a',encoding='utf-8') as f:f.write(json.dumps({'query_id':q['query_id'],'state':'STARTED','time':now()})+'\n')
   row=pipe.run(q);out['cases'].append(row);write(F/'test_run.json',out)
   with (ROOT/journal).open('a',encoding='utf-8') as f:f.write(json.dumps({'query_id':q['query_id'],'state':'COMPLETED','time':now()})+'\n')
   print('TEST',q['query_id'],len(out['cases']),'/40',round(row['timings_ms']['end_to_end'],2),'ms',flush=True)
  verify_lock();out.update(status='COMPLETE',completed_at=now());write(F/'test_run.json',out)
  scores=evaluate(out['cases'],validation['mapping']);write(F/'test_metrics_frozen.json',{'status':'FROZEN','run_sha256':sha(F/'test_run.json'),'pre_test_manifest_sha256':lock['pre_test_manifest_sha256'],'metrics':scores,'created_at':now()});print('FINAL_TEST_COMPLETE_ONCE',flush=True)
 except Exception as exc:
  out.update(status='FAILED_NO_RETRY',error=type(exc).__name__,detail=str(exc));write(F/'test_run.json',out);raise

if __name__=='__main__':
 a=argparse.ArgumentParser();a.add_argument('action',choices=['preflight','test']);args=a.parse_args();preflight() if args.action=='preflight' else test()
