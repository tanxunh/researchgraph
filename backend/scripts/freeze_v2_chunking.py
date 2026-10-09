"""C2 exact BASE freeze; verification only, no artifact regeneration or retrieval."""
import hashlib,json,sys,types
from pathlib import Path
R=Path(__file__).resolve().parents[2];B=R/'benchmarks/real_research/v2';A=R/'artifacts/evaluation_v2';O=A/'c2'
sys.path.insert(0,str(R/'backend'));pkg=types.ModuleType('app.services.evaluation');pkg.__path__=[str(R/'backend/app/services/evaluation')];sys.modules['app.services.evaluation']=pkg
from app.services.evaluation.chunking_freeze import corpus_identities,validate_config
from app.services.indexing.hash_service import hash_text,stable_chunk_id

def read(p):return json.loads(p.read_text(encoding='utf-8-sig'))
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def save(p,d):p.write_text(json.dumps(d,ensure_ascii=False,sort_keys=True,indent=2)+'\n',encoding='utf-8')
def main():
    target=B/'final_chunking_config.json';assert not target.exists(),'freeze_already_exists_do_not_overwrite'
    O.mkdir(exist_ok=True)
    c1r=read(A/'c1r/summary.json');assert c1r['status']=='COMPLETE' and c1r['selected_candidate']=='BASE' and c1r['ready_for_c2']
    for p,h in c1r['protected_hashes'].items():assert sha(R/p)==h,p
    assert sha(B/'dev_gold_evidence_spans_v2.json')==c1r['annotation_sha256']
    # Snapshot all historical experiment files and all retained experimental indexes as bytes.
    paths=set()
    for directory in ['c0','c1','c1r']:
        paths.update(p for p in (A/directory).rglob('*') if p.is_file())
    paths.update(p for p in (R/'.tmp/v2c1').rglob('*') if p.is_file())
    paths.update(R/p for p in c1r['protected_hashes'])
    paths.update([B/'dev_gold_evidence_spans_v2.json',B/'HUMAN_DEV_EVIDENCE_SPAN_REVIEW.md',R/'backend/app/services/chunking/text_chunker.py',R/'backend/app/services/indexing/hash_service.py'])
    before={p.relative_to(R).as_posix():sha(p) for p in sorted(paths)}
    co=read(A/'c1/BASE_corpus.json');chunks=co['chunks'];src=read(A/'c0/source_reconstruction.json');manifest=read(B/'corpus_manifest.json');b4=read(A/'b4/corpus.json');b6=read(A/'b6/protocol.json')
    assert sha(A/'b4/corpus.json')==b6['protected_hashes']['artifacts/evaluation_v2/b4/corpus.json']
    assert len(chunks)==len(b4['ids'])==len(src['chunks'])==3837
    assert len(src['documents'])==len(manifest['documents'])==30
    old={sid:row for sid,row in zip(b4['ids'],b4['rows'])};raw={c['chunk_id']:c for c in src['chunks']};docs={d['document_id']:d for d in src['documents']}
    assert set(old)==set(raw)=={c['chunk_id'] for c in chunks}
    manifest_docs={d['document_id']:d for d in manifest['documents']};pdf_checks=[]
    for did,d in docs.items():
        m=manifest_docs[did];assert d['document_version_id']==m['document_version_id'] and d['paper_id']==m['paper_id'] and d['source_sha256']==m['sha256']
        assert hashlib.sha256(d['text'].encode('utf-8')).hexdigest()==d['text_hash']
        pdf=R/'benchmarks/real_research/papers'/m['filename'];assert sha(pdf)==d['source_sha256'],m['paper_id']
        pdf_checks.append({'paper_id':m['paper_id'],'sha256':sha(pdf)})
        assert len(d['pages'])==m['page_count']==d['page_count']
        assert len([c for c in chunks if c['document_id']==did])==d['chunk_count']==m['chunk_count']
    assert sum(d['page_count'] for d in docs.values())==432
    occurrence={}
    for c in chunks:
        row=old[c['chunk_id']];orig=raw[c['chunk_id']];m=row['metadata'];d=docs[c['document_id']]
        assert row['document']==orig['text']==c['text']
        assert m['document_id']==c['document_id'] and m['document_version_id']==c['document_version_id']
        assert m['page_number']==c['page']==orig['page'] and (m['section_title'] or None)==c['section']==orig['section']
        assert hash_text(c['text'])==m['chunk_hash'] and orig['ordinal']==m['chunk_index']
        assert orig['raw_span_candidates']==[c['document_char_start']]
        assert d['text'][c['document_char_start']:c['document_char_end']]==c['text']
        page,=[p for p in d['pages'] if p['page']==c['page']]
        assert page['start']<=c['document_char_start']<c['document_char_end']<=page['end']
        key=(c['document_id'],m['chunk_hash']);n=occurrence.get(key,0);occurrence[key]=n+1
        assert stable_chunk_id(c['document_id'],m['chunk_hash'],n)==c['chunk_id']
    # BASE ranks from B6 are byte-independent equivalent to the later C1 records.
    b6cases=read(A/'b6/m3.json')['cases'];c1cases=read(A/'c1/BASE_retrieval.json')['cases']
    assert len(b6cases)==len(c1cases)==35
    for p,q in zip(b6cases,c1cases):
        assert p['query_id']==q['query_id'] and all(p[k]==q[k] for k in ('bm25','dense','hybrid'))
    ids=corpus_identities(chunks,src['documents'])
    config=dict(schema_version='researchgraph.chunking-freeze.v1',chunker_name='TextChunker',chunker_implementation='backend/app/services/chunking/text_chunker.py:TextChunker',implementation_sha256=sha(R/'backend/app/services/chunking/text_chunker.py'),identity_implementation='backend/app/services/indexing/hash_service.py',identity_implementation_sha256=sha(R/'backend/app/services/indexing/hash_service.py'),target_chars=700,overlap_chars=100,page_contained=True,cross_page=False,sentence_boundary_aware=False,document_count=30,page_count=432,chunk_count=3837,**ids,corpus_manifest_sha256=sha(B/'corpus_manifest.json'),base_corpus_artifact='artifacts/evaluation_v2/c1/BASE_corpus.json',base_corpus_sha256=sha(A/'c1/BASE_corpus.json'),source_reconstruction_sha256=sha(A/'c0/source_reconstruction.json'),selected_from='V2-C1R',selection_reason='Highest repaired pre-rerank Hybrid candidate coverage under human-reviewed 100%-containment portable evidence.',DEV_SELECTED=True,TEST_VALIDATED=False,PRODUCTION_DEFAULT=False,reviewed_evidence_sha256=sha(B/'dev_gold_evidence_spans_v2.json'),selection_summary_sha256=sha(A/'c1r/summary.json'),c1_config_hash=co['audit']['chunking_config_hash'],base_observed_max_chars=max(len(c['text']) for c in chunks),target_is_universal_hard_max=False,behavior_note='Freeze existing paragraph packing and hard character windows. Existing paragraph overflow branch can prepend overlap without rechecking target; no new strict-max guarantee is introduced. Observed frozen BASE max is700.',hash_contract='Aggregate hashes use sorted records and JSON(sort_keys=True,ensure_ascii=False,separators=(comma,colon)), UTF-8. Text entries hash exact raw UTF-8; production normalized chunk_hash is independently verified. corpus_hash binds IDs,raw text hashes,locators and source document/version/PDF/text identities. Config SHA256 hashes complete sorted/indented UTF-8 JSON plus final LF; recorded externally to avoid self-reference.')
    validate_config(config);save(target,config);digest=sha(target);(B/'final_chunking_config.sha256').write_text(digest+'  final_chunking_config.json\n',encoding='utf-8')
    for name,h in before.items():assert sha(R/name)==h,name
    save(O/'freeze_validation.json',{'status':'INTEGRITY_PASS_TESTS_PENDING','config_sha256':digest,'config_path':target.relative_to(R).as_posix(),'identities':ids,'document_count':30,'page_count':432,'chunk_count':3837,'pdf_source_checks':pdf_checks,'b6_c1_base_ranks_equal':True,'protected_hashes':before,'all_protected_unchanged':True,'metric_recalculation':False,'retrieval_run':False,'encoding_run':False,'test_semantics_read':False})
    print(json.dumps({'config_sha256':digest,**ids,'protected_files':len(before)},indent=2))
if __name__=='__main__':main()
