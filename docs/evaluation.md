# Frozen evaluation

See the [complete frozen tables](../README.md#evaluation).

Retrieval: real-research-pilot-v1, 19 papers, 274 pages, 2,298 chunks, 30
HUMAN-CURATED English queries, 45 gold evidence, 38 unique chunks, 19/19 paper
coverage. Query categories: factual 6, exact_term 4, semantic 5, relational 5,
cross_document 6, multi_hop 4. Recall uses evidence locators, not document hits;
multi-gold recall is fractional. Candidate Recall@20 is measured before reranking.

Reranker: KEEP OPTIONAL, default OFF. CPU p50: 569.208 ms to 7480.493 ms.
English embedding: NO CLEAR WIN; production embedding unchanged. Real Graph/Auto
NOT RUN. Fusion diagnostics and real graph validation remain deferred.

Agent: 10 tasks, 7 completed, 3 failed closed (70% completion). A004/A007/A008
remain fact_document_mismatch. Human review covered 30 Claim-Evidence units from
7 trusted reports: 25 supported (83.33%), 5 partial (16.67%), 0 unsupported (0%).
Partial support is separate. These are not Agent accuracy or proof of zero
hallucination rate. Later correctness fixes do not retroactively change scores.

Backend Vertical Gate PASS; Final Browser Product Gate PASS (owner-confirmed).
Product acceptance is separate from quality evaluation. Screenshots: DEFERRED / OPTIONAL.
No benchmark or real LLM run was repeated for portfolio documentation.
