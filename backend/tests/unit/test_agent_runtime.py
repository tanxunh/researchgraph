import asyncio
import json
import time
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from pydantic import BaseModel, ConfigDict

from app.core.llm_client import LLMClientError
from app.services.runtime.contracts import AgentRuntimeError, ExecutionBudget
from app.services.runtime.runtime import AgentRuntime
from app.services.runtime.tools import ToolRegistry, SearchInput, ResolveInput
from app.schemas.research import EvidenceLocator


class Answer(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    answer: str


def runtime(client=None, search=None, resolve=None, **budget):
    registry = ToolRegistry(SimpleNamespace(search=search or (lambda *a, **k: {"results": []})),
                            resolve or (lambda keys: {}))
    return AgentRuntime("test-run", client or SimpleNamespace(generate=AsyncMock(return_value='{"answer":"ok"}')),
                        registry, budget=ExecutionBudget(**budget), model_name="mock")


def payload():
    return SearchInput(query="method", document_scope=[1], top_k=5)


@pytest.mark.asyncio
async def test_structured_and_text_counters_usage_and_trace():
    r = runtime()
    with r.node("plan_task"):
        result = await r.model.invoke_structured(Answer, "secret prompt", operation="plan")
    assert result.answer == "ok"
    await r.model.invoke_text("other secret", operation="synthesize")
    summary = r.finish("completed")
    assert summary.model_calls == 2 and summary.retries == 0
    assert [e.event_type for e in r.context.trace] == [
        "run_started", "node_started", "model_call", "node_finished", "model_call", "run_finished"]
    model_events = [e for e in r.context.trace if e.event_type == "model_call"]
    assert [e.structured for e in model_events] == [True, False]
    assert all(e.input_tokens is None and e.output_tokens is None for e in model_events)


@pytest.mark.asyncio
@pytest.mark.parametrize("persistent", [False, True])
async def test_transient_model_retry_exactly_once(persistent):
    err = LLMClientError("SECRET provider detail", "llm_network_error")
    client = SimpleNamespace(generate=AsyncMock(side_effect=[err, err if persistent else '{"answer":"ok"}']))
    r = runtime(client)
    if persistent:
        with pytest.raises(AgentRuntimeError, match="model_transient_error"):
            await r.model.invoke_structured(Answer, "private", operation="plan")
    else:
        assert (await r.model.invoke_structured(Answer, "private", operation="plan")).answer == "ok"
    assert client.generate.await_count == r.context.model_calls == 2
    assert r.context.retry_count == 1
    assert [e.attempt for e in r.context.trace if e.event_type == "model_call"] == [1, 2]
    assert "SECRET" not in r.context.model_dump_json()


@pytest.mark.asyncio
@pytest.mark.parametrize("raw", ['{}', 'not json', '{"answer":2}', ''])
async def test_invalid_output_never_retried(raw):
    client = SimpleNamespace(generate=AsyncMock(return_value=raw)); r = runtime(client)
    with pytest.raises(AgentRuntimeError, match="model_output_invalid"):
        await r.model.invoke_structured(Answer, "prompt", operation="plan")
    assert client.generate.await_count == 1 and r.context.retry_count == 0


@pytest.mark.asyncio
async def test_async_model_timeout_is_bounded_and_typed():
    client = SimpleNamespace(generate=AsyncMock(side_effect=lambda *a, **k: None))
    async def slow(*a, **k):
        await asyncio.sleep(10)
    client.generate.side_effect = slow
    r = runtime(client); r.model.timeout = .005
    with pytest.raises(AgentRuntimeError, match="model_timeout"):
        await r.model.invoke_text("private", operation="plan")
    assert r.context.model_calls == 2 and r.context.retry_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("status,retries", [(503, 1), (401, 0), (400, 0)])
async def test_http_provider_retry_requires_transient_status(status, retries):
    response = httpx.Response(status, request=httpx.Request("POST", "https://example.invalid"))
    err = LLMClientError("secret", "llm_provider_error")
    err.__cause__ = httpx.HTTPStatusError("secret", request=response.request, response=response)
    r = runtime(SimpleNamespace(generate=AsyncMock(side_effect=err)))
    with pytest.raises(AgentRuntimeError):
        await r.model.invoke_text("prompt", operation="plan")
    assert r.context.retry_count == retries and r.context.model_calls == 1 + retries


def test_registered_empty_search_and_unknown_tool():
    r = runtime()
    assert r.tools.execute("search_evidence", payload()).root == []
    assert r.context.tool_calls == r.context.retrieval_calls == 1
    for name in ["shell", "python", "SECRET/unregistered"]:
        with pytest.raises(AgentRuntimeError, match="tool_not_found"):
            r.tools.execute(name, {})
    assert r.context.tool_calls == 1
    assert "SECRET" not in r.context.model_dump_json()


def test_invalid_input_does_not_execute_handler():
    calls = []
    r = runtime(search=lambda *a, **k: calls.append(k))
    with pytest.raises(AgentRuntimeError, match="tool_input_invalid"):
        r.tools.execute("search_evidence", {"query": "x", "top_k": "5"})
    assert calls == [] and r.context.tool_calls == 0


def test_invalid_tool_output_is_typed_without_retry():
    r = runtime()
    definition = r.tools.registry.get("search_evidence")
    r.tools.registry._definitions = {"search_evidence": replace(definition, handler=lambda data: ["invalid"])}
    with pytest.raises(AgentRuntimeError, match="tool_output_invalid"):
        r.tools.execute("search_evidence", payload())
    assert r.context.tool_calls == 1 and r.context.retry_count == 0


def test_sync_tool_timeout_waits_for_completion_no_abandoned_thread():
    calls = []
    def slow(*a, **k):
        calls.append("start"); time.sleep(.005); calls.append("end")
        return {"results": []}
    r = runtime(search=slow); r.tools.timeout = .001
    with pytest.raises(AgentRuntimeError, match="tool_timeout"):
        r.tools.execute("search_evidence", payload())
    assert calls == ["start", "end", "start", "end"] and r.context.tool_calls == 2


@pytest.mark.parametrize("persistent", [False, True])
def test_transient_tool_retry_only_once(persistent):
    calls = []
    def search(*a, **k):
        calls.append(1)
        if persistent or len(calls) == 1:
            raise ConnectionError("SECRET")
        return {"results": []}
    r = runtime(search=search)
    if persistent:
        with pytest.raises(AgentRuntimeError, match="tool_transient_error"):
            r.tools.execute("search_evidence", payload())
    else:
        assert r.tools.execute("search_evidence", payload()).root == []
    assert len(calls) == 2 and r.context.retry_count == 1


def test_internal_and_business_tool_failures_not_retried():
    for failure, code in [(ValueError("secret"), "tool_business_error"), (RuntimeError("secret"), "tool_internal_error")]:
        def fail(*a, **k):
            raise failure
        r = runtime(search=fail)
        with pytest.raises(AgentRuntimeError, match=code):
            r.tools.execute("search_evidence", payload())
        assert r.context.tool_calls == 1 and r.context.retry_count == 0


def test_historical_resolution_preserves_version_and_rejects_substitution():
    row = dict(document={"id": 1}, version={"id": 7}, chunk_id="old", text="old source",
               location={"ordinal": 0, "page_number": 1, "section_title": None})
    seen = []
    def resolve(keys):
        seen.append(keys)
        return {(7, "old"): row}
    r = runtime(resolve=resolve)
    p = ResolveInput(locators=[EvidenceLocator(document_id=1, document_version_id=7, chunk_id="old")])
    assert r.tools.execute("resolve_evidence", p).root[0].version.id == 7
    assert seen == [[(7, "old")]] and r.context.retrieval_calls == 0
    row["version"]["id"] = 8
    with pytest.raises(AgentRuntimeError, match="tool_output_invalid"):
        r.tools.execute("resolve_evidence", p)


@pytest.mark.asyncio
async def test_model_limit_counts_attempts_and_stops_retry():
    client = SimpleNamespace(generate=AsyncMock(side_effect=ConnectionError("secret")))
    r = runtime(client, max_model_calls=1)
    with pytest.raises(AgentRuntimeError, match="budget_exceeded"):
        await r.model.invoke_text("prompt", operation="plan")
    assert r.context.model_calls == 1 and r.context.retry_count == 0
    assert r.finish("failed", "budget_exceeded").budget_exceeded
    assert any(e.event_type == "budget_exceeded" for e in r.context.trace)


@pytest.mark.parametrize("budget", [{"max_tool_calls": 1}, {"max_retrieval_calls": 1}])
def test_tool_and_retrieval_budgets_stop_later_handlers(budget):
    calls = []
    def search(*a, **k):
        calls.append(1); return {"results": []}
    r = runtime(search=search, **budget)
    r.tools.execute("search_evidence", payload())
    with pytest.raises(AgentRuntimeError, match="budget_exceeded"):
        r.tools.execute("search_evidence", payload())
    assert len(calls) == r.context.tool_calls == r.context.retrieval_calls == 1


@pytest.mark.asyncio
async def test_elapsed_deadline_prevents_new_model_and_tool_calls():
    r = runtime(max_runtime_seconds=.01)
    r.context.started_clock -= 1
    with pytest.raises(AgentRuntimeError, match="budget_exceeded"):
        await r.model.invoke_text("prompt", operation="plan")
    with pytest.raises(AgentRuntimeError, match="budget_exceeded"):
        r.tools.execute("search_evidence", payload())
    assert r.context.model_calls == r.context.tool_calls == 0


@pytest.mark.asyncio
async def test_deadline_during_model_stops_without_retry():
    async def slow(*a, **k):
        await asyncio.sleep(10)
    r = runtime(SimpleNamespace(generate=slow), max_runtime_seconds=.005)
    with pytest.raises(AgentRuntimeError, match="budget_exceeded"):
        await r.model.invoke_text("prompt", operation="plan")
    assert r.context.model_calls == 1 and r.context.retry_count == 0


def test_deadline_during_sync_tool_discards_result_and_stops_retry():
    def search(*a, **k):
        time.sleep(.01); return {"results": []}
    r = runtime(search=search, max_runtime_seconds=.005)
    with pytest.raises(AgentRuntimeError, match="budget_exceeded"):
        r.tools.execute("search_evidence", payload())
    assert r.context.tool_calls == 1 and r.context.retry_count == 0


@pytest.mark.asyncio
async def test_context_trace_isolation_and_failed_trace_redaction(caplog):
    import logging
    caplog.set_level(logging.INFO)
    a, b = runtime(), runtime(SimpleNamespace(generate=AsyncMock(side_effect=RuntimeError("SECRET API KEY PDF PROMPT"))))
    a.context.run_id = "a"; b.context.run_id = "b"
    async def good():
        with a.node("plan_task"):
            await a.model.invoke_text("PRIVATE PROMPT", operation="plan")
    async def bad():
        with pytest.raises(AgentRuntimeError):
            with b.node("plan_task"):
                await b.model.invoke_text("SECRET PDF", operation="plan")
    await asyncio.gather(good(), bad())
    a.finish("completed"); b.finish("failed", "model_internal_error")
    assert a.context is not b.context and a.context.trace is not b.context.trace
    assert a.context.model_calls == b.context.model_calls == 1
    assert b.context.trace[-2].status == "failed"
    assert "SECRET" not in caplog.text and "PRIVATE" not in caplog.text


@pytest.mark.asyncio
async def test_cancellation_records_failure_without_retry():
    entered=asyncio.Event()
    async def slow(*a,**k):
        entered.set();await asyncio.sleep(10)
    r=runtime(SimpleNamespace(generate=slow))
    async def call():
        with r.node('plan_task'):
            await r.model.invoke_text('private',operation='plan')
    task=asyncio.create_task(call());await entered.wait();task.cancel()
    with pytest.raises(asyncio.CancelledError):await task
    assert r.context.model_calls==1 and r.context.retry_count==0
    assert [e.error_code for e in r.context.trace[-2:]]==['model_cancelled','research_cancelled']


def test_negative_scope_is_rejected_before_handler():
    r=runtime()
    with pytest.raises(AgentRuntimeError,match='tool_input_invalid'):
        r.tools.execute('search_evidence',{'query':'x','document_scope':[-1],'top_k':5})
    assert r.context.tool_calls==0
