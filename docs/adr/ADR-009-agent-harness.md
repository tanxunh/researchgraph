# ADR-009: Research-only Agent Harness

Status: Accepted. Scope: Phase 9.

1. **LangGraph vs Harness:** LangGraph owns workflow/state/branches/coverage loops.
   Harness owns reliable model/tool invocation, budgets, error policy and trace. It
   cannot select nodes, plan tasks or implement another agent loop.
2. **Why an allowlist:** exactly search_evidence and resolve_evidence are bound to
   existing read-only services with typed I/O. No arbitrary function, import, shell,
   filesystem or SQL execution can be selected by a model or request.
3. **Why centralized retry:** only explicit transient failures receive one retry,
   with every attempt counted/traced. Invalid schema, planner, business or citation
   output must fail under existing semantics, never be silently repaired. Async
   models have cancellable timeouts; synchronous tools use safe pre/post boundaries.
4. **Why execution budgets:** workflow limits bound tasks/refinement, but not repeated
   infrastructure attempts or elapsed time. Separate model/tool/retrieval counters
   and an overall deadline stop new work. A report requiring further unbudgeted
   synthesis or validation cannot be returned as trusted partial output.
5. **Why Research only:** Phase 8 provides concrete repeated execution points; ordinary
   Search/QA already have a stable direct path. This phase needs no universal Context
   framework, API redesign, new dependencies, tables or durable step store.
6. **Why no Multi-Agent/MCP:** neither is needed to execute this one workflow reliably.
   Coordination and external tool discovery are separately authorized future work,
   alongside durable resume, async ResearchRun, quality evaluation and distributed trace.
