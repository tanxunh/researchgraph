from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

import logging

from app.core.database import get_db
from app.core.llm_client import LLMClientError
from app.schemas.search import QAErrorEnvelope, QARequest, QASuccessEnvelope
from app.services.generation.citation_validator import CitationValidationError
from app.services.generation.grounded_answer_service import GroundedAnswerService
from app.services.retrieval.retrieval_service import ResearchRetrievalService, GraphUnavailableError
from app.utils.response import fail, success

router = APIRouter(prefix="/api/qa", tags=["QA"])


@router.post("", response_model=QASuccessEnvelope | QAErrorEnvelope)
async def qa(payload: QARequest, db: Session = Depends(get_db)):
    try:
        result = await GroundedAnswerService(ResearchRetrievalService(db)).answer(
            payload.question,
            mode=payload.retrieval_mode,
            top_k=payload.top_k,
            document_ids=payload.document_ids,
        )
    except GraphUnavailableError as exc:
        return fail(str(exc), {"error_type": "graph_unavailable"})
    except CitationValidationError as exc:
        return fail(str(exc), {"error_type": "citation_validation_failed",
                               "citation_validation": exc.validation.model_dump()})
    except LLMClientError as exc:
        return fail(str(exc), {"error_type": exc.error_type})
    except Exception:
        logging.getLogger(__name__).error("qa_retrieval_failure")
        return fail("QA retrieval failed. Check database and vector service.", {"error_type": "retrieval_error"})
    return success(result)
