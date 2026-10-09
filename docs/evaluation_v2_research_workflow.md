> Current status: V2-G POC COMPLETE; workflow readiness PARTIAL. Runtime: RECONSTRUCTED_EVALUATION_RUNTIME. Review: MODEL_ASSISTED_SEMANTIC_REVIEW. Earlier sections below preserve chronological protocol history, not the current status. Private artifact paths are provenance references, not publicly distributed downloads. See [final report](V2_POC_FINAL_REPORT.md).

# V2-G Research / Cross-paper Workflow Evaluation

Status: **V2-G0 PROPOSAL ? STOP BEFORE SCORING**.

Frozen retrieval manifest: `bc601f31786987de88a1a9b1851508960332371654bc9d3a81f0e4a8a4f94e7a` ? PASS.

No previously frozen V2-G workflow benchmark was found in the specified search roots. The old Agent pilot and frozen retrieval TEST are not automatically a V2-G workflow contract. Existing Research code performs scoped subtask/refinement retrieval, which differs from the requested fixed V2-F Top10 context. Generation implementation exists; its V2-G runtime/context/task contract is not frozen.

See V2-G0 proposal (`benchmarks/real_research/v2/V2_G0_WORKFLOW_BENCHMARK_PROPOSAL.md`; private historical artifact, not distributed) for the complete source contract audit, independent dataset construction options, blind review protocol, denominators and execution gates. Machine-readable evidence: `artifacts/evaluation_v2/g/dataset_gate_audit.json`.

No generation, retrieval, workflow scoring, new question authoring or semantic labeling was performed. No workflow funnel or rates are available; pending is not zero. Research workflow readiness and dominant workflow bottleneck are NOT ASSESSED. V2-F cross-document limitations are carried forward unchanged, not treated as new workflow evidence.

All recorded frozen/input/code hashes remain unchanged. Production and historical B/C/D/E/F artifacts are untouched. Stop awaiting dataset and generation/context protocol approval; no next research phase started.

## V2-G1 protocol freeze checkpoint

G0 has been approved in principle; G1 now includes the full frozen 40-question / 63-Gold benchmark without rewriting, sampling or exclusions. Both tracks use these same questions. Exact Track A Top10 contexts (400 passages) are saved and pass rank/raw-text equality and the existing rendered-character limit. No new metadata, Gold text or passages were added to the generator context.

- Benchmark lock: PASS.
- Track A context lock: PASS.
- Generation lock: FAIL ? effective runtime model/provider/config not yet identified.
- Track B lock: FAIL ? authoritative existing runtime/data sources and effective settings unresolved.

No repository .env, backend/.env or previous .tmp/phase11h/runtime.env was present; Docker reported no running services. Source defaults are recorded as defaults only, not runtime proof. Model revision is MODEL_REVISION_NOT_PINNABLE; this alone is not the blocker. The missing runtime identity is the blocker. User has been asked for the existing deployment/config path.

Track B preserves current ResearchTaskRequest defaults (four comparison fields) and exact question/document_scope; this schema may not fit every question and will be reported rather than rewritten. Existing ToolRegistry explicitly passes rerank=false. Track B must not be mislabeled as frozen-V2-only retrieval or silently migrated to V2 parameters. Existing runtime traces omit request/response payloads; a tested read-only capture adapter is still required before execution.

Four config JSON files and SHA files are saved under benchmarks/real_research/v2. Generation and agent configs explicitly remain PENDING_RUNTIME_IDENTITY. Details and source hashes are in artifacts/evaluation_v2/g/g1_freeze_status.json and generation_prompt_sources.json.

HUMAN_WORKFLOW_REVIEW.md contains 80 neutral review slots, all AWAITING_GENERATION, with a separate private track mapping. These are templates, not generated answers or completed reviews. No answer/trace JSONL files were fabricated. No semantic metrics were calculated. Stop before generation until all locks pass.


## V2-G1.6 Reconstructed Evaluation Runtime

This is a **RECONSTRUCTED_EVALUATION_RUNTIME**, not a recovered or production deployment.
Track A remains **FROZEN_CONTEXT** with its unchanged saved V2-F final Top10 (400 passages).
Track B-R is **RECONSTRUCTED_RESEARCH_AGENT**, using unchanged ResearchService/LangGraph
planner, coverage, refinement, extraction, synthesis and citation validation source.

The historical datasource has 3 document IDs / 298 chunks and zero stable-ID overlap
with the frozen 30-document / 3,837-chunk corpus. It is not used for evaluation.
Full document/version/chunk/text identity validation of the reconstructed corpus passed.
Historical provenance is retained in `g15_original_v2_g_runtime_provenance.json`.

### Explicit adapter and admission contract

Every search invokes the existing frozen V2-F Pipeline: global BM25200 + Dense200,
M3 pinned revision, weighted RRF (BM25 1.25, Dense 1.0, k20), frozen base reranker
Top20 to Top10. No scope filtering happens inside retrieval. The adapter preserves
all ten IDs, order, scores and raw text. Legacy `rerank=False` / `top_k=5` arguments
do not change that frozen pipeline.

The user separately approved **global Top10 + explicit scope admission**. An
evaluation-only ToolRegistry factory applies the requested document scope to that
Top10 and then the existing EvidenceBuilder (maximum 5 passages, 12,000 rendered
characters). It performs no backfill, extra retrieval or reordering. Empty admission
is permitted and flows into existing coverage/refinement semantics. Raw Top10,
scope-eligible IDs and admitted Evidence are recorded separately. This is a documented
evaluation tool substitution, not unchanged production retrieval behavior.

The serial evaluation binding restores the production factory on exit. It must not
be used concurrently with production traffic. Historical resolution uses the exact
frozen version and text; missing/wrong-version locators are never substituted.

### Execution bounds and generation

Existing bounds: 8 subtasks, one coverage refinement round, 40 admitted Evidence,
36 model calls, 34 retrieval calls, 40 tool calls, 300-second workflow deadline,
60-second model/tool timeouts, and LangGraph recursion limit 20. There is no standalone
subquery setting (`SOURCE_UNBOUNDED`); the existing graph bounds imply at most 16
subtask search invocations plus optional discovery, including at most 8 supplemental
invocations. Existing transient retries remain within the recorded runtime budgets.
No new retry, decomposition, prompt or semantic-repair rule was added.

Generation uses DeepSeek `deepseek-chat`, temperature 0.1, existing prompts and
HTTPX 0.28.1. Model revision is not pinnable. `top_p` and `max_tokens` remain omitted;
provider defaults are unknown. Both tracks share this generation contract.
The full installed package snapshot is recorded, with Python 3.11.15 and LangGraph
1.0.5. No dependencies were installed or upgraded.

### Validation checkpoint

76 offline regressions passed, including scope/no-backfill, exact-version resolution,
factory restoration and coverage-triggered supplemental retrieval with a fake model.
The latter establishes path executability, not a real-model quality result.
After explicit user approval of the endpoint and document-2/7 payload, the single
synthetic health request passed. Direct frozen retrieval and adapter output matched
exactly in IDs, order, document IDs, scores and ranks. One synthetic Research task ran:
7 model calls, 8 workflow retrieval calls, one coverage-triggered supplemental round,
zero transport retries and zero task reruns. Scope admission admitted only document 2;
no out-of-scope evidence was sent to the model.

The task failed closed at synthesis with `comparison_field_set_mismatch`: the only
covered cell was `2/optimization_objective`, but the model additionally emitted
`7/optimization_objective`. No trusted report was returned; the final citation
validation stage was not reached. The rejection and complete model input/output,
retrieval and admission records are retained in `reconstructed_workflow_smoke.json`.
This is a synthetic execution check, not a benchmark quality metric.

Generation lock: PASS. Track A lock: PASS. Track B-R lock: FAIL.
Ready for V2-G2: **NO**. No TEST answers were generated, no prompts/validators were
changed and no whole task was rerun. The runtime contract is recorded but the failed
live workflow gate must not be labeled complete. Machine-readable current status:
`artifacts/evaluation_v2/g/reconstructed_runtime_audit.json`.


## V2-G1.6 Structured Synthesis Contract Fix

The prior failed smoke is preserved. Synthesis now receives a dynamic Pydantic schema with paired document/field constants derived from allowed_covered_cells. Independent enums cannot admit invalid Cartesian-product pairs. Unsupported cells, invalid status and overlong comparison lists fail structural validation. Existing complete-covered-set, uniqueness, Fact ownership and citation checks remain in place. Missing requested cells are inserted by the system as insufficient_evidence, never filled by the model. No retrieval, admission, planner or coverage/refinement behavior changed.

78 regression tests passed. Same-input replay of all eight previous workflow calls confirmed identical retrieval results and Evidence admission. One newly authorized synthetic Research smoke was executed; no extra health check, TEST generation or task rerun.

Latest smoke checks: `{"abstention": true, "admission_unchanged": true, "citation_validation_reached": true, "covered_cells": [[2, "optimization_objective"]], "doc7_objective_insufficient": true, "missing_requested_cells": [[2, "main_findings"], [2, "method"], [2, "optimization_variables"], [7, "main_findings"], [7, "method"], [7, "optimization_objective"], [7, "optimization_variables"]], "retrieval_unchanged": true, "supplemental_rounds": 1, "unsupported_generated_cells": []}`.

Track B-R lock: PASS. Ready for V2-G2: True. No G2 tasks started.


## V2-G2 Frozen Answer Generation

Generation execution is complete: each of the 40 frozen tasks has exactly one record
per track (80 records, no duplicates or omissions). Track A was executed first in
frozen benchmark order, followed by Track B-R in the same order. No task was rerun.
All frozen configuration and input hashes remain unchanged.

Track A: 40 outputs, 24 answered and 16 explicit insufficient-evidence outputs;
zero execution failures and zero retries. Its 400 passages were replayed exactly,
without retrieval or planning.

Track B-R: 40 execution records, 23 completed, 15 partial, 2 failed. V2Q048 failed
closed on malformed citation output during synthesis; V2Q075 failed after an existing
technical retry (timeout followed by network error). The retry used identical prompt,
system prompt and frozen model parameters. Rejected content was not promoted to a
trusted report and neither failed task was regenerated. Across Track B-R there were
201 retrieval calls, including 41 supplemental calls across 19 tasks. Validated
reports emitted zero out-of-scope supported comparison cells.

These are execution/structural statuses, not semantic correctness labels. Track A
structural/reference validation passed for all 40 outputs (including abstentions);
Track B-R reached and passed final citation validation for 38 reports. The other two
records retain their failure diagnostics. No semantic workflow metrics were computed.

The run recorded 350 client invocations across both tracks. Provider token usage is
unavailable through the frozen client and was not obtained through extra requests.
The human review package has 80 items in the pre-existing blinded mapping order,
with track identity, retrieval metrics, Gold hits and runtime histories omitted.
The two failed records state that no validated answer was returned, rather than
substituting rejected output. All semantic labels remain PENDING. The original
mapping had no recorded shuffle seed; no new shuffle or invented seed was introduced.

Artifacts: `track_a_answers.jsonl`, `track_b_answers.jsonl`,
`track_b_retrieval_trace.jsonl`, `generation_run_summary.json`, and
`HUMAN_WORKFLOW_REVIEW.md` under `artifacts/evaluation_v2/g/`.
80 focused regressions passed; `git diff --check` passed. Ready for V2-G3 human review.
No human judgments have been supplied by the runtime.

## V2-G4 Final Offline Aggregation

V2/POC COMPLETE; readiness PARTIAL; bottleneck MIXED. Review provenance: **MODEL_ASSISTED_SEMANTIC_REVIEW**, not independent human-blind review. All 80 frozen labels passed checksum and deterministic mapping. A COMPLETE 23/40; B-R COMPLETE 28/40; paired improved/unchanged/regressed 9/30/1. Failures remain in denominator 40. No labels, answers, retrieval or configs were changed.

Full diagnostics, exact-Gold limitations, abstention definitions, and claim boundaries: [V2 POC Final Report](V2_POC_FINAL_REPORT.md). Recommended optional next phase: GENERATION_SYNTHESIS_OPTIMIZATION; not started.

G4 offline integrity: 16 passed / 0 failed; protected hashes and `git diff --check` PASS.
