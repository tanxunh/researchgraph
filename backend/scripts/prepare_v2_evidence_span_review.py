"""C1R blind annotation preparation. No candidate corpus/ranking is opened semantically."""
import csv
import hashlib
import json
from pathlib import Path

R = Path(__file__).resolve().parents[2]
B = R / 'benchmarks/real_research/v2'
O = R / 'artifacts/evaluation_v2/c1r'

def read(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')

def main():
    target = B / 'dev_gold_evidence_spans_v2.json'
    review = B / 'HUMAN_DEV_EVIDENCE_SPAN_REVIEW.md'
    assert not target.exists() and not review.exists(), 'Never overwrite human annotation work'
    O.mkdir(parents=True, exist_ok=True)
    # TEST is hashed as opaque bytes only. Rankings are hashed, never parsed.
    protected_paths = [B / n for n in ('queries_dev.jsonl','queries_test.jsonl','corpus_manifest.json','dev_gold_portable_anchors.json')]
    source_path = R / 'artifacts/evaluation_v2/c0/source_reconstruction.json'
    protected_paths.append(source_path)
    for pattern in ('*_retrieval.json','*_reranked.json','*_corpus.json','*_vectors.npz'):
        protected_paths.extend(sorted((R/'artifacts/evaluation_v2/c1').glob(pattern)))
    protected = {p.relative_to(R).as_posix():sha(p) for p in protected_paths}
    source = read(source_path)
    old = read(B / 'dev_gold_portable_anchors.json')
    queries = [json.loads(line) for line in (B/'queries_dev.jsonl').read_text(encoding='utf-8').splitlines() if line.strip()]
    assert len(queries) == 35
    chunks = {c['chunk_id']:c for c in source['chunks']}
    docs = {d['document_id']:d for d in source['documents']}
    old_by_id = {a['anchor_id']:a for a in old['anchors']}
    units = []
    for query in sorted(queries, key=lambda q:q['query_id']):
        for ordinal, gold in enumerate(query['gold_evidence'], 1):
            gid = f"{query['query_id']}:G{ordinal}"
            a = old_by_id[gid]
            c = chunks[gold['chunk_id']]
            doc = docs[gold['document_id']]
            assert len(c['raw_span_candidates']) == 1
            start = c['raw_span_candidates'][0]
            end = start + len(c['text'])
            page, = [p for p in doc['pages'] if p['page'] == gold['page']]
            assert a['original_gold_chunk_id'] == gold['chunk_id']
            assert c['document_version_id'] == gold['document_version_id'] == doc['document_version_id']
            assert a['document_char_start'] == start and a['document_char_end'] == end
            assert a['anchor_text'] == c['text'] == doc['text'][start:end]
            assert page['start'] <= start < end <= page['end']
            assert doc['text'][page['start']:page['end']] == page['text']
            units.append(dict(
                query_id=query['query_id'], gold_id=gid, query_text=query['query'], query_type=query['query_type'],
                document_scope=query['document_scope'], paper_id=gold['paper_id'], document_id=gold['document_id'],
                document_version=gold['document_version_id'], document_version_id=gold['document_version_id'],
                page=gold['page'], section=gold['section'], original_gold_chunk_id=gold['chunk_id'],
                original_gold_chunk_text=c['text'], original_gold_document_char_start=start, original_gold_document_char_end=end,
                authoritative_page_text=page['text'], authoritative_page_char_start=page['start'], authoritative_page_char_end=page['end'],
                suggested_locator_context=dict(document_id=gold['document_id'], document_version_id=gold['document_version_id'],
                    page=gold['page'], section=gold['section'], original_gold_page_char_start=start-page['start'], original_gold_page_char_end=end-page['start']),
                source_text_hash=doc['text_hash'], source_pdf_sha256=doc['source_sha256'],
                evidence_start=None, evidence_end=None, evidence_text=None, evidence_text_hash=None,
                document_char_start=None, document_char_end=None,
                reviewed_by_human=False, review_status='PENDING', reviewer_note='',
                normalization_version='nfc-whitespace-v1'))
    assert len(units) == 55 and {u['gold_id'] for u in units} == set(old_by_id)
    result = dict(schema_version='c1r-evidence-spans-v2', status='ANNOTATION_REQUIRED', annotation_layer='DERIVED',
        gold_unit_count=55, reviewed_count=0,
        source_dev_sha256=sha(B/'queries_dev.jsonl'), source_original_anchors_sha256=sha(B/'dev_gold_portable_anchors.json'),
        authoritative_source_sha256=sha(source_path),
        coordinate_system='Zero-based Unicode codepoints, half-open [start,end) in saved authoritative document text; not UTF-8 bytes or page-relative positions.',
        offset_field_contract='evidence_start/evidence_end are aliases of document_char_start/document_char_end; populate both consistently after exact-text resolution.',
        evidence_hash_contract='SHA-256 of exact raw evidence_text encoded as UTF-8, without Unicode or whitespace changes.',
        normalization_contract='nfc-whitespace-v1 is retained as provenance. Exact source text and raw offsets govern validation; normalized/fuzzy/partial matches cannot establish equivalence.',
        equivalence_rule='After human approval: identical document/version and source identity; candidate fully contains the exact reviewed evidence span (100%).',
        human_review_protocol=['Review all55 units independently of retrieval outcomes.',
          'Choose minimal jointly sufficient evidence for this unit from its original Gold text; do not infer missing facts from surrounding context.',
          'The span must be one exact contiguous substring wholly inside the original Gold chunk.',
          'Do not resize a span to fit a candidate chunk length.',
          'If no sufficient contiguous span exists inside the original Gold, mark NEEDS_DISCUSSION; do not expand it or change the Query/Gold.',
          'Return gold_id plus exact evidence_text and APPROVED or NEEDS_DISCUSSION. Offsets and hashes can then be calculated deterministically.',
          'Only explicit human decisions may set reviewed_by_human=true. No remapping or scoring before all55 approvals and validation.'],
        units=units)
    save(target,result)
    md=['# DEV Evidence Span Human Review','', 'Status: ANNOTATION_REQUIRED — 0/55 reviewed.','',
        '为每条 Query–Gold 单元选择必要且充分的最小连续原文。只允许位于该单元原始 Gold chunk 内，不可拼接、改写、修复连字符或换行。页文本只供理解上下文，不允许用它扩展 Gold 语义。',
        '', '可返回：`gold_id`、`APPROVED`、完整原样 `evidence_text`。之后可确定性计算 offset/hash；不要凭印象填写。若原 Gold 内没有充分连续文本，标记 `NEEDS_DISCUSSION` 并说明，不能自动扩展 Gold。',
        '', 'Offsets 使用权威 document text 的 Unicode codepoint 半开区间 [start,end)，不是页内偏移或 UTF-8 字节。全体55条均需人工确认；此文件不提供检索结果或候选切分信息。','']
    for u in units:
        md += ['## '+u['gold_id'],'', 'Query ID: '+u['query_id'], 'Query type: '+u['query_type'],
          'Question: '+u['query_text'], 'Document scope: '+str(u['document_scope']),
          f"Locator: {u['paper_id']} / document {u['document_id']} / immutable version {u['document_version_id']} / page {u['page']} / section {u['section']}",
          'Original Gold chunk: '+u['original_gold_chunk_id'],
          f"Original Gold document offsets: [{u['original_gold_document_char_start']}, {u['original_gold_document_char_end']})",
          '', '### Original Gold text', '', '```text', u['original_gold_chunk_text'],'```','',
          f"### Authoritative page text — document offsets [{u['authoritative_page_char_start']}, {u['authoritative_page_char_end']})",'',
          '```text',u['authoritative_page_text'],'```','',
          '### Human annotation','', '- evidence_start:','- evidence_end:','- evidence_text:','- review_status: PENDING','- reviewed_by_human: false','- Reviewer note:','']
    review.write_text('\n'.join(md)+'\n', encoding='utf-8')
    # Empty schemas only: no zero-valued placeholder measurements.
    for name, fields in [('c1r_gold_mapping_summary.csv',['config','mapped','unmapped','one','two','three_or_more','mean_multiplicity','median','max']),
                         ('c1r_rescored_metrics.csv',['config','path','Hit@5','R@5','R@10','MRR@10','CR@20','CR@30','CR@50'])]:
        p=B/name
        assert not p.exists(), 'Do not overwrite rescoring output'
        with p.open('w',encoding='utf-8',newline='') as f:csv.writer(f).writerow(fields)
    for name,digest in protected.items():assert sha(R/name)==digest,name
    pending_fields=('evidence_start','evidence_end','evidence_text','evidence_text_hash','document_char_start','document_char_end')
    assert all(all(u[k] is None for k in pending_fields) and not u['reviewed_by_human'] and u['review_status']=='PENDING' for u in units)
    forbidden=('hybrid_rank','candidate_rank','recovered','lost','metric_delta','benefiting_config')
    assert all(not any(k in json.dumps(u) for k in forbidden) for u in units)
    save(O/'summary.json',dict(status='ANNOTATION_REQUIRED',gold_units=55,reviewed=0,pending=55,exact_reviewed_spans=0,
        original_gold_source_recovery=dict(exact=55,unmapped=0,ambiguous=0),
        reviewed_span_validation='NOT_RUN_AWAITING_HUMAN_REVIEW',span_statistics=None,mapping=None,rescored_metrics=None,
        annotation_artifact=str(target.relative_to(R)).replace('\\','/'),review_artifact=str(review.relative_to(R)).replace('\\','/'),
        original_C1_claim='PROVISIONAL / INVALIDATED BY PORTABILITY AUDIT',original_B_CR50=0.9285714285714286,
        selected_candidate='BASE',chunking_conclusion='INCONCLUSIVE',ready_for_c2=False,ready_for_v2_d=False,
        protected_hashes=protected,integrity='PASS',ranking_content_read=False,retrieval_run=False,embedding_run=False,
        tests=dict(all55_present=True,original_gold_and_pages_exact=True,all_annotation_fields_pending=True,blind_payload=True,protected_bytes_unchanged=True)))
    print('Prepared55 exact-source units;0 reviewed; no mapping or rescoring performed.')

if __name__ == '__main__':
    main()
