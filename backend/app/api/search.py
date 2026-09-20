from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.schemas.search import SearchRequest
from app.services.retrieval.retrieval_service import ResearchRetrievalService, GraphUnavailableError
from app.utils.response import fail, success
from app.services.search_scope import resolve_search_scope

router = APIRouter(prefix="/api/search", tags=["Search"])


@router.post("")
def search(payload: SearchRequest, db: Session = Depends(get_db)):
    try:
        scope = resolve_search_scope(db, payload.document_ids)
        if payload.document_ids == []:
            return JSONResponse(status_code=422, content=fail(
                "Select at least one document or omit document_ids for global search.",
                {"error_type": "empty_document_scope", "scope": scope}))
        eligible_ids = scope.get("eligible_document_ids")
        if payload.document_ids is not None and not eligible_ids:
            return fail("None of the selected documents are currently searchable.",
                        {"error_type": "no_eligible_documents", "scope": scope})
        result = ResearchRetrievalService(db).search(payload.query, mode=payload.retrieval_mode, top_k=payload.top_k,
            document_ids=eligible_ids)
    except GraphUnavailableError as exc:
        return fail(str(exc), {"error_type": "graph_unavailable"})
    except Exception as exc:
        return fail(f"Search failed: {exc}")
    return success({**result, "scope": scope})
