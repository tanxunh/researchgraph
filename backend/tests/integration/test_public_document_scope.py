"""Public scope through existing retrieval, without external LLM calls."""
from unittest.mock import AsyncMock, Mock
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.api import search, qa
from app.core.database import get_db
from app.core.llm_client import LLMClient
from app.models.document import Document
from app.services.indexing.ingestion import DocumentIngestion
from app.services.indexing.incremental_indexer import IncrementalIndexer
from app.services.retrieval.retrieval_service import ResearchRetrievalService

pytestmark = pytest.mark.integration

@pytest.fixture
def scoped_api(integration_db, vector_store, rule_extractor, monkeypatch):
    ingestion = DocumentIngestion(IncrementalIndexer(vector_store, rule_extractor))
    ids = [ingestion.import_text(integration_db, f'Paper {i}',
        f'Method Alpha evidence experiment {i}.', f'scope:{i}')['document_id'] for i in range(3)]
    retrieval = ResearchRetrievalService(integration_db, vector_store)
    for module in (search, qa):
        monkeypatch.setattr(module, 'ResearchRetrievalService', lambda db: retrieval)
    app = FastAPI()
    app.include_router(search.router)
    app.include_router(qa.router)
    app.dependency_overrides[get_db] = lambda: integration_db
    llm = AsyncMock(return_value='Method Alpha [C1].')
    monkeypatch.setattr(LLMClient, 'generate', llm)
    return TestClient(app), ids, integration_db, llm

@pytest.mark.parametrize('mode', ['vector', 'hybrid', 'auto'])
def test_filter_before_top_k(scoped_api, mode):
    client, ids, db, llm = scoped_api
    request = dict(query='Method Alpha', mode=mode, top_k=1)
    def run(**extra):
        body = client.post('/api/search', json=request | extra).json()
        assert body['code'] == 0, body
        return body['data']
    global_result = run()
    assert run(document_ids=None)['results'] == global_result['results']
    first = global_result['results'][0]['document']['id']
    outside = next(i for i in ids if i != first)
    assert [r['document']['id'] for r in run(document_ids=[outside])['results']] == [outside]
    pair = run(document_ids=ids[:2])['results']
    assert pair and all(r['document']['id'] in ids[:2] for r in pair)

@pytest.mark.parametrize('size', [1, 2])
def test_qa_scope_citations(scoped_api, size):
    client, ids, db, llm = scoped_api
    body = client.post('/api/qa', json=dict(question='Method Alpha', document_ids=ids[:size])).json()
    assert body['code'] == 0, body
    result = body['data']
    assert result['status'] == 'answered' and result['citations']
    assert all(c['document_id'] in ids[:size] for c in result['citations'])
    assert all(r['document']['id'] in ids[:size] for r in result['search']['results'])
    llm.assert_awaited_once()

@pytest.mark.parametrize('kind', ['empty', 'missing', 'deleted', 'not_ready'])
def test_no_eligible_scope_no_fallback(scoped_api, kind):
    client, ids, db, llm = scoped_api
    scope = [] if kind == 'empty' else [999999] if kind == 'missing' else [ids[0]]
    if kind in {'deleted', 'not_ready'}:
        db.get(Document, ids[0]).status = 'deleted' if kind == 'deleted' else 'publish_failed'
        db.commit()
    body = client.post('/api/search', json=dict(query='Method Alpha', document_ids=scope)).json()
    assert body['code'] == 1
    assert body['data']['error_type'] == ('empty_document_scope' if kind == 'empty' else 'no_eligible_documents')
    body = client.post('/api/qa', json=dict(question='Method Alpha', document_ids=scope)).json()
    assert body['code'] == 0 and body['data']['status'] == 'insufficient_evidence'
    assert body['data']['citations'] == []
    llm.assert_not_called()

def test_scoped_graph_rejected(scoped_api):
    client, ids, db, llm = scoped_api
    for endpoint, field in [('search', 'query'), ('qa', 'question')]:
        assert client.post(f'/api/{endpoint}', json={field: 'Method Alpha', 'mode': 'graph_enhanced', 'document_ids': ids}).status_code == 422
    llm.assert_not_called()


@pytest.mark.parametrize('kind', ['empty', 'missing', 'not_ready', 'no_current_version'])
def test_ineligible_never_constructs_retrieval(scoped_api, monkeypatch, kind):
    client, ids, db, _ = scoped_api
    scope = [] if kind == 'empty' else [999999] if kind == 'missing' else [ids[0]]
    if kind == 'not_ready':
        db.get(Document, ids[0]).status = 'publish_failed'
    if kind == 'no_current_version':
        db.get(Document, ids[0]).current_version = 99999
    db.commit()
    constructor = Mock(side_effect=AssertionError('Retrieval must not be called'))
    monkeypatch.setattr(search, 'ResearchRetrievalService', constructor)
    response = client.post('/api/search', json={'query': 'Alpha', 'document_ids': scope})
    assert response.status_code == (422 if kind == 'empty' else 200)
    body = response.json()
    assert body['code'] == 1
    assert body['data']['error_type'] == ('empty_document_scope' if kind == 'empty' else 'no_eligible_documents')
    assert body['data']['scope']['eligible_document_ids'] == []
    constructor.assert_not_called()


@pytest.mark.parametrize('kind', ['ready', 'not_ready', 'missing'])
def test_eligibility_metadata_and_pre_retrieval_filter(scoped_api, monkeypatch, kind):
    client, ids, db, _ = scoped_api
    requested = [ids[0]]
    excluded = []
    if kind == 'not_ready':
        db.get(Document, ids[1]).status = 'publish_failed'
        db.commit()
        requested.append(ids[1])
        excluded = [{'document_id': ids[1], 'reason': 'not_ready'}]
    elif kind == 'missing':
        requested.append(999999)
        excluded = [{'document_id': 999999, 'reason': 'not_found'}]
    retrieval = search.ResearchRetrievalService(db)
    spy = Mock(wraps=retrieval.search)
    monkeypatch.setattr(retrieval, 'search', spy)
    response = client.post('/api/search', json={'query': 'Method Alpha', 'mode': 'hybrid', 'document_ids': requested}).json()
    assert response['code'] == 0
    data = response['data']
    assert data['scope'] == {'mode': 'explicit', 'requested_document_ids': requested,
                             'eligible_document_ids': [ids[0]], 'excluded_documents': excluded}
    assert spy.call_args.kwargs['document_ids'] == [ids[0]]
    assert data['results'] and all(r['document']['id'] == ids[0] for r in data['results'])
    # Public wrapper must not change any Evidence fields or ranking.
    baseline = spy('Method Alpha', mode='hybrid', top_k=10, document_ids=[ids[0]])
    assert data['results'] == baseline['results']


@pytest.mark.parametrize('explicit_null', [False, True])
def test_global_metadata_preserves_request_and_evidence(scoped_api, monkeypatch, explicit_null):
    client, ids, db, _ = scoped_api
    retrieval = search.ResearchRetrievalService(db)
    baseline = retrieval.search('Method Alpha', mode='hybrid', top_k=10)
    spy = Mock(wraps=retrieval.search)
    monkeypatch.setattr(retrieval, 'search', spy)
    request = {'query': 'Method Alpha', 'mode': 'hybrid'}
    if explicit_null:
        request['document_ids'] = None
    data = client.post('/api/search', json=request).json()['data']
    assert data['scope'] == {'mode': 'global'}
    assert spy.call_args.kwargs['document_ids'] is None
    assert data['results'] == baseline['results']


def test_eligible_but_no_hits_is_success(scoped_api, monkeypatch):
    client, ids, db, _ = scoped_api
    retrieval = search.ResearchRetrievalService(db)
    monkeypatch.setattr(retrieval, 'search', Mock(return_value={'results': []}))
    body = client.post('/api/search', json={'query': 'no match', 'document_ids': [ids[0]]}).json()
    assert body['code'] == 0 and body['data']['results'] == []
    assert body['data']['scope']['eligible_document_ids'] == [ids[0]]
