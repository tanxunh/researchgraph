"""Single-use real HTTP vertical gate. No service imports or automatic task retries."""
import argparse
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
import httpx
from urllib.parse import urlparse

QUESTION = 'What optimization objective does the latency-constrained wireless-powered MEC design use?'
RESEARCH = 'Compare DROO and the latency-constrained wireless-powered MEC design in terms of system roles, local/offloading methods, and optimization objectives.'

def runtime_preflight(client, *, post_warmup=False):
    """BGE contract: cold=False/False/error=None is legal only before real import."""
    def read(path):
        response=client.get(path)
        response.raise_for_status()
        body=response.json()
        if body.get('code')!=0:
            raise ValueError('RUNTIME_METADATA_UNAVAILABLE')
        return body['data']
    health=read('/health')
    system=read('/api/system/status')
    embedding=system.get('embedding',{})
    llm=health.get('llm',{})
    for condition,code in [
        (embedding.get('configured_provider')=='bge','EMBEDDING_PROVIDER_MISMATCH'),
        (embedding.get('configured_model')=='BAAI/bge-small-zh-v1.5','EMBEDDING_MODEL_MISMATCH'),
        (embedding.get('dimension')==512 and embedding.get('device')=='cpu','EMBEDDING_SHAPE_MISMATCH'),
        ('error' in embedding and embedding['error'] is None,'EMBEDDING_LOAD_FAILED'),
        ((embedding.get('ready') is True and embedding.get('loaded') is True) or
         (not post_warmup and embedding.get('ready') is False and embedding.get('loaded') is False),
         'EMBEDDING_NOT_READY_AFTER_WARMUP' if post_warmup else 'EMBEDDING_STATE_INVALID'),
        (llm.get('graph_extraction_enabled') is False,'GRAPH_MUST_BE_DISABLED'),
        (llm.get('llm_model')=='deepseek-chat','LLM_MODEL_MISMATCH'),
        (urlparse(llm.get('llm_base_url','')).hostname=='api.deepseek.com'
         and urlparse(llm.get('llm_base_url','')).scheme=='https','LLM_PROVIDER_MISMATCH'),
        (llm.get('llm_api_key_configured') is True,'LLM_CONFIGURATION_UNAVAILABLE'),
        (system.get('llm')==llm,'RUNTIME_METADATA_INCONSISTENT'),
    ]:
        if not condition:
            raise ValueError(code)
    return {'embedding':{k:embedding[k] for k in ('configured_provider','configured_model','dimension','device','loaded','ready')},
            'llm':{k:llm[k] for k in ('llm_model','llm_base_url','graph_extraction_enabled','llm_api_key_configured')}}

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--base-url', default=os.getenv('BASE_URL', 'http://127.0.0.1:8765'))
    parser.add_argument('--chroma-url', default=os.getenv('CHROMA_URL'))
    parser.add_argument('--pdf-a', default=os.getenv('PDF_A'), required=not os.getenv('PDF_A'))
    parser.add_argument('--pdf-b', default=os.getenv('PDF_B'), required=not os.getenv('PDF_B'))
    parser.add_argument('--request-timeout', type=float, default=float(os.getenv('REQUEST_TIMEOUT', '360')))
    parser.add_argument('--job-timeout', type=float, default=float(os.getenv('JOB_TIMEOUT', '600')))
    parser.add_argument('--output', default='artifacts/release_gate/rg003-vertical-result.json')
    args = parser.parse_args()
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    # Reserve before any action: a second invocation cannot repeat paid requests.
    with output.open('x', encoding='utf-8') as handle:
        handle.write('{}')
    result = dict(timestamp=datetime.now(timezone.utc).isoformat(), release_gate='FAIL',
                  steps={}, documents={}, qa_requests=0, research_requests=0, graph_extraction_enabled=False)
    step = 'Preflight'
    client = httpx.Client(base_url=args.base_url, timeout=args.request_timeout, trust_env=False)
    def save():
        output.write_text(json.dumps(result, indent=2)+'\n', encoding='utf-8')
    def check(condition, reason):
        if not condition:
            raise ValueError(reason)
    def call(method, url, **kwargs):
        response = client.request(method, url, **kwargs)
        check(response.is_success, 'HTTP_'+str(response.status_code))
        body = response.json()
        if body.get('code') != 0:
            data = body.get('data') or {}
            result['rejection'] = {k:data[k] for k in ('status','run_id','errors','error_type') if k in data}
            raise ValueError('API_BUSINESS_FAILURE')
        return response.status_code, body['data']
    def passed():
        result['steps'][step] = 'PASS'; save(); print(step+': PASS', flush=True)
    def locator(c):
        return c['document_id'], c['document_version_id'], c['chunk_id']
    def resolve(c):
        _, doc = call('GET', '/api/documents/'+str(c['document_id']))
        _, versions = call('GET', '/api/documents/'+str(c['document_id'])+'/versions')
        check(any(v['id']==c['document_version_id'] and v['is_current'] for v in versions), 'VERSION_NOT_RESOLVED')
        chunk = next((x for x in doc['chunks'] if x['stable_chunk_id']==c['chunk_id']), None)
        check(chunk is not None and chunk['document_version_id']==c['document_version_id'], 'CHUNK_NOT_RESOLVED')
        check(chunk['page_number']==c['page'] and chunk['section_title']==c['section'], 'LOCATION_MISMATCH')
    def verify_storage(documents):
        collections = client.get(args.chroma_url+'/api/v1/collections').json()
        check(len(collections)==1, 'CHROMA_ISOLATION_INVALID')
        vector_data = client.post(args.chroma_url+'/api/v1/collections/'+collections[0]['id']+'/get',json={'include':['metadatas']}).json()
        metadata = vector_data['metadatas']
        for doc in documents:
            _, detail = call('GET', '/api/documents/'+str(doc['document_id']))
            check(detail['status']=='ready' and detail['chunks'], 'DOCUMENT_NOT_READY')
            ids = {c['stable_chunk_id'] for c in detail['chunks']}
            actual = {i for i,m in zip(vector_data['ids'], metadata) if m['document_id']==doc['document_id']}
            check(ids==actual, 'VECTOR_MEMBERSHIP_MISMATCH')
            check(detail['entity_count']==0 and detail['relation_count']==0, 'UNEXPECTED_GRAPH')
            doc.update(status='ready',chunks=len(ids),vector_count=len(actual),current_version=detail['current_version'])
    try:
        result['environment'] = runtime_preflight(client)
        _, docs = call('GET', '/api/documents')
        check(docs==[], 'ISOLATED_DATABASE_NOT_EMPTY')
        result['environment']['initial_document_count']=0
        check(bool(args.chroma_url), 'CHROMA_URL_REQUIRED_FOR_STORAGE_VERIFICATION')
        heartbeat = client.get(args.chroma_url+'/api/v1/heartbeat')
        check(heartbeat.is_success, 'CHROMA_UNAVAILABLE')
        passed()
        for paper, filename in [('P002',args.pdf_a),('P007',args.pdf_b)]:
            step = 'Fresh Import '+paper
            started = time.monotonic()
            with Path(filename).open('rb') as handle:
                status, submitted = call('POST', '/api/documents/import/file/async',
                    files={'file':(Path(filename).name,handle,'application/pdf')})
            check(status==202 and submitted.get('job_id'), 'ASYNC_ACCEPTANCE_INVALID')
            result['documents'][paper] = dict(job_id=submitted['job_id'], document_id=submitted.get('document_id'),
                                            acceptance_ms=round((time.monotonic()-started)*1000,2))
            passed()
            step = 'Job Completion '+paper
            doc = result['documents'][paper]
            deadline = time.monotonic()+args.job_timeout
            while True:
                _, job = call('GET', '/api/index-jobs/'+str(doc['job_id']))
                doc['job'] = {k:job.get(k) for k in ('status','progress_stage','attempts','started_at','finished_at','error_type')}
                doc['document_id'] = job.get('document_id') or doc['document_id']; save()
                if job['status'] in ('failed','succeeded'):
                    break
                check(time.monotonic()<deadline, 'JOB_TIMEOUT'); time.sleep(1.5)
            check(job['status']=='succeeded' and doc['document_id'], 'IMPORT_FAILED')
            check(job['started_at'] and job['finished_at'] and job['progress_stage']=='completed', 'JOB_METADATA_INCOMPLETE')
            passed()
            if paper == 'P002':
                step = 'Post-warmup Embedding Assertion'
                result['post_warmup_environment'] = runtime_preflight(client, post_warmup=True)
                verify_storage([doc])
                passed()
        step = 'Storage Ready'
        verify_storage(result['documents'].values())
        passed()
        scope = [d['document_id'] for d in result['documents'].values()]
        p007 = scope[1]
        step = 'Search'
        _, found = call('POST','/api/search',json=dict(query=QUESTION,mode='hybrid',document_ids=[p007]))
        check(found['results'] and all(r['document']['id']==p007 and r['chunk_id'] and r['document_version_id'] and r['location']['page_number'] for r in found['results']), 'SEARCH_EVIDENCE_INVALID')
        passed()
        step = 'Grounded QA'
        result['qa_requests']=1; save()
        _, answer = call('POST','/api/qa',json=dict(question=QUESTION,mode='hybrid',document_ids=[p007]))
        check(answer['status']=='answered' and answer['answer'].strip() and answer['citations'], 'QA_NOT_ANSWERED')
        check(answer['citation_validation']['valid'], 'QA_CITATION_INVALID')
        returned = {(r['document']['id'],r['document_version_id'],r['chunk_id']) for r in answer['search']['results']}
        check(all(c['document_id']==p007 and locator(c) in returned for c in answer['citations']), 'QA_SCOPE_OR_MEMBERSHIP_INVALID')
        result['qa'] = dict(status=answer['status'],citations=[dict(zip(('document_id','document_version_id','chunk_id'),locator(c))) for c in answer['citations']],citation_validation='PASS')
        passed()
        step = 'Evidence Resolution'
        for c in answer['citations']: resolve(c)
        passed()
        step = 'Research Task'
        result['research_requests']=1; save()
        _, research = call('POST','/api/research/tasks',json=dict(question=RESEARCH,document_ids=scope,
            requested_fields=['system_scenario','method','optimization_objective']))
        check(research['status'] in ('completed','partial') and research['run_id'] and research['report'] and research['report']['summary'].strip() and research['citations'], 'RESEARCH_NOT_TRUSTED')
        result['research'] = {k:research[k] for k in ('run_id','status','coverage','retry_count')}
        result['research']['citations']=[dict(zip(('document_id','document_version_id','chunk_id'),locator(c))) for c in research['citations']]
        passed()
        step = 'Citation Validation'
        for c in research['citations']:
            check(c['document_id'] in scope, 'RESEARCH_CITATION_SCOPE'); resolve(c)
        passed()
        result['release_gate']='PENDING_HARNESS_TRACE_REVIEW'
    except Exception as exc:
        result['steps'][step]='FAIL'
        result['blocker']={'step':step,'error':str(exc) if isinstance(exc,ValueError) else type(exc).__name__}
        print(step+': FAIL',flush=True)
    finally:
        save(); client.close()
    return 0 if result['release_gate']=='PENDING_HARNESS_TRACE_REVIEW' else 1

if __name__=='__main__':
    raise SystemExit(main())
