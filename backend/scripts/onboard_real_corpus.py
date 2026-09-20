"""Local PDF onboarding through the existing ingestion pipeline; no Gold or LLM."""
from __future__ import annotations
import argparse
import hashlib
import html
import io
import json
import time
from pathlib import Path
from dataclasses import replace
from collections import Counter


def discover(papers):
    from pypdf import PdfReader
    from app.services.parsing.pdf_parser import PdfParser
    from app.services.chunking.text_chunker import TextChunker
    rows, hashes = [], set()
    for path in sorted(Path(papers).iterdir(), key=lambda p: (p.name.casefold(), p.name)):
        if not path.is_file() or path.suffix.lower() != '.pdf':
            continue
        data = path.read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        row = dict(source_filename=path.name, source_bytes=len(data), source_sha256=digest,
                   duplicate=digest in hashes, error=None)
        hashes.add(digest)
        try:
            parsed = PdfParser().parse(path.name, data)
            reader = PdfReader(io.BytesIO(data))
            metadata_title = str((reader.metadata or {}).get('/Title') or '').strip()
            title = ' '.join(html.unescape(metadata_title).split())
            if not title or title.lower() in ('untitled', 'microsoft word'):
                title = path.stem.replace('_', ' ')
                title_source = 'filename_fallback'
            else:
                title_source = 'pdf_metadata'
            row.update(title=title[:255], title_source=title_source,
                       page_count=parsed.metadata['page_count'], text_characters=len(parsed.text),
                       planned_chunks=len(TextChunker().chunk(parsed)),
                       language_if_available=str(reader.trailer['/Root'].get('/Lang') or '') or None)
        except Exception as exc:
            row['error'] = type(exc).__name__ + ': ' + str(exc)[:250]
        rows.append(row)
        print(json.dumps({'parsed': path.name, 'error': row['error']}), flush=True)
    return rows


def assign_ids(rows, previous):
    old = {r['source_sha256']: r['benchmark_document_id'] for r in previous}
    next_id = max([int(value[1:]) for value in old.values()] or [0]) + 1
    for row in rows:
        digest = row['source_sha256']
        if digest not in old:
            old[digest] = f'P{next_id:03d}'
            next_id += 1
        row['benchmark_document_id'] = old[digest]


def validate_exports(documents, catalog):
    by_id = {d['benchmark_document_id']: d for d in documents if d['index_status'] == 'ready'}
    seen, counts = set(), Counter()
    for row in catalog:
        doc = by_id[row['benchmark_document_id']]
        key = (row['document_id'], row['document_version_id'], row['chunk_id'])
        if key in seen or row['document_id'] != doc['document_id'] or row['document_version_id'] != doc['document_version_id']:
            raise ValueError('Catalog identity mismatch or duplicate')
        if not row['text_preview'] or len(row['text_preview']) > 240 or row['ordinal'] < 0:
            raise ValueError('Invalid annotation preview/ordinal')
        if row['page'] is not None and not 1 <= row['page'] <= doc['page_count']:
            raise ValueError('Invalid page locator')
        seen.add(key)
        counts[row['benchmark_document_id']] += 1
    for key, doc in by_id.items():
        if counts[key] != doc['chunk_count'] or counts[key] < 1:
            raise ValueError('Catalog count does not match current version')


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--papers', default='/papers')
    parser.add_argument('--output', default='/output')
    parser.add_argument('--manifest-root', default='/corpus')
    parser.add_argument('--import-corpus', action='store_true')
    parser.add_argument('--use-discovery', action='store_true')
    args = parser.parse_args()
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    if args.use_discovery:
        rows = json.loads((output/'corpus_discovery.json').read_text(encoding='utf-8'))['files']
        actual = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in Path(args.papers).iterdir()
                  if p.is_file() and p.suffix.lower() == '.pdf'}
        if actual != {r['source_filename']: r['source_sha256'] for r in rows}:
            raise ValueError('Corpus changed since discovery; rerun discovery')
        for row in rows:
            if row.get('title'):
                row['title'] = html.unescape(row['title'])
    else:
        rows = discover(args.papers)
    previous_path = output / 'document_manifest.json'
    previous = json.loads(previous_path.read_text(encoding='utf-8-sig')).get('documents', []) if previous_path.exists() else []
    assign_ids(rows, previous)
    write_json(output / 'corpus_discovery.json', {'pdf_count': len(rows), 'files': rows})
    summary = dict(discovered=len(rows), duplicates=sum(r['duplicate'] for r in rows),
                   parse_failed=sum(bool(r['error']) for r in rows),
                   planned_chunks=sum(r.get('planned_chunks', 0) for r in rows if not r['duplicate']))
    print(json.dumps(summary), flush=True)
    if not args.import_corpus:
        return 0
    from sqlalchemy import select
    from app.core.config import get_settings
    from app.core.database import SessionLocal, create_db_tables
    from app.models.document import Document, DocumentVersion
    from app.services.indexing.ingestion import DocumentIngestion
    from app.services.indexing.incremental_indexer import IncrementalIndexer
    from app.services.indexing.version_chunks import version_chunks
    from app.services.graph.extraction_schema import ChunkGraphExtraction
    from app.services.retrieval.retrieval_service import ResearchRetrievalService
    from app.vectorstore.embeddings import get_embedding_provider
    from app.vectorstore.chroma_store import ChromaStore
    settings = get_settings()
    if settings.embedding_provider != 'bge' or settings.embedding_model != 'BAAI/bge-small-zh-v1.5':
        raise ValueError('Onboarding requires the existing production BGE model')
    if not settings.database_url.startswith('mysql+pymysql://'):
        raise ValueError('Onboarding requires MySQL')

    class DeferredGraph:
        def extract(self, text):
            return ChunkGraphExtraction(entities=[], relations=[])

    # Empty extraction is an explicit deferred stage, not a claim that real Graph was built.
    started = time.perf_counter()
    provider = get_embedding_provider()
    provider._get_model()
    load_ms = (time.perf_counter()-started)*1000
    store = ChromaStore(provider)
    create_db_tables()
    ingestion = DocumentIngestion(IncrementalIndexer(store, DeferredGraph()))
    documents, catalog = [], []
    for row in rows:
        if row['duplicate']:
            continue
        entry = {**row, 'document_id': None, 'document_version_id': None,
                 'chunk_count': 0, 'index_status': 'failed',
                 'graph_status': 'GRAPH_INDEX_PENDING_EXTERNAL_LLM'}
        documents.append(entry)
        if row['error']:
            continue
        with SessionLocal() as db:
            try:
                # Reuse existing source identity when these exact raw PDF bytes already exist.
                existing = db.execute(select(Document, DocumentVersion).join(DocumentVersion,
                    DocumentVersion.document_id == Document.id).where(
                    Document.source_type == 'pdf', DocumentVersion.source_checksum == row['source_sha256'],
                    DocumentVersion.version == Document.current_version)).all()
                if len(existing) > 1:
                    raise ValueError('Multiple existing documents share these bytes; explicit identity review required')
                uri = existing[0][0].source_uri if existing else 'benchmark:pdf:sha256:' + row['source_sha256']
                title = existing[0][1].title if existing else row['title']
                result = ingestion.import_bytes(db, (Path(args.papers)/row['source_filename']).read_bytes(),
                                                'pdf', uri, title, 'application/pdf')
                document = db.get(Document, result['document_id'])
                chunks = version_chunks(db, document.id, document.current_version)
                if document.status != 'ready' or not chunks or not store.verify_document_chunks(chunks):
                    raise ValueError('Current version/vector verification failed')
                version = chunks[0].version
                if version.source_checksum != row['source_sha256'] or not version.source_storage_key:
                    raise ValueError('Raw source reference mismatch')
                ingestion.storage.load(version.source_storage_key)
                entry.update(document_id=document.id, document_version_id=version.id, title=version.title,
                             chunk_count=len(chunks), index_status='ready',
                             import_action='reused' if existing else result['index_action'], error=None,
                             chroma_verified=True, raw_source_verified=True)
                catalog.extend(dict(benchmark_document_id=row['benchmark_document_id'], document_id=document.id,
                    document_version_id=version.id, chunk_id=c.stable_chunk_id, ordinal=c.chunk_index,
                    page=c.page_number, section=c.section_title,
                    text_preview=' '.join(c.text.split())[:240]) for c in chunks)
                print(json.dumps({k: entry[k] for k in ('benchmark_document_id','title','chunk_count','index_status','import_action')}), flush=True)
            except Exception as exc:
                db.rollback()
                entry['error'] = type(exc).__name__ + ': ' + str(exc)[:250]
                print(json.dumps({'failed': row['benchmark_document_id'], 'error': entry['error']}), flush=True)
        write_json(previous_path, {'benchmark_version': 'real-research-v1', 'documents': documents})
    validate_exports(documents, catalog)
    (output/'annotation_catalog.jsonl').write_text('\n'.join(json.dumps(c, ensure_ascii=False) for c in catalog)+'\n', encoding='utf-8')
    write_json(output/'queries.template.json', {
        'template_only': True, 'not_a_formal_query': True,
        'query_types': ['factual','exact_term','semantic','relational','cross_document','multi_hop'],
        'gold_evidence_fields': ['document_id','document_version_id','chunk_id','page','section'],
        'example': dict(query_id='EXAMPLE_ONLY', question='REPLACE WITH A HUMAN RESEARCH QUESTION',
            query_type='semantic', language='en', gold_document_ids=[], gold_evidence=[],
            annotation_status='pending', annotator='', notes='', annotation_notes=''),
        'notes_mapping': 'Copy notes to annotation_notes and omit notes when submitting to the Phase 6 strict schema.'})
    ready = [d for d in documents if d['index_status'] == 'ready']
    # Companion manifest directly accepted by the existing Phase 6 runner; no formal queries generated.
    manifest_root = Path(args.manifest_root)
    write_json(manifest_root/'manifest.json', dict(benchmark_version='real-research-v1', corpus_kind='real_papers',
        queries_path='queries.jsonl', documents=[dict(document_id=d['document_id'], document_version_id=d['document_version_id'],
        title=d['title'], source_reference='local-user-provided:'+d['source_filename'],
        path='papers/'+d['source_filename'], sha256=d['source_sha256']) for d in ready]))
    if not (manifest_root/'queries.jsonl').exists():
        (manifest_root/'queries.jsonl').write_text('', encoding='utf-8')
    smoke = []
    with SessionLocal() as db:
        service = ResearchRetrievalService(db, store)
        for query in ('computation offloading', 'resource allocation', 'UAV'):
            for mode in ('bm25','dense','hybrid'):
                result = service.search(query, mode=mode, top_k=3, rerank=False)
                ids = [c['document']['id'] for c in result['results']]
                if not ids or not set(ids).issubset({d['document_id'] for d in ready}):
                    raise ValueError('Smoke results missing or outside corpus')
                smoke.append(dict(query=query, mode=mode, returned_document_ids=ids))
    summary.update(imported=sum(d.get('import_action') == 'created' for d in documents),
        reused=sum(d.get('import_action') == 'reused' for d in documents), failed=len(documents)-len(ready),
        chunk_count=len(catalog), embedding_model=provider.model_name, dimension=provider.dimension,
        device=settings.embedding_device, cold_load_ms=round(load_ms,3),
        graph_status='GRAPH_INDEX_PENDING_EXTERNAL_LLM', external_llm_calls=0,
        graph_estimated_max_calls=len({c['chunk_id'] for c in catalog}), smoke=smoke)
    write_json(output/'onboarding_report.json', summary)
    print(json.dumps(summary), flush=True)
    return 0 if not summary['failed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
