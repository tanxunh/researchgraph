from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from app.schemas.evidence import Evidence
from app.services.generation.citation_validator import (
    CitationValidationError, CitationValidator, INSUFFICIENT_ANSWER,
)
from app.services.generation.evidence_builder import EvidenceBuilder
from app.services.generation.grounded_answer_service import GroundedAnswerService


def candidate(index=1):
    return {"chunk_id": f"chunk-{index}", "chunk_occurrence_id": index,
            "document_version_id": 11, "text": f"Evidence content {index}.",
            "document": {"id": 1, "version": 1, "version_id": 11, "title": "Study",
                         "source_uri": "C:\\private\\sources\\study.pdf"},
            "location": {"page_number": index, "section_title": "Results", "ordinal": index - 1},
            "source_type": "pdf", "source_snapshot_available": True,
            "scores": {"fusion_score": 0.01}}


def search(*rows):
    return {"query": "question", "mode": "hybrid", "results": list(rows), "timing": {}}


def resolved(rows):
    return {(row["document_version_id"], row["chunk_id"]): {
        "document": row["document"], "version": {"id": row["document_version_id"]},
        "chunk_id": row["chunk_id"], "text": row["text"], "location": row["location"],
    } for row in rows}


def setup_service(answer="Answer [C1]", rows=None, builder=None):
    rows = [candidate(i) for i in range(1, 4)] if rows is None else rows
    retrieval = SimpleNamespace(search=Mock(return_value=search(*rows)))
    llm = SimpleNamespace(generate=AsyncMock(return_value=answer))
    resolver = Mock(return_value=resolved(rows))
    service = GroundedAnswerService(retrieval, llm, evidence_builder=builder, resolver=resolver)
    return service, llm, resolver


def test_ids_ranking_deduplication_and_stable_locator():
    rows = [candidate(1), candidate(2), candidate(1), candidate(3)]
    first = EvidenceBuilder().build(search(*rows))
    second = EvidenceBuilder().build(search(*deepcopy(rows)))
    assert first == second
    assert [e.evidence_id for e in first] == ["C1", "C2", "C3"]
    assert [e.chunk_id for e in first] == ["chunk-1", "chunk-2", "chunk-3"]
    assert first[0].locator == (11, "chunk-1")


@pytest.mark.parametrize("field,value", [
    ("document_version_id", None), ("document_version_id", True),
    ("document_version_id", 0), ("chunk_id", ""), ("chunk_id", []),
    ("text", " "), ("source_type", None),
    ("location", {}), ("location", {"page_number": -1, "section_title": None, "ordinal": 0}),
    ("location", {"page_number": 1, "section_title": [], "ordinal": 0}),
    ("location", {"page_number": 1, "section_title": None, "ordinal": -1}),
])
def test_contract_rejects_incomplete_or_malformed_candidates(field, value):
    row = candidate()
    row[field] = value
    assert EvidenceBuilder().build(search(row)) == []


def test_version_mismatch_rejected():
    row = candidate()
    row["document"]["version_id"] = 12
    assert not EvidenceBuilder().build(search(row))


def test_budget_counts_metadata_and_never_truncates_chunk():
    rows = [candidate(i) for i in range(1, 4)]
    assert len(EvidenceBuilder(max_count=2).build(search(*rows))) == 2
    first = EvidenceBuilder().build(search(rows[0]))[0]
    budget = len(first.context()) + 2
    assert EvidenceBuilder(max_characters=budget).build(search(*rows)) == [first]
    rows[0]["document"]["title"] = "x" * budget
    selected = EvidenceBuilder(max_characters=budget).build(search(*rows))
    assert selected[0].chunk_id == "chunk-2" and selected[0].evidence_id == "C1"
    assert selected[0].content == rows[1]["text"]


@pytest.mark.parametrize("answer,valid,used,missing", [
    ("Answer [C1]", True, ["C1"], False),
    ("Answer [C999]", False, ["C999"], False),
    ("An unsupported answer", False, [], True),
    ("[C1][C1]", True, ["C1"], False),
    ("[C1][C3]", True, ["C1", "C3"], False),
    (INSUFFICIENT_ANSWER, True, [], False),
    (INSUFFICIENT_ANSWER + " Extra unsupported claim.", False, [], True),
])
def test_validator_rules(answer, valid, used, missing):
    rows = [candidate(i) for i in range(1, 4)]
    resolver = Mock(return_value=resolved(rows))
    result = CitationValidator(resolver).validate(answer, EvidenceBuilder().build(search(*rows)))
    assert result.valid is valid and result.used_citation_ids == used
    assert result.missing_citation is missing
    if "C999" in answer:
        assert result.invalid_citation_ids == ["C999"]
    if answer == "[C1][C1]":
        assert result.warnings == ["repeated_citation"]
        resolver.assert_called_once_with([(11, "chunk-1")])


@pytest.mark.parametrize("malformed", ["[c1]", "[C01]", "[C0]", "[C 1]", "[C1, C2]",
                                      "[C1", "C1]", "[[C1]]", "［C1］", "[C-1]", "[Cfoo]", "[C1\n"])
def test_malformed_citations_never_succeed(malformed):
    rows = [candidate()]
    result = CitationValidator(lambda _: resolved(rows)).validate(
        "Answer [C1] " + malformed, EvidenceBuilder().build(search(*rows)))
    assert not result.valid and "malformed_citation" in result.warnings


@pytest.mark.parametrize("change", ["deleted", "document", "text", "location"])
def test_resolver_missing_or_mismatched_evidence_fails(change):
    rows = [candidate()]
    data = resolved(deepcopy(rows))
    row = data[(11, "chunk-1")]
    if change == "deleted":
        data.clear()
    elif change == "document":
        row["document"]["id"] = 999
    elif change == "text":
        row["text"] = "Not the prompt text"
    else:
        row["location"]["page_number"] = 100
    result = CitationValidator(lambda _: data).validate("[C1]", EvidenceBuilder().build(search(*rows)))
    assert not result.valid and result.invalid_citation_ids == ["C1"]


@pytest.mark.asyncio
async def test_only_actual_citations_and_prompt_source_privacy():
    service, llm, resolver = setup_service("Answer [C1][C3][C1]")
    result = await service.answer("Question", mode="hybrid")
    assert result["status"] == "answered"
    assert [c["citation_id"] for c in result["citations"]] == ["C1", "C3"]
    assert result["evidence_count"] == result["retrieved_evidence_count"] == 3
    assert result["citations"][0]["document_version_id"] == 11
    assert result["citations"][0]["page"] == 1
    assert "C:\\private" not in str(result)
    prompt = llm.generate.call_args.args[0]
    assert "Document: Study" in prompt and "Version: 11" in prompt
    assert "Page: 1" in prompt and "Section: Results" in prompt
    assert "fusion_score" not in prompt and "C:\\private" not in prompt
    resolver.assert_called_once_with([(11, "chunk-1"), (11, "chunk-3")])
    llm.generate.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("rows", [[], [None], [{"chunk_id": "orphan", "missing": True}]])
async def test_no_evidence_never_calls_model(rows):
    service, llm, resolver = setup_service(rows=[])
    service.retrieval.search.return_value = search(*rows)
    result = await service.answer("Question")
    assert result["status"] == "insufficient_evidence" and result["evidence_count"] == 0
    assert result["citations"] == []
    llm.generate.assert_not_called()
    resolver.assert_not_called()


@pytest.mark.asyncio
async def test_budget_empty_never_calls_model():
    service, llm, _ = setup_service(builder=EvidenceBuilder(max_characters=1))
    assert (await service.answer("Question"))["status"] == "insufficient_evidence"
    llm.generate.assert_not_called()


@pytest.mark.asyncio
async def test_explicit_insufficiency_allows_no_citations():
    service, _, _ = setup_service(INSUFFICIENT_ANSWER)
    result = await service.answer("Question")
    assert result["status"] == "insufficient_evidence" and result["citations"] == []
    assert result["evidence_count"] == 3 and result["citation_validation"]["valid"]


@pytest.mark.asyncio
@pytest.mark.parametrize("answer", ["Answer [C999]", "Answer without citations", "Answer [C1, C2]"])
async def test_invalid_answer_is_error_not_answered(answer):
    service, llm, _ = setup_service(answer)
    with pytest.raises(CitationValidationError):
        await service.answer("Question")
    llm.generate.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("answer", [None, "", " "])
async def test_empty_model_output_is_infrastructure_failure(answer):
    from app.core.llm_client import LLMClientError
    service, _, _ = setup_service(answer)
    with pytest.raises(LLMClientError) as error:
        await service.answer("Question")
    assert error.value.error_type == "invalid_model_response"


@pytest.mark.asyncio
async def test_resolver_failure_is_not_validated_success():
    service, _, resolver = setup_service()
    resolver.side_effect = RuntimeError("database unavailable")
    with pytest.raises(RuntimeError):
        await service.answer("Question")


def test_legacy_source_reference_is_explicit_warning():
    row = candidate()
    row["source_snapshot_available"] = False
    result = CitationValidator(lambda _: resolved([row])).validate(
        "[C1]", EvidenceBuilder().build(search(row)))
    assert result.valid and result.warnings == ["raw_source_unavailable"]
