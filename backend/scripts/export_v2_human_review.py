"""Export pending frozen TEST candidates with exact evidence text for human review."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.document import DocumentChunk
from app.schemas.real_benchmark import V2ResearchQuery


def quote(text: str) -> list[str]:
    return [f'> {line}' if line else '>' for line in text.strip().splitlines()]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', default='../benchmarks/real_research/v2')
    parser.add_argument('--output', default='../benchmarks/real_research/v2/HUMAN_TEST_REVIEW.md')
    args = parser.parse_args()
    root = Path(args.root).resolve()
    rows = [
        V2ResearchQuery.model_validate(json.loads(line))
        for line in (root / 'queries_test.jsonl').read_text(encoding='utf-8').splitlines()
        if line.strip()
    ]
    pending = [row for row in rows if not row.human_verified]
    settings = get_settings()
    if not settings.database_url.startswith('mysql+pymysql://'):
        raise ValueError('Human review export requires the isolated V2 MySQL corpus')
    engine = create_engine(settings.database_url, pool_pre_ping=True)
    lines = [
        '# ResearchGraph V2 Test Annotation Review', '',
        f'Pending TEST candidates: {len(pending)}', '',
        'The 35/40 split is already frozen. Review must not move, delete, or replace hard queries based on retrieval outcomes.', '',
        'For each item, verify that the question is meaningful and that the listed chunks jointly contain the complete answer. '
        'Choose `APPROVE`, `REVISE_GOLD`, or `REJECT_INVALID_QUERY`, and add a short note.', '',
    ]
    try:
        with Session(engine) as db:
            for query in pending:
                lines.extend([
                    f'## {query.query_id} — {query.query_type}', '',
                    f'**Question:** {query.query}', '',
                    f'**Document scope:** {query.document_scope}', '',
                ])
                for gold in query.gold_evidence:
                    chunk = db.scalar(select(DocumentChunk).where(
                        DocumentChunk.stable_chunk_id == gold.chunk_id,
                        DocumentChunk.document_version_id == gold.document_version_id,
                    ))
                    if chunk is None or chunk.document_id != gold.document_id:
                        raise ValueError(f'unresolved_review_locator: {query.query_id}/{gold.chunk_id}')
                    lines.extend([
                        f"### {gold.paper_id} · page {gold.page} · `{gold.chunk_id}`", '',
                        *quote(chunk.text), '',
                    ])
                lines.extend(['- Decision: PENDING', '- Reviewer note:', ''])
    finally:
        engine.dispose()
    output = Path(args.output).resolve()
    output.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print(json.dumps({'pending_queries': len(pending), 'output': output.name}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
