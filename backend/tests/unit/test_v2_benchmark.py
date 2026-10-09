from app.schemas.real_benchmark import V2ResearchQuery
from app.services.evaluation.v2_benchmark import (
    aggregate,
    candidate_diagnostics,
    raw_union,
)


def query_payload(**overrides):
    value = {
        'query_id': 'V2Q001',
        'query': 'What is optimized?',
        'query_type': 'factual',
        'document_scope': [1],
        'gold_evidence': [{
            'paper_id': 'P001',
            'document_id': 1,
            'document_version_id': 2,
            'chunk_id': 'doc-1-chunk-gold',
            'page': 1,
            'section': None,
        }],
        'human_verified': False,
        'notes': 'DEV draft',
    }
    value.update(overrides)
    return value


def test_v2_query_contract_exposes_explicit_scope():
    row = V2ResearchQuery.model_validate(query_payload())
    assert row.scoped_document_ids == [1]
    assert V2ResearchQuery.model_validate(query_payload(document_scope='global')).scoped_document_ids is None


def test_raw_union_keeps_each_retrievers_top_k_and_deduplicates():
    assert raw_union(['A', 'B', 'C'], ['B', 'D', 'E'], 2) == ['A', 'B', 'D']


def test_aggregate_uses_fractional_multi_gold_candidate_recall():
    case = {
        'valid': True,
        'returned_chunk_ids': ['A'],
        'candidate_chunk_ids': ['A'] + [f'X{i}' for i in range(49)],
        'relevant_chunk_ids': ['A', 'B'],
        'latency_ms': 10.0,
        'retrieval_latency_ms': 8.0,
        'reranker_latency_ms': 2.0,
    }
    metrics = aggregate([case])
    assert metrics['Recall@10'] == 0.5
    assert metrics['Candidate Recall@20'] == 0.5
    assert metrics['Candidate Recall@50'] == 0.5
    assert metrics['reranker_latency_ms'] == {'p50': 2.0, 'p95': 2.0}


def test_candidate_diagnostics_distinguish_union_from_rrf():
    base = {
        'query_id': 'V2Q001',
        'query_type': 'factual',
        'valid': True,
        'relevant_chunk_ids': ['G'],
    }
    cases = {
        'bm25': [{**base, 'candidate_chunk_ids': ['B', 'G']}],
        'dense': [{**base, 'candidate_chunk_ids': ['D']}],
        'hybrid': [{**base, 'candidate_chunk_ids': ['B', 'D']}],
    }
    metrics = candidate_diagnostics(cases)['at_k']['10']
    assert metrics['BM25 Recall'] == 1.0
    assert metrics['UNION Recall'] == 1.0
    assert metrics['RRF Recall'] == 0.0
