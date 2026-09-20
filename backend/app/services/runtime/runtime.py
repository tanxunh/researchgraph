"""Reliable invocation boundaries, not a second workflow engine."""
from __future__ import annotations

import asyncio
import logging
import time
from contextlib import contextmanager
from typing import TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from app.core.llm_client import LLMClientError
from app.services.runtime.contracts import (
    AgentRuntimeError, ExecutionBudget, ExecutionContext, ExecutionSummary, TraceEvent, utc_now,
)
from app.services.runtime.tools import ToolRegistry

logger = logging.getLogger(__name__)
Schema = TypeVar('Schema', bound=BaseModel)


class ErrorPolicy:
    @staticmethod
    def normalize(exc: Exception, kind: str) -> AgentRuntimeError:
        if isinstance(exc, AgentRuntimeError):
            return exc
        if isinstance(exc, (TimeoutError, httpx.TimeoutException)):
            return AgentRuntimeError(f'{kind}_timeout', transient=True)
        if isinstance(exc, (ConnectionError, httpx.ConnectError)):
            return AgentRuntimeError(f'{kind}_transient_error', transient=True)
        if isinstance(exc, httpx.HTTPStatusError):
            temporary = exc.response.status_code in {500, 502, 503, 504}
            return AgentRuntimeError(f'{kind}_transient_error' if temporary else f'{kind}_internal_error',
                                     transient=temporary)
        if isinstance(exc, LLMClientError):
            code = exc.error_type
            if code == 'invalid_model_response':
                return AgentRuntimeError('model_output_invalid', public_code=code)
            if code == 'llm_timeout':
                return AgentRuntimeError('model_timeout', transient=True, public_code=code)
            if code == 'llm_network_error':
                return AgentRuntimeError('model_transient_error', transient=True, public_code=code)
            cause = exc.__cause__
            temporary = (isinstance(cause, httpx.HTTPStatusError)
                         and cause.response.status_code in {500, 502, 503, 504})
            return AgentRuntimeError('model_transient_error' if temporary else 'model_provider_error',
                                     transient=temporary, public_code=code)
        if isinstance(exc, ValidationError):
            return AgentRuntimeError(f'{kind}_output_invalid')
        if isinstance(exc, ValueError) and kind == 'tool':
            return AgentRuntimeError('tool_business_error')
        return AgentRuntimeError(f'{kind}_internal_error')


class TraceCollector:
    def __init__(self, context: ExecutionContext):
        self.context = context

    def emit(self, event_type, operation, status, **metadata) -> None:
        event = TraceEvent(run_id=self.context.run_id, event_type=event_type,
                           node=self.context.node, operation=operation, status=status, **metadata)
        self.context.trace.append(event)
        logger.info('research_execution_event %s', event.model_dump_json())


class AgentRuntime:
    def __init__(self, run_id: str, client, registry: ToolRegistry, *, budget: ExecutionBudget,
                 model_name: str, model_timeout: float = 60, tool_timeout: float = 60):
        self.context = ExecutionContext(run_id=run_id, budget=budget)
        self.trace = TraceCollector(self.context)
        self.model = ModelGateway(self, client, model_name, model_timeout)
        self.tools = ToolExecutor(self, registry, tool_timeout)
        self.trace.emit('run_started', 'research_compare', 'running')

    def remaining(self) -> float:
        self.context.elapsed_ms = (time.monotonic() - self.context.started_clock) * 1000
        return self.context.budget.max_runtime_seconds - self.context.elapsed_ms / 1000

    def check_deadline(self) -> None:
        if self.context.budget_exceeded or self.remaining() <= 0:
            self.exhaust('runtime')

    def exhaust(self, operation: str) -> None:
        self.context.budget_exceeded = True
        self.trace.emit('budget_exceeded', operation, 'failed', error_code='budget_exceeded')
        raise AgentRuntimeError('budget_exceeded')

    def reserve(self, kind: str, operation: str, attempt: int) -> None:
        self.check_deadline()
        ctx, budget = self.context, self.context.budget
        if kind == 'model' and ctx.model_calls >= budget.max_model_calls:
            self.exhaust('model_calls')
        if kind == 'tool':
            if ctx.tool_calls >= budget.max_tool_calls:
                self.exhaust('tool_calls')
            if operation == 'search_evidence' and ctx.retrieval_calls >= budget.max_retrieval_calls:
                self.exhaust('retrieval_calls')
            ctx.tool_calls += 1
            if operation == 'search_evidence':
                ctx.retrieval_calls += 1
        else:
            ctx.model_calls += 1
        if attempt > 1:
            ctx.retry_count += 1

    @contextmanager
    def node(self, name: str):
        previous = self.context.node
        self.context.node = name
        started, clock = utc_now(), time.monotonic()
        self.trace.emit('node_started', name, 'running', started_at=started)
        error = None
        try:
            self.check_deadline()
            yield
            self.check_deadline()
        except asyncio.CancelledError:
            error = 'research_cancelled'
            raise
        except Exception as exc:
            if isinstance(exc, AgentRuntimeError):
                error = exc.code
            elif isinstance(exc, LLMClientError):
                error = ErrorPolicy.normalize(exc, 'model').code
            else:
                # Never render exception messages or class-specific payloads.
                error = 'workflow_validation_or_execution_failed'
            raise
        finally:
            self.trace.emit('node_finished', name, 'failed' if error else 'succeeded',
                            started_at=started, duration_ms=(time.monotonic() - clock) * 1000,
                            error_code=error)
            self.context.node = previous

    def finish(self, status: str, error_code: str | None = None) -> ExecutionSummary:
        self.remaining()
        summary = ExecutionSummary(run_id=self.context.run_id, status=status,
            duration_ms=self.context.elapsed_ms, model_calls=self.context.model_calls,
            tool_calls=self.context.tool_calls, retrieval_calls=self.context.retrieval_calls,
            retries=self.context.retry_count, budget_exceeded=self.context.budget_exceeded,
            error_code=error_code)
        self.trace.emit('run_finished', 'research_compare', status,
                        duration_ms=summary.duration_ms, error_code=error_code)
        logger.info('research_execution_summary %s', summary.model_dump_json())
        return summary


class ModelGateway:
    def __init__(self, runtime: AgentRuntime, client, model_name: str, timeout: float):
        self.runtime, self.client = runtime, client
        self.model_name, self.timeout = model_name, timeout

    async def invoke_text(self, prompt: str, *, operation: str, system_prompt: str | None = None) -> str:
        return await self._invoke(prompt, operation, system_prompt, None)

    async def invoke_structured(self, schema: type[Schema], prompt: str, *, operation: str,
                                system_prompt: str | None = None) -> Schema:
        return await self._invoke(prompt, operation, system_prompt, schema)

    async def _invoke(self, prompt, operation, system_prompt, schema):
        for attempt in (1, 2):
            self.runtime.reserve('model', operation, attempt)
            started, clock, error = utc_now(), time.monotonic(), None
            try:
                raw = await asyncio.wait_for(self.client.generate(prompt, system_prompt=system_prompt),
                    timeout=min(self.timeout, self.runtime.remaining()))
                self.runtime.check_deadline()
                if not isinstance(raw, str) or not raw.strip():
                    raise AgentRuntimeError('model_output_invalid', public_code='invalid_model_response')
                if schema is None:
                    return raw
                if raw.strip().startswith('```'):
                    raw = '\n'.join(raw.strip().splitlines()[1:-1])
                try:
                    return schema.model_validate_json(raw)
                except (ValidationError, ValueError, TypeError) as exc:
                    raise AgentRuntimeError('model_output_invalid', public_code='invalid_model_response') from exc
            except asyncio.CancelledError:
                error = AgentRuntimeError('model_cancelled')
                raise
            except Exception as exc:
                error = ErrorPolicy.normalize(exc, 'model')
                if self.runtime.remaining() <= 0 and error.code != 'budget_exceeded':
                    error = AgentRuntimeError('budget_exceeded')
                    self.runtime.context.budget_exceeded = True
                    self.runtime.trace.emit('budget_exceeded', 'runtime', 'failed', error_code=error.code)
                if not error.transient or attempt == 2:
                    raise error from exc
            finally:
                self.runtime.trace.emit('model_call', operation, 'failed' if error else 'succeeded',
                    started_at=started, duration_ms=(time.monotonic() - clock) * 1000,
                    model=self.model_name, structured=schema is not None, attempt=attempt,
                    error_code=error.code if error else None)


class ToolExecutor:
    """Synchronous read-only services retain session/thread affinity.

    Deadlines are cooperative pre/post boundaries, not a forced I/O cancellation.
    No abandoned thread or concurrent retry can continue using the request session.
    """
    def __init__(self, runtime: AgentRuntime, registry: ToolRegistry, timeout: float):
        self.runtime, self.registry, self.timeout = runtime, registry, timeout

    def execute(self, name: str, payload):
        started = utc_now()
        try:
            definition = self.registry.get(name)
            try:
                data = definition.input_schema.model_validate(payload)
            except (ValidationError, ValueError, TypeError) as exc:
                raise AgentRuntimeError('tool_input_invalid') from exc
        except AgentRuntimeError as exc:
            # Unknown user-provided names are intentionally not copied into trace.
            safe_name = name if name in {'search_evidence', 'resolve_evidence'} else 'unregistered'
            self.runtime.trace.emit('tool_call', safe_name, 'rejected', tool_name=safe_name,
                                    started_at=started, attempt=0, error_code=exc.code)
            raise
        for attempt in (1, 2):
            self.runtime.reserve('tool', name, attempt)
            started, clock, error = utc_now(), time.monotonic(), None
            try:
                raw = definition.handler(data)
                self.runtime.check_deadline()
                if time.monotonic() - clock >= self.timeout:
                    raise AgentRuntimeError('tool_timeout', transient=True)
                return definition.output_schema.model_validate(raw)
            except Exception as exc:
                error = ErrorPolicy.normalize(exc, 'tool')
                if self.runtime.remaining() <= 0 and error.code != 'budget_exceeded':
                    error = AgentRuntimeError('budget_exceeded')
                    self.runtime.context.budget_exceeded = True
                    self.runtime.trace.emit('budget_exceeded', 'runtime', 'failed', error_code=error.code)
                if not error.transient or attempt == 2:
                    raise error from exc
            finally:
                self.runtime.trace.emit('tool_call', name, 'failed' if error else 'succeeded',
                    tool_name=name, started_at=started, duration_ms=(time.monotonic() - clock) * 1000,
                    attempt=attempt, error_code=error.code if error else None)
