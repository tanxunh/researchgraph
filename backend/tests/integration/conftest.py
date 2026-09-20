from __future__ import annotations

import os

from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.database import Base
from app.models import Document, DocumentChunk, DocumentVersion, Entity, EntityAlias, EntityMention, EvaluationRun, IndexJob, Relation
from app.services.graph.extraction_schema import ChunkGraphExtraction, ExtractedEntity, ExtractedRelation
from app.services.parsing.base import ParsedDocument, ParsedSection
from app.vectorstore.chroma_store import ChromaStore
from app.vectorstore.embeddings import FakeEmbeddingProvider

_ = (Document, DocumentChunk, DocumentVersion, Entity, EntityAlias, EntityMention, EvaluationRun, IndexJob, Relation)

ENTITY_TYPES = {
    "Paper Alpha": "Paper",
    "Paper Other": "Paper",
    "Method Alpha": "Method",
    "Dataset Beta": "Dataset",
    "Metric Gamma": "Metric",
    "Task Omega": "Task",
    "Concept Bridge": "Concept",
}
RELATIONS = ["USES", "TARGETS", "EVALUATED_ON", "REPORTS", "COMPARES_WITH"]


class RuleExtractor:
    def extract(self, text: str) -> ChunkGraphExtraction:
        names = [name for name in ENTITY_TYPES if name in text]
        entities = [ExtractedEntity(name=name, entity_type=ENTITY_TYPES[name], aliases=[], description="test", confidence=0.95) for name in names]
        relations = []
        for rel in RELATIONS:
            if rel not in text:
                continue
            for source in names:
                for target in names:
                    if source != target and source in text and target in text:
                        start = text.find(source)
                        mid = text.find(rel, start)
                        end = text.find(target, mid)
                        if start >= 0 and mid >= 0 and end >= 0:
                            evidence = text[start : end + len(target)]
                            relations.append(ExtractedRelation(source_name=source, relation_type=rel, target_name=target, evidence_text=evidence, confidence=0.9))
        return ChunkGraphExtraction(entities=entities, relations=relations)


@pytest.fixture
def integration_db(tmp_path):
    if os.environ.get("CONSISTENCY_REAL") == "1":
        # Fixed disposable service/schema, never a user-provided business URL.
        engine = create_engine(
            "mysql+pymysql://consistency:isolated_test_password@mysql-consistency:3306/"
            "lifeflow_consistency_test?charset=utf8mb4", pool_pre_ping=True)
    else:
        engine = create_engine(f"sqlite:///{tmp_path / 'lifeflow-integration.db'}", connect_args={"check_same_thread": False})
    SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    Base.metadata.create_all(bind=engine)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


@pytest.fixture
def vector_store():
    # Opt-in real tests only use the disposable Compose Chroma service.
    if os.environ.get("CONSISTENCY_REAL") == "1":
        from app.core.config import get_settings
        get_settings().chroma_host = "chroma-consistency"
        get_settings().chroma_port = 8000
    store = ChromaStore(FakeEmbeddingProvider(version=f"test-{uuid4().hex[:16]}"))
    try:
        yield store
    finally:
        store.client.delete_collection(store.collection_name)


def parsed_doc(source_uri: str, title: str, sections: list[tuple[str, str]]) -> ParsedDocument:
    parsed_sections = [ParsedSection(text=text, order=index, section_title=key, source_uri=f"{source_uri}:{key}") for index, (key, text) in enumerate(sections)]
    return ParsedDocument(title=title, source_type="text", source_uri=source_uri, text="\n\n".join(text for _, text in sections), sections=parsed_sections, metadata={"dataset_name": "integration_test"})

@pytest.fixture
def rule_extractor():
    return RuleExtractor()


@pytest.fixture
def make_parsed_doc():
    return parsed_doc
