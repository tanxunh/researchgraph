"""Small typed execution contracts; trace never stores invocation payloads."""
from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class ExecutionBudget(BaseModel):
    model_config = ConfigDict(frozen=True)
    max_model_calls: int = Field(default=36, ge=1)
    max_tool_calls: int = Field(default=40, ge=1)
    max_retrieval_calls: int = Field(default=34, ge=1)
    max_runtime_seconds: float = Field(default=300, gt=0)


class TraceEvent(BaseModel):
    run_id: str
    event_type: Literal['run_started', 'node_started', 'model_call', 'tool_call',
                        'budget_exceeded', 'node_finished', 'run_finished']
    node: str | None = None
    operation: str
    status: str
    started_at: datetime = Field(default_factory=utc_now)
    duration_ms: float = 0
    model: str | None = None
    structured: bool | None = None
    tool_name: str | None = None
    attempt: int | None = None
    error_code: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None


class ExecutionContext(BaseModel):
    run_id: str
    started_at: datetime = Field(default_factory=utc_now)
    started_clock: float = Field(default_factory=time.monotonic, exclude=True)
    model_calls: int = 0
    tool_calls: int = 0
    retrieval_calls: int = 0
    retry_count: int = 0
    elapsed_ms: float = 0
    budget: ExecutionBudget
    trace: list[TraceEvent] = Field(default_factory=list)
    budget_exceeded: bool = False
    node: str | None = None


class ExecutionSummary(BaseModel):
    run_id: str
    status: str
    duration_ms: float
    model_calls: int
    tool_calls: int
    retrieval_calls: int
    retries: int
    budget_exceeded: bool
    error_code: str | None = None


class AgentRuntimeError(Exception):
    """Code-only error: provider messages and invocation data must not enter trace."""
    def __init__(self, code: str, *, transient: bool = False, public_code: str | None = None):
        super().__init__(code)
        self.code = code
        self.transient = transient
        self.public_code = public_code or code
