# ADR-008: Single Research Compare workflow with LangGraph

Status: Accepted for Phase 8.

1. **Why ordinary QA does not use LangGraph:** its stable linear Retrieval -> Evidence
   -> Generation -> Citation Validation contract needs no plan or coverage loop. The
   existing QA route/service remain untouched and have a no-LangGraph regression test.
2. **Why complex research needs LangGraph:** a comparison needs explicit typed state,
   structured field subtasks, separate evidence extraction, deterministic coverage and
   a bounded conditional retry. StateGraph expresses these transitions directly.
3. **Why single workflow rather than Multi-Agent:** all nodes serve one comparison
   request; separate autonomous roles have no demonstrated benefit and would add
   coordination, cost and failure modes. No general tools or external search are added.
4. **Why deterministic coverage:** a cell is covered only by a validated fact with
   matching document/version/chunk evidence. This is inspectable and testable without
   a second model/critic, and does not claim semantic entailment.
5. **Why Harness waits for Phase 9:** shared tool execution, centralized timeout/retry,
   token accounting, tracing and policies are separate concerns. Phase 8 uses direct
   adapters to existing services and emits only minimal execution metadata.
6. **Why ResearchRun is not asynchronous yet:** synchronous execution isolates workflow
   correctness from scheduling. Return a UUID run_id and bounded completed/partial/failed
   result without database/checkpoint migration; async ResearchRun is deferred.

Implementation uses official [StateGraph and conditional edges](https://docs.langchain.com/oss/python/langgraph/graph-api).
Pinned direct dependency: langgraph==1.0.5. No LangSmith service or key is required.
Research defaults to Hybrid (the stable text retrieval path), so Graph corpus
validation remains deferred without blocking a task. Scoped retrieval predicates are
pushed to existing SQL and Chroma adapters before Top-K; no ranking weights change.
Phase 6 embedding/reranker/fusion decisions and Phase 7 indexing contracts are unchanged.
