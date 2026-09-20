from __future__ import annotations

from pydantic import BaseModel, Field


class EvaluationRunRequest(BaseModel):
    dataset_path: str = Field(default="backend/tests/fixtures/retrieval_eval_cases.jsonl")
    top_k: int = Field(default=10, ge=1, le=50)
