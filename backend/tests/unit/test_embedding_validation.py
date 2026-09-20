from copy import deepcopy
from types import SimpleNamespace
import json
import pytest
from scripts import run_embedding_validation as run


def test_independent_collection_guard():
    run.check_isolation('zh', 'en', None)
    with pytest.raises(ValueError, match='NEW collection'):
        run.check_isolation('zh', 'zh', None)
    with pytest.raises(ValueError, match='NEW collection'):
        run.check_isolation('zh', 'en', object())


def fixture_store(monkeypatch):
    monkeypatch.setattr(run, 'EXPECTED', 2)
    chunks = [SimpleNamespace(stable_chunk_id='a', text='one'), SimpleNamespace(stable_chunk_id='b', text='two')]
    data = dict(ids=['b','a'], documents=['two','one'], metadatas=[{'id':'b'},{'id':'a'}], embeddings=[[0.,1.],[1.,0.]])
    store = SimpleNamespace(count=lambda:2, collection_name='en',
        collection=SimpleNamespace(metadata={'model':'en'}, get=lambda **kwargs:data),
        iter_id_batches=lambda:iter([['a','b']]), metadata_matches=lambda a,b:a==b,
        chunk_metadata=lambda c:[{'id':c[0].stable_chunk_id}])
    return store,chunks,data


def test_parity_checks_all_ids_text_metadata_dimensions_and_hash(monkeypatch):
    store,chunks,data=fixture_store(monkeypatch)
    before=run.snapshot_index(store,chunks,2)
    assert before['count']==2 and before['dimension']==2
    data['embeddings'][0]=[.1,.9]
    assert run.snapshot_index(store,chunks,2)['sha256'] != before['sha256']


@pytest.mark.parametrize('failure',['count','dimension','nonfinite','text','metadata','duplicate'])
def test_parity_rejects_invalid_index(monkeypatch,failure):
    store,chunks,data=fixture_store(monkeypatch)
    if failure=='count': store.count=lambda:1
    if failure=='dimension': data['embeddings'][0]=[1.]
    if failure=='nonfinite': data['embeddings'][0]=[float('nan'),1.]
    if failure=='text': data['documents'][0]='modified'
    if failure=='metadata': data['metadatas'][0]={'id':'wrong'}
    if failure=='duplicate': data['ids']=['a','a']
    with pytest.raises(ValueError): run.snapshot_index(store,chunks,2)


def test_gold_diff_only_changed_gold_references():
    old={'query_diagnostics':[dict(query_id='Q1',query_type='semantic', relevant_chunk_ids=['a','b'],candidate_chunk_ids=['a','x']),
                              dict(query_id='Q2',query_type='factual',relevant_chunk_ids=['c'],candidate_chunk_ids=['c'])]}
    new=deepcopy(old)
    new['query_diagnostics'][0]['candidate_chunk_ids']=['b','y']
    new['query_diagnostics'][1]['candidate_chunk_ids']=['c','z']
    assert run.gold_diff(old,new)==[dict(query_id='Q1',query_type='semantic',newly_recovered_gold=['b'],newly_lost_gold=['a'])]


def test_result_serialization_preserves_hash(tmp_path):
    from app.services.evaluation.real_benchmark import evaluate,write_report
    frozen=tmp_path/'frozen.json'
    frozen.write_text('{"question":"unchanged"}')
    before=run.sha(frozen)
    report=dict(status='TEST_ONLY',benchmark_sha256=before,modes=evaluate([],None,baseline_modes=('dense','hybrid')))
    write_report(report,tmp_path/'result')
    saved=json.loads((tmp_path/'result.json').read_text())
    assert saved['benchmark_sha256']==run.sha(frozen)==before
    assert set(saved['modes'])=={'dense','hybrid'}
    assert (tmp_path/'result.md').is_file()
