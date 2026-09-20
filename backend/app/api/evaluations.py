from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.schemas.evaluation import EvaluationRunRequest
from app.services.evaluation.retrieval_evaluator import RetrievalEvaluator
from app.utils.response import fail, success

router = APIRouter(prefix="/api/evaluations", tags=["Evaluations"])


@router.get("/latest")
def latest_evaluation(db: Session = Depends(get_db)):
    result = RetrievalEvaluator(db).latest()
    if result is None:
        return success({"status": "not_run", "message": "待本地评测"})
    return success(result)


@router.post("/run")
def run_evaluation(payload: EvaluationRunRequest, db: Session = Depends(get_db)):
    try:
        result = RetrievalEvaluator(db).run(payload.dataset_path, top_k=payload.top_k)
    except Exception as exc:
        return fail(f"Evaluation failed: {exc}")
    return success(result)
