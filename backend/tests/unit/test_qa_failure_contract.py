from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import qa as qa_api
from app.api import documents as document_api
from app.core.database import get_db
from app.core.llm_client import LLMClient, LLMClientError
from app.services.generation import grounded_answer_service as grounded_service
from app.services.generation.grounded_answer_service import GroundedAnswerService


def evidence():
    return {"chunk_id": "valid", "text": "Method Alpha uses Dataset Beta.",
            "document_version_id": 11, "source_type": "text", "source_snapshot_available": True,
            "document": {"id": 1, "title": "Study", "source_uri": "test:study", "version": 1, "version_id": 11},
            "location": {"page_number": None, "section_title": "Body", "ordinal": 0}}


def client(monkeypatch, results):
    class Retrieval:
        def __init__(self, db):
            self.db = db
        def search(self, *args, **kwargs):
            return {"results": results}
    monkeypatch.setattr(qa_api, "ResearchRetrievalService", Retrieval)
    row = evidence()
    monkeypatch.setattr(grounded_service, "resolve_version_chunks", lambda db, locators: {
        (11, "valid"): {"document": row["document"], "version": {"id": 11},
                        "chunk_id": "valid", "text": row["text"], "location": row["location"]}
    })
    app = FastAPI()
    app.include_router(qa_api.router)
    app.include_router(document_api.router)
    app.dependency_overrides[get_db] = lambda: None
    return TestClient(app)


def test_missing_llm_configuration_is_api_failure(monkeypatch):
    response = client(monkeypatch, [evidence()]).post("/api/qa", json={"question": "Method Alpha"})
    body = response.json()
    assert body["code"] != 0
    assert body["data"]["error_type"] == "llm_configuration_error"
    assert "answer" not in body["data"]


@pytest.mark.parametrize("results", [[], [{"chunk_id": "orphan", "missing": True}],
                                   [{"chunk_id": "broken", "text": "Incomplete"}], [None]])
def test_no_valid_evidence_never_calls_llm(monkeypatch, results):
    generate = AsyncMock(side_effect=AssertionError("LLM must not run"))
    monkeypatch.setattr(LLMClient, "generate", generate)
    response = client(monkeypatch, results).post("/api/qa", json={"question": "Method Alpha"})
    body = response.json()
    assert body["code"] == 0 and body["data"]["status"] == "insufficient_evidence"
    assert body["data"]["citations"] == [] and body["data"]["search"]["results"] == []
    generate.assert_not_called()


@pytest.mark.parametrize("error_type", ["llm_timeout", "llm_network_error", "invalid_model_response", "llm_provider_error"])
def test_llm_failures_have_distinct_api_contract(monkeypatch, error_type):
    monkeypatch.setattr(LLMClient, "generate", AsyncMock(side_effect=LLMClientError("Safe failure.", error_type)))
    body = client(monkeypatch, [evidence()]).post("/api/qa", json={"question": "Method Alpha"}).json()
    assert body == {"code": 1, "message": "Safe failure.", "data": {"error_type": error_type}}


def test_successful_answer_contract(monkeypatch):
    monkeypatch.setattr(LLMClient, "generate", AsyncMock(return_value="Method Alpha uses Dataset Beta [C1]."))
    body = client(monkeypatch, [evidence()]).post("/api/qa", json={"question": "Method Alpha"}).json()
    assert body["code"] == 0 and body["data"]["status"] == "answered"
    assert body["data"]["citations"][0]["document"]["id"] == 1


@pytest.mark.parametrize("answer", ["Invalid [C999]", "No citation", "Malformed [C01]"])
def test_citation_failure_is_business_error_without_answer(monkeypatch, answer):
    monkeypatch.setattr(LLMClient, "generate", AsyncMock(return_value=answer))
    body = client(monkeypatch, [evidence()]).post("/api/qa", json={"question": "Method Alpha"}).json()
    assert body["code"] == 1
    assert body["data"]["error_type"] == "citation_validation_failed"
    assert not body["data"]["citation_validation"]["valid"]
    assert "answer" not in body["data"]


def test_retrieval_infrastructure_error_is_safe_failure(monkeypatch):
    api = client(monkeypatch, [])
    monkeypatch.setattr(qa_api.ResearchRetrievalService, "search", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("sensitive-internal-value")))
    body = api.post("/api/qa", json={"question": "Method Alpha"}).json()
    assert body["code"] == 1 and body["data"]["error_type"] == "retrieval_error"
    assert "sensitive-internal-value" not in str(body)


@pytest.mark.parametrize("payload", [{}, {"choices": []}, {"choices": [{"message": {"content": ""}}]}])
def test_invalid_llm_response_is_typed(payload):
    with pytest.raises(LLMClientError) as raised:
        LLMClient()._extract_content(payload)
    assert raised.value.error_type == "invalid_model_response"


@pytest.mark.asyncio
@pytest.mark.parametrize("failure,expected", [
    (httpx.ReadTimeout("timeout"), "llm_timeout"),
    (httpx.ConnectError("network"), "llm_network_error"),
    ("not-json", "invalid_model_response"),
])
async def test_actual_llm_client_classifies_transport_and_json(monkeypatch, failure, expected):
    llm = LLMClient()
    llm.settings.llm_api_key = "test-only-placeholder"
    original = httpx.AsyncClient
    def respond(request):
        if isinstance(failure, Exception):
            raise failure
        return httpx.Response(200, text=failure)
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: original(transport=httpx.MockTransport(respond), **kwargs))
    with pytest.raises(LLMClientError) as raised:
        await llm.generate("test")
    assert raised.value.error_type == expected


@pytest.mark.parametrize("filename", ["empty.txt", "empty.pdf"])
def test_parser_error_is_clean_http_400(monkeypatch, filename):
    api = client(monkeypatch, [])
    response = api.post("/api/documents/import/file", files={"file": (filename, b"", "application/octet-stream")})
    assert response.status_code == 400
    assert response.json()["code"] == 1
