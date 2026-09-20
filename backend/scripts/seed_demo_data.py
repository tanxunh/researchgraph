from __future__ import annotations

from app.core.database import SessionLocal, create_db_tables
from app.services.indexing.incremental_indexer import IncrementalIndexer
from app.services.parsing.text_parser import TextParser

DEMO_DOCS = [
    (
        "ProtoNet Few-shot Notes",
        "ProtoNet is a Method for few-shot classification. ProtoNet is evaluated on miniImageNet and reports Accuracy for classification tasks.",
    ),
    (
        "Knowledge Distillation Notes",
        "Knowledge Distillation is a Concept used by compact Method models. Distillation targets few-shot classification and can compare with ProtoNet.",
    ),
    (
        "Retrieval Metrics Notes",
        "Dense retrieval and BM25 are retrieval Concepts. Retrieval experiments report Recall and MRR as Metrics. Graph Enhanced retrieval uses Relation evidence chunks.",
    ),
]


if __name__ == "__main__":
    create_db_tables()
    db = SessionLocal()
    try:
        indexer = IncrementalIndexer()
        for title, text in DEMO_DOCS:
            parsed = TextParser().parse(title=title, text=text, source_uri=f"demo:{title}")
            print(indexer.import_parsed(db, parsed))
    finally:
        db.close()
