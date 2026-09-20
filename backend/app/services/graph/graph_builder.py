from __future__ import annotations

from sqlalchemy import delete, func, or_, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.document import DocumentChunk
from app.models.entity import Entity, EntityAlias, EntityMention
from app.models.relation import Relation
from app.services.graph.entity_extractor import EntityExtractor
from app.services.graph.entity_normalizer import EntityNormalizer
from app.services.graph.extraction_schema import ChunkGraphExtraction, ExtractedEntity


class GraphBuilder:
    def __init__(self, db: Session, extractor: EntityExtractor | None = None) -> None:
        self.db = db
        self.extractor = extractor or EntityExtractor()
        self.normalizer = EntityNormalizer()
        self.settings = get_settings()

    def rebuild_chunks(self, chunks: list[DocumentChunk]) -> dict:
        stats = {"chunks": len(chunks), "entities": 0, "mentions": 0, "relations": 0}
        for chunk in chunks:
            self.cleanup_chunk(chunk.id)
            extraction = self.extractor.extract(chunk.text)
            chunk_stats = self.apply_extraction(chunk, extraction)
            for key in ("entities", "mentions", "relations"):
                stats[key] += chunk_stats[key]
        self.db.flush()
        return stats

    def cleanup_chunk(self, chunk_id: int) -> None:
        self.db.execute(delete(Relation).where(Relation.evidence_chunk_id == chunk_id))
        self.db.execute(delete(EntityMention).where(EntityMention.chunk_id == chunk_id))
        self.db.flush()
        self.cleanup_orphan_entities()

    def cleanup_orphan_entities(self) -> int:
        entities = self.db.scalars(select(Entity)).all()
        removed = 0
        for entity in entities:
            mention_exists = self.db.scalar(select(func.count(EntityMention.id)).where(EntityMention.entity_id == entity.id))
            relation_exists = self.db.scalar(
                select(func.count(Relation.id)).where(
                    or_(Relation.source_entity_id == entity.id, Relation.target_entity_id == entity.id)
                )
            )
            if not mention_exists and not relation_exists:
                self.db.execute(delete(EntityAlias).where(EntityAlias.entity_id == entity.id))
                self.db.delete(entity)
                removed += 1
        self.db.flush()
        return removed

    def apply_extraction(self, chunk: DocumentChunk, extraction: ChunkGraphExtraction) -> dict:
        entity_map: dict[str, Entity] = {}
        stats = {"entities": 0, "mentions": 0, "relations": 0}
        for extracted in extraction.entities:
            entity, created = self._get_or_create_entity(extracted)
            entity_map[self.normalizer.normalize(extracted.name)] = entity
            if created:
                stats["entities"] += 1
            if not self._mention_exists(entity.id, chunk.id, extracted.name):
                self.db.add(EntityMention(entity_id=entity.id, chunk_id=chunk.id, mention_text=extracted.name, confidence=extracted.confidence))
                stats["mentions"] += 1
        self.db.flush()

        for relation in extraction.relations:
            if relation.confidence < self.settings.graph_min_relation_confidence:
                continue
            source = entity_map.get(self.normalizer.normalize(relation.source_name))
            target = entity_map.get(self.normalizer.normalize(relation.target_name))
            if not source or not target or not self._evidence_matches(chunk.text, relation.evidence_text):
                continue
            if self._relation_exists(source.id, relation.relation_type, target.id, chunk.id):
                continue
            self.db.add(
                Relation(
                    source_entity_id=source.id,
                    relation_type=relation.relation_type,
                    target_entity_id=target.id,
                    evidence_chunk_id=chunk.id,
                    confidence=relation.confidence,
                    extractor_version=self.settings.graph_extractor_version,
                )
            )
            stats["relations"] += 1
        self.db.flush()
        return stats

    def _get_or_create_entity(self, extracted: ExtractedEntity) -> tuple[Entity, bool]:
        normalized = self.normalizer.normalize(extracted.name)
        entity = self.db.scalar(
            select(Entity).where(Entity.entity_type == extracted.entity_type, Entity.normalized_name == normalized)
        )
        if entity:
            return entity, False
        entity = Entity(
            entity_type=extracted.entity_type,
            canonical_name=extracted.name,
            normalized_name=normalized,
            description=extracted.description,
        )
        self.db.add(entity)
        self.db.flush()
        for alias in extracted.aliases:
            normalized_alias = self.normalizer.normalize(alias)
            if normalized_alias and not self._alias_exists(entity.id, normalized_alias):
                self.db.add(EntityAlias(entity_id=entity.id, alias=alias, normalized_alias=normalized_alias))
        self.db.flush()
        return entity, True

    def _alias_exists(self, entity_id: int, normalized_alias: str) -> bool:
        return bool(
            self.db.scalar(select(EntityAlias.id).where(EntityAlias.entity_id == entity_id, EntityAlias.normalized_alias == normalized_alias))
        )

    def _mention_exists(self, entity_id: int, chunk_id: int, mention_text: str) -> bool:
        return bool(
            self.db.scalar(
                select(EntityMention.id).where(
                    EntityMention.entity_id == entity_id,
                    EntityMention.chunk_id == chunk_id,
                    EntityMention.mention_text == mention_text,
                )
            )
        )

    def _relation_exists(self, source_id: int, relation_type: str, target_id: int, chunk_id: int) -> bool:
        return bool(
            self.db.scalar(
                select(Relation.id).where(
                    Relation.source_entity_id == source_id,
                    Relation.relation_type == relation_type,
                    Relation.target_entity_id == target_id,
                    Relation.evidence_chunk_id == chunk_id,
                )
            )
        )

    def _evidence_matches(self, chunk_text: str, evidence_text: str) -> bool:
        evidence = " ".join(evidence_text.split())
        chunk = " ".join(chunk_text.split())
        return bool(evidence and (evidence in chunk or len(set(evidence.lower().split()) & set(chunk.lower().split())) >= 3))
