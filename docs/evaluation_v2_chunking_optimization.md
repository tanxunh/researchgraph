# V2-C Chunking Optimization

## C0 Gold Portability

Status: COMPLETE. C0 is derived benchmark portability and descriptive audit only; C1 NOT RUN.

### Current Gold Schema

Frozen DEV35 contains55 Query-Gold units,34 unique chunks. Every locator has paper_id/document_id/document_version_id/chunk_id/page/section (section null). No offsets or text in queries_dev.jsonl. Full human-reviewed immutable chunk text is available in the authoritative snapshot/review record. No narrower approved exact span is persisted; retain all699-700 original characters. DocumentVersion ID is not assumed to be the version ordinal.

### Portable Anchor Contract

Artifact: `benchmarks/real_research/v2/dev_gold_portable_anchors.json`. All55 anchors are EXACT_SPAN. Each retains full raw reviewed text plus normalized text/hash, immutable ownership, original chunk ID, page, raw half-open Unicode offsets and source text/PDF hashes.
All30 PDF checksums matched the frozen corpus manifest. Existing PdfParser and TextChunker reproduced all3837 chunk texts/hashes/pages/ordinals exactly. Full document text is deterministically reconstructed from immutable raw source, not claimed to exist as a stored full-text DocumentVersion column.
Normalization: nfc-whitespace-v1; function SHA256 `b44787fa4c9c8316185a68121e7289d4ce9fc873be720f0db50735364b49992f`; Unicode database 15.0.0. NFC + whitespace collapse/strip; no lowercasing, hyphen repair, stemming or semantic rewriting.

### Mapping Rule

Predeclared before reading saved DEV misses: same document/version, same source-text hash for offset comparisons; intersection length / Gold raw span length >=0.50. Coordinates are zero-based Unicode codepoints in PdfParser full_text, end exclusive. If offsets unavailable, require same page/section, unambiguous location, and longest CONTIGUOUS exact normalized character overlap >=0.50. No token-bag/fuzzy match.
One original Query-Gold item remains one denominator unit. ANY mapped chunk recalls the unit once. C1 must carry offsets/source identity through its chunker and stop on unmapped/ambiguous anchors. The50% rule is a deterministic coverage proxy, not a claim of semantic entailment. Anchor definitions/threshold cannot be tuned on rankings.

### Backward Validation

55/55 mapped,0 unmapped,0 ambiguous,100% recoverability. Each anchor matches exactly its original current chunk; therefore current membership scoring is backward-compatible. Original DEV/Gold files unchanged. See c0_anchor_mapping_audit.csv and current_mapping.json.
12 unique Gold anchors inspected with all matched chunks;0 observed false positives. Full snippets and notes saved in false_positive_samples.json. This is agent text inspection, not new human annotation approval.
Coverage limits: no genuinely short Gold (all699-700 chars), cross-page Gold or table/caption-heavy Gold. Closest Gold span is386 chars from a page edge. Inspected available extrema, nearest-edge cases, equation residue, textual Introduction heading and cross-document ownership; absent strata are not claimed as validated. Alternative chunking mappings require renewed checks before retrieval.

### Ambiguous Cases

None. Every current chunk occurs uniquely on its recorded page; each Gold text also occurs once in its document. Offset/page identity protects against repeated boilerplate; ambiguous text-only locations fail closed.

### Current Chunking Audit

TextChunker: page-local double-LF paragraph packing, falling back to hard character windows. Target700, overlap100; not token-based. Hard-window maximum700; paragraph overflow can theoretically produce up to800 because overlap is prepended without a second size check. Observed maximum is700 for this corpus; no code fix performed. No page-crossing chunks or inter-page overlap.
Separators: page -> double LF -> raw character cut. Headings remain plain text; section titles are absent. Tables/captions/formulas/references are flattened extracted text, without structured cells, section attribution or reference filtering. Page, ordinal, document/version and text hash propagate to each chunk; original offsets do not.
Character lengths (nearest-rank quantiles): {'min': 102, 'p25': 699, 'median': 700, 'p75': 700, 'p95': 700, 'max': 700}.
Pinned M3 tokenizer lengths including special tokens, no truncation: {'min': 30, 'median': 188, 'p95': 295, 'max': 520}. Stored token_count is only len(text)//2, not real tokenization.
Chunk IDs use document ID + first24 hash hex, plus occurrence suffix for repeated content. Hash normalization is the existing hash_service.normalized_text, separate from portability normalization.
Structure:432/432 pages have page metadata;0 section titles; only1 page contains double LF. Heading-like text found in30 documents (200 heuristic lines), TABLE mentions in25 documents (64), figure/caption mentions in30 (795), REFERENCES text in30. These are lexical signals, not validated semantic sections/table layouts. No section-aware C1 design is justified by current metadata.

### Miss Diagnosis

Uses only saved B6 New Hybrid results after anchors were fixed; no new retrieval.17 missed Query-Gold units atTop20,11 atTop50. One primary descriptive category per unit; counts may reuse the same original chunk across different questions. NOT_CHUNKING_RELATED means no visible loss of the needed contiguous facts, not a proven alternative cause.
|Category|Top20 misses|Top50 misses|
|---|---:|---:|
|BOUNDARY_SPLIT|4|3|
|CHUNK_TOO_BROAD|6|4|
|CHUNK_TOO_NARROW|0|0|
|HEADING_CONTEXT_LOST|0|0|
|TABLE_OR_CAPTION|0|0|
|REFERENCE_NOISE|0|0|
|NOT_CHUNKING_RELATED|6|3|
|UNCLEAR|1|1|

|Unit|Category|Reason|
|---|---|---|
|V2Q031:G1|CHUNK_TOO_BROAD|The complete variable list occupies the opening; solver, numerical gains and index terms dominate the remaining chunk. Possible representation dilution, not demonstrated causation.|
|V2Q038:G1|CHUNK_TOO_BROAD|HMDP name is intact but shares a chunk with several competing algorithm acronyms, results and index terms.|
|V2Q043:G1|NOT_CHUNKING_RELATED|Nonconvexity and alternating block-descent strategy are both intact. No visible boundary defect removes the requested facts; retrieval cause remains unproven.|
|V2Q049:G1|BOUNDARY_SPLIT|The conflict sentence ends at minimization of; completion and relative goal importance continue in the following chunk.|
|V2Q050:G2|CHUNK_TOO_BROAD|Local/OBS offloading role shares the chunk with welfare, revenue and solver details beyond the immediate resource-limit question.|
|V2Q056:G2|CHUNK_TOO_BROAD|Utility objective and solver are mixed with manuscript dates and funding boilerplate; the motivation is in the previous Gold chunk.|
|V2Q061:G2|UNCLEAR|Decomposition and HMDP are intact, with tiers in another approved Gold unit. Multi-unit evidence is intentional; cannot isolate a chunking contribution.|
|V2Q061:G3|BOUNDARY_SPLIT|Architecture, objectives and decision variables share the chunk; the variable list cuts off at co and continues next chunk.|
|V2Q061:G4|NOT_CHUNKING_RELATED|All four JCORM subproblems are present contiguously. Equation residue and a cut termination sentence do not remove the requested decomposition.|
|V2Q063:G1|NOT_CHUNKING_RELATED|Security/cost conflict and all three MOP objectives are present; no necessary objective is visibly split.|
|V2Q066:G1|CHUNK_TOO_BROAD|Energy/AoI/slot variables are followed by algorithm, numerical-results and publication-footer content.|
|V2Q066:G2|NOT_CHUNKING_RELATED|Energy objective, offloading variables and secrecy provisioning are all intact in the same chunk.|
|V2Q067:G1|BOUNDARY_SPLIT|Scheduling mechanism antecedent/name is in the previous chunk; this chunk starts s is introduced and primarily describes the second routing mechanism.|
|V2Q068:G1|BOUNDARY_SPLIT|NOMA/OMA introduction is split at the start; potentially NOMA-served user decision continues after the end.|
|V2Q068:G2|NOT_CHUNKING_RELATED|Virtual clusters, NOMA inclusion and interference/power-allocation context remain intact.|
|V2Q072:G1|NOT_CHUNKING_RELATED|Task partition and optimized variables are intact. Alternating-method rationale is intentionally covered by the other approved Gold unit.|
|V2Q074:G2|CHUNK_TOO_BROAD|Decomposition methods are mixed with numerical comparisons and index terms; architecture is in the other Gold unit.|

### Proposed C1 Matrix

Proposal only; no alternative chunks/index/vector/benchmark produced. Same frozen source, Gold anchors, retrieval stack and100-character overlap.
|Config|Size|Strategy / hypothesis|
|---|---:|---|
|Baseline|700 chars|unchanged current TextChunker. Frozen reference; portable scoring must first reproduce baseline exactly.|
|Alternative A|450 chars|same page-local chunker, size only. Test whether smaller chunks reduce mixed solver/results/boilerplate dilution. Size still exceeds half of current699-700 character anchors; recheck recoverability before any retrieval.|
|Alternative B|1000 chars|same page-local chunker, size only. Test whether larger windows keep cut antecedents/variable lists together, with explicit dilution/candidate-count trade-off.|
|Alternative C|700 chars|page-local sentence-end preference in end-offset range600..700; otherwise hard700 fallback; keep raw text and max700; proposed only. Test boundary continuity without assuming reliable headings, paragraphs or tables. Predeclare punctuation rule before C1; no section-aware reconstruction.|

No broad grid, no speculative section-aware parser. C1 must validate mapped membership before evaluating retrieval. Any unavailable Gold mapping is a stop, not a denominator reduction.

### Integrity

Original DEV/Gold and TEST hashes unchanged. TEST only hash-checked: no query/Gold semantics opened, no ranking or metric computed. Anchors are DERIVED ONLY. Dense/BM25/RRF/reranker/chunking production files and defaults unchanged. No LLM calls and no retrieval benchmark run in C0.

Validation:11 focused tests passed; `git diff --check` PASS. Full normalized anchor text is also unique within each authoritative document (55/55). Two supplementary non-Gold negative controls (table-caption text and short page-end/footer text) were inspected; neither maps to any Gold. These controls do not imply unavailable short/table-heavy Gold strata were reviewed.

## C1 Controlled Chunking Ablation

Execution: complete. Closeout: **STOPPED_PORTABILITY_ROBUSTNESS**. Selected candidate remains **BASE**; C2 is not authorized to proceed.

### Experimental Matrix

BASE=700, A=450, B=1000 characters, all using existing TextChunker; C=sentence-boundary-aware character chunking with preferred600/hard700. Absolute overlap100 and page containment are fixed. C0 parser output was reused unchanged. No new configurations, encoding, retrieval or model calls were run during closeout.

### Gold Mapping Integrity

All four geometric gates mapped55/55 with zero unresolved span ambiguity. This is not semantic equivalence. B has31 anchors mapped to two chunks, and both chunks are partial for every one of these31 anchors. All31 were screened geometrically; full texts are saved. Text inspection found decisive counterexamples; the remaining cases are not automatically approved.

The complete six-recovery audit and31 double mappings, including raw texts, immutable locators, lengths, coverage and ranks, are in closeout robustness audit (`artifacts/evaluation_v2/c1/closeout_robustness.md`; private historical artifact, not distributed), with machine-readable data (`artifacts/evaluation_v2/c1/closeout_robustness.json`; private historical artifact, not distributed).

**Decisive counterexample: V2Q072:G1.** Rank16 contains task partition/local-versus-UAV offloading but not the explicit weighted-energy objective, joint trajectory/resource variables or computation-bit constraint. Rank21 contains the latter facts but not the explicit partition. Both receive400/700 coverage (57.14%) and independently qualify. Top50 retrieves both and jointly preserves the anchor, but Top20 credits only the incomplete rank16 fragment. Thus a real Top50 recovery does not validate the ANY-mapped-chunk rule. No Gold, threshold, mapping or ranking was altered, and no revised recall score is invented.

A second counterexample is V2Q034:G1: the second mapped chunk has400/700 overlap but does not state the queried two UAV roles (computing unit and relay). V2Q074:G1 similarly splits architecture and constraints across independently credited fragments.

### Chunk Corpus Statistics

All configurations retain30 documents/432 pages, with no empty chunks, duplicate IDs or missing/extra pages. Chunk counts: BASE3837, A6421, B2627, C3988. Full character/token distributions remain in summary.json.

### ANN Sanity

All four completed the fixed ANN checks; exact diagnostics and unchanged raw rankings remain in the artifacts. Portability failure is distinct from ANN fidelity.

### Global Retrieval

Observed metrics below retain the original geometric mapping rule. They must not be described as validated semantic evidence-recall improvements or used to freeze B.

| Config | R@10 | MRR@10 | CR@20 | CR@30 | CR@50 |
| --- | --- | --- | --- | --- | --- |
| BASE | 54.05% | 0.3355 | 73.57% | 79.29% | 84.29% |
| A | 33.57% | 0.1777 | 43.57% | 48.57% | 61.43% |
| B | 71.90% | 0.4808 | 80.00% | 85.71% | 92.86% |
| C | 57.86% | 0.3601 | 70.71% | 72.14% | 80.71% |

### Miss Recovery

B observed Top50 recovery: V2Q049:G1, V2Q050:G2, V2Q056:G2, V2Q067:G1, V2Q068:G1, V2Q072:G1; lost0, net+6 under the unchanged proxy. Q050/Q056/Q067 preserve full anchors. Q049 rank2 preserves the conflict/MOP rationale, although its other mapped chunk does not. Q068 rank7 preserves core hybrid access/QoS/power-allocation use but not the whole anchor. Q072 requires the two complementary retrieved chunks; it is not a valid single-chunk-equivalence case. Six observed recoveries are therefore not six independently validated ANY-chunk equivalences.

### Boundary / Broadness Diagnosis

Original C0-category recovery observations are retained in summary.json. The MATERIAL bottleneck claim is **NOT SUPPORTED by this closeout**, because portability robustness failed. This does not establish that all observed gains are spurious or that chunking has no effect.

### Query-type Diagnostic

Existing descriptive results are retained unchanged in summary.json; no new metrics computed.

### Cross-document Diagnostic

Existing n=7 descriptive results are retained unchanged; no type-specific selection.

### Reranker Diagnostic

Reranker ranking metrics (R@10, MRR@10, Hit@5, R@5) are unchanged. CR@20/30/50 now reference the corresponding pre-rerank Hybrid pool. Actual reranker input is only Top20; CR30/50 describe upstream candidate coverage, not additional reranker inputs. The previous incorrect final-Top10-derived CR fields are preserved in summary_before_closeout.json for audit.

| Config | Reranked R@10 | Reranked MRR@10 | Hybrid CR@20 | Hybrid CR@30 | Hybrid CR@50 |
| --- | --- | --- | --- | --- | --- |
| BASE | 67.86% | 0.3074 | 73.57% | 79.29% | 84.29% |
| A | 33.57% | 0.1955 | 43.57% | 48.57% | 61.43% |
| B | 67.38% | 0.4402 | 80.00% | 85.71% | 92.86% |
| C | 57.86% | 0.3261 | 70.71% | 72.14% | 80.71% |

### Cost Trade-off

| Cost | BASE | B |
|---|---:|---:|
| Chunks | 3837 | 2627 |
| Index bytes | 44722875 | 41172948 |
| Corpus encoding seconds | 5746.11 (historical) | 4463.59 |

B has no structural cost explosion and uses fewer chunks/a smaller index. Absolute query-latency differences are not interpreted as a chunking-algorithm speedup: unchanged M3 query encoding also showed timing variation across configurations.

### Decision

Portability robustness: **FAIL**. Retain **BASE**; do not freeze B or enter C2. The observed proxy-metric leader remains B, but its semantic evidence-recall gain cannot be certified by the current ANY-chunk50% rule. Threshold and Gold remain unchanged. No additional chunk configurations or retrieval tuning were performed. Historical ledger rows remain preserved; C1 observations carry the failed portability-selection outcome.


## C1R Portable Gold Repair

Status: **COMPLETE**. Relevant regression:56 passed; independent recall oracle and git diff --check:PASS. Frozen-file and saved-ranking hashes unchanged.55/55 human-approved exact spans validated, zero ambiguous selections and zero validation failures. Selected candidate: **BASE**, TextChunker700/overlap100/page-contained. No new semantic annotation, encoding, index building, retrieval or reranker execution occurred.

### Why C1 Original Scoring Was Invalidated

Historical **C1 ORIGINAL PORTABILITY / INVALIDATED BY PORTABILITY AUDIT** measurements are retained unchanged. The old B Hybrid CR@50=92.86% is not reproduced: repaired B CR@50=70.95%. This is an annotation/evaluation correction on identical saved rankings, not an algorithm change. The50% old-anchor rule is not used here.

### Evidence Span Annotation Protocol

c1r_human_approvals_55.json (`benchmarks/real_research/v2/c1r_human_approvals_55.json`; private historical artifact, not distributed) contains all55 explicit human-approved raw selections. The target JSON was still PENDING per unit at entry; project-side finalization copied those exact approved selections, set55 APPROVED/true flags and derived offsets/hashes. No evidence_text was shortened, expanded, normalized, dehyphenated or otherwise rewritten.

All55 spans occur exactly once inside their original frozen Gold chunks and match the authoritative saved source at Unicode-codepoint half-open document offsets. Each SHA-256 is over the unchanged raw UTF-8 text. Page text was used only for identity/context checks, never to extend evidence. Annotation validation (`artifacts/evaluation_v2/c1r/annotation_validation.json`; private historical artifact, not distributed) and finalized annotation (`benchmarks/real_research/v2/dev_gold_evidence_spans_v2.json`; private historical artifact, not distributed) preserve provenance. Review source sections are unchanged; only annotation/status fields were updated.

### Blind Review

Human decisions came from the persisted approval record. No additional span selection occurred after outcomes were read. All55 units are included. TEST was treated only as opaque bytes for hash protection; no TEST semantic content, rankings or metrics were inspected.

### Span Statistics

| Statistic | Characters |
| --- | --- |
| min | 55.0 |
| p25 | 188.5 |
| median | 261.0 |
| p75 | 482.0 |
| p95 | 625.8 |
| max | 656.0 |
| mean | 309.5455 |

Spans >450: 15; >700: 0; >1000: 0. These observations do not alter spans.

### Mapping Integrity

| Config | Mapped | Unmapped | 1 | 2 | >=3 | Mean | Median | Max |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| BASE | 55 | 0 | 54 | 1 | 0 | 1.0182 | 1 | 2 |
| A | 22 | 33 | 22 | 0 | 0 | 0.4000 | 0 | 1 |
| B | 40 | 15 | 40 | 0 | 0 | 0.7273 | 1 | 1 |
| C | 47 | 8 | 46 | 1 | 0 | 0.8727 | 1 | 2 |

Mappings require exact document/version/source identity and100% containment of the approved span. Zero mappings in alternatives are valid representational limitations, not failed annotations. Each unit counts once regardless of multiplicity. Recall uses35-query macro averages, with every query retaining all its Gold units including unmapped units (55 units total). Thus macro recall is not total hits divided by55.

All four saved ranking identities passed: protected SHA-256, chunking hash, unique IDs, document/version/text equality, query identity, frozen M3 model fingerprint and config-specific namespace. Equal-weight RRF60/200+200/Top100 was independently reconstructed from saved BM25/Dense input rankings and matched exactly. Reranker output is a ten-item subset of the saved Hybrid Top20. No ranking changed.

### Re-scored C1 Results

#### bm25

| Config | Hit@5 | R@5 | R@10 | MRR@10 | CR@20 | CR@30 | CR@50 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| BASE | 45.71% | 35.71% | 46.67% | 0.2518 | 60.00% | 64.29% | 71.43% |
| A | 20.00% | 18.57% | 25.00% | 0.1742 | 25.00% | 28.57% | 31.43% |
| B | 48.57% | 43.33% | 50.00% | 0.3078 | 59.52% | 60.95% | 63.81% |
| C | 40.00% | 31.43% | 43.33% | 0.2394 | 53.33% | 59.05% | 64.76% |

#### dense

| Config | Hit@5 | R@5 | R@10 | MRR@10 | CR@20 | CR@30 | CR@50 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| BASE | 57.14% | 45.24% | 51.19% | 0.3115 | 61.19% | 62.62% | 70.71% |
| A | 31.43% | 27.86% | 34.52% | 0.1829 | 34.52% | 37.38% | 37.38% |
| B | 48.57% | 40.71% | 43.57% | 0.3074 | 53.81% | 59.52% | 65.24% |
| C | 45.71% | 39.05% | 39.76% | 0.3583 | 53.10% | 59.76% | 61.19% |

#### hybrid

| Config | Hit@5 | R@5 | R@10 | MRR@10 | CR@20 | CR@30 | CR@50 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| BASE | 45.71% | 32.86% | 54.05% | 0.3355 | 73.57% | 79.29% | 84.29% |
| A | 22.86% | 21.43% | 25.95% | 0.1752 | 30.24% | 32.38% | 38.10% |
| B | 57.14% | 47.86% | 52.38% | 0.3679 | 58.10% | 63.81% | 70.95% |
| C | 45.71% | 39.05% | 51.19% | 0.2972 | 61.19% | 62.62% | 69.76% |

#### reranked

| Config | Hit@5 | R@5 | R@10 | MRR@10 | CR@20 | CR@30 | CR@50 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| BASE | 68.57% | 54.76% | 67.86% | 0.3074 | 73.57% | 79.29% | 84.29% |
| A | 25.71% | 22.86% | 26.43% | 0.2088 | 30.24% | 32.38% | 38.10% |
| B | 48.57% | 45.24% | 50.71% | 0.3291 | 58.10% | 63.81% | 70.95% |
| C | 42.86% | 38.10% | 52.62% | 0.2801 | 61.19% | 62.62% | 69.76% |

Reranked CR20/30/50 reference pre-rerank Hybrid coverage; CR30/50 describe the upstream pool, not the actual Top20 reranker input. R@10/MRR@10/Hit@5/R@5 use final reranker rankings.

### Gain/Loss vs Repaired BASE

| Config | Recovered20 | Lost20 | Net20 | Recovered30 | Lost30 | Net30 | Recovered50 | Lost50 | Net50 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| BASE | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| A | 3 | 27 | -24 | 3 | 28 | -25 | 2 | 28 | -26 |
| B | 4 | 13 | -9 | 5 | 13 | -8 | 4 | 12 | -8 |
| C | 1 | 8 | -7 | 1 | 10 | -9 | 1 | 10 | -9 |

Exact Query?Gold IDs for every recovered/lost case are in c1r_gain_loss.csv (`benchmarks/real_research/v2/c1r_gain_loss.csv`; private historical artifact, not distributed) and summary.json. B Top50 recovers V2Q049:G1,V2Q050:G2,V2Q056:G2,V2Q067:G1 but loses12 previously retrieved units, net?8.

### Historical C0 Category Diagnostic

Historical labels are unchanged. Recovery is restricted to historical C0 misses still missed by repaired BASE. New losses are separately recorded above, without inventing historical labels for them. Descriptive only.

| Category | BASE miss20 | BASE miss50 | A recovered20 | A recovered50 | B recovered20 | B recovered50 | C recovered20 | C recovered50 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| BOUNDARY_SPLIT | 4 | 3 | 1 | 1 | 2 | 2 | 1 | 1 |
| CHUNK_TOO_BROAD | 6 | 4 | 2 | 1 | 2 | 2 | 0 | 0 |
| NOT_CHUNKING_RELATED | 6 | 3 | 0 | 0 | 0 | 0 | 0 | 0 |
| UNCLEAR | 1 | 1 | 0 | 0 | 0 | 0 | 0 | 0 |

### Cross-document

n=7; descriptive only.

| Config | R@10 | MRR@10 | CR@20 | CR@30 | CR@50 |
| --- | --- | --- | --- | --- | --- |
| BASE | 34.52% | 0.2194 | 46.43% | 53.57% | 64.29% |
| A | 3.57% | 0.0238 | 3.57% | 14.29% | 14.29% |
| B | 11.90% | 0.1190 | 11.90% | 26.19% | 26.19% |
| C | 34.52% | 0.0786 | 41.67% | 48.81% | 55.95% |

### Duplicate Evidence

Queries with repeated hits count any evidence unit matched by multiple retrieved chunks. Redundant chunks count only retrieved chunks that contribute no new approved evidence unit; a chunk also contributing a new unit is not counted as wasted. Waste percentage is redundant chunks divided by actual candidate slots (700 at20;1750 at50).

| Config | Queries20 | Redundant20 | Waste20 | Queries50 | Redundant50 | Waste50 |
| --- | --- | --- | --- | --- | --- | --- |
| BASE | 0 | 0 | 0.0000% | 1 | 1 | 0.0571% |
| A | 0 | 0 | 0.0000% | 0 | 0 | 0.0000% |
| B | 0 | 0 | 0.0000% | 0 | 0 | 0.0000% |
| C | 1 | 1 | 0.1429% | 1 | 1 | 0.0571% |

### Decision

**BASE**, by the first frozen selection criterion: Hybrid CR@50=84.29%, versus B70.95%, C69.76%, A38.10%. The order is BASE>B>C>A; no tie-break or weighted score is needed. B MRR@10 is higher, but cannot override candidate coverage under the frozen order. B has lower chunk/index cost, but negative Top50 gain/loss. Historical latency differences remain observational and are not claimed as an algorithm speedup.

Chunking bottleneck: **NOT SUPPORTED** for the tested alternatives on this reviewed DEV benchmark. This is not a claim that all other chunking strategies would fail. Ready for C2: **YES**, to freeze BASE. Regression and protection checks passed. C2 and V2-D have not started.


## C2 Chunking Freeze

Status: **COMPLETE**. Selected BASE behavior is frozen for DEV handoff; TEST_VALIDATED=false and PRODUCTION_DEFAULT=false. Ready for V2-D Fusion Optimization: **YES**. V2-D has not started. No retrieval, embedding, reranker, index or metric rerun occurred.

### Frozen implementation and configuration

[final_chunking_config.json](../benchmarks/real_research/v2/final_chunking_config.json) freezes the existing `backend/app/services/chunking/text_chunker.py:TextChunker` with target700 characters, overlap100 characters, page containment and no cross-page/sentence-aware/semantic chunking. Production code was not changed or reimplemented.

Existing paragraph packing and hard-window logic are retained exactly, including the paragraph-overflow branch that prepends overlap without a new target-length check. Therefore700 is the configured target, not a newly imposed universal hard maximum. The actual3837 frozen BASE chunks have observed maximum700. The implementation and ID/hash-service byte hashes are pinned in the config.

Config SHA-256 (complete deterministic UTF-8 JSON file including trailing LF):

`008845cdc4c45d8921173138d8b8591fa06d85e44082a5d73627801be3887079`

The external checksum file avoids a self-referential config hash. Aggregate hash definitions are recorded in the config; corpus_hash binds chunk IDs, exact raw text hashes, immutable locators and source document/version/PDF/text identities. It is distinct from the unchanged corpus-manifest file hash.

| Identity | SHA-256 |
|---|---|
| corpus_hash | `e51ec1fca029b03d6a007a0a3d862c501f54435d907ed0849e5b0aedff67ad76` |
| chunk_id_hash | `78d08f569068004ec2e2f458769c7a9c99110ec4891e4e30f17604eeba07307a` |
| chunk_text_hash | `9a8fd2b7b0565d1df597028f0c6b40019032e03f6ab77ee8c42d1ecf28ce5d3a` |
| chunk_locator_hash | `888842913bc7c2ee20c1c88f06e403dbd594f48c7b47feb88ba90361e4c8a924` |
| source_document_set_hash | `e7a50a7e4ac47f3e614a978aceb03686d07ff26d9d8cb6367003e8c37dc9ec19` |

### Corpus and historical identity

30 documents,432 pages,3837 chunks. All30 current PDF byte hashes match the frozen manifest and C0 source identities; no PDF was reparsed. The B6-used B4 authority snapshot, C0 reconstructed chunks and C1/C1R BASE corpus agree on document/version IDs, chunk IDs, normalized production chunk hashes, exact raw text, ordinal, page/section metadata and available raw character offsets. The saved B6 and C1 BASE BM25/Dense/Hybrid rankings are identical. No source representation was regenerated or replaced.

### C0?C1R closeout provenance

- C0: descriptive chunking audit and original portability preparation.
- C1: controlled four-configuration ablation.
- C1 closeout: portability robustness failed; partial fragments could be credited as complete evidence.
- C1R: all55 human-approved exact minimal spans validated, then existing rankings rescored using100% containment.

Historical B CR@50=92.86% remains **INVALIDATED BY PORTABILITY AUDIT**. Repaired pre-rerank Hybrid CR@50: BASE84.29%, B70.95%, C69.76%, A38.10%. BASE700/100 is selected by the first frozen criterion. Chunking bottleneck: **NOT SUPPORTED** for these alternatives on this reviewed DEV benchmark. No historical metrics were changed by C2.

### Representability diagnostic ? not a new experiment

All reviewed evidence spans are at most656 characters. Nevertheless, BASE maps55/55, A22/55, B40/55 and C47/55. Increasing chunk size alone does not guarantee full containment because window boundaries also move.

B's evidence-unit representability ceiling is40/55=72.73%. Its Hybrid CR@50 is70.95%, but these numbers use different weighting:72.73% is a unit fraction and70.95% is a35-query macro average. The corresponding macro representability ceiling is77.38%; these ceilings must not be directly conflated. Independently, **all12 BASE hits lost by B at Top50 are unmapped in B**. This supports a representability/chunk-boundary explanation for those losses, rather than failing to retrieve an already-representable span. Diagnostic only; it does not reopen chunk tuning.

### Protection and tests

20 tests passed,0 failed. Tests pin the complete config SHA/schema,700/100 parameters, actual per-page/no-cross-page behavior, stable chunk IDs/occurrences, implementation byte hashes and3837-chunk corpus identity. The integration check executes only the unchanged TextChunker in memory over saved source pages and compares outputs with BASE; it does not parse PDFs, write new chunks or access an index. Tests do not depend on alternative chunk configs.

All194 protected files were rehashed unchanged, including C0/C1/closeout/C1R history, retained A/B/C index files and saved rankings. DEV queries, opaque TEST bytes, original Frozen Gold, reviewed portable Gold, B5 Dense config, B6 Hybrid config and reranker implementation remain unchanged. Freeze validation (`artifacts/evaluation_v2/c2/freeze_validation.json`; private historical artifact, not distributed) records the protection manifest and test outcome.
