"""RG-003: base readiness with no Graph extraction or external API calls."""
from unittest.mock import Mock, AsyncMock
from types import SimpleNamespace
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select, func
from app.core.config import get_settings, Settings
from app.core.database import get_db
from app.models.document import Document, DocumentChunk
from app.models.relation import Relation
from app.api import search, qa
from app.core.llm_client import LLMClient
from app.services.graph.entity_extractor import EntityExtractor
from app.services.indexing.ingestion import DocumentIngestion
from app.services.indexing.incremental_indexer import IncrementalIndexer, IncrementalIndexError
from app.services.indexing.async_jobs import IndexWorker, enqueue, serialize
from app.services.retrieval.retrieval_service import ResearchRetrievalService
from app.services.graph.graph_search import GraphSearch

pytestmark = pytest.mark.integration

@pytest.fixture
def no_graph(integration_db, vector_store, monkeypatch):
    get_settings().graph_extraction_enabled = False
    extract = Mock(side_effect=AssertionError('Graph extraction must not run'))
    monkeypatch.setattr(EntityExtractor, 'extract', extract)
    ingestion = DocumentIngestion(IncrementalIndexer(vector_store))
    return integration_db, vector_store, ingestion, extract

def test_default_disabled(monkeypatch):
    monkeypatch.delenv('GRAPH_EXTRACTION_ENABLED')
    assert Settings(_env_file=None).graph_extraction_enabled is False

def test_disabled_import_update_reindex_and_job(no_graph, tmp_path):
    db, store, ingestion, extract = no_graph
    job = enqueue(db, dict(source_type='text', source_uri='optional:job', title='Study',
        content_type='text/plain', encoding='utf-8'), b'Method Alpha USES Dataset Beta.')
    worker = IndexWorker(db.get_bind(), ingestion_factory=lambda: ingestion, lock_root=tmp_path)
    assert worker.run_one()
    # End MySQL REPEATABLE READ snapshot before observing the worker's transaction.
    db.rollback()
    db.expire_all()
    result = serialize(db.get(type(job), job.id))
    assert result['status'] == 'succeeded'
    document = db.get(Document, result['document_id'])
    assert document.status == 'ready' and store.count() > 0
    assert store.verify_document_chunks(ingestion.indexer._chunks(db, document.id))
    assert db.scalar(select(func.count(Relation.id))) == 0
    assert db.scalar(select(DocumentChunk.graph_extractor_version)) == 'not-extracted'
    updated = ingestion.import_text(db, 'Study', 'Method Alpha USES Dataset Beta. New content.', 'optional:job')
    assert updated['status'] == 'ready' and updated['stats']['chunks_graphed'] == 0
    assert ingestion.indexer.reindex(db, document, 'full')['status'] == 'ready'
    with pytest.raises(IncrementalIndexError, match='disabled'):
        ingestion.indexer.reindex(db, document, 'graph_only')
    extract.assert_not_called()

def test_disabled_search_qa_and_graph_runtime(no_graph, monkeypatch):
    db, store, ingestion, extract = no_graph
    ingestion.import_text(db, 'Study', 'Method Alpha USES Dataset Beta.', 'optional:qa')
    retrieval = ResearchRetrievalService(db, store)
    for module in (search, qa):
        monkeypatch.setattr(module, 'ResearchRetrievalService', lambda db: retrieval)
    llm = AsyncMock(return_value='Method Alpha [C1].')
    monkeypatch.setattr(LLMClient, 'generate', llm)
    app = FastAPI(); app.include_router(search.router); app.include_router(qa.router)
    app.dependency_overrides[get_db] = lambda: db
    client = TestClient(app)
    for mode in ['hybrid', 'auto']:
        body = client.post('/api/search', json=dict(query='Which datasets does Method Alpha use?', mode=mode)).json()
        assert body['code'] == 0 and body['data']['results']
        assert body['data']['routing']['graph_enabled'] is False
        if mode == 'auto':
            assert body['data']['routing']['reason'] == 'graph_unavailable_hybrid_fallback'
    body = client.post('/api/qa', json=dict(question='Which datasets does Method Alpha use?')).json()
    assert body['code'] == 0 and body['data']['status'] == 'answered'
    llm.reset_mock()
    for endpoint, field in [('search', 'query'), ('qa', 'question')]:
        body = client.post('/api/'+endpoint, json={field:'Method Alpha', 'mode':'graph_enhanced'}).json()
        assert body['code'] == 1 and body['data']['error_type'] == 'graph_unavailable'
    llm.assert_not_called(); extract.assert_not_called()

def test_enabled_call_and_failure_semantics(integration_db, vector_store, rule_extractor):
    get_settings().graph_extraction_enabled = True
    extract = Mock(wraps=rule_extractor.extract)
    ingestion = DocumentIngestion(IncrementalIndexer(vector_store, SimpleNamespace(extract=extract)))
    result = ingestion.import_text(integration_db, 'Graph', 'Method Alpha USES Dataset Beta.', 'optional:enabled')
    assert result['status'] == 'ready' and extract.call_count == 1
    assert GraphSearch(integration_db).is_available()
    extract.side_effect = RuntimeError('test extraction failure')
    with pytest.raises(IncrementalIndexError):
        ingestion.import_text(integration_db, 'Failure', 'Method Alpha TARGETS Task Omega.', 'optional:failure')
    assert integration_db.scalar(select(func.count(Document.id))) == 1
    integration_db.get(Document, result['document_id']).status = 'publish_failed'
    integration_db.commit()
    assert not GraphSearch(integration_db).is_available()
