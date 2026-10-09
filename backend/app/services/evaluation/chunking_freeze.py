"""Deterministic BASE corpus fingerprinting, without parsing or retrieval."""
import hashlib
import json


def canonical_hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode('utf-8')).hexdigest()


def corpus_identities(chunks, documents):
    ids=sorted(c['chunk_id'] for c in chunks)
    assert len(ids)==len(set(ids))
    text_rows=sorted([[c['chunk_id'], hashlib.sha256(c['text'].encode('utf-8')).hexdigest()] for c in chunks])
    locator_rows=sorted([[c['chunk_id'],c['document_id'],c['document_version_id'],c['page'],c['section'],c['document_char_start'],c['document_char_end'],c['source_text_hash']] for c in chunks])
    doc_rows=sorted([[d['document_id'],d['document_version_id'],d['paper_id'],d['source_sha256'],d['text_hash'],d['page_count'],d['chunk_count']] for d in documents])
    return dict(chunk_id_hash=canonical_hash(ids),chunk_text_hash=canonical_hash(text_rows),chunk_locator_hash=canonical_hash(locator_rows),source_document_set_hash=canonical_hash(doc_rows),corpus_hash=canonical_hash({'ids':ids,'texts':text_rows,'locators':locator_rows,'documents':doc_rows}))


def validate_config(config):
    assert config['schema_version']=='researchgraph.chunking-freeze.v1'
    assert config['chunker_name']=='TextChunker'
    assert (config['target_chars'],config['overlap_chars'])==(700,100)
    assert config['page_contained'] is True and config['cross_page'] is False
    assert config['sentence_boundary_aware'] is False
    assert (config['document_count'],config['page_count'],config['chunk_count'])==(30,432,3837)
    assert config['selected_from']=='V2-C1R'
    assert config['DEV_SELECTED'] is True and config['TEST_VALIDATED'] is False and config['PRODUCTION_DEFAULT'] is False
    for key in ('corpus_hash','chunk_id_hash','chunk_text_hash','chunk_locator_hash','source_document_set_hash','implementation_sha256'):
        value=config[key];assert len(value)==64 and all(c in '0123456789abcdef' for c in value)
