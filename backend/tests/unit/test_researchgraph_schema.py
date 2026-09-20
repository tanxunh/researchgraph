import pytest
from pydantic import ValidationError

from app.services.graph.extraction_schema import ChunkGraphExtraction, ExtractedEntity, ExtractedRelation


def test_graph_extraction_schema_accepts_allowed_types():
    data = ChunkGraphExtraction(
        entities=[ExtractedEntity(name="ProtoNet", entity_type="Method", confidence=0.9)],
        relations=[
            ExtractedRelation(
                source_name="ProtoNet",
                relation_type="EVALUATED_ON",
                target_name="miniImageNet",
                evidence_text="ProtoNet is evaluated on miniImageNet.",
                confidence=0.8,
            )
        ],
    )
    assert data.entities[0].entity_type == "Method"


def test_graph_extraction_schema_rejects_unknown_relation():
    with pytest.raises(ValidationError):
        ExtractedRelation(source_name="A", relation_type="MAGIC", target_name="B", evidence_text="A magic B", confidence=0.8)
