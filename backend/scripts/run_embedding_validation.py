"""Phase 6E: one alternate embedding, isolated derived index, immutable SQL corpus."""
from __future__ import annotations
import argparse
import hashlib
import json
import math
import os
import time
from importlib.metadata import version
from pathlib import Path
from datetime import datetime, timezone

from scripts.run_pilot_ablation import load_pilot, sha

EN_MODEL = 'BAAI/bge-small-en-v1.5'
EN_REVISION = '5c38ec7c405ec4b44b94cc5a9bb96e735b38267a'
EXPECTED = 2298


def digest_json(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def check_isolation(current_name, experiment_name, existing_collection):
    if current_name == experiment_name or existing_collection is not None:
        raise ValueError('independent NEW collection required; existing collections are never overwritten')


def snapshot_index(store, chunks, dimension):
    expected = {c.stable_chunk_id: c for c in chunks}
    if len(expected) != EXPECTED or store.count() != EXPECTED:
        raise ValueError('2298 chunk parity failed')
    rows = []
    seen = set()
    for ids in store.iter_id_batches():
        result = store.collection.get(ids=ids, include=['documents', 'metadatas', 'embeddings'])
        for key, text, metadata, vector in zip(result['ids'], result['documents'], result['metadatas'], result['embeddings'], strict=True):
            if key not in expected or key in seen:
                raise ValueError('index identity parity failed')
            chunk = expected[key]
            if text != chunk.text or not store.metadata_matches(metadata, store.chunk_metadata([chunk])[0]):
                raise ValueError('index text/locator parity failed')
            values = [float(v) for v in vector]
            if len(values) != dimension or not all(math.isfinite(v) for v in values):
                raise ValueError('index dimension/finite check failed')
            rows.append((key, text, metadata, values))
            seen.add(key)
    if seen != set(expected):
        raise ValueError('index ID parity failed')
    return dict(count=len(rows), dimension=dimension, sha256=digest_json(sorted(rows)),
                collection=store.collection_name, metadata=store.collection.metadata)


def gold_diff(before, after):
    old = {c['query_id']: c for c in before['query_diagnostics']}
    changes = []
    for c in after['query_diagnostics']:
        b = old[c['query_id']]
        gold = set(c['relevant_chunk_ids'])
        gains = sorted((set(c['candidate_chunk_ids']) - set(b['candidate_chunk_ids'])) & gold)
        losses = sorted((set(b['candidate_chunk_ids']) - set(c['candidate_chunk_ids'])) & gold)
        if gains or losses:
            changes.append(dict(query_id=c['query_id'], query_type=c['query_type'],
                newly_recovered_gold=gains, newly_lost_gold=losses))
    return changes


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--benchmark', required=True)
    parser.add_argument('--manifest', required=True)
    parser.add_argument('--papers', required=True)
    parser.add_argument('--baseline', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    os.environ.update(LLM_API_KEY='', LLM_BASE_URL='http://127.0.0.1:1/v1', RERANKER_ENABLED='false')
    from sqlalchemy import create_engine, select
    from sqlalchemy.orm import Session
    from app.core.config import get_settings
    from app.models.document import Document, DocumentVersion
    from app.services.indexing.version_chunks import membership_query, VersionChunk
    from app.services.evaluation.real_benchmark import validate_queries, evaluate, write_report
    from app.services.retrieval.retrieval_service import ResearchRetrievalService
    from app.vectorstore.chroma_store import ChromaStore
    from app.vectorstore.embeddings import BgeEmbeddingProvider, get_embedding_provider
    baseline = json.loads(Path(args.baseline).read_text())
    frozen_hash = sha(args.benchmark)
    if baseline['benchmark_sha256'] != frozen_hash or baseline['benchmark_sha256_after'] != frozen_hash:
        raise ValueError('baseline frozen benchmark differs')
    if baseline['manifest_sha256'] != sha(args.manifest):
        raise ValueError('corpus manifest differs from Phase 6D')
    for name, checksum in baseline['code_sha256'].items():
        if sha(name) != checksum:
            raise ValueError('Phase 6D implementation changed; baseline reuse rejected')
    settings = get_settings()
    if {k: v for k, v in settings.model_dump().items() if k.startswith('embedding_')} != baseline['embedding']:
        raise ValueError('baseline embedding config differs')
    if settings.rrf_k != baseline['retrieval_config']['rrf_k'] or settings.dense_top_k != baseline['retrieval_config']['dense_top_k']:
        raise ValueError('retrieval config differs')
    for package in ('torch','sentence-transformers','transformers','chromadb'):
        if version(package) != baseline['runtime'][package]:
            raise ValueError('runtime differs from Phase 6D')
    frozen, manifest, raw = load_pilot(args.benchmark, args.manifest, args.papers)
    url = os.environ.get('BENCHMARK_DATABASE_URL', '')
    if not url.startswith('mysql+pymysql://'):
        raise ValueError('isolated MySQL required')
    snapshot = Path(settings.embedding_cache_dir) / 'models--BAAI--bge-small-en-v1.5' / 'snapshots' / EN_REVISION
    if not snapshot.is_dir():
        raise ValueError('download the pinned EN model first')
    dimension = json.loads((snapshot/'config.json').read_text())['hidden_size']
    experiment_settings = settings.model_copy(update={'embedding_model': str(snapshot), 'embedding_dimension': dimension})
    embedding = BgeEmbeddingProvider(experiment_settings)
    embedding.model_name = EN_MODEL  # Canonical collection identity; load the pinned local snapshot.
    current = ChromaStore(get_embedding_provider(settings), create_collection=False)
    experiment = ChromaStore(embedding, create_collection=False)
    check_isolation(current.collection_name, experiment.collection_name, experiment.collection)
    checksums = {**baseline['code_sha256'], str(Path(__file__)): sha(__file__),
                 'app/services/indexing/bm25_index.py': sha('app/services/indexing/bm25_index.py')}
    engine = create_engine(url, pool_pre_ping=True)
    with Session(engine) as db:
        def read_corpus():
            active = set(db.execute(select(Document.id, DocumentVersion.id).join(DocumentVersion,
                (DocumentVersion.document_id == Document.id) & (DocumentVersion.version == Document.current_version))
                .where(Document.status == 'ready')).all())
            if active != {(d.document_id, d.document_version_id) for d in manifest.documents}:
                raise ValueError('active document version set mismatch')
            for d in manifest.documents:
                v = db.get(DocumentVersion, d.document_version_id)
                if v.source_checksum != d.sha256:
                    raise ValueError('SQL source checksum mismatch')
            chunks = [VersionChunk(c,m,v) for c,m,v,d in db.execute(membership_query().where(Document.status == 'ready')).all()]
            chunks.sort(key=lambda c:(c.document_id,c.chunk_index))
            if len(chunks) != EXPECTED:
                raise ValueError('2298 authoritative chunks required')
            fingerprint = digest_json([(c.id,c.stable_chunk_id,c.document_id,c.document_version_id,
                c.chunk_index,c.page_number,c.section_title,c.chunk_hash,c.text) for c in chunks])
            return chunks, fingerprint
        chunks, corpus_hash = read_corpus()
        rows = validate_queries(db, manifest, raw, {})
        if len(rows) != 30 or not all(r['valid'] for r in rows):
            raise ValueError('30 valid human Gold queries required')
        current_before = snapshot_index(current, chunks, settings.embedding_dimension)
        started = time.perf_counter()
        model = embedding._get_model()
        cold_ms = (time.perf_counter()-started)*1000
        if model.get_sentence_embedding_dimension() != dimension:
            raise ValueError('actual model dimension mismatch')
        print(f'Model loaded: {dimension} dimensions; indexing {len(chunks)} existing chunks', flush=True)
        started = time.perf_counter()
        for offset in range(0, len(chunks), current.batch_size):
            experiment.upsert_document_chunks(chunks[offset:offset+current.batch_size])
            print(f'indexed {min(offset+current.batch_size,len(chunks))}/{len(chunks)}',flush=True)
        build_ms = (time.perf_counter()-started)*1000
        experiment_before = snapshot_index(experiment, chunks, dimension)
        print('2298 parity PASS; running EN Dense and Hybrid only', flush=True)
        measured = evaluate(rows, ResearchRetrievalService(db, vector_store=experiment),
            baseline_modes=('dense','hybrid'), progress=lambda m,q: print(f'{m} {q} complete',flush=True))
        db.rollback()
        db.expire_all()
        after_chunks, after_hash = read_corpus()
        if after_hash != corpus_hash:
            raise ValueError('authoritative corpus changed')
        if snapshot_index(current,after_chunks,settings.embedding_dimension) != current_before:
            raise ValueError('current collection changed')
        if snapshot_index(experiment,after_chunks,dimension) != experiment_before:
            raise ValueError('experimental index changed during queries')
    engine.dispose()
    if sha(args.benchmark) != frozen_hash or any(sha(p) != h for p,h in checksums.items()):
        raise ValueError('benchmark or implementation changed during run')
    import torch
    report = dict(status='MEASURED', benchmark_id=frozen['benchmark_id'], benchmark_sha256=frozen_hash,
        benchmark_sha256_after=sha(args.benchmark), baseline_report_sha256=sha(args.baseline),
        manifest_sha256=sha(args.manifest), run_timestamp=datetime.now(timezone.utc).isoformat(),
        corpus_size=19, query_count=30, query_language='English', gold_source='HUMAN-CURATED',
        authoritative_corpus_sha256=corpus_hash, current_index=current_before, experimental_index=experiment_before,
        model=EN_MODEL, model_revision=EN_REVISION, device='cpu', normalize=settings.embedding_normalize,
        embedding_batch_size=settings.embedding_batch_size, max_seq_length=model.max_seq_length,
        query_instruction='none; same raw-query encoding as Phase 6D', code_sha256=checksums,
        runtime={p:version(p) for p in ('torch','sentence-transformers','transformers','chromadb')},
        torch_num_threads=torch.get_num_threads(), torch_interop_threads=torch.get_num_interop_threads(),
        timing=dict(embedding_cold_load_ms=cold_ms,index_build_ms=build_ms,query_repetitions=1,
            query_warmup=False,embedding_warmed_by_index_build=True,download_excluded=True),
        retrieval_config=baseline['retrieval_config'], baseline_source='Phase 6D frozen result; code/config/runtime and corpus checks passed',
        bm25_candidate_recall_at20=baseline['modes']['bm25']['Candidate Recall@20'],
        reranker='NOT RUN', graph='NOT RUN', auto='NOT RUN', embedding_decision='PENDING_REVIEW',
        modes={**{'zh_'+m:baseline['modes'][m] for m in ('dense','hybrid')},
               **{'en_'+m:measured[m] for m in ('dense','hybrid')}},
        gold_diff={m:gold_diff(baseline['modes'][m],measured[m]) for m in ('dense','hybrid')})
    for m in report['modes'].values():
        m['benchmark_sha256'] = frozen_hash
    write_report(report,args.output)
    print(json.dumps({m:{k:v[k] for k in ('Recall@5','Recall@10','MRR@10','Candidate Recall@20','P50 Latency','P95 Latency')} for m,v in report['modes'].items()}),flush=True)


if __name__ == '__main__':
    main()
