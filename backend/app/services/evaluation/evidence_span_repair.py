"""C1R exact reviewed spans. No semantic annotation or partial-coverage fallback."""
import hashlib


def resolve_approved_span(unit, decision, anchor, document):
    text = decision.get('evidence_text')
    if decision.get('review_status') != 'APPROVED' or not isinstance(text, str) or not text:
        raise ValueError('missing_approved_nonempty_text')
    if unit.get('evidence_text') not in (None, '', text):
        raise ValueError('approval_annotation_text_conflict')
    if unit['gold_id'] != decision['gold_id'] or unit['gold_id'] != anchor['anchor_id']:
        raise ValueError('gold_identity_mismatch')
    for field in ('document_id', 'document_version_id', 'page', 'original_gold_chunk_id'):
        if unit[field] != anchor[field]:
            raise ValueError(field + '_mismatch')
    if unit['document_version'] != anchor['document_version_id'] or document['document_version_id'] != anchor['document_version_id']:
        raise ValueError('document_version_mismatch')
    if document['document_id'] != anchor['document_id'] or document['text_hash'] != anchor['source_text_hash']:
        raise ValueError('source_identity_mismatch')
    original = anchor['anchor_text']
    positions = []
    pos = original.find(text)
    while pos >= 0:
        positions.append(pos)
        pos = original.find(text, pos + 1)
    if len(positions) != 1:
        raise ValueError(f'exact_match_count={len(positions)};locations={positions}')
    start = anchor['document_char_start'] + positions[0]
    end = start + len(text)
    if not anchor['document_char_start'] <= start < end <= anchor['document_char_end']:
        raise ValueError('outside_original_gold')
    if document['text'][start:end] != text:
        raise ValueError('source_text_mismatch')
    values = dict(evidence_start=start, evidence_end=end, document_char_start=start,
                  document_char_end=end, evidence_text_hash=hashlib.sha256(text.encode('utf-8')).hexdigest())
    for key, value in values.items():
        if unit.get(key) is not None and unit[key] != value:
            raise ValueError(key + '_mismatch')
    return dict(unit, **values, evidence_text=text, reviewed_by_human=True,
                review_status='APPROVED')


def fully_contains(span, chunk):
    if span.get('review_status') != 'APPROVED' or span.get('reviewed_by_human') is not True:
        raise ValueError('human_approval_required')
    if any(span[k] != chunk[k] for k in ('document_id', 'document_version_id', 'source_text_hash')):
        return False
    a, b = span['document_char_start'], span['document_char_end']
    c, d = chunk['document_char_start'], chunk['document_char_end']
    return c <= a < b <= d and chunk['text'][a-c:b-c] == span['evidence_text']
