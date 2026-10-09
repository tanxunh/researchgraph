import hashlib
import json
from pathlib import Path
import pytest
from app.services.evaluation.chunking_freeze import validate_config
from app.services.chunking.text_chunker import TextChunker
from app.services.parsing.base import ParsedDocument, ParsedSection
from app.services.indexing.hash_service import hash_text, stable_chunk_id

ROOT=Path(__file__).resolve().parents[3]
CONFIG=ROOT/'benchmarks/real_research/v2/final_chunking_config.json'
PACKAGED_CONFIG=Path(__file__).resolve().parents[1]/'fixtures/final_chunking_config.json'
if not CONFIG.exists():
    CONFIG=PACKAGED_CONFIG
EXPECTED_SHA256='008845cdc4c45d8921173138d8b8591fa06d85e44082a5d73627801be3887079'


def frozen_source_sha256(source: bytes, *, historical_endings: str) -> str:
    """Reconstruct frozen source bytes without decoding or stripping the BOM.

    The Windows freeze captured mixed endings in TextChunker (LF except its
    final CRLF) and all-CRLF in hash_service. Git's Linux checkout uses LF.
    Only newline representation is normalized; content, BOM and final-newline
    presence remain part of the single original frozen hash contract.
    """
    lf = source.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    if historical_endings == "lf_with_final_crlf":
        canonical = lf[:-1] + b"\r\n" if lf.endswith(b"\n") else lf
    elif historical_endings == "crlf":
        canonical = lf.replace(b"\n", b"\r\n")
    else:
        raise ValueError("Unknown frozen source newline representation")
    return hashlib.sha256(canonical).hexdigest()


def test_config_schema_hash_and_implementation_pinned():
    cfg=json.loads(CONFIG.read_text(encoding='utf-8'))
    validate_config(cfg)
    assert hashlib.sha256(CONFIG.read_bytes()).hexdigest()==EXPECTED_SHA256
    assert hashlib.sha256(PACKAGED_CONFIG.read_bytes()).hexdigest()==EXPECTED_SHA256
    contracts = [
        (ROOT/'backend/app/services/chunking/text_chunker.py',
         'implementation_sha256', 'lf_with_final_crlf'),
        (ROOT/cfg['identity_implementation'],
         'identity_implementation_sha256', 'crlf'),
    ]
    for path, key, endings in contracts:
        source = path.read_bytes()
        expected = cfg[key]
        lf = source.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
        # Exercise Linux LF, Windows CRLF and the current checkout independently.
        for checkout in (source, lf, lf.replace(b"\n", b"\r\n")):
            assert frozen_source_sha256(checkout, historical_endings=endings) == expected
        # Source-content drift and BOM changes must still fail the frozen check.
        assert frozen_source_sha256(lf + b"# drift\n", historical_endings=endings) != expected
        changed_bom = lf[3:] if lf.startswith(b"\xef\xbb\xbf") else b"\xef\xbb\xbf" + lf
        assert frozen_source_sha256(changed_bom, historical_endings=endings) != expected
        assert frozen_source_sha256(lf.rstrip(b"\n"), historical_endings=endings) != expected


@pytest.mark.parametrize('key,value',[('target_chars',800),('overlap_chars',0),('page_contained',False),('cross_page',True),('sentence_boundary_aware',True),('chunk_count',3836),('TEST_VALIDATED',True),('PRODUCTION_DEFAULT',True)])
def test_contract_rejects_drift(key,value):
    cfg=json.loads(CONFIG.read_text(encoding='utf-8'));cfg[key]=value
    with pytest.raises(AssertionError):validate_config(cfg)


def test_actual_chunker_page_containment_and_absolute_overlap():
    cfg=json.loads(CONFIG.read_text(encoding='utf-8'))
    parsed=ParsedDocument(title='fixture',source_type='pdf',source_uri='fixture',text='a'*900+'\n\n'+'b'*900,sections=[ParsedSection(text='a'*900,order=0,page_number=1),ParsedSection(text='b'*900,order=1,page_number=2)])
    chunker=TextChunker(cfg['target_chars'],cfg['overlap_chars']);chunks=chunker.chunk(parsed)
    assert [(c.page_number,len(c.text)) for c in chunks]==[(1,700),(1,300),(2,700),(2,300)]
    assert all(set(c.text)==({'a'} if c.page_number==1 else {'b'}) for c in chunks)
    assert chunks==chunker.chunk(parsed)
    assert chunks[0].text[-100:]==chunks[1].text[:100]


def test_stable_id_format_and_occurrences_are_pinned():
    assert hash_text('abc')=='ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad'
    assert stable_chunk_id(7,hash_text('abc'))=='doc-7-chunk-ba7816bf8f01cfea414140de'
    assert stable_chunk_id(7,hash_text('abc'),1)=='doc-7-chunk-ba7816bf8f01cfea414140de-occ-1'
