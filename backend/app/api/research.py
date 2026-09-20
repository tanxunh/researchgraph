from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.schemas.research import ResearchTaskRequest
from app.services.retrieval.retrieval_service import ResearchRetrievalService
from app.services.research.workflow import ResearchService
from app.utils.response import fail, success

router=APIRouter(prefix='/api/research',tags=['Research'])


def get_research_service(db:Session=Depends(get_db)):
    return ResearchService(ResearchRetrievalService(db))


@router.post('/tasks')
async def research_task(payload:ResearchTaskRequest,service:ResearchService=Depends(get_research_service)):
    result=await service.run(payload)
    data=result.model_dump()
    return fail('Research task failed.',data) if result.status=='failed' else success(data)
