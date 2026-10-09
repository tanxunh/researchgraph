"""B3 query-only encoding and same-graph Dense search; offline and DEV-only."""
import os
os.environ.update(LLM_API_KEY="", GRAPH_EXTRACTION_ENABLED="false", HF_HUB_OFFLINE="1",
                  TRANSFORMERS_OFFLINE="1", ANONYMIZED_TELEMETRY="false")
import sys, types, json, time, hashlib, argparse
from pathlib import Path
from importlib.metadata import version
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / "benchmarks/real_research/v2"
OUT = ROOT / "artifacts/evaluation_v2"
pkg = types.ModuleType("app.services.evaluation")
pkg.__path__ = [str(ROOT / "backend/app/services/evaluation")]
sys.modules["app.services.evaluation"] = pkg
from app.services.evaluation.query_instruction import (
    MODEL, REVISION, INSTRUCTION, STRATEGIES, SOURCE, encoded_text, fingerprint, summary, paired_case)
from app.services.evaluation.ann_exactness import vector_fingerprint, percentile

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def save(path, value):
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)

def inputs():
    previous = json.loads((OUT / "b2_ef_sweep.json").read_text(encoding="utf-8"))
    manifest = previous["identity"]
    def guard():
        for name, digest in previous["protected_hashes"].items():
            assert sha(ROOT/name) == digest, name
        for name, digest in manifest["graph_hashes"].items():
            assert sha(ROOT/manifest["snapshot_path"]/name) == digest, name
        assert sha(BASE/"corpus_manifest.json") == manifest["identity"]["corpus_hash"]
    guard()
    queries = [json.loads(line) for line in (BASE/"queries_dev.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    export = json.loads((ROOT/".tmp/v2b2/export.json").read_text(encoding="utf-8"))
    assert len(queries) == 35 and queries == export["queries"]
    return previous, manifest, queries, export, guard

def encode():
    output = OUT/"b3_query_encoding.json"
    assert not output.exists(), "encoding_already_completed"
    previous, manifest, queries, export, guard = inputs()
    from sentence_transformers import SentenceTransformer
    import torch
    t = time.perf_counter()
    model = SentenceTransformer(MODEL, revision=REVISION, device="cpu",
                                cache_folder="/models/model_cache", local_files_only=True)
    cold = (time.perf_counter()-t)*1000
    assert model[0].auto_model.config._commit_hash == REVISION
    assert model.get_sentence_embedding_dimension() == 512
    assert model[1].pooling_mode_cls_token and not model[1].pooling_mode_mean_tokens
    assert model[2].__class__.__name__ == "Normalize"
    assert model.default_prompt_name is None and not model.prompts
    original_tokenize = model.tokenize
    observed = []
    def capture(texts, *args, **kwargs):
        observed.extend(texts)
        return original_tokenize(texts, *args, **kwargs)
    model.tokenize = capture
    vectors, detail, timings = {}, {}, {s:[[] for _ in queries] for s in STRATEGIES}
    for strategy in STRATEGIES:
        texts = [encoded_text(q["query"], strategy) for q in queries]
        observed.clear()
        v = model.encode(texts, batch_size=32, normalize_embeddings=True, show_progress_bar=False)
        assert sorted(observed) == sorted(texts), "encoded_text_not_seen_by_tokenizer"
        assert v.shape == (35,512) and np.isfinite(v).all()
        assert np.allclose(np.linalg.norm(v,axis=1),1,atol=1e-6), "normalization_changed"
        vectors[strategy] = v
        detail[strategy] = []
        for q,text,vec in zip(queries,texts,v):
            token_ids = model.tokenizer(text, truncation=False)["input_ids"]
            assert len(token_ids) <= model.max_seq_length
            detail[strategy].append(dict(query_id=q["query_id"], raw_query=q["query"],
                actual_encoded_text=text, token_count=len(token_ids), vector_dimension=len(vec),
                vector_norm=float(np.linalg.norm(vec)), tokenizer_input_verified=True))
        for text in texts:
            model.encode([text], batch_size=32, normalize_embeddings=True, show_progress_bar=False)
        print("ENCODING VERIFIED", strategy, flush=True)
    assert all(not np.array_equal(a,b) for a,b in zip(vectors["raw"],vectors["official_instruction"])), "identical_strategy_vectors"
    frozen = np.load(ROOT/".tmp/v2b2/vectors.npz")["query_vectors"]
    assert np.allclose(vectors["raw"], frozen, atol=1e-5), "raw_encoding_contract_drift"
    for round_no in range(3):
        for strategy in STRATEGIES[::1 if round_no%2 == 0 else -1]:
            for i,q in enumerate(queries):
                text = encoded_text(q["query"],strategy)
                t = time.perf_counter_ns()
                actual = model.encode([text], batch_size=32, normalize_embeddings=True, show_progress_bar=False)[0]
                elapsed = (time.perf_counter_ns()-t)/1e6
                assert np.allclose(actual, vectors[strategy][i], atol=1e-5)
                timings[strategy][i].append(elapsed)
        print("ENCODING LATENCY ROUND",round_no+1,flush=True)
    guard()
    np.savez(OUT/"b3_query_vectors.npz",**vectors)
    result = dict(status="COMPLETE", source=SOURCE, instruction=INSTRUCTION, model=MODEL, revision=REVISION,
        samples=detail, query_encoding_latency_ms=timings, rounds=3, warmup_queries_per_strategy=35,
        cold_load_ms_excluded=cold, raw_max_abs_error_vs_frozen=float(np.max(np.abs(vectors["raw"]-frozen))),
        vectors_sha256=sha(OUT/"b3_query_vectors.npz"),
        query_vector_fingerprints={s:vector_fingerprint([q["query_id"] for q in queries],v) for s,v in vectors.items()},
        packages={p:version(p) for p in ("sentence-transformers","transformers","torch","numpy")},
        torch_threads=torch.get_num_threads(), cpu_only=True, document_encoding_calls=0)
    save(output,result)
    print("QUERY ENCODING COMPLETE",flush=True)

def search():
    target = OUT/"b3_query_instruction.json"
    assert not target.exists(), "ablation_already_completed"
    previous, manifest, queries, export, guard = inputs()
    enc = json.loads((OUT/"b3_query_encoding.json").read_text(encoding="utf-8"))
    assert sha(OUT/"b3_query_vectors.npz") == enc["vectors_sha256"]
    with np.load(OUT/"b3_query_vectors.npz") as archive:
        vectors = {strategy: archive[strategy].copy() for strategy in STRATEGIES}
    for s in STRATEGIES:
        assert vector_fingerprint([q["query_id"] for q in queries],vectors[s]) == enc["query_vector_fingerprints"][s]
    import chromadb
    from chromadb.config import Settings
    from chromadb.segment import VectorReader
    assert chromadb.__version__ == "0.5.23" and version("chroma-hnswlib") == "0.7.6"
    t = time.perf_counter()
    client = chromadb.PersistentClient(path=str(ROOT/manifest["snapshot_path"]),settings=Settings(anonymized_telemetry=False))
    coll = client.get_collection(export["collection"],embedding_function=None)
    stored = coll.get(include=["embeddings","metadatas","documents"])
    assert coll.count() == 3837 and vector_fingerprint(stored["ids"],stored["embeddings"]) == manifest["identity"]["vector_fingerprint"]
    metadata = {sid:{"metadata":stored["metadatas"][i],"document":stored["documents"][i]} for i,sid in enumerate(stored["ids"])}
    assert hashlib.sha256(json.dumps(metadata,sort_keys=True).encode()).hexdigest() == manifest["metadata_text_hash"]
    query_lists = {s: vectors[s].tolist() for s in STRATEGIES}
    def query(strategy,i,track):
        kw = {} if track=="global" else {"where":{"document_id":{"$in":queries[i]["document_scope"]}}}
        return coll.query(query_embeddings=[query_lists[strategy][i]],n_results=200,include=["distances"],**kw)["ids"][0]
    query("raw",0,"global")
    segment = client._server._manager.get_segment(coll.id,VectorReader)
    index = segment._index
    assert index.ef == 10 and segment._params.M == 16 and segment._params.construction_ef == 100 and segment._params.space == "l2"
    mapping = dict(segment._id_to_label)
    assert len(mapping) == 3800 and len(segment._curr_batch._ids_to_records) == 37
    cold = (time.perf_counter()-t)*1000
    cases = {s:{tr:[] for tr in ("global","scoped")} for s in STRATEGIES}
    for s in STRATEGIES:
        for track in ("global","scoped"):
            for i,q in enumerate(queries):
                ids = query(s,i,track)
                if s=="raw" and track=="global":
                    assert ids[:50] == previous["cases"]["10"][i]["ids"][:50], "raw_top50_baseline_drift"
                if track=="scoped":
                    assert all(metadata[sid]["metadata"]["document_id"] in q["document_scope"] for sid in ids)
                cases[s][track].append(dict(query_id=q["query_id"],query_type=q["query_type"],
                    ids=ids,gold=[g["chunk_id"] for g in q["gold_evidence"]],latency_ms=[]))
            print("SEARCH WARMUP",s,track,flush=True)
    for round_no in range(3):
        for s in STRATEGIES[::1 if round_no%2==0 else -1]:
            for track in ("global","scoped"):
                for i,q in enumerate(queries):
                    t = time.perf_counter_ns()
                    ids = query(s,i,track)
                    elapsed = (time.perf_counter_ns()-t)/1e6
                    row = cases[s][track][i]
                    assert ids == row["ids"] and index.ef == 10
                    row["latency_ms"].append(elapsed)
        guard()
        assert segment._index is index and segment._id_to_label == mapping
        save(OUT/"b3_search_progress.json",dict(completed_rounds=round_no+1,cases=cases))
        print("DENSE SEARCH ROUND",round_no+1,flush=True)
    experiments = []
    for s in STRATEGIES:
        config = dict(embedding_model=MODEL,embedding_revision=REVISION,query_strategy=s,
            query_encoding_strategy=s,query_instruction=INSTRUCTION if s!="raw" else "",
            document_strategy="raw",pooling="CLS",normalization=True,dimension=512,metric="squared_l2",
            n_results=200,search_ef=10,chunking_config_hash=fingerprint(json.loads((BASE/"results/dev_baseline_frozen_gold.json").read_text())["metadata"]["chunking"]),
            chunking_config=json.loads((BASE/"results/dev_baseline_frozen_gold.json").read_text())["metadata"]["chunking"],
            chunking_code_sha256=previous["protected_hashes"]["backend/app/services/chunking/text_chunker.py"],
            corpus_manifest_hash=manifest["identity"]["corpus_hash"])
        tracks = {}
        for tr,rows in cases[s].items():
            tracks[tr] = dict(overall=summary(rows),by_type={ty:summary([r for r in rows if r["query_type"]==ty]) for ty in sorted({q["query_type"] for q in queries})})
        samples = [ms for row in enc["query_encoding_latency_ms"][s] for ms in row]
        experiments.append(dict(strategy=s,config=config,config_fingerprint=fingerprint(config),tracks=tracks,
            encoding_latency=dict(p50=percentile(samples,.5),p95=percentile(samples,.95)),cases=cases[s]))
    pairs = [paired_case(q,a["ids"],b["ids"]) for q,a,b in zip(queries,cases["raw"]["global"],cases["official_instruction"]["global"])]
    stored_after = coll.get(include=["embeddings"])
    assert vector_fingerprint(stored_after["ids"],stored_after["embeddings"]) == manifest["identity"]["vector_fingerprint"]
    guard()
    result = dict(status="COMPLETE",official_contract=dict(source=SOURCE,instruction=INSTRUCTION,
        no_instruction_allowed=True,query_only=True,document_instruction=False,v15_reduced_instruction_dependence=True),
        identity=manifest,collection_name=coll.name,collection_id=str(coll.id),protected_hashes=previous["protected_hashes"],
        encoding_artifact="artifacts/evaluation_v2/b3_query_encoding.json",experiments=experiments,paired=pairs,
        paired_classification_rule="lexicographic (CR50, CR20, R10, MRR10); UNCHANGED means selected metrics equal, not identical full ranks",
        candidate_changes={str(k):{"new":sum(len(p[f"new_gold{k}"]) for p in pairs),"lost":sum(len(p[f"lost_gold{k}"]) for p in pairs)} for k in (20,50)},
        protocol=dict(rounds=3,warmup_queries_per_group=35,search_latency="Local Chroma collection.query including SQLite filter/HNSW/buffer merge, excludes embedding/HTTP/MySQL/metric calculation",
                      encoding_latency="single-query model.encode, three rounds; model load and 35-query warmup excluded; measured separately from search, not contiguous end-to-end",
                      index_load_ms_excluded=cold,packages={"chromadb":chromadb.__version__,"chroma-hnswlib":version("chroma-hnswlib"),"numpy":np.__version__}),
        integrity=dict(dev_frozen=True,gold_unchanged=True,test_untouched=True,test_hash_only=True,test_ranking_read=False,
                       document_vectors_unchanged=True,same_graph=True,embedding_model_unchanged=True,production_changed=False,
                       reranker_involved=False,hybrid_run=False,external_llm_calls=0))
    save(target,result)
    print("B3 SEARCH COMPLETE",json.dumps({e["strategy"]:e["tracks"] for e in experiments}),flush=True)

if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("stage",choices=["encode","search"])
    args=parser.parse_args()
    try:
        (encode if args.stage=="encode" else search)()
    except Exception as exc:
        save(OUT/f"b3_{args.stage}_failure_{time.time_ns()}.json",dict(status="FAILED",error_type=type(exc).__name__,error=str(exc)))
        raise

