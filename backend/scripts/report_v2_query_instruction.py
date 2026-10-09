"""Publish B3 results without rerunning retrieval or model inference."""
import argparse, csv, json
from collections import Counter
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
BASE=ROOT/"benchmarks/real_research/v2"
OUT=ROOT/"artifacts/evaluation_v2"
parser=argparse.ArgumentParser()
parser.add_argument("--selected",choices=["raw","official_instruction"],required=True)
parser.add_argument("--effect",choices=["BENEFICIAL","NEUTRAL","HARMFUL"],required=True)
parser.add_argument("--reason",required=True)
args=parser.parse_args()
path=OUT/"b3_query_instruction.json"
r=json.loads(path.read_text(encoding="utf-8"))
enc=json.loads((OUT/"b3_query_encoding.json").read_text(encoding="utf-8"))
assert r["status"]=="COMPLETE"
r["decision"]={"selected_query_strategy":args.selected,"instruction_effect":args.effect,"reason":args.reason,
               "scope":"Frozen DEV only; no model language-fit generalization","production_default_changed":False,"ready_for_b4":True,"b4_started":False}
r["validation"]={"related_regression":{"passed":35,"failed":0,"seconds":11.62},
                 "initial_search_harness_issue":"Two harness failures retained: missing /chroma module path before search; missing installed Chroma metadata at final serialization after three rounds, whose in-memory measurements were not saved. Fixed module path/version lookup and added per-round persistence; reran identical search protocol, no re-encoding or parameter changes."}
r["paired_counts"]=dict(Counter(p["classification"] for p in r["paired"]))
path.write_text(json.dumps(r,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
pairs=r["paired"]
fields=list(pairs[0])
with (BASE/"b3_instruction_paired_cases.csv").open("w",encoding="utf-8",newline="") as f:
    w=csv.DictWriter(f,fieldnames=fields);w.writeheader()
    w.writerows({k:json.dumps(v,ensure_ascii=False) if isinstance(v,(dict,list)) else v for k,v in row.items()} for row in pairs)
ledger=BASE/"experiments.csv"
with ledger.open(encoding="utf-8",newline="") as f:
    reader=csv.DictReader(f);columns=list(reader.fieldnames);old=list(reader)
new=[]
for e in r["experiments"]:
    g=e["tracks"]["global"]["overall"];s=e["tracks"]["scoped"]["overall"]
    row=dict(experiment_id="v2b3-"+e["strategy"],phase="V2-B3",status="COMPLETE",split="dev",
             **e["config"],config_fingerprint=e["config_fingerprint"],
             vector_fingerprint=r["identity"]["identity"]["vector_fingerprint"],
             query_latency_p50=e["encoding_latency"]["p50"],query_latency_p95=e["encoding_latency"]["p95"],
             global_search_p50=g["p50"],global_search_p95=g["p95"],scoped_search_p50=s["p50"],scoped_search_p95=s["p95"],
             global_hit5=g["Hit@5"],global_r5=g["Recall@5"],global_r10=g["Recall@10"],global_mrr10=g["MRR@10"],
             global_cr20=g["CR@20"],global_cr50=g["CR@50"],
             scoped_hit5=s["Hit@5"],scoped_r5=s["Recall@5"],scoped_r10=s["Recall@10"],scoped_mrr10=s["MRR@10"],
             scoped_cr20=s["CR@20"],scoped_cr50=s["CR@50"],
             notes="Same frozen graph, DEV only; query prefix only; no reranker/hybrid. Encoding and local search separately timed.")
    for ty,prefix in [("semantic","semantic"),("cross_document","crossdoc"),("multi_hop","multihop")]:
        m=e["tracks"]["global"]["by_type"][ty]
        row[prefix+"_cr20"]=m["CR@20"];row[prefix+"_cr50"]=m["CR@50"]
    row={k:json.dumps(v,sort_keys=True) if isinstance(v,dict) else v for k,v in row.items()}
    assert not any(x["experiment_id"]==row["experiment_id"] for x in old),"ledger_already_published"
    new.append(row)
    columns.extend(k for k in row if k not in columns)
with ledger.with_suffix(".csv.tmp").open("w",encoding="utf-8",newline="") as f:
    w=csv.DictWriter(f,fieldnames=columns);w.writeheader();w.writerows(old+new)
ledger.with_suffix(".csv.tmp").replace(ledger)
exps=r["experiments"]
def metric_row(label,m):
    return f'|{label}|{100*m["Hit@5"]:.2f}%|{100*m["Recall@5"]:.2f}%|{100*m["Recall@10"]:.2f}%|{m["MRR@10"]:.4f}|{100*m["CR@20"]:.2f}%|{100*m["CR@50"]:.2f}%|{m["p50"]:.3f}|{m["p95"]:.3f}|'
def table(track):
    return ["|Strategy|Hit@5|R@5|R@10|MRR@10|CR@20|CR@50|Search p50 ms|Search p95 ms|",
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|"]+[metric_row(e["strategy"],e["tracks"][track]["overall"]) for e in exps]
lines=["## B3 Query Instruction Ablation","","Status: COMPLETE. Production remains unchanged. B4 not started.","",
"### Official Model Contract","",
f'Model: {enc["model"]}; revision: {enc["revision"]}.',
f'Official query prefix: `{enc["instruction"]}` (Chinese full-width colon, directly concatenated with the unchanged English query; no extra separator).',
"The fixed-revision model card permits no-instruction retrieval with v1.5 and describes improved instruction-free performance. It recommends trying a query instruction for short-query/long-passage retrieval and selecting using task results. Documents/passages never receive an instruction.",
f'Source: [fixed revision model card]({enc["source"]}), Model List row for bge-small-zh-v1.5 and FAQ 3. This evaluates an optional encoding strategy, not a bug fix.',"",
"### Experimental Setup","",
"Frozen 35 DEV queries; TEST bytes used only for SHA-256 protection. No query rewriting, translation, scope injection or Gold edits. CPU, 512 dimensions, CLS, normalization ON. Same existing 3,837 document vectors, same graph, squared L2, M16, construction_ef100, n_results200, search_ef10. No document encoding or insertion; no reranker or Hybrid execution.",
f'Collection: `{r["collection_name"]}`; UUID `{r["collection_id"]}`.',
f'Document vector fingerprint: `{r["identity"]["identity"]["vector_fingerprint"]}`.',
f'Corpus hash: `{r["identity"]["identity"]["corpus_hash"]}`.',
"Each configuration is fingerprinted with the actual frozen chunking config (version/size/overlap), model revision, query strategy/prefix, document strategy, pooling, normalization, dimension, metric and search controls. Chunker source hash is separately recorded.",
f'Fresh raw batch query vectors are byte-identical to the frozen baseline (max absolute error {enc["raw_max_abs_error_vs_frozen"]}). Every instructed query vector differs from raw; every tokenizer input was captured and checked, with no truncation. Full 35-query encoding details per strategy are in `artifacts/evaluation_v2/b3_query_encoding.json`.',
""]
for e in exps:lines.append(f'- {e["strategy"]} config fingerprint: `{e["config_fingerprint"]}`.')
lines+=["","Encoding verification samples (fixed positions 0, 17, 34; selected without ranking inspection):",""]
for s in ("raw","official_instruction"):
    for i in (0,17,34):
        sample=enc["samples"][s][i]
        lines += [f'- {s} / {sample["query_id"]}: tokens={sample["token_count"]}, dim={sample["vector_dimension"]}, norm={sample["vector_norm"]:.9f}.',
                  f'  Raw: {sample["raw_query"]}',f'  Encoded: {sample["actual_encoded_text"]}']
lines+=["","### Global Results","","Primary selection track. Existing macro-averaged chunk-locator metrics; multi-Gold recall denominator preserved.",""]+table("global")
lines+=["","### Scoped Diagnostic","","DIAGNOSTIC ONLY; document_id filter uses each frozen document scope. Scoped results do not independently select the strategy.",""]+table("scoped")
lines+=["","### Query-type Results","","Global DEV; small category samples, descriptive observations only.","",
"|Type|n|Strategy|R@10|MRR@10|CR@20|CR@50|","|---|---:|---|---:|---:|---:|---:|"]
for ty in exps[0]["tracks"]["global"]["by_type"]:
    for e in exps:
        m=e["tracks"]["global"]["by_type"][ty]
        lines.append(f'|{ty}|{m["n"]}|{e["strategy"]}|{100*m["Recall@10"]:.2f}%|{m["MRR@10"]:.4f}|{100*m["CR@20"]:.2f}%|{100*m["CR@50"]:.2f}%|')
lines+=["","### Paired Query Analysis","",r["paired_classification_rule"]+". This predeclared comparison prioritizes candidate coverage; full per-Gold ranks and all mixed-direction changes are retained, including when the headline class is UNCHANGED.",
        "Counts: "+json.dumps(r["paired_counts"])+".",
        "Complete 35-row export: `benchmarks/real_research/v2/b3_instruction_paired_cases.csv`. Ranks are within the Top200 result; blank/null means not returned, not an inferred exact rank.",
        "","### Candidate Gains and Losses","","Counts are query-Gold pairs, not globally unique chunks; macro recall and these counts have different weighting.","",
        "|Cutoff|New Gold hits|Lost Gold hits|Net|","|---|---:|---:|---:|"]
for k,c in r["candidate_changes"].items():lines.append(f'|{k}|{c["new"]}|{c["lost"]}|{c["new"]-c["lost"]}|')
lines+=["","### Cross-document Diagnostic","","DIAGNOSTIC ONLY: few cross-document queries; no generalization claim.","",
"|Strategy|n|R@10|MRR@10|CR@20|CR@50|","|---|---:|---:|---:|---:|---:|"]
for e in exps:
    m=e["tracks"]["global"]["by_type"]["cross_document"]
    lines.append(f'|{e["strategy"]}|{m["n"]}|{100*m["Recall@10"]:.2f}%|{m["MRR@10"]:.4f}|{100*m["CR@20"]:.2f}%|{100*m["CR@50"]:.2f}%|')
lines+=["","### Latency","",
"Three rounds x 35 queries per strategy/track after a complete 35-query warmup. Strategy order alternates each round; all samples retained. Model load, index load and cold starts excluded. Query encoding and search measured separately in their pinned runtimes; values are not contiguous HTTP end-to-end latency. Search runs without concurrent tests.",
r["protocol"]["search_latency"]+".",
"Encoding runtime: "+json.dumps(enc["packages"])+". Search runtime: "+json.dumps(r["protocol"]["packages"])+". Both strategies share the same runtime for each measured component.",
"","|Strategy|Encoding p50 ms|Encoding p95 ms|Global search p50 ms|Global search p95 ms|","|---|---:|---:|---:|---:|"]
for e in exps:
    g=e["tracks"]["global"]["overall"];l=e["encoding_latency"]
    lines.append(f'|{e["strategy"]}|{l["p50"]:.3f}|{l["p95"]:.3f}|{g["p50"]:.3f}|{g["p95"]:.3f}|')
lines+=["","### Decision","",f'Selected query strategy: **{args.selected.upper()}**. Instruction effect: **{args.effect}**.',
args.reason,"Selection uses Frozen Global DEV, with CR50 before CR20/R10/MRR10, then cross-document coverage/regressions/latency. No claim that English queries inherently require an instruction or that this establishes model language fit.",
"Production configuration unchanged. Ready for B4; B4 not started.","",
"### Integrity and Regression","",
"DEV/Gold unchanged; TEST untouched, ranking unread; stable graph and document vector fingerprints unchanged; model/chunking/BM25/RRF unchanged; reranker not involved; external LLM calls zero.",
"Related regression: 35 passed / 0 failed. Two harness failures were retained: missing /chroma in PYTHONPATH before retrieval, then package-metadata lookup at final serialization. The latter lost its in-memory measurements; it was not a quality-based exclusion. The identical search protocol was rerun after correcting version reporting and adding per-round checkpoints. No query re-encoding or parameter changes.",
"Raw result: `artifacts/evaluation_v2/b3_query_instruction.json`. Query vectors and encoding validation retained alongside it. Exactly two V2-B3 rows appended to experiments.csv; previous rows preserved. An intermediate attempt was stopped before the measured protocol completed because lazy NPZ loading would contaminate search timing. Query vectors were materialized in memory before the final run; aborted-run provenance is retained. No strategy/quality-based run selection was performed.",""]
doc=ROOT/"docs/evaluation_v2_embedding_optimization.md"
text=doc.read_text(encoding="utf-8")
assert "## B3 Query Instruction Ablation" not in text,"report_already_published"
text=text.replace("ready for B3 (not started).","B3 query instruction ablation COMPLETE; ready for B4 (not started).",1)
doc.write_text(text+"\n"+"\n".join(lines),encoding="utf-8")
print(json.dumps({"decision":r["decision"],"paired":r["paired_counts"],"gains_losses":r["candidate_changes"]},ensure_ascii=False))

