"""Deterministic offline measurements; no model judge and no gold creation."""
from __future__ import annotations

import hashlib
import json
import statistics
from collections import Counter
from pathlib import Path

from app.schemas.agent_evaluation import AgentDataset, AgentRunRecord, BadCase, TaskMetrics
from app.schemas.evidence import CitationValidation
from app.schemas.research import EvidenceLocator
from app.services.generation.citation_validator import CitationValidator


def digest(path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load_agent_dataset(path, source_path) -> AgentDataset:
    dataset = AgentDataset.model_validate_json(Path(path).read_text(encoding='utf-8-sig'))
    source = json.loads(Path(source_path).read_text(encoding='utf-8-sig'))
    if digest(source_path) != dataset.source_sha256:
        raise ValueError('source_benchmark_hash_mismatch')
    if source['benchmark_id'] != dataset.source_benchmark or source['annotation_source'] != 'HUMAN_CURATED':
        raise ValueError('human_gold_required')
    queries = {q['query_id']: q for q in source['queries']}
    if len({t.task_id for t in dataset.tasks}) != len(dataset.tasks):
        raise ValueError('duplicate_task_id')
    for task in dataset.tasks:
        expected = {}
        for qid in task.source_query_ids:
            q = queries[qid]
            if q['annotation_status'] != 'HUMAN_APPROVED':
                raise ValueError('unapproved_gold')
            for e in q['gold_evidence']:
                expected.setdefault((e['document_id'], e['document_version_id'], e['chunk_id']), e)
        actual = {(e.document_id, e.document_version_id, e.chunk_id): e.model_dump() for e in task.expected_evidence}
        if actual != expected:
            raise ValueError('expected_evidence_not_exact_source_union')
    return dataset


def identity(item) -> tuple[int, int, str]:
    return item.document_id, item.document_version_id, item.chunk_id


def ratio(numerator, denominator):
    return numerator / denominator if denominator else None


def measure(task, response, state, execution, trace, resolver, final_evidence=()) -> AgentRunRecord:
    # Measure committed, prompt-admitted Evidence, not every raw ranked candidate.
    admitted = {identity(e): e for rows in state['evidence_by_subtask'].values() for e in rows}
    facts = state['extracted_facts']
    rows = resolver(list(dict.fromkeys(e.locator for e in admitted.values()))) if admitted else {}
    valid_evidence = {key: e for key, e in admitted.items() if CitationValidator._matches(e, rows.get(e.locator))}
    valid_facts = []
    for fact in facts:
        supports = set(fact.supporting_evidence_ids)
        keys = {e.key for e in fact.evidence_locators}
        valid = bool(keys) and supports == keys and all(
            identity(e) in valid_evidence and (e.document_id, e.document_version_id) ==
            (fact.document_id, fact.document_version_id) for e in fact.evidence_locators)
        if valid:
            valid_facts.append(fact)
    required_cells = {(d, f) for d in task.document_scope for f in task.required_fields}
    fact_cells = {(f.document_id, f.field) for f in valid_facts if f.fact_status == 'SUPPORTED'} & required_cells
    checker_cells = {(c.document_id, c.field) for c in response.coverage.covered}
    covered_cells = fact_cells & checker_cells
    fields = {field for _, field in fact_cells}
    completion = ('failed' if response.status == 'failed' else
                  'completed' if response.status == 'completed' and covered_cells == required_cells else 'partial')
    flags = []
    if len(valid_facts) != len(facts):
        flags.append('ungrounded_structured_fact')
    if response.status == 'completed' and covered_cells != required_cells:
        flags.append('completed_with_missing_coverage')
    validation = None
    if response.report and response.citations:
        by_id = {e.evidence_id: e for e in final_evidence}
        available = [by_id[c.citation_id] for c in response.citations if c.citation_id in by_id]
        validator = CitationValidator(lambda keys: {k: rows[k] for k in keys if k in rows})
        text = '\n'.join([response.report.summary] +
                         [c.value for c in response.report.comparison if c.status == 'supported'] +
                         response.report.limitations)
        checks = [validator.validate(text, available), validator.validate(response.report.summary, available)]
        for item in response.report.comparison:
            if item.status == 'supported':
                support_keys = {e.key for f in valid_facts if (f.document_id, f.field) ==
                                (item.document_id, item.field) for e in f.evidence_locators}
                scoped = [e for e in available if EvidenceLocator(document_id=e.document_id,
                          document_version_id=e.document_version_id, chunk_id=e.chunk_id).key in support_keys]
                checks.append(validator.validate(item.value, scoped))
        invalid = set(h for check in checks for h in check.invalid_citation_ids)
        invalid.update(c.citation_id for c in response.citations if c.citation_id not in by_id or
                       identity(c) != identity(by_id[c.citation_id]))
        validation = CitationValidation(valid=all(c.valid for c in checks) and not invalid,
            used_citation_ids=checks[0].used_citation_ids, invalid_citation_ids=sorted(invalid),
            missing_citation=any(c.missing_citation for c in checks),
            warnings=sorted({w for c in checks for w in c.warnings}))
    elif response.report and any(c.status == 'supported' for c in response.report.comparison):
        validation = CitationValidator(lambda keys: rows).validate(response.report.summary, [])
    if validation is not None and not validation.valid:
        flags.append('returned_invalid_citation')
    expected = {identity(e) for e in task.expected_evidence}
    cited = {identity(c) for c in response.citations}
    tools = [e for e in trace if e.event_type == 'tool_call' and e.attempt and e.attempt > 0]
    model_retries = sum(e.event_type == 'model_call' and bool(e.attempt and e.attempt > 1) for e in trace)
    tool_retries = sum(e.event_type == 'tool_call' and bool(e.attempt and e.attempt > 1) for e in trace)
    coverage_ran = any(e.event_type == 'node_finished' and e.node == 'check_coverage' and e.status == 'succeeded' for e in trace)
    missing = required_cells - fact_cells
    insuff = {(c.document_id, c.field) for c in response.report.comparison if c.status == 'insufficient_evidence'} if response.report else set()
    metrics = TaskMetrics(completion=completion, required_field_count=len(task.required_fields),
        covered_field_count=len(fields), field_coverage=len(fields)/len(task.required_fields),
        required_cell_count=len(required_cells), covered_cell_count=len(covered_cells),
        document_field_coverage=len(covered_cells)/len(required_cells), total_facts=len(facts),
        grounded_facts=len(valid_facts), grounded_fact_rate=ratio(len(valid_facts), len(facts)),
        citation_validation=validation,
        valid_cited_evidence=len(set(validation.used_citation_ids)-set(validation.invalid_citation_ids)) if validation else 0,
        invalid_citations=len(validation.invalid_citation_ids) if validation else 0,
        missing_citation=validation.missing_citation if validation else False,
        expected_count=len(expected), retrieved_expected_count=len(expected & set(admitted)),
        cited_expected_count=len(expected & cited),
        retrieved_expected_evidence_coverage=len(expected & set(admitted))/len(expected),
        cited_expected_evidence_coverage=len(expected & cited)/len(expected),
        successful_tool_calls=sum(e.status == 'succeeded' for e in tools), executed_tool_calls=len(tools),
        tool_success_rate=ratio(sum(e.status == 'succeeded' for e in tools),len(tools)),
        workflow_retries=response.retry_count, model_transient_retries=model_retries,
        tool_transient_retries=tool_retries, honest_partial_eligible=coverage_ran and bool(missing),
        honest_partial=response.status == 'partial' and bool(missing) and missing <= insuff,
        correctness_flags=flags)
    record = AgentRunRecord(task_id=task.task_id, run_id=response.run_id, task_type=task.task_type,
        response=response, retrieved_evidence=list(admitted.values()), facts=facts,
        final_citation_ids=[c.citation_id for c in response.citations], execution=execution,
        trace=trace, metrics=metrics, failure_category=None, root_cause=None)
    record.failure_category, record.root_cause = classify(record)
    return record


def classify(record):
    m, ex = record.metrics, record.execution
    if 'returned_invalid_citation' in m.correctness_flags:
        return 'citation_failure', 'Returned citations fail the existing structural validator.'
    if 'completed_with_missing_coverage' in m.correctness_flags:
        return 'coverage_failure', 'Completed status conflicts with grounded document/field coverage.'
    if 'ungrounded_structured_fact' in m.correctness_flags:
        return 'extraction_failure', 'A stored fact lacks a matching admitted historical evidence locator.'
    if m.completion == 'completed':
        return None, None  # Gold misses alone do not make an otherwise valid report a failure.
    error = ex.error_code or ''
    if ex.budget_exceeded:
        return 'budget_exhausted', 'Harness stopped at an execution budget; see budget_exceeded trace operation.'
    if error.startswith('tool_'):
        return 'tool_failure', 'Runtime reported a typed tool failure; payloads are excluded.'
    if error in {'model_timeout', 'model_transient_error', 'model_provider_error', 'model_internal_error'} or error.startswith('llm_'):
        return 'model_failure', 'Model infrastructure failed; not evidence of semantic answer quality.'
    if error == 'citation_validation_failed':
        return 'citation_failure', 'Workflow rejected the draft at citation validation; no trusted report returned.'
    node = next((e.node for e in reversed(record.trace) if e.event_type == 'node_finished' and e.status == 'failed'), None)
    if m.completion == 'failed' and node in {'plan_task', 'extract_facts', 'synthesize'}:
        return {'plan_task':'planning_failure','extract_facts':'extraction_failure','synthesize':'synthesis_failure'}[node], f'Execution failed at {node}; inspect the typed error and retained state, without inferring semantic cause.'
    if not record.retrieved_evidence:
        return 'retrieval_miss', 'No committed admitted Evidence was available; this is an observed retrieval-stage gap.'
    if m.retrieved_expected_count < m.expected_count:
        return 'evidence_partial', 'Incomplete coverage coincides with missing expected Evidence; diagnostic association, not proof of answer incorrectness or sole cause.'
    if not record.facts:
        return 'extraction_failure', 'Expected Evidence was admitted but no committed StructuredFact was extracted.'
    if m.workflow_retries:
        return 'retry_ineffective', 'Missing coverage remains after the bounded workflow refinement.'
    if m.completion == 'partial':
        return 'coverage_failure', 'Required document/field coverage remains incomplete.'
    return 'unknown', 'Available trace/state does not isolate the failure cause.'


def aggregate(records):
    n = len(records)
    mean = lambda values: statistics.mean(values) if values else None
    ms = [r.metrics for r in records]
    ex = [r.execution for r in records]
    validations = [m.citation_validation for m in ms if m.citation_validation is not None]
    return dict(valid_tasks=n, counts=dict(Counter(m.completion for m in ms)),
        task_completion_rate=ratio(sum(m.completion == 'completed' for m in ms), n),
        field_coverage=ratio(sum(m.covered_field_count for m in ms),sum(m.required_field_count for m in ms)),
        document_field_coverage=ratio(sum(m.covered_cell_count for m in ms),sum(m.required_cell_count for m in ms)),
        grounded_fact_rate=ratio(sum(m.grounded_facts for m in ms),sum(m.total_facts for m in ms)),
        citation_structural_validity=ratio(sum(v.valid for v in validations),len(validations)),
        citation_evaluated_reports=len(validations), valid_cited_evidence=sum(m.valid_cited_evidence for m in ms),
        invalid_citations=sum(m.invalid_citations for m in ms), missing_citation_reports=sum(m.missing_citation for m in ms),
        retrieved_expected_evidence_coverage=mean([m.retrieved_expected_evidence_coverage for m in ms]),
        cited_expected_evidence_coverage=mean([m.cited_expected_evidence_coverage for m in ms]),
        tool_success_rate=ratio(sum(m.successful_tool_calls for m in ms),sum(m.executed_tool_calls for m in ms)),
        workflow_retry_rate=ratio(sum(m.workflow_retries > 0 for m in ms),n),
        model_retry_rate=ratio(sum(m.model_transient_retries > 0 for m in ms),n),
        tool_retry_rate=ratio(sum(m.tool_transient_retries > 0 for m in ms),n),
        model_transient_retries=sum(m.model_transient_retries for m in ms),
        tool_transient_retries=sum(m.tool_transient_retries for m in ms),
        average_model_calls=mean([e.model_calls for e in ex]), average_tool_calls=mean([e.tool_calls for e in ex]),
        average_retrieval_calls=mean([e.retrieval_calls for e in ex]), average_duration_ms=mean([e.duration_ms for e in ex]),
        budget_exhaustion_rate=ratio(sum(e.budget_exceeded for e in ex),n),
        budget_triggers=dict(Counter(e.operation for r in records for e in r.trace if e.event_type == 'budget_exceeded')),
        honest_partial_rate=ratio(sum(m.honest_partial and m.honest_partial_eligible for m in ms),sum(m.honest_partial_eligible for m in ms)),
        honest_partial_eligible=sum(m.honest_partial_eligible for m in ms),
        failure_breakdown=dict(Counter(r.failure_category for r in records if r.failure_category)),
        semantic_review_status='SEMANTIC_REVIEW_PENDING', supported_claim_rate=None,
        partially_supported_claim_rate=None, unsupported_claim_rate=None)


def badcase(task, record):
    if record.failure_category is None:
        return None
    return BadCase(task_id=task.task_id, question=task.question, task_type=task.task_type,
        failure_category=record.failure_category, expected_fields=task.required_fields,
        covered_fields=sorted({f.field for f in record.facts if f.field in task.required_fields}),
        expected_evidence=task.expected_evidence,
        retrieved_evidence=[EvidenceLocator(document_id=e.document_id, document_version_id=e.document_version_id, chunk_id=e.chunk_id) for e in record.retrieved_evidence],
        cited_evidence=[EvidenceLocator(document_id=e.document_id, document_version_id=e.document_version_id, chunk_id=e.chunk_id) for e in record.response.citations],
        trace_summary=record.execution, root_cause=record.root_cause)


def review_markdown(tasks, records):
    lines = ['# Agent Report Review', '', 'SEMANTIC_REVIEW_PENDING', '',
        'Human labels only: SUPPORTED / PARTIALLY_SUPPORTED / UNSUPPORTED. Leave PENDING until reviewed.',
        'Summary and supported comparison items are review units; a unit with multiple claims should be split by the reviewer.',
        'Evidence snippets are navigation aids; full admitted chunks and immutable locators are saved in the run records.', '']
    for task, record in zip(tasks, records):
        lines += [f'## {task.task_id} — {record.metrics.completion}', '', task.question, '']
        report = record.response.report
        if not report:
            lines += ['No trusted report returned. No semantic score assigned.', '']; continue
        evidence = {identity(e): e for e in record.retrieved_evidence}
        citations = {c.citation_id:c for c in record.response.citations}
        claims = [('summary', report.summary)] + [(f'{c.document_id}/{c.field}', c.value) for c in report.comparison if c.status == 'supported']
        if not citations:
            lines += ['Insufficient-evidence report; no supported claims to score.', '']; continue
        for index, (label, text) in enumerate(claims, 1):
            # Extraction of handles and their validity belongs to the existing validator.
            handles = CitationValidator(lambda keys: {}).validate(text, []).used_citation_ids
            lines += [f'### {task.task_id}-C{index:02d} ({label})', '', f'Claim: {text}', '',
                      f'Citation IDs: {", ".join(handles) or "NONE"}', '', 'Human label: PENDING', '']
            for handle in handles:
                citation = citations.get(handle)
                if citation:
                    e = evidence.get(identity(citation))
                    snippet = e.content[:1000] if e else citation.snippet
                    lines += [f'- {handle} locator {identity(citation)}; page {citation.page}',
                              '  ' + snippet.replace('\n', '\n  ') + (' [excerpt]' if e and len(e.content)>1000 else ''), '']
        lines += ['Limitations: ' + ' | '.join(report.limitations), '']
    return '\n'.join(lines)
