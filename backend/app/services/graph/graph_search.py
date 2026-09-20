from __future__ import annotations

from dataclasses import dataclass, field
import re

from sqlalchemy import or_, select
from sqlalchemy.orm import Session, aliased

from app.core.config import get_settings
from app.models.document import Document, DocumentChunk, DocumentVersion, DocumentVersionChunk
from app.models.entity import Entity, EntityAlias, EntityMention
from app.models.relation import Relation
from app.services.indexing.hash_service import normalize_entity_name


def linking_terms(query: str) -> list[str]:
    # Bounded phrase generation, matched by indexed equality rather than all-entity scans.
    tokens = re.findall(r"[a-z0-9_+.-]+|[\u4e00-\u9fff]", normalize_entity_name(query)[:512])[:64]
    terms = set()
    for start in range(len(tokens)):
        for length in range(1, min(8, len(tokens)-start)+1):
            part = tokens[start:start+length]
            terms.add(normalize_entity_name(" ".join(part)))
            if any(re.fullmatch(r"[\u4e00-\u9fff]", t) for t in part):
                terms.add(normalize_entity_name("".join(part)))
    return sorted(terms, key=lambda t: (-len(t), t))[:512]


@dataclass(frozen=True)
class GraphPath:
    seed_entity: str
    relations: list[dict]
    entities: list[str]
    hop_count: int
    evidence_chunk_id: int
    evidence_stable_chunk_id: str
    document_id: int
    document_version_id: int
    score: float
    # Retain terminal-edge fields for existing Search diagnostics.
    source_entity: str
    source_type: str
    relation_type: str
    target_entity: str
    target_type: str
    confidence: float


@dataclass
class GraphExpansion:
    chunk_id: int
    stable_chunk_id: str
    score: float
    rank: int
    matched_entities: list[str] = field(default_factory=list)
    graph_paths: list[GraphPath] = field(default_factory=list)


class GraphSearch:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.settings = get_settings()
        self.last_stats = {}

    def is_available(self) -> bool:
        """Only current-ready, evidence-backed relations count as available enrichment."""
        return self.db.scalar(select(Relation.id)
            .join(DocumentChunk, DocumentChunk.id == Relation.evidence_chunk_id)
            .join(DocumentVersionChunk, DocumentVersionChunk.chunk_id == DocumentChunk.id)
            .join(DocumentVersion, DocumentVersion.id == DocumentVersionChunk.document_version_id)
            .join(Document, Document.id == DocumentVersion.document_id)
            .where(Document.id == DocumentChunk.document_id,
                   Document.current_version == DocumentVersion.version, Document.status == "ready",
                   DocumentChunk.text != "", Relation.confidence >= self.settings.graph_min_relation_confidence,
                   Relation.confidence <= 1).limit(1)) is not None

    def find_query_entities(self, query: str) -> list[Entity]:
        terms = linking_terms(query)
        if not terms:
            return []
        alias_ids = select(EntityAlias.entity_id).where(EntityAlias.normalized_alias.in_(terms))
        return list(self.db.scalars(select(Entity).where(or_(
            Entity.normalized_name.in_(terms), Entity.id.in_(alias_ids)))
            .order_by(Entity.id).limit(min(self.settings.graph_max_neighbors,
                                          self.settings.graph_max_expanded_entities))).all())

    def chunk_entities(self, chunk_ids: list[int]) -> list[Entity]:
        if not chunk_ids:
            return []
        return list(self.db.scalars(select(Entity).join(EntityMention, EntityMention.entity_id == Entity.id)
            .where(EntityMention.chunk_id.in_(chunk_ids[:self.settings.graph_max_neighbors]))
            .distinct().order_by(Entity.id).limit(self.settings.graph_max_neighbors)).all())

    def _edges(self, frontier: list[int], visited_relations: set[int], remaining: int):
        source, target = aliased(Entity), aliased(Entity)
        # Every edge is backed by current ready SQL evidence, including intermediate edges.
        query = (select(Relation, source, target, DocumentChunk, DocumentVersion)
            .join(source, source.id == Relation.source_entity_id)
            .join(target, target.id == Relation.target_entity_id)
            .join(DocumentChunk, DocumentChunk.id == Relation.evidence_chunk_id)
            .join(DocumentVersionChunk, DocumentVersionChunk.chunk_id == DocumentChunk.id)
            .join(DocumentVersion, DocumentVersion.id == DocumentVersionChunk.document_version_id)
            .join(Document, Document.id == DocumentVersion.document_id)
            .where(Document.id == DocumentChunk.document_id,
                   Document.current_version == DocumentVersion.version, Document.status == "ready",
                   DocumentChunk.text != "",
                   Relation.confidence >= self.settings.graph_min_relation_confidence,
                   Relation.confidence <= 1,
                   or_(Relation.source_entity_id.in_(frontier), Relation.target_entity_id.in_(frontier)))
            .order_by(Relation.confidence.desc(), Relation.id).limit(remaining))
        if visited_relations:
            query = query.where(Relation.id.not_in(visited_relations))
        return self.db.execute(query).all()

    def expand(self, query: str, seed_chunk_ids: list[int]) -> list[GraphExpansion]:
        linked = self.find_query_entities(query)
        # Text-derived seeds are a fallback only; they must not turn an entire corpus into seeds.
        seeds = linked or self.chunk_entities(seed_chunk_ids)
        cap = self.settings.graph_max_expanded_entities
        seeds = seeds[:min(cap, self.settings.graph_max_neighbors)]
        seed_relevance = 1.0 if linked else 0.5
        # entity -> (seed name, entity sequence, edge sequence, confidence product)
        frontier = {s.id: (s.canonical_name, [s.canonical_name], [], 1.0) for s in seeds}
        visited_entities, visited_relations = set(frontier), set()
        expansions = {}
        path_count = 0
        for hop in range(1, self.settings.graph_max_hops+1):
            if not frontier or path_count >= self.settings.graph_max_paths:
                break
            rows = self._edges(list(frontier), visited_relations, self.settings.graph_max_paths-path_count)
            next_frontier = {}
            for relation, source, target, chunk, version in rows:
                if relation.id in visited_relations:
                    continue
                visited_relations.add(relation.id)
                parent, neighbor = ((source, target) if source.id in frontier else (target, source))
                if neighbor.id not in visited_entities and len(visited_entities) >= cap:
                    continue
                if chunk is None or version is None or not chunk.text.strip():
                    continue
                seed, names, edges, confidence = frontier[parent.id]
                if neighbor.canonical_name in names:
                    continue
                confidence *= relation.confidence
                score = seed_relevance * confidence * self.settings.graph_hop_decay ** (hop-1)
                edge = {"relation_id": relation.id, "source_entity_id": source.id,
                        "target_entity_id": target.id, "relation_type": relation.relation_type,
                        "confidence": relation.confidence, "evidence_chunk_id": chunk.id,
                        "chunk_id": chunk.stable_chunk_id, "document_id": chunk.document_id,
                        "document_version_id": version.id,
                        "traversal_direction": "outgoing" if parent.id == source.id else "incoming"}
                path = GraphPath(seed, edges+[edge], names+[neighbor.canonical_name], hop,
                                 chunk.id, chunk.stable_chunk_id, chunk.document_id, version.id, score,
                                 source.canonical_name, source.entity_type, relation.relation_type,
                                 target.canonical_name, target.entity_type, relation.confidence)
                previous = expansions.get(chunk.id)
                if previous is None or score > previous.score:
                    expansions[chunk.id] = GraphExpansion(chunk.id, chunk.stable_chunk_id, score, 0,
                                                         path.entities, [path])
                path_count += 1
                if neighbor.id not in visited_entities:
                    visited_entities.add(neighbor.id)
                    next_frontier[neighbor.id] = (seed, path.entities, path.relations, confidence)
            frontier = next_frontier
        self.last_stats = {"visited_entities": len(visited_entities), "visited_relations": len(visited_relations),
                           "path_count": path_count}
        ranked = sorted(expansions.values(), key=lambda item: (-item.score, item.chunk_id))
        for rank, item in enumerate(ranked, 1):
            item.rank = rank
        return ranked

    def chunk_matched_entities(self, chunk_id: int) -> list[str]:
        return [f"{e.entity_type}: {e.canonical_name}" for e in self.chunk_entities([chunk_id])]
