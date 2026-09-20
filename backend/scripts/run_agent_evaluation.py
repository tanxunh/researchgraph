"""One-shot offline Research pilot. No retrieval tuning or external judge."""
from __future__ import annotations
import argparse
import asyncio
import json
import logging
import platform
import sys
from pathlib import Path
from urllib.parse import urlsplit

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

from app.core.config import get_settings
from app.core.database import SessionLocal
from app.schemas.research import ResearchTaskRequest
from app.services.research.workflow import ResearchService
from app.services.retrieval.retrieval_service import ResearchRetrievalService
from app.services.indexing.evidence_resolver import resolve_version_chunks
from app.services.evaluation.agent_evaluation import (
    load_agent_dataset, digest, measure, aggregate, badcase, review_markdown,
)


def write_json(path, data):
    path=Path(path)
    temporary=path.with_suffix(path.suffix+'.tmp')
    temporary.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    temporary.replace(path)


def model_metadata(settings):
    return dict(provider=urlsplit(settings.llm_base_url).hostname, model_id=settings.llm_model,
        temperature=0.1, structured_output='prompt JSON schema + strict Pydantic validation; no provider response_format',
        embedding=settings.embedding_model, embedding_provider=settings.embedding_provider,
        retrieval='hybrid', reranker=False, graph_assisted_agent_evaluation='NOT RUN',
        python=platform.python_version(),
        budget=dict(max_model_calls=settings.research_max_model_calls,max_tool_calls=settings.research_max_tool_calls,
                    max_retrieval_calls=settings.research_max_retrieval_calls,max_runtime_seconds=settings.research_max_runtime_seconds))


def persist(root,dataset,metadata,records,status):
    out=root/'results';out.mkdir(exist_ok=True)
    summary=aggregate(records)
    packet=dict(dataset_id=dataset.dataset_id,dataset_sha256=digest(root/'agent-eval-pilot-v1.json'),
        source_sha256=dataset.source_sha256,mode='REAL_LLM',status=status,configuration=metadata,
        semantic_review_status='SEMANTIC_REVIEW_PENDING',summary=summary,
        tasks=[r.model_dump(mode='json') for r in records])
    write_json(out/'agent-eval-pilot-v1-results.json',packet)
    text='# Agent Evaluation Pilot Summary\n\n'+status+'\n\nSEMANTIC_REVIEW_PENDING\n\n'
    text+='Production configuration: '+json.dumps(metadata,ensure_ascii=False)+'\n\n'
    text+='| Metric | Value |\n| --- | --- |\n'
    for k,v in summary.items():text+=f'| {k} | {json.dumps(v,ensure_ascii=False)} |\n'
    text+='\nRates: field/fact/tool coverage use pooled counts; expected-evidence coverage is task macro mean. Retry rates mean tasks with that retry / all executed valid tasks. Null means undefined, never zero.\n'
    text+='Citation validity is among returned reports with assessable supported claims; failed citation validation is separately a failure category.\n'
    text+='Honest Partial denominator: runs that reached coverage with missing grounded document/field cells; numerator: partial with explicit insufficient cells.\n'
    text+='Gold misses diagnose candidate coverage only, not semantic error. Retained Evidence is committed prompt-admitted state; failed mid-node calls may not be represented in retained state.\n'
    (out/'agent-eval-pilot-v1-summary.md').write_text(text,encoding='utf-8')
    review=review_markdown(dataset.tasks[:len(records)],records)
    (root/'AGENT_REPORT_REVIEW.md').write_text(review,encoding='utf-8')
    (out/'agent-eval-pilot-v1-review.md').write_text(review,encoding='utf-8')
    for task,record in zip(dataset.tasks,records):
        bad=badcase(task,record)
        if bad:write_json(root/'badcases'/f'{task.task_id}.json',bad.model_dump(mode='json'))


async def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--root',type=Path,required=True)
    parser.add_argument('--source',type=Path,required=True)
    parser.add_argument('--run-real',action='store_true')
    args=parser.parse_args()
    dataset=load_agent_dataset(args.root/'agent-eval-pilot-v1.json',args.source)
    settings=get_settings()
    if settings.embedding_provider!='bge' or settings.embedding_model!='BAAI/bge-small-zh-v1.5':
        raise SystemExit('production_embedding_configuration_mismatch')
    metadata=model_metadata(settings)
    # Read-only authoritative preflight: no create_all, migration or ingestion.
    with SessionLocal() as db:
        expected={(e.document_version_id,e.chunk_id):e for t in dataset.tasks for e in t.expected_evidence}
        resolved=resolve_version_chunks(db,list(expected))
        if any(key not in resolved or resolved[key]['document']['id']!=e.document_id or
               resolved[key]['location']['page_number']!=e.page or resolved[key]['location']['section_title']!=e.section
               for key,e in expected.items()):
            raise SystemExit('expected_evidence_locator_preflight_failed')
        retrieval=ResearchRetrievalService(db)
        vector_count=retrieval.vector_store.count()
        if vector_count<=0:raise SystemExit('production_vector_index_empty')
        print(json.dumps(dict(preflight='PASS',tasks=len(dataset.tasks),unique_gold=len(expected),
                              vectors=vector_count,llm_configured=bool(settings.llm_api_key),configuration=metadata)),flush=True)
    if not args.run_real:return
    if not settings.llm_api_key.strip():raise SystemExit('REAL_LLM_EVAL_REQUIRED')
    sentinel=args.root/'results'/'REAL_RUN_STARTED.json'
    # Exclusive creation prevents accidental repeat runs, including after interruption.
    with sentinel.open('x',encoding='utf-8') as f:
        json.dump(dict(dataset_sha256=digest(args.root/'agent-eval-pilot-v1.json'),configuration=metadata),f)
    records=[]
    for task in dataset.tasks:
        print('TASK_STARTED '+task.task_id,flush=True)
        with SessionLocal() as db:
            service=ResearchService(ResearchRetrievalService(db))
            response=await service.run(ResearchTaskRequest(question=task.question,document_ids=task.document_scope,
                        requested_fields=task.required_fields,retrieval_mode='hybrid'))
            # Save the completed execution before any offline analysis; never rerun if analysis fails.
            write_json(args.root/'results'/f'{task.task_id}-execution.json',dict(
                response=response.model_dump(mode='json'),execution=service.execution_summary.model_dump(mode='json'),
                trace=[e.model_dump(mode='json') for e in service.runtime.context.trace],
                facts=[f.model_dump(mode='json') for f in service.last_state['extracted_facts']],
                evidence=[e.model_dump(mode='json') for values in service.last_state['evidence_by_subtask'].values() for e in values],
                final_evidence=[e.model_dump(mode='json') for e in getattr(service,'final_evidence',[])]))
            record=measure(task,response,service.last_state,service.execution_summary,service.runtime.context.trace,
                           lambda keys:resolve_version_chunks(db,keys),getattr(service,'final_evidence',[]))
        records.append(record)
        persist(args.root,dataset,metadata,records,'AUTOMATIC EVALUATION COMPLETE' if len(records)==10 else 'RUNNING')
        print('TASK_FINISHED '+task.task_id+' '+record.metrics.completion,flush=True)
    print(json.dumps(aggregate(records)),flush=True)


if __name__=='__main__':
    logging.basicConfig(level=logging.WARNING)
    asyncio.run(main())
