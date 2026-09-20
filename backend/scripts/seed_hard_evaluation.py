from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

os.environ["APP_ENV"] = "test"
os.environ["EMBEDDING_PROVIDER"] = "fake"
os.environ["EMBEDDING_DIMENSION"] = "8"
os.environ["EMBEDDING_VERSION"] = "hard-eval-v1"
os.environ["GRAPH_EXTRACTOR_MODE"] = "mock"
os.environ["GRAPH_EXTRACTOR_VERSION"] = "hard-eval-mock-v1"
os.environ["DATABASE_URL"] = os.environ.get("HARD_EVAL_DATABASE_URL", "sqlite:////tmp/lifeflow_hard_eval.db")

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from sqlalchemy import func, select  # noqa: E402

from app.core.database import SessionLocal, create_db_tables  # noqa: E402
from app.models.document import Document, DocumentChunk  # noqa: E402
from app.models.entity import Entity, EntityMention  # noqa: E402
from app.models.relation import Relation  # noqa: E402
from app.services.graph.extraction_schema import ChunkGraphExtraction, ExtractedEntity, ExtractedRelation  # noqa: E402
from app.services.indexing.incremental_indexer import IncrementalIndexer  # noqa: E402
from app.services.parsing.base import ParsedDocument, ParsedSection  # noqa: E402
from app.vectorstore.chroma_store import ChromaStore  # noqa: E402
from app.vectorstore.embeddings import FakeEmbeddingProvider  # noqa: E402

DATASET_DIR = BACKEND_ROOT / "tests" / "fixtures" / "hard_eval"
MANIFEST_PATH = DATASET_DIR / "manifest.json"
CASES_PATH = DATASET_DIR / "cases.jsonl"
RESOLVED_CASES_PATH = DATASET_DIR / "resolved_cases.jsonl"
DATASET_NAME = "hard_eval_v1"
RELATIONS = ["EVALUATED_ON", "COMPARES_WITH", "TARGETS", "REPORTS", "USES"]
ENTITY_TYPES = {
    "Paper Atlas Trial": "Paper", "Paper Beacon Note": "Paper", "Paper Cascade Brief": "Paper", "Paper Delta Memo": "Paper",
    "Paper Echo Report": "Paper", "Paper Flux Note": "Paper", "Paper Gradient Card": "Paper", "Paper Harbor Sheet": "Paper",
    "AtlasRetriever": "Method", "BeaconPlanner": "Method", "CascadeReader": "Method", "DeltaIndexer": "Method",
    "EchoGraph": "Method", "FluxRank": "Method", "GradientMemo": "Method", "HarborQA": "Method",
    "AuroraSet": "Dataset", "WorkshopCards": "Dataset", "CitationWeave": "Dataset", "LabNotes-42": "Dataset",
    "ScholarToy": "Dataset", "MetroReviews": "Dataset", "TimelineQA": "Dataset",
    "Literature Mapping": "Task", "Study Planning": "Task", "Cross Paper Evidence": "Task", "Incremental Note Search": "Task",
    "Citation Trace": "Task", "Method Comparison": "Task", "Experiment Recall": "Task", "Dataset Grounding": "Task",
    "Source Hit Rate": "Metric", "Complete Evidence Recall": "Metric", "MRR@10": "Metric", "Recall@5": "Metric",
    "Graph Path Validity": "Metric", "Latency P95": "Metric",
    "Graph Expansion": "Concept", "Evidence Stitching": "Concept", "Relation Path": "Concept", "Chunk Stability": "Concept",
    "Query Paraphrase": "Concept", "Semantic Drift": "Concept",
}


class HardEvalMockExtractor:
    def extract(self, text: str) -> ChunkGraphExtraction:
        names = [name for name in ENTITY_TYPES if name in text]
        entities = [ExtractedEntity(name=name, entity_type=ENTITY_TYPES[name], aliases=[], description="Synthetic hard-eval entity", confidence=0.95) for name in sorted(names, key=len, reverse=True)]
        relations = []
        for relation_type in RELATIONS:
            if relation_type not in text:
                continue
            for source in sorted(names, key=len, reverse=True):
                for target in sorted(names, key=len, reverse=True):
                    if source == target:
                        continue
                    match = re.search(re.escape(source) + r".{0,80}" + relation_type + r".{0,80}" + re.escape(target), text)
                    if match:
                        relations.append(ExtractedRelation(source_name=source, relation_type=relation_type, target_name=target, evidence_text=match.group(0), confidence=0.9))
        return ChunkGraphExtraction(entities=entities, relations=relations)

def load_manifest() -> dict[str, Any]:
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8-sig"))


def parse_document(entry: dict[str, Any]) -> ParsedDocument:
    raw = (DATASET_DIR / entry["path"]).read_text(encoding="utf-8-sig")
    sections = []
    matches = list(re.finditer(r"^##\s+([^\n]+)\n", raw, flags=re.MULTILINE))
    for index, match in enumerate(matches):
        section_key = match.group(1).strip().split()[0]
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(raw)
        text = raw[start:end].strip()
        sections.append(ParsedSection(text=text, order=index, section_title=section_key, source_uri=f"{DATASET_NAME}:{entry['document_key']}:{section_key}"))
    return ParsedDocument(
        title=entry["title"],
        source_type="text",
        source_uri=f"{DATASET_NAME}:{entry['document_key']}",
        text="\n\n".join(section.text for section in sections),
        sections=sections,
        metadata={"dataset_name": DATASET_NAME, "document_key": entry["document_key"], "synthetic_test_corpus": True},
    )


def hard_vector_store() -> ChromaStore:
    return ChromaStore(FakeEmbeddingProvider(version="hard-eval-v1"))


def reset_seeded_docs(db) -> dict[str, int]:
    vector_store = hard_vector_store()
    indexer = IncrementalIndexer(vector_store=vector_store, graph_extractor=HardEvalMockExtractor())
    docs = db.scalars(select(Document).where(Document.metadata_json.like(f'%"dataset_name": "{DATASET_NAME}"%'))).all()
    if not docs:
        docs = db.scalars(select(Document).where(Document.source_uri.like(f"{DATASET_NAME}:%"))).all()
    deleted = 0
    for document in docs:
        indexer.delete_document(db, document)
        deleted += 1
    try:
        vector_store.client.delete_collection(vector_store.collection_name)
    except Exception:
        pass
    vector_store = hard_vector_store()
    return {"deleted_documents": deleted, "vector_count_after_reset": vector_store.count()}


def seed_docs(db) -> dict[str, Any]:
    manifest = load_manifest()
    vector_store = hard_vector_store()
    indexer = IncrementalIndexer(vector_store=vector_store, graph_extractor=HardEvalMockExtractor())
    imported = 0
    actions: dict[str, int] = {}
    for entry in manifest["documents"]:
        result = indexer.import_parsed(db, parse_document(entry))
        imported += 1
        actions[result["index_action"]] = actions.get(result["index_action"], 0) + 1
    counts = current_counts(db, vector_store)
    counts.update({"imported_documents": imported, "actions": actions})
    if counts["chunk_count"] < int(manifest.get("minimum_expected_chunks", 40)):
        raise RuntimeError(f"hard_eval_v1 corpus resolved to only {counts['chunk_count']} chunks")
    return counts

def current_counts(db, vector_store: ChromaStore | None = None) -> dict[str, int]:
    vector_store = vector_store or hard_vector_store()
    doc_ids = [row[0] for row in db.execute(select(Document.id).where(Document.source_uri.like(f"{DATASET_NAME}:%"))).all()]
    chunk_ids = [row[0] for row in db.execute(select(DocumentChunk.id).where(DocumentChunk.document_id.in_(doc_ids))).all()] if doc_ids else []
    return {
        "document_count": len(doc_ids),
        "chunk_count": len(chunk_ids),
        "entity_count": db.scalar(select(func.count(Entity.id))) or 0,
        "mention_count": db.scalar(select(func.count(EntityMention.id))) or 0,
        "relation_count": db.scalar(select(func.count(Relation.id))) or 0,
        "vector_count": vector_store.count(),
    }


def resolve_cases(db) -> dict[str, Any]:
    unresolved = []
    resolved = []
    for line in CASES_PATH.read_text(encoding="utf-8-sig").splitlines():
        if not line.strip():
            continue
        case = json.loads(line)
        chunk_ids = []
        doc_ids = []
        for doc_key in case.get("relevant_document_keys", []):
            document = db.scalar(select(Document).where(Document.source_uri == f"{DATASET_NAME}:{doc_key}"))
            if document:
                doc_ids.append(document.id)
            else:
                unresolved.append({"case_id": case["id"], "document_key": doc_key})
        for logical_key in case.get("relevant_chunk_keys", []):
            doc_key, section_key = logical_key.split(":", 1)
            chunk = resolve_chunk(db, doc_key, section_key)
            if chunk:
                chunk_ids.append(chunk.stable_chunk_id)
            else:
                unresolved.append({"case_id": case["id"], "chunk_key": logical_key})
        case["relevant_document_ids"] = doc_ids
        case["relevant_chunk_ids"] = chunk_ids
        resolved.append(case)
    if unresolved:
        raise RuntimeError("Unresolved hard_eval gold keys: " + json.dumps(unresolved, ensure_ascii=False))
    RESOLVED_CASES_PATH.write_text("\n".join(json.dumps(case, ensure_ascii=False) for case in resolved) + "\n", encoding="utf-8")
    return {"resolved_case_count": len(resolved), "unresolved": unresolved, "resolved_path": str(RESOLVED_CASES_PATH)}


def resolve_chunk(db, doc_key: str, section_key: str) -> DocumentChunk | None:
    document = db.scalar(select(Document).where(Document.source_uri == f"{DATASET_NAME}:{doc_key}"))
    if not document:
        return None
    marker = f"DOCUMENT_KEY={doc_key}; SECTION_KEY={section_key}"
    chunk = db.scalar(select(DocumentChunk).where(DocumentChunk.document_id == document.id, DocumentChunk.section_title == section_key, DocumentChunk.text.contains(marker)))
    if chunk:
        return chunk
    chunk = db.scalar(select(DocumentChunk).where(DocumentChunk.document_id == document.id, DocumentChunk.text.contains(marker)))
    if chunk:
        return chunk
    manifest = load_manifest()
    entry = next(item for item in manifest["documents"] if item["document_key"] == doc_key)
    section_order = entry["sections"].index(section_key)
    return db.scalar(select(DocumentChunk).where(DocumentChunk.document_id == document.id, DocumentChunk.chunk_index == section_order))

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--reset", action="store_true")
    parser.add_argument("--seed", action="store_true")
    args = parser.parse_args()
    create_db_tables()
    db = SessionLocal()
    try:
        if args.reset:
            print(json.dumps(reset_seeded_docs(db), ensure_ascii=False))
        if args.seed:
            print(json.dumps(seed_docs(db), ensure_ascii=False))
            print(json.dumps(resolve_cases(db), ensure_ascii=False))
        if not args.reset and not args.seed:
            print(json.dumps(current_counts(db), ensure_ascii=False))
    finally:
        db.close()


if __name__ == "__main__":
    main()
