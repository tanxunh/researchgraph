from __future__ import annotations

import json
import re
from typing import Any

from pydantic import ValidationError

from app.core.config import get_settings
from app.core.llm_client import LLMClient, LLMClientError
from app.services.graph.extraction_schema import ChunkGraphExtraction, ExtractedEntity, ExtractedRelation
from app.services.indexing.hash_service import normalize_entity_name

_METHOD_HINTS = ("method", "model", "algorithm", "network", "net", "transformer", "bert", "gpt", "protonet", "distillation")
_DATASET_HINTS = ("imagenet", "cifar", "mnist", "squad", "glue", "dataset", "corpus", "miniimagenet", "tieredimagenet")
_METRIC_HINTS = ("accuracy", "f1", "recall", "precision", "auc", "bleu", "rouge", "mrr")
_TASK_HINTS = ("classification", "retrieval", "question answering", "detection", "segmentation", "few-shot")
_NAME_RE = re.compile(r"\b[A-Z][A-Za-z0-9+_.-]{2,}(?:\s+[A-Z][A-Za-z0-9+_.-]{2,}){0,3}\b")


class EntityExtractionError(Exception):
    """Raised when graph extraction cannot produce validated structured output."""


class EntityExtractor:
    """Graph extraction with formal LLM mode and test-only mock mode."""

    def __init__(self, llm_client: LLMClient | None = None, mode: str | None = None) -> None:
        self.settings = get_settings()
        self.mode = (mode or self.settings.graph_extractor_mode).lower().strip()
        self.llm_client = llm_client or LLMClient()
        if self.mode == "mock" and self.settings.app_env.lower().strip() != "test":
            raise EntityExtractionError("GRAPH_EXTRACTOR_MODE=mock is only allowed when APP_ENV=test.")

    def extract(self, text: str) -> ChunkGraphExtraction:
        if self.mode == "mock":
            return self._mock_extract(text)
        if self.mode != "llm":
            raise EntityExtractionError(f"Unsupported graph extractor mode: {self.mode}")
        return self._extract_with_llm(text)

    def _extract_with_llm(self, text: str) -> ChunkGraphExtraction:
        prompt = self._prompt(text)
        try:
            raw = self.llm_client.generate_sync(prompt, system_prompt=self._system_prompt())
        except LLMClientError as exc:
            raise EntityExtractionError(str(exc)) from exc
        try:
            return self._parse(raw)
        except EntityExtractionError as first_error:
            repair_prompt = (
                "The previous output failed validation. Return ONLY corrected strict JSON matching the schema.\n"
                f"Validation error: {first_error}\n"
                f"Previous output:\n{raw}\n"
            )
            try:
                repaired = self.llm_client.generate_sync(repair_prompt, system_prompt=self._system_prompt())
                return self._parse(repaired)
            except (LLMClientError, EntityExtractionError, ValidationError) as exc:
                raise EntityExtractionError(f"LLM graph extraction validation failed after one repair attempt: {exc}") from exc

    def _parse(self, raw: str) -> ChunkGraphExtraction:
        cleaned = self._strip_code_fence(raw)
        try:
            data: Any = json.loads(cleaned)
        except json.JSONDecodeError as exc:
            raise EntityExtractionError(f"LLM output is not valid JSON: {exc}") from exc
        try:
            return ChunkGraphExtraction.model_validate(data)
        except ValidationError as exc:
            raise EntityExtractionError(str(exc)) from exc

    def _strip_code_fence(self, raw: str) -> str:
        value = raw.strip()
        if value.startswith("```"):
            value = re.sub(r"^```(?:json)?\s*", "", value, flags=re.IGNORECASE)
            value = re.sub(r"\s*```$", "", value)
        return value.strip()

    def _system_prompt(self) -> str:
        return "You extract research entities and evidence-backed relations. Return strict JSON only."

    def _prompt(self, text: str) -> str:
        return f"""
Extract entities and relations from the chunk below.

Allowed entity_type values: Paper, Method, Dataset, Task, Metric, Concept.
Allowed relation_type values: USES, EVALUATED_ON, TARGETS, REPORTS, COMPARES_WITH, PART_OF, CITES, RELATED_TO.
Every relation must include evidence_text copied from or tightly matching the chunk.
Confidence must be between 0 and 1.

Return exactly this JSON shape:
{{
  "entities": [{{"name": "...", "entity_type": "Method", "aliases": [], "description": null, "confidence": 0.8}}],
  "relations": [{{"source_name": "...", "relation_type": "EVALUATED_ON", "target_name": "...", "evidence_text": "...", "confidence": 0.8}}]
}}

Chunk:
{text[:6000]}
""".strip()

    def _mock_extract(self, text: str) -> ChunkGraphExtraction:
        entities = self._mock_entities(text)
        relations = self._mock_relations(text, entities)
        return ChunkGraphExtraction(entities=entities, relations=relations)

    def _mock_entities(self, text: str) -> list[ExtractedEntity]:
        seen: set[tuple[str, str]] = set()
        entities: list[ExtractedEntity] = []
        for raw in _NAME_RE.findall(text):
            name = raw.strip()
            lowered = name.lower()
            entity_type = "Concept"
            if any(hint in lowered for hint in _DATASET_HINTS):
                entity_type = "Dataset"
            elif any(hint in lowered for hint in _METRIC_HINTS):
                entity_type = "Metric"
            elif any(hint in lowered for hint in _TASK_HINTS):
                entity_type = "Task"
            elif any(hint in lowered for hint in _METHOD_HINTS):
                entity_type = "Method"
            elif "paper" in lowered or "study" in lowered:
                entity_type = "Paper"
            key = (entity_type, normalize_entity_name(name))
            if key in seen:
                continue
            seen.add(key)
            entities.append(ExtractedEntity(name=name, entity_type=entity_type, confidence=0.7))
        return entities[:20]

    def _mock_relations(self, text: str, entities: list[ExtractedEntity]) -> list[ExtractedRelation]:
        relations: list[ExtractedRelation] = []
        names = [entity.name for entity in entities]
        sentences = re.split(r"(?<=[.!?。！？])\s+|\n+", text)
        for sentence in [item.strip() for item in sentences if item.strip()]:
            present = [name for name in names if name in sentence]
            if len(present) < 2:
                continue
            lowered = sentence.lower()
            relation_type = "RELATED_TO"
            if "evaluat" in lowered or "benchmark" in lowered or "dataset" in lowered:
                relation_type = "EVALUATED_ON"
            elif "use" in lowered or "based on" in lowered or "with" in lowered:
                relation_type = "USES"
            elif "target" in lowered or "task" in lowered:
                relation_type = "TARGETS"
            elif "report" in lowered or "achieve" in lowered:
                relation_type = "REPORTS"
            relations.append(
                ExtractedRelation(
                    source_name=present[0],
                    relation_type=relation_type,
                    target_name=present[1],
                    evidence_text=sentence[:500],
                    confidence=0.7,
                )
            )
        return relations[:20]
