from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from app.services.retrieval.reranker import rerank_candidates, CrossEncoderReranker
from app.services.evaluation.real_benchmark import aggregate, evaluate, load_dataset


def candidates(n=20):
    return [{'chunk_id': str(i), 'text': f'evidence {i}', 'document': {'id': i+1, 'version_id': 1},
             'document_version_id': 1, 'scores': {'fusion_score': 1/(60+i)}} for i in range(n)]


def test_rerank_preserves_identity_and_original_scores_without_mutating_input():
    original = candidates()
    saved = deepcopy(original)
    result, meta = rerank_candidates('q', original, SimpleNamespace(score=lambda q, t: list(range(len(t)))))
    assert not meta['reranker_failed']
    assert [r['chunk_id'] for r in result] == [str(i) for i in reversed(range(20))]
    assert original == saved
    for rank, item in enumerate(result, 1):
        source = original[int(item['chunk_id'])]
        assert {k: v for k, v in item.items() if k != 'scores'} == {k: v for k, v in source.items() if k != 'scores'}
        assert item['scores']['original_retrieval_score'] == source['scores']['fusion_score']
        assert item['scores']['fusion_score'] == source['scores']['fusion_score']
        assert item['scores']['reranked_rank'] == rank


@pytest.mark.parametrize('output', [[1], [float('nan')]*20, [float('inf')]*20, ['new-evidence']*20])
def test_invalid_scores_fallback(output):
    original = candidates()
    result, meta = rerank_candidates('q', original, SimpleNamespace(score=lambda q, t: output))
    assert result == original and meta['reranker_failed']


def test_load_and_inference_failure_observable(caplog):
    scorer = SimpleNamespace(score=Mock(side_effect=RuntimeError('private internal error')))
    original = candidates()
    result, meta = rerank_candidates('q', original, scorer)
    assert result == original and meta['failure_reason'] == 'RuntimeError'
    assert 'reranker_failed=true' in caplog.text and 'private internal error' not in caplog.text


def test_empty_candidates_do_not_load_model():
    scorer = Mock()
    assert rerank_candidates('q', [], scorer)[0] == []
    scorer.score.assert_not_called()


def row(kind='semantic', valid=True):
    return dict(query_id='q', question='q', query_type=kind, language='en', valid=valid,
                invalid_reason=None if valid else 'empty_gold', gold_evidence=[],
                relevant_chunk_ids=['0', '19'], returned_chunk_ids=[], latency_ms=None)


def test_candidate_recall_and_breakdown_and_routing_use_same_auto_candidates():
    retrieval = SimpleNamespace(search=Mock(return_value={'results': candidates(),
        'routing': {'query_type': 'relational', 'effective_mode': 'graph_enhanced', 'graph_enabled': True}}))
    result = evaluate([row(), row('multi_hop', False)], retrieval,
                      SimpleNamespace(score=lambda q, t: list(range(len(t)))))
    for mode in result.values():
        assert mode['Candidate Recall@20'] == 1
        assert mode['Recall@5'] == .5
        assert mode['valid_scored_cases'] == 1 and mode['invalid_cases'] == 1
        assert mode['category_metrics']['semantic']['count'] == 1
        assert mode['category_metrics']['multi_hop']['valid_scored_cases'] == 0
        assert mode['category_metrics']['factual']['count'] == 0
        assert mode['graph_activation_rate'] == 1
    assert retrieval.search.call_count == 4
    assert result['auto']['query_diagnostics'][0]['candidate_chunk_ids'] == result['auto_reranker']['query_diagnostics'][0]['candidate_chunk_ids']
    assert result['auto_reranker']['query_diagnostics'][0]['returned_chunk_ids'][0] == '19'


def test_candidate_recall_strict_cutoff_twenty():
    r = {**row(), 'candidate_chunk_ids': [str(i) for i in range(21)], 'relevant_chunk_ids': ['0', '20']}
    assert aggregate([r])['Candidate Recall@20'] == .5


def test_manifest_path_and_hash_validation(tmp_path):
    import json
    source = tmp_path / 'paper.txt'
    source.write_text('engineering fixture, not a paper')
    (tmp_path / 'queries.jsonl').write_text('{bad json}\n')
    manifest = {'benchmark_version': 'test', 'corpus_kind': 'real_papers', 'queries_path': 'queries.jsonl',
                'documents': [{'document_id': 1, 'document_version_id': 1, 'title': 'test',
                'source_reference': 'test:only', 'path': 'paper.txt', 'sha256': '0'*64}]}
    path = tmp_path / 'manifest.json'
    path.write_text(json.dumps(manifest))
    _, raw, errors, _ = load_dataset(path)
    assert len(raw) == 1 and errors[1] == 'corpus_hash_mismatch'
    manifest['queries_path'] = '../outside.jsonl'
    path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match='outside_root'):
        load_dataset(path)


def test_cross_encoder_adapter_load_once_and_predict_contract(monkeypatch):
    import sys
    factory = Mock()
    factory.return_value.predict.return_value = SimpleNamespace(tolist=lambda: [0.2, 0.9])
    monkeypatch.setitem(sys.modules, 'sentence_transformers', SimpleNamespace(CrossEncoder=factory))
    model = CrossEncoderReranker('model', 'revision', 'cpu', '/cache', True)
    assert model.score('query', ['a', 'b']) == [.2, .9]
    model.load()
    factory.assert_called_once_with('model', revision='revision', device='cpu', cache_dir='/cache',
                                    local_files_only=True, max_length=512, trust_remote_code=False)
    assert model.cold_load_ms is not None
    factory.return_value.predict.assert_called_once_with([('query', 'a'), ('query', 'b')],
                                                         batch_size=8, show_progress_bar=False)


def test_cross_encoder_load_failure_is_cached_and_falls_back(monkeypatch):
    import sys
    factory = Mock(side_effect=OSError('missing weights'))
    monkeypatch.setitem(sys.modules, 'sentence_transformers', SimpleNamespace(CrossEncoder=factory))
    model = CrossEncoderReranker('model', 'revision', 'cpu', '/cache', True)
    for _ in range(2):
        result, metadata = rerank_candidates('q', candidates(), model)
        assert result == candidates() and metadata['reranker_failed']
    assert factory.call_count == 1 and model.cold_load_ms is not None


def test_empty_real_runner_emits_data_required_without_model_or_database(tmp_path):
    import subprocess
    import sys
    import json
    output = tmp_path / 'empty_report'
    subprocess.run([sys.executable, '-m', 'scripts.run_real_retrieval_benchmark',
                    '--output', str(output)], check=True, timeout=30)
    report = json.loads(output.with_suffix('.json').read_text())
    assert report['status'] == 'REAL_BENCHMARK_DATA_REQUIRED'
    assert report['corpus_size'] == report['query_count'] == report['valid_queries'] == 0
    assert report['modes'] == {} and report['timing']['reranker_cold_load_ms'] is None
    assert all(v == 0 for v in report['query_type_distribution'].values())
    assert output.with_suffix('.md').is_file()


def test_pilot_only_baselines_and_same_hybrid_candidates():
    retrieval = SimpleNamespace(search=Mock(return_value={'results': candidates()}))
    result = evaluate([row()], retrieval, SimpleNamespace(score=lambda q, t: list(range(len(t)))),
                      baseline_modes=('bm25', 'dense', 'hybrid'), rerank_mode='hybrid')
    assert set(result) == {'bm25', 'dense', 'hybrid', 'hybrid_reranker'}
    assert [c.kwargs['mode'] for c in retrieval.search.call_args_list] == ['bm25', 'dense', 'hybrid']
    base = result['hybrid']['query_diagnostics'][0]
    paired = result['hybrid_reranker']['query_diagnostics'][0]
    assert base['candidate_chunk_ids'] == paired['candidate_chunk_ids']
    assert paired['returned_chunk_ids'] == list(reversed(base['candidate_chunk_ids']))[:10]
    assert result['hybrid']['Candidate Recall@20'] == result['hybrid_reranker']['Candidate Recall@20'] == 1
    assert result['hybrid']['Recall@10'] == .5


def test_document_hit_is_not_evidence_hit():
    r = row()
    r['relevant_chunk_ids'] = ['different-chunk-from-same-document']
    result = evaluate([r], SimpleNamespace(search=Mock(return_value={'results': candidates()})),
                      baseline_modes=('bm25',))
    assert result['bm25']['HitRate@5'] == result['bm25']['Candidate Recall@20'] == 0


def test_frozen_pilot_projection_preserves_gold_and_bytes(tmp_path):
    import json
    import hashlib
    from scripts.run_pilot_ablation import load_pilot
    paper = tmp_path / 'paper.pdf'
    paper.write_bytes(b'fixture only')
    doc = dict(benchmark_document_id='P001', document_id=1, document_version_id=2, title='fixture',
               source_filename='paper.pdf', source_sha256=hashlib.sha256(paper.read_bytes()).hexdigest())
    gold = dict(benchmark_document_id='P001', document_id=1, document_version_id=2,
                chunk_id='chunk-x', page=3, section=None)
    q = dict(query_id='Q001', question='unchanged question?', query_type='semantic', language='en',
             gold_document_ids=['P001'], gold_evidence=[gold], annotation_status='HUMAN_APPROVED', annotator='human')
    frozen = dict(benchmark_id='test', status='FINALIZED', annotation_source='HUMAN_CURATED',
                  queries=[q], query_count=1, corpus={'paper_count': 1})
    path = tmp_path / 'pilot.json'
    path.write_text(json.dumps(frozen))
    manifest = tmp_path / 'manifest.json'
    manifest.write_text(json.dumps({'documents': [doc]}))
    before = path.read_bytes()
    _, _, rows = load_pilot(path, manifest, tmp_path)
    assert rows[0]['question'] == q['question'] and rows[0]['query_type'] == q['query_type']
    assert rows[0]['gold_evidence'] == [{k: v for k, v in gold.items() if k != 'benchmark_document_id'}]
    assert path.read_bytes() == before
    gold['document_version_id'] = 999
    path.write_text(json.dumps(frozen))
    with pytest.raises(ValueError, match='identity mismatch'):
        load_pilot(path, manifest, tmp_path)
