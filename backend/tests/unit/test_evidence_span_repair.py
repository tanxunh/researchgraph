import hashlib
import pytest
from app.services.evaluation.evidence_span_repair import resolve_approved_span, fully_contains
from app.services.evaluation.chunking_ablation import score_portable


def fixture():
    text='xﬁ-\nyz'
    a=dict(anchor_id='q:G1',anchor_text=text,document_char_start=2,document_char_end=8,
           document_id=1,document_version_id=7,page=1,original_gold_chunk_id='old',source_text_hash='h')
    u=dict(gold_id='q:G1',document_version=7,**{k:a[k] for k in ('document_id','document_version_id','page','original_gold_chunk_id','source_text_hash')})
    d=dict(document_id=1,document_version_id=7,text_hash='h',text='00'+text+'99')
    return u,a,d


def test_raw_codepoint_offsets_and_hash_no_normalization():
    u,a,d=fixture();v=resolve_approved_span(u,dict(gold_id='q:G1',review_status='APPROVED',evidence_text='ﬁ-\ny'),a,d)
    assert (v['document_char_start'],v['document_char_end'])==(3,7)
    assert v['evidence_text_hash']==hashlib.sha256('ﬁ-\ny'.encode()).hexdigest()
    assert v['reviewed_by_human']


def test_cannot_repair_hyphen_or_ligature():
    u,a,d=fixture()
    with pytest.raises(ValueError,match='exact_match_count=0'):
        resolve_approved_span(u,dict(gold_id='q:G1',review_status='APPROVED',evidence_text='fiy'),a,d)


def test_existing_wrong_offset_is_not_silently_fixed():
    u,a,d=fixture();u['document_char_start']=0
    with pytest.raises(ValueError,match='document_char_start_mismatch'):
        resolve_approved_span(u,dict(gold_id='q:G1',review_status='APPROVED',evidence_text='yz'),a,d)


def test_ambiguous_text_rejected():
    u,a,d=fixture();a['anchor_text']='aaa'
    with pytest.raises(ValueError,match='exact_match_count=2'):
        resolve_approved_span(u,dict(gold_id='q:G1',review_status='APPROVED',evidence_text='aa'),a,d)


def test_only_full_containment_counts_and_zero_mapping_keeps_denominator():
    u,a,d=fixture();s=resolve_approved_span(u,dict(gold_id='q:G1',review_status='APPROVED',evidence_text=a['anchor_text']),a,d)
    c=dict(document_id=1,document_version_id=7,source_text_hash='h',document_char_start=2,document_char_end=8,text=a['anchor_text'])
    assert fully_contains(s,c)
    assert not fully_contains(s,dict(c,document_char_end=7,text=c['text'][:-1]))
    assert not fully_contains(s,dict(c,document_version_id=8))
    scores=score_portable(['a','b'],{'q:G1':['a','b'],'q:G2':[]},'q')
    assert scores['CR@20']==.5 and scores['MRR@10']==1
