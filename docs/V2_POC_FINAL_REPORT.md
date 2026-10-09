# ResearchGraph V2 Final POC Report

V2 and the workflow POC are COMPLETE; research workflow readiness is PARTIAL. This is a small descriptive evaluation of a RECONSTRUCTED_EVALUATION_RUNTIME, not production certification.

## Review provenance and integrity

MODEL_ASSISTED_SEMANTIC_REVIEW. Not independent human-blind review; no later human adoption is assumed. Both supplied SHA-256 values matched. The 80 Markdown labels match the JSON judgments and expected totals: COMPLETE/PARTIAL/INCORRECT 51/18/11; evidence 69/9/2; citations 58/4/18; seven flagged claims across four items.

All 80 reviewed payloads match the original blinded material byte-for-byte after newline normalization and before label fields. The saved private mapping, query ID, exact rendered answer, parsed citation payload and evidence text establish 40 A + 40 B-R matches. Mapping hashes are in final_summary.json. No stylistic track inference. All inputs are preserved.

## Track-level results

| Track | n | Complete | Partial | Incorrect | Complete rate | Evidence sufficient | Citation ALL | Flagged claims / answers | Complete + ALL |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| A | 40 | 23 | 9 | 8 | 57.50% | 32 | 24 | 0/0 | 23 / 57.50% |
| B-R | 40 | 28 | 9 | 3 | 70.00% | 37 | 34 | 7/4 | 28 / 70.00% |

Full partial/incorrect rates, all evidence/citation counts and denominators are in v2_g4_track_metrics.csv. Both workflow failures remain in B-R n=40.

## Workflow status versus semantic correctness

| Runtime status | Semantic COMPLETE | PARTIAL | INCORRECT |
| --- | --- | --- | --- |
| completed | 20 | 2 | 1 |
| failed | 0 | 0 | 2 |
| partial | 8 | 7 | 0 |

Eight runtime-partial reports are semantically COMPLETE for the original question. A runtime completed state is not semantic correctness.

## Paired comparison

| A → B-R | COMPLETE | PARTIAL | INCORRECT |
| --- | --- | --- | --- |
| COMPLETE | 22 | 0 | 1 |
| INCORRECT | 3 | 3 | 2 |
| PARTIAL | 3 | 6 | 0 |

Improved 9; unchanged 30; regressed 1. A incomplete → B complete: 6; A complete → B incomplete: 1. No significance or causal claim.

## Query type breakdown — LOW_SAMPLE_DESCRIPTIVE

| Track | Type | n | Complete | Partial | Incorrect | Complete rate | Citation ALL rate | Flagged claims |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| A | factual | 8 | 7 | 1 | 0 | 87.50% | 100.00% | 0 |
| A | exact_term | 5 | 4 | 1 | 0 | 80.00% | 80.00% | 0 |
| A | semantic | 8 | 6 | 0 | 2 | 75.00% | 75.00% | 0 |
| A | relational | 5 | 4 | 1 | 0 | 80.00% | 80.00% | 0 |
| A | cross_document | 8 | 0 | 6 | 2 | 0.00% | 0.00% | 0 |
| A | multi_hop | 6 | 2 | 0 | 4 | 33.33% | 33.33% | 0 |
| B-R | factual | 8 | 8 | 0 | 0 | 100.00% | 100.00% | 0 |
| B-R | exact_term | 5 | 4 | 1 | 0 | 80.00% | 100.00% | 0 |
| B-R | semantic | 8 | 7 | 0 | 1 | 87.50% | 87.50% | 0 |
| B-R | relational | 5 | 4 | 0 | 1 | 80.00% | 80.00% | 2 |
| B-R | cross_document | 8 | 1 | 7 | 0 | 12.50% | 62.50% | 5 |
| B-R | multi_hop | 6 | 4 | 1 | 1 | 66.67% | 83.33% | 0 |

## Frozen retrieval ceiling

| Exclusive class | n | rate | A COMPLETE | A PARTIAL | A INCORRECT |
| --- | --- | --- | --- | --- | --- |
| ANSWERABLE_FROM_TOP10 | 21 | 52.50% | 18 | 1 | 2 |
| ANSWERABLE_FROM_TOP20 | 1 | 2.50% | 1 | 0 | 0 |
| NOT_ANSWERABLE_FROM_TOP20 | 18 | 45.00% | 4 | 8 | 6 |

Top20-only means not Top10-answerable. Inclusive all-Gold Hybrid20 count is 22/40. Three Top10-answerable tasks were not COMPLETE. Four tasks judged COMPLETE lack all exact Gold in Hybrid20: locator absence does not prove absence of equivalent semantic evidence. Fourteen incomplete A tasks are in the not-Top20 class; retrieval may bind, without causal certainty.

## Agent Gold recovery

Before Agent = frozen A Final10; after Agent = union of actually admitted exact immutable locators across all calls, with no inherited A context. Global-returned coverage is separately recorded; it never counts as evidence sent to the model. A Gold unit is counted once, attributed to its first admitted phase.

| Measure | Value |
| --- | --- |
| ORCHESTRATION_RECOVERY_SUCCESS | 1 |
| missing_units_before | 32 |
| previously_missing_still_missing | 27 |
| queries_all_missing_recovered | 2 |
| queries_still_retrieval_limited | 21 |
| queries_with_recovery | 4 |
| units_recovered_admitted | 5 |
| units_recovered_initial | 4 |
| units_recovered_supplemental | 1 |
| global_returned_missing_units | 8 |
| initially_missing_queries | 19 |
| initially_missing_still_limited_queries | 17 |

| Recovered cohort | Complete | Partial | Incorrect |
| --- | --- | --- | --- |
| recovered_semantics | 1 | 3 | 0 |
| all_recovered_semantics | 1 | 1 | 0 |

Only one A-incomplete → B-complete pair also recovered missing exact Gold. This is ORCHESTRATION_RECOVERY_SUCCESS bookkeeping, not a causal estimate. B can lose Gold originally present in A because retrieval/context admission differ; those lost locators are retained in the recovery CSV.

## Retrieval intensity and cost

| Per-task measure | Mean | Median | p95 | Max |
| --- | --- | --- | --- | --- |
| calls_per_task | 5.025 | 4.0 | 8.0 | 8 |
| llm_calls | 7.75 | 6.0 | 15.0 | 16 |
| subquery_invocations_per_task | 5.025 | 4.0 | 8.0 | 8 |
| unique_admitted_chunks | 9 | 9.0 | 13.0 | 14 |
| unique_admitted_documents | 1.2 | 1.0 | 2.0 | 2 |
| unique_returned_chunks | 22.5 | 20.0 | 34.05 | 43 |
| unique_returned_documents | 6.55 | 6.0 | 15.05 | 16 |
| unique_subqueries_per_task | 5.025 | 4.0 | 8.0 | 8 |
| workflow_latency_ms | 58965.19 | 51217.835 | 98733.17 | 101586.89 |

201 retrieval calls; 19/40 tasks triggered supplemental retrieval. Subqueries are recorded both as invocations and distinct query strings. p95 uses linear interpolation at (n−1)×0.95. Workflow latency units are ms. No missing timing/token data were obtained by rerunning tasks.

## Supplemental versus no supplemental — observational

| Group | n | Complete rate | Partial rate | Incorrect rate | Paired improved | unchanged | regressed |
| --- | --- | --- | --- | --- | --- | --- | --- |
| NO_SUPPLEMENTAL | 21 | 80.95% | 4.76% | 14.29% | 4 | 16 | 1 |
| SUPPLEMENTAL_USED | 19 | 57.89% | 42.11% | 0.00% | 5 | 14 | 0 |

Coverage-triggered groups differ in difficulty. These rates do not measure causal benefit or harm from supplemental retrieval.

## Failure attribution

| Primary cause | A | B-R |
| --- | --- | --- |
| CITATION_ERROR | 0 | 0 |
| EVIDENCE_SELECTION_MISS | 3 | 1 |
| OTHER | 0 | 0 |
| RERANKER_MISS | 0 | 0 |
| RETRIEVAL_MISS | 14 | 9 |
| SYNTHESIS_ERROR | 0 | 0 |
| UNSUPPORTED_INFERENCE | 0 | 0 |
| WORKFLOW_TECHNICAL_FAILURE | 0 | 2 |

Exactly one primary cause per incomplete answer, following the requested exact-Gold precedence. This is proxy-based diagnosis: review-sufficient / Gold-absent conflicts and full reviewer notes remain in the CSV. Lower-priority synthesis problems are not erased: seven frozen flagged claims remain recorded separately. V2Q048 is a validator rejection (not a transport failure); V2Q075 is timeout/network failure. Both use the requested WORKFLOW_TECHNICAL_FAILURE bucket, with their distinction preserved.

## Workflow funnels

Counts below are marginal stage counts (denominator 40); they may increase because review sufficiency and exact Gold availability are different constructs. Strict cumulative-intersection counts are also shown, preventing an invalid monotonic-funnel claim.

### A

| Stage | Marginal n | Marginal % | Cumulative n | Cumulative % |
| --- | --- | --- | --- | --- |
| tasks | 40 | 100.00% | 40 | 100.00% |
| all_gold_hybrid20 | 22 | 55.00% | 22 | 55.00% |
| all_gold_final10 | 21 | 52.50% | 21 | 52.50% |
| review_evidence_sufficient | 32 | 80.00% | 21 | 52.50% |
| semantic_complete | 23 | 57.50% | 18 | 45.00% |
| correctly_cited_complete | 23 | 57.50% | 18 | 45.00% |

### B-R

| Stage | Marginal n | Marginal % | Cumulative n | Cumulative % |
| --- | --- | --- | --- | --- |
| tasks | 40 | 100.00% | 40 | 100.00% |
| execution_succeeded | 38 | 95.00% | 38 | 95.00% |
| all_gold_admitted_after_agent | 19 | 47.50% | 19 | 47.50% |
| review_evidence_sufficient | 37 | 92.50% | 19 | 47.50% |
| semantic_complete | 28 | 70.00% | 18 | 45.00% |
| correctly_cited_complete | 28 | 70.00% | 18 | 45.00% |

## Cross-document and multi-hop POC

LOW_SAMPLE_DESCRIPTIVE: cross_document n=8; multi_hop n=6 per track.

| Category | Track | FULL | PARTIAL | FAIL |
| --- | --- | --- | --- | --- |
| cross_document | A | 0 | 6 | 2 |
| cross_document | B-R | 1 | 7 | 0 |
| multi_hop | A | 2 | 0 | 4 |
| multi_hop | B-R | 1 | 4 | 1 |

| Category | Diagnostic | Count |
| --- | --- | --- |
| cross_document | n | 8 |
| cross_document | A_all_gold_top10 | 0 |
| cross_document | A_all_gold_top20 | 0 |
| cross_document | B_supplemental_tasks | 8 |
| cross_document | B_queries_recovered_missing | 3 |
| cross_document | B_all_missing_recovered | 1 |
| cross_document | A_incomplete_B_complete | 1 |
| cross_document | A_complete_B_incomplete | 0 |
| multi_hop | n | 6 |
| multi_hop | A_all_gold_top10 | 2 |
| multi_hop | A_all_gold_top20 | 2 |
| multi_hop | B_supplemental_tasks | 2 |
| multi_hop | B_queries_recovered_missing | 0 |
| multi_hop | B_all_missing_recovered | 0 |
| multi_hop | A_incomplete_B_complete | 2 |
| multi_hop | A_complete_B_incomplete | 0 |

Cross-paper FULL requires COMPLETE + citations ALL + all scoped papers actually cited; a one-paper answer cannot qualify. Multi-hop FULL additionally requires all exact frozen Gold available in the track context. Other non-INCORRECT / nonfailed outputs are conservative PARTIAL, not FULL. B-R has four semantic COMPLETE multi-hop answers but only one satisfies the stricter exact-Gold FULL rule; do not conflate the two.

## Abstention

| Track | Safe | Missed opportunity |
| --- | --- | --- |
| A | 8 | 8 |
| B-R | 3 | 12 |

A counts whole-answer abstention. B-R counts validated reports containing any insufficient-evidence cell, including cells broader than the original question. A sufficient G3 evidence label or full exact-Gold availability marks missed opportunity; otherwise safe under the frozen evidence review. Individual records retain both bases. This does not rejudge G3 labels or treat all abstentions as safety failures.

## Unsupported / contradicted claims and citations

| Track | Query | Review ID | Frozen count | Original distinction |
| --- | --- | --- | --- | --- |
| B-R | V2Q018 | R019 | 2 | 2 contradicted core claims explicitly described |
| B-R | V2Q019 | R080 | 1 | 1 mixed unsupported/contradicted claim; no forced split |
| B-R | V2Q059 | R024 | 1 | 1 material mischaracterization |
| B-R | V2Q062 | R003 | 3 | 3 contradictions / conflicts explicitly described |

Five issues are explicitly contradictions/conflicts (R003, R019); R024 is a mischaracterization and R080 has mixed unsupported/contradicted wording. Counts are unchanged and no new per-claim labels are invented. Zero flagged claims for A is not a zero-hallucination-rate claim.

| Track | ALL | PARTIAL | NONE | COMPLETE+ALL | COMPLETE+PARTIAL/NONE | PARTIAL+ALL |
| --- | --- | --- | --- | --- | --- | --- |
| A | 24 | 0 | 16 | 23 | 0 | 1 |
| B-R | 34 | 4 | 2 | 28 | 0 | 6 |

## POC readiness and next phase

Readiness: **PARTIAL**. Dominant bottleneck: **MIXED**.

Exact Gold ceiling and cross-paper recovery remain limited, while supplied evidence is judged sufficient for 32/40 A and 37/40 B-R. A has eight missed-opportunity abstentions; B-R has contradictions, omissions and two failures. Agent improves nine pairs but recovers missing exact Gold in only four; no single causal bottleneck is established. Prioritize evidence-use/synthesis as one optional next phase; do not implement it.

Primary recommendation: **GENERATION_SYNTHESIS_OPTIMIZATION**, with no implementation in this closeout. This prioritizes supplied-evidence use and incorrect insufficiency/contradiction behavior; it does not deny the unresolved cross-paper candidate-coverage limitation. No retroactive numeric pass threshold is introduced.

## WHAT WE CAN CLAIM

- V2 retrieval was optimized on DEV and frozen before the single final retrieval TEST; no post-TEST retrieval tuning.
- Saved V2-F results show positive reranker value on this TEST, not general superiority.
- A and B-R use the same frozen 40-task benchmark; B-R uses frozen V2 retrieval in a reconstructed evaluation runtime.
- Semantic judgments are MODEL_ASSISTED_SEMANTIC_REVIEW, with 80 frozen records and two workflow failures retained.
- Observed paired outcomes: nine improvements, thirty unchanged, one regression.

Saved final TEST Hybrid R@10 = 0.4625; reranked R@10 = 0.5917. This is retrieval ranking value on that fixed TEST, not proof of semantic or production superiority.

## WHAT WE CANNOT CLAIM

- Production readiness or historical production Agent performance.
- Independent human-blind evaluation or human endorsement.
- Reliable cross-paper retrieval / universal multi-hop success.
- Statistically generalizable superiority from n=40 or causal benefit of supplemental retrieval.
- Zero hallucination rate from Track A unsupported-count zero.

## Reproduction and artifacts

Run only `python backend/scripts/aggregate_v2_g4.py`, followed by `python backend/scripts/report_v2_g4.py`, then offline integrity tests. These use only standard-library file processing and saved results. No LLM, retriever, model encoding, label edits or answer regeneration. Seven CSVs in benchmarks/real_research/v2 and final_summary.json, workflow_funnel.json, poc_closeout.json in artifacts/evaluation_v2/g contain complete machine-readable results and hashes. V2 COMPLETE; POC COMPLETE; no further optimization started.

## Offline integrity result

16 passed / 0 failed. Both expected G3 SHA-256 hashes match; 80/80 mapped, 40 paired tasks, two failures preserved, all protected input hashes unchanged. `git diff --check`: PASS. No LLM/retrieval calls and no label edits.
