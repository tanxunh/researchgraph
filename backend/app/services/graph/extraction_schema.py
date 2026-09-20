from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

EntityType = Literal["Paper", "Method", "Dataset", "Task", "Metric", "Concept"]
RelationType = Literal["USES", "EVALUATED_ON", "TARGETS", "REPORTS", "COMPARES_WITH", "PART_OF", "CITES", "RELATED_TO"]


class ExtractedEntity(BaseModel):
    name: str = Field(min_length=1)
    entity_type: EntityType
    aliases: list[str] = Field(default_factory=list)
    description: str | None = None
    confidence: float = Field(ge=0.0, le=1.0)

    @field_validator("aliases")
    @classmethod
    def strip_aliases(cls, value: list[str]) -> list[str]:
        return [item.strip() for item in value if item and item.strip()]


class ExtractedRelation(BaseModel):
    source_name: str = Field(min_length=1)
    relation_type: RelationType
    target_name: str = Field(min_length=1)
    evidence_text: str = Field(min_length=1)
    confidence: float = Field(ge=0.0, le=1.0)


class ChunkGraphExtraction(BaseModel):
    entities: list[ExtractedEntity] = Field(default_factory=list)
    relations: list[ExtractedRelation] = Field(default_factory=list)
