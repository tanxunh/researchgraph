from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from app.schemas.real_benchmark import ResearchManifest
from app.services.evaluation.real_benchmark import validate_queries, evaluate
from app.services.indexing.incremental_indexer import IncrementalIndexer
from app.services.indexing.version_chunks import version_chunks
from app.services.parsing.text_parser import TextParser
from app.services.retrieval.retrieval_service import ResearchRetrievalService

pytestmark = pytest.mark.integration


def setup_case(db, store, extractor):
    imported = IncrementalIndexer(store, extractor).import_parsed(
        db, TextParser().parse('Fixture', 'Method Alpha USES Dataset Beta.', 'test:phase6'))
    chunk = version_chunks(db, imported['document_id'], imported['version'])[0]
    manifest = ResearchManifest(benchmark_version='engineering-test', corpus_kind='real_papers',
        documents=[dict(document_id=imported['document_id'], document_version_id=chunk.document_version_id,
                        title='Fixture', source_reference='test:phase6', path='test.txt', sha256='0'*64)], queries_path='test.jsonl')
    case = dict(query_id='q', question='Method Alpha', query_type='exact_term', language='en',
        gold_document_ids=[imported['document_id']], gold_evidence=[dict(document_id=imported['document_id'],
        document_version_id=chunk.document_version_id, chunk_id=chunk.stable_chunk_id,
        page=chunk.page_number, section=chunk.section_title)], annotation_status='human_reviewed',
        annotator='TEST FIXTURE ONLY', annotation_notes='Tests validation; not real Gold')
    return manifest, case


def test_gold_validation_and_unscored_denominator(integration_db, vector_store, rule_extractor):
    manifest, case = setup_case(integration_db, vector_store, rule_extractor)
    cases = [case]
    for field, value in [('document_version_id', 999999), ('chunk_id', 'missing'), ('page', 999)]:
        invalid = deepcopy(case)
        invalid['query_id'] = field
        invalid['gold_evidence'][0][field] = value
        cases.append(invalid)
    cases.append({**case, 'query_id': 'pending', 'annotation_status': 'pending'})
    cases.append({**case, 'query_id': 'empty', 'gold_evidence': []})
    rows = validate_queries(integration_db, manifest, cases, {})
    assert [r['valid'] for r in rows] == [True, False, False, False, False, False]
    reports = evaluate(rows, ResearchRetrievalService(integration_db, vector_store))
    assert reports['auto']['valid_scored_cases'] == 1 and reports['auto']['invalid_cases'] == 5
    assert reports['auto']['Candidate Recall@20'] == 1
    duplicate = validate_queries(integration_db, manifest, [case, case], {})
    assert all(r['invalid_reason'] == 'duplicate_query_id' for r in duplicate)


def test_disabled_baseline_and_enabled_evidence_identity(integration_db, vector_store, rule_extractor, monkeypatch):
    setup_case(integration_db, vector_store, rule_extractor)
    service = ResearchRetrievalService(integration_db, vector_store)
    import app.services.retrieval.reranker as module
    scorer = SimpleNamespace(score=Mock(return_value=[1.0]))
    monkeypatch.setattr(module, 'get_reranker', lambda settings: scorer)
    before = service.search('Method Alpha')
    explicit = service.search('Method Alpha', rerank=False)
    assert before['results'] == explicit['results'] and 'reranker' not in before
    scorer.score.assert_not_called()
    after = service.search('Method Alpha', rerank=True)
    assert after['results'][0]['chunk_id'] == before['results'][0]['chunk_id']
    assert after['results'][0]['document_version_id'] == before['results'][0]['document_version_id']
    from app.services.generation.evidence_builder import EvidenceBuilder
    assert EvidenceBuilder().build(after)[0].locator == EvidenceBuilder().build(before)[0].locator
    scorer.score.side_effect = RuntimeError('inference failed')
    fallback = service.search('Method Alpha', rerank=True)
    assert fallback['reranker']['reranker_failed'] and fallback['results'] == explicit['results']
