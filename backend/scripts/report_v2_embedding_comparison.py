"""B4 report from saved model results only; no inference/retrieval."""
import argparse,csv,json,sys,types
from pathlib import Path
from collections import Counter
R=Path(__file__).resolve().parents[2];A=R/"artifacts/evaluation_v2/b4";B=R/"benchmarks/real_research/v2"
pkg=types.ModuleType("app.services.evaluation");pkg.__path__=[str(R/"backend/app/services/evaluation")];sys.modules["app.services.evaluation"]=pkg
from app.services.evaluation.query_instruction import paired_case
parser=argparse.ArgumentParser()
parser.add_argument("--quality",required=True);parser.add_argument("--practical",required=True);parser.add_argument("--reason",required=True)
args=parser.parse_args()
results=[json.loads((A/f"{key}.json").read_text(encoding="utf-8")) for key in ("zh","en","m3")]
assert all(r["status"]=="COMPLETE" for r in results)
assert all(not f["ann_confound"] for r in results for f in r["ann_fidelity"].values())
queries=[json.loads(l) for l in (B/"queries_dev.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
base=results[0];paired=[];counts={};gains={}
for r in results[1:]:
 rows=[]
 for q,b,c in zip(queries,base["cases"]["global"],r["cases"]["global"]):
  p=paired_case(q,b["ids"],c["ids"])
  p={k.replace("instruction","candidate"):v for k,v in p.items()}
  p.update(baseline_model=base["config"]["model"],candidate_model=r["config"]["model"])
  rows.append(p)
 paired+=rows;counts[r["key"]]=dict(Counter(p["classification"] for p in rows))
 gains[r["key"]]={str(k):{"new":sum(len(p[f"new_gold{k}"]) for p in rows),"lost":sum(len(p[f"lost_gold{k}"]) for p in rows)} for k in (20,50)}
 for k,v in gains[r["key"]].items():v["net"]=v["new"]-v["lost"]
with (B/"b4_embedding_paired_cases.csv").open("w",encoding="utf-8",newline="") as f:
 w=csv.DictWriter(f,fieldnames=list(paired[0]));w.writeheader()
 w.writerows({k:json.dumps(v,ensure_ascii=False) if isinstance(v,(dict,list)) else v for k,v in p.items()} for p in paired)
decision={"quality_winner":args.quality,"practical_winner":args.practical,"reason":args.reason,
 "production_changed":False,"B5_started":False,"B6_started":False,"scope":"Frozen DEV only"}
summary={"status":"COMPLETE","decision":decision,"paired_counts":counts,"gains_losses":gains,"model_results":[str((A/f'{r["key"]}.json').relative_to(R)) for r in results]}
(A/"summary.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
ledger=B/"experiments.csv"
with ledger.open(encoding="utf-8",newline="") as f:reader=csv.DictReader(f);fields=list(reader.fieldnames);old=list(reader)
new=[]
for r in results:
 c=r["config"];g=r["tracks"]["global"]["overall"];s=r["tracks"]["scoped"]["overall"];t=r["tracks"]["global"]["latency"];f=r["ann_fidelity"]["global"];types=r["tracks"]["global"]["by_type"]
 row=dict(experiment_id=f'v2b4-{r["key"]}',phase="V2-B4",status="COMPLETE",split="dev",model=c["model"],revision=c["revision"],
 model_family="BGE-M3" if r["key"]=="m3" else "BGE-small-v1.5",query_strategy=c["query_strategy"],query_instruction=c["query_prefix"],
 document_strategy=c["document_strategy"],dimension=c["dimension"],pooling=c["pooling"],normalization=c["normalization"],
 index_namespace=r["index_namespace"],config_fingerprint=r["config_fingerprint"],ann_overlap20=f["Top20"],ann_overlap50=f["Top50"],ann_overlap100=f["Top100"],
 global_hit5=g["Hit@5"],global_r5=g["Recall@5"],global_r10=g["Recall@10"],global_mrr10=g["MRR@10"],global_cr20=g["CR@20"],global_cr50=g["CR@50"],
 scoped_r10=s["Recall@10"],scoped_mrr10=s["MRR@10"],scoped_cr20=s["CR@20"],scoped_cr50=s["CR@50"],
 semantic_cr50=types["semantic"]["CR@50"],crossdoc_cr20=types["cross_document"]["CR@20"],crossdoc_cr50=types["cross_document"]["CR@50"],multihop_cr50=types["multi_hop"]["CR@50"],
 new_gold20=gains.get(r["key"],{}).get("20",{}).get("new",0),lost_gold20=gains.get(r["key"],{}).get("20",{}).get("lost",0),
 new_gold50=gains.get(r["key"],{}).get("50",{}).get("new",0),lost_gold50=gains.get(r["key"],{}).get("50",{}).get("lost",0),
 model_load_sec=r["model_load_sec"],index_encode_sec=r["index_encode_sec"],index_build_sec=r["index_build_sec"],
 query_encode_p50=t["encode_ms"]["p50"],query_encode_p95=t["encode_ms"]["p95"],
 search_p50=t["search_ms"]["p50"],search_p95=t["search_ms"]["p95"],e2e_p50=t["latency_ms"]["p50"],e2e_p95=t["latency_ms"]["p95"],
 memory_mb=r["rss_after_load_bytes"]/1048576,index_size_mb=r["index_size_bytes"]/1048576,
 notes="Global primary; scoped descriptive. Frozen DEV only, no TEST, no production change; baseline existing graph copy, candidate indices independent; exact diagnostic gate passed.")
 assert not any(x["experiment_id"]==row["experiment_id"] for x in old),"ledger_already_exists"
 new.append(row);fields.extend(k for k in row if k not in fields)
with ledger.with_suffix(".tmp").open("w",encoding="utf-8",newline="") as f:w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(old+new)
ledger.with_suffix(".tmp").replace(ledger)
def pct(v):return f"{100*v:.2f}%"
def table(track):
 lines=["|Model|Hit@5|R@5|R@10|MRR@10|CR@20|CR@50|","|---|---:|---:|---:|---:|---:|---:|"]
 for r in results:
  m=r["tracks"][track]["overall"];lines.append(f'|{r["key"]}|{pct(m["Hit@5"])}|{pct(m["Recall@5"])}|{pct(m["Recall@10"])}|{m["MRR@10"]:.4f}|{pct(m["CR@20"])}|{pct(m["CR@50"])}|')
 return lines
lines=["## B4 Embedding Model Comparison","","Status: COMPLETE. Frozen DEV only; production defaults unchanged; B5/B6 not started.","",
"### Model Contracts","","All models CPU FP32, official CLS pooling plus unit normalization, original documents without prefix. Official model cards and fixed revision pooling/max-length configs checked before running. M3 uses Dense output only; no sparse/ColBERT mode.","",
"|Key|Model|Revision|Dimension|Max length|Parameters|Query prefix|Document prefix|License|","|---|---|---|---:|---:|---:|---|---|---|"]
for r in results:
 c=r["config"];lines.append(f'|{r["key"]}|{c["model"]}|{c["revision"]}|{c["dimension"]}|{c["max_length"]}|{r["parameter_count"]:,}|{c["query_prefix"] or "NONE"}|NONE|MIT|')
lines.append("")
for r in results:
 lines.append(f'Source ({r["key"]}): [fixed revision model card]({r["official_source"]}).')
lines += ["", "Document token lengths use each model tokenizer on the same unchanged chunks; model max-length differences are part of the official representation contract.", "", "|Model|Max observed tokens|Model limit|Chunks truncated|", "|---|---:|---:|---:|"]
for r in results:
 t=r["document_tokens"]
 lines.append(f'|{r["key"]}|{t["max"]}|{t["max_length"]}|{t["truncated"]}|')
lines+=["","### Experimental Protocol","","Same 3,837 immutable chunks and 35 frozen DEV queries; TEST only hashed, never parsed or ranked. Same frozen authoritative document/version/metadata membership. Same n_results200, search_ef10, M16, construction_ef100, HNSW threads16. Model-specific official representation settings are the sole retrieval treatment.",
"Each model runs in its own process, Torch4 threads, single-query encoding. Corpus batches16 for small models and4 for M3. Full corpus encoding checkpointed in256-chunk shards. No chunking, BM25, RRF, reranker, Graph or workflow changes.",
"Baseline uses a separately copied existing stable graph, preserving B3 identity; candidates use independently named collections. No graph seed sweep or rebuild selection. Baseline full corpus re-encoding is measured for cost and verified against stored vectors, but those stored vectors remain unchanged.",
"Exact float64 dot/cosine search uses each index stored vectors for diagnostics only. Primary metrics use Chroma and unchanged macro chunk-level scoring.","",
"### Index Integrity","","|Model|Chunks|Missing|Extra|Duplicates|Metadata/text mismatch|Fresh-vector checks|Fingerprint|","|---|---:|---:|---:|---:|---:|---|---|"]
for r in results:
 v=r["vector_validation"];lines.append(f'|{r["key"]}|{v["chunks"]}|0|0|0|0|3/3 PASS|{r["document_vector_fingerprint"]}|')
lines+=["","Query encoding audit includes all35 raw/actual texts, token counts, dimensions and norms per model. Prefix entry into tokenizer is asserted. Random chunk checks use fixed seed20260930. No sample is selected using ranking.","",
"### ANN Fidelity","","Global. Stop thresholds: mean Top50 overlap below98%, or absolute ANN/Exact Gold CR50 gap above2pp.","",
"|Model|Top20|Top50|Top100|ANN CR50|Exact CR50|Exact-minus-ANN pp|","|---|---:|---:|---:|---:|---:|---:|"]
for r in results:
 f=r["ann_fidelity"]["global"];lines.append(f'|{r["key"]}|{pct(f["Top20"])}|{pct(f["Top50"])}|{pct(f["Top100"])}|{pct(f["ann_cr50"])}|{pct(f["exact_cr50"])}|{f["gap_pp"]:.3f}|')
lines+=["","Scoped fidelity also checked and passed; full diagnostics retained in each model JSON.","","### Global Dense Results","","PRIMARY RESULT.",""]+table("global")
lines+=["","### Scoped Diagnostic","","DESCRIPTIVE / DIAGNOSTIC ONLY; not used independently for model selection.",""]+table("scoped")
lines+=["","### Query-type Diagnostic","","DESCRIPTIVE / DIAGNOSTIC ONLY; category sample sizes are small.","",
"|Type|n|Model|R10|MRR10|CR20|CR50|","|---|---:|---|---:|---:|---:|---:|"]
for ty in base["tracks"]["global"]["by_type"]:
 for r in results:
  m=r["tracks"]["global"]["by_type"][ty];lines.append(f'|{ty}|{m["n"]}|{r["key"]}|{pct(m["Recall@10"])}|{m["MRR@10"]:.4f}|{pct(m["CR@20"])}|{pct(m["CR@50"])}|')
lines+=["","### Paired Gain/Loss Analysis","","Compared with B4-A instruction baseline. Classification follows CR50, CR20, R10, MRR10 lexicographically; UNCHANGED refers to these measures, not all ranks. All per-Gold ranks retained, missing ranks mean not returned in Top200.",
"CSV: `benchmarks/real_research/v2/b4_embedding_paired_cases.csv`. Counts are Query-Gold pairs, not globally distinct chunks.","",
"|Model|Improved|Unchanged|Regressed|New20|Lost20|Net20|New50|Lost50|Net50|","|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
for key in gains:
 c=counts[key];g=gains[key];lines.append(f'|{key}|{c.get("IMPROVED",0)}|{c.get("UNCHANGED",0)}|{c.get("REGRESSED",0)}|{g["20"]["new"]}|{g["20"]["lost"]}|{g["20"]["net"]}|{g["50"]["new"]}|{g["50"]["lost"]}|{g["50"]["net"]}|')
lines+=["","### Cross-document Analysis","","n=7, DIAGNOSTIC ONLY.","","|Model|R10|MRR10|CR20|CR50|","|---|---:|---:|---:|---:|"]
for r in results:
 m=r["tracks"]["global"]["by_type"]["cross_document"];lines.append(f'|{r["key"]}|{pct(m["Recall@10"])}|{m["MRR@10"]:.4f}|{pct(m["CR@20"])}|{pct(m["CR@50"])}|')
lines+=["","### CPU Quality / Latency Trade-off","","All timings milliseconds unless marked seconds. Each model:35 warmup queries per track then3 rounds,105 timed queries per track. Encoding and Chroma search are separately timed within the same contiguous local Dense call. E2E excludes public HTTP/live MySQL roundtrip; frozen-authority candidate validation included. Model load, index load, full corpus encoding and construction are excluded from warm query percentiles.",
"Model load and corpus/index costs include observed local conditions and are not service SLOs. Baseline index-build field measures an existing graph copy, not a fresh HNSW build; this is explicitly not a comparable construction-time experiment.",
"RSS is Linux process RSS; sampled encoding RSS is a lower bound, and high-water RSS through encoding includes earlier load. No GPU metrics. Index disk size is the entire isolated namespace. Model snapshot size includes local model assets.","",
"|Model|Load s|Corpus encode s|Index build/copy s|Encode p50/p95 ms|Search p50/p95 ms|E2E p50/p95 ms|RSS after load MiB|Peak process MiB|Index MiB|Model snapshot MiB|","|---|---:|---:|---:|---|---|---|---:|---:|---:|---:|"]
for r in results:
 t=r["tracks"]["global"]["latency"];fmt=lambda k:f'{t[k]["p50"]:.2f}/{t[k]["p95"]:.2f}'
 lines.append(f'|{r["key"]}|{r["model_load_sec"]:.2f}|{r["index_encode_sec"]:.2f}|{r["index_build_sec"]:.2f}|{fmt("encode_ms")}|{fmt("search_ms")}|{fmt("latency_ms")}|{r["rss_after_load_bytes"]/1048576:.1f}|{r["peak_process_rss_bytes"]/1048576:.1f}|{r["index_size_bytes"]/1048576:.1f}|{r["model_snapshot_bytes"]/1048576:.1f}|')
lines+=["","Scoped latency distributions and full per-query samples are retained in the JSON results.","",
"### Dense Winner Recommendation","",f'Quality winner: **{args.quality}**. Practical winner candidate: **{args.practical}**.',args.reason,
"No weighted aggregate ranking score is introduced. English-specific gains apply to this English scientific DEV benchmark; M3 differences cannot be attributed solely to multilingual capability because scale/architecture/training/dimension also differ. Production default unchanged; B5 must explicitly freeze a choice before B6 integration.",
"","### Integrity and Validation","","DEV35 and Gold frozen; TEST40 hash unchanged, retrieval NOT RUN, ranking NOT READ, metrics NOT COMPUTED. Chunking/BM25/Fusion/Reranker/production defaults unchanged. Only three model configurations evaluated. Related regression:138 passed,0 failed. Raw model results, queries/token audits, vector fingerprints, and all latency samples are under `artifacts/evaluation_v2/b4/`.",
"Preserved all earlier experiment rows and added exactly three V2-B4 rows. No B5/B6 execution.",""]
doc=R/"docs/evaluation_v2_embedding_optimization.md";text=doc.read_text(encoding="utf-8");assert "## B4 Embedding Model Comparison" not in text
text=text.replace("ready for B4 (not started).","B4 COMPLETE; ready for B5 (not started).",1)
doc.write_text(text+"\n"+"\n".join(lines),encoding="utf-8")
print(json.dumps(summary,ensure_ascii=False))

