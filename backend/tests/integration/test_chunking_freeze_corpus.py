"""Exact BASE verification in memory from saved source; no PDF parse/index write."""
import hashlib,json
from pathlib import Path
from app.services.chunking.text_chunker import TextChunker
from app.services.parsing.base import ParsedDocument,ParsedSection
from app.services.indexing.hash_service import stable_chunk_id
from app.services.evaluation.chunking_freeze import corpus_identities
ROOT=Path(__file__).resolve().parents[3]


def test_frozen_base_all3837_chunks_match_actual_production_implementation():
    cfg=json.loads((ROOT/'benchmarks/real_research/v2/final_chunking_config.json').read_text())
    source_path=ROOT/'artifacts/evaluation_v2/c0/source_reconstruction.json'
    base_path=ROOT/cfg['base_corpus_artifact']
    assert hashlib.sha256(source_path.read_bytes()).hexdigest()==cfg['source_reconstruction_sha256']
    assert hashlib.sha256(base_path.read_bytes()).hexdigest()==cfg['base_corpus_sha256']
    source=json.loads(source_path.read_text());base=json.loads(base_path.read_text())['chunks']
    chunker=TextChunker(cfg['target_chars'],cfg['overlap_chars']);total=0
    for d in source['documents']:
        parsed=ParsedDocument(title='frozen',source_type='pdf',source_uri='frozen',text=d['text'],sections=[ParsedSection(text=p['text'],order=i,page_number=p['page'],section_title=p['section']) for i,p in enumerate(d['pages'])])
        actual=chunker.chunk(parsed);expected=[c for c in base if c['document_id']==d['document_id']]
        assert len(actual)==len(expected)==d['chunk_count'];seen={}
        for candidate,c in zip(actual,expected):
            assert candidate.text==c['text'] and candidate.page_number==c['page'] and candidate.section_title==c['section']
            n=seen.get(candidate.chunk_hash,0);seen[candidate.chunk_hash]=n+1
            assert stable_chunk_id(d['document_id'],candidate.chunk_hash,n)==c['chunk_id']
            page,=[p for p in d['pages'] if p['page']==c['page']]
            assert page['start']<=c['document_char_start']<c['document_char_end']<=page['end']
            assert d['text'][c['document_char_start']:c['document_char_end']]==candidate.text
        total+=len(actual)
    assert total==3837 and len(source['documents'])==30
    for key,value in corpus_identities(base,source['documents']).items():assert cfg[key]==value
