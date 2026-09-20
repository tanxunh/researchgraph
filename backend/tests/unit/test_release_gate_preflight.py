"""No external network: exercise the real HTTP gate entry point and runtime checks."""
import importlib.util
import json
from pathlib import Path
import sys
import httpx
import pytest

spec=importlib.util.spec_from_file_location('release_gate_smoke',Path(__file__).resolve().parents[3]/'scripts/release_gate_smoke.py')
gate=importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)

def metadata():
    llm=dict(llm_model='deepseek-chat',llm_base_url='https://api.deepseek.com/v1',
             llm_api_key_configured=True,graph_extraction_enabled=False)
    return dict(embedding=dict(configured_provider='bge',configured_model='BAAI/bge-small-zh-v1.5',
        dimension=512,device='cpu',ready=True,loaded=True,error=None),llm=llm)

@pytest.mark.parametrize('area,key,value',[
    ('embedding','configured_provider','hash'),('embedding','configured_provider','fake'),
    ('embedding','configured_model','BAAI/other'),('embedding','ready',False),
    ('llm','graph_extraction_enabled',True),('llm','llm_model','other-model'),
    ('llm','llm_base_url','https://api.deepseek.com.evil.example/v1'),
    ('llm','llm_api_key_configured',False)])
def test_runtime_mismatch_stops_main_before_upload_or_model(monkeypatch,tmp_path,area,key,value):
    data=metadata();data[area][key]=value;calls=[]
    def respond(request):
        calls.append((request.method,request.url.path))
        assert request.method=='GET' and request.url.path in ('/health','/api/system/status')
        body={'llm':data['llm']} if request.url.path=='/health' else data
        return httpx.Response(200,json={'code':0,'data':body})
    original=httpx.Client
    monkeypatch.setattr(gate.httpx,'Client',lambda **kw: original(**kw,transport=httpx.MockTransport(respond)))
    output=tmp_path/'result.json'
    monkeypatch.setattr(sys,'argv',['gate','--pdf-a','must-not-open-a.pdf','--pdf-b','must-not-open-b.pdf','--output',str(output)])
    assert gate.main()==1
    result=json.loads(output.read_text())
    assert result['steps']=={'Preflight':'FAIL'}
    assert result['qa_requests']==result['research_requests']==0 and result['documents']=={}
    assert len(calls)==2

def test_expected_runtime_passes_without_posts():
    data=metadata();calls=[]
    def respond(request):
        calls.append(request.method)
        return httpx.Response(200,json={'code':0,'data':{'llm':data['llm']} if request.url.path=='/health' else data})
    with httpx.Client(base_url='http://test',transport=httpx.MockTransport(respond)) as client:
        result=gate.runtime_preflight(client)
    assert result['embedding']['configured_provider']=='bge' and calls==['GET','GET']


@pytest.mark.parametrize('loaded,ready,error,post,passes',[
    (False,False,None,False,True),
    (True,True,None,True,True),
    (False,False,None,True,False),
    (False,False,'load failure',False,False),
    (False,False,'load failure',True,False),
    (False,True,None,False,False),
    (True,False,None,True,False),
])
def test_lazy_state_contract(loaded,ready,error,post,passes):
    data=metadata();data['embedding'].update(loaded=loaded,ready=ready,error=error)
    def respond(request):
        return httpx.Response(200,json={'code':0,'data':{'llm':data['llm']} if request.url.path=='/health' else data})
    with httpx.Client(base_url='http://test',transport=httpx.MockTransport(respond)) as client:
        if passes:
            result=gate.runtime_preflight(client,post_warmup=post)
            assert result['embedding']['loaded'] is loaded
            assert result['embedding']['ready'] is ready
        else:
            with pytest.raises(ValueError):gate.runtime_preflight(client,post_warmup=post)


@pytest.mark.parametrize('outcome',['ready','cold','load_failed','job_failed','missing_vectors'])
def test_p002_warms_before_p007_and_no_early_search(monkeypatch,tmp_path,outcome):
    calls=[];submitted=[];completed=[];checks=[]
    def respond(request):
        path=request.url.path;calls.append((request.method,path))
        def ok(data,status=200):return httpx.Response(status,json={'code':0,'data':data})
        if path in ('/health','/api/system/status'):
            data=metadata()
            warm=bool(completed) and outcome not in ('cold','load_failed')
            data['embedding'].update(loaded=warm,ready=warm,error='load failure' if completed and outcome=='load_failed' else None)
            if path=='/api/system/status':checks.append((list(submitted),warm))
            return ok({'llm':data['llm']} if path=='/health' else data)
        if path=='/api/documents':return ok([])
        if path=='/api/v1/heartbeat':return httpx.Response(200,json={})
        if path=='/api/documents/import/file/async':
            if submitted:
                assert completed==[1] and checks[-1]==([1],True)
                assert ('POST','/api/v1/collections/c/get') in calls
            submitted.append(len(submitted)+1)
            return ok({'job_id':submitted[-1],'status':'queued'},202)
        if path.startswith('/api/index-jobs/'):
            doc=int(path.rsplit('/',1)[-1]);completed.append(doc)
            return ok(dict(document_id=doc,status='failed' if outcome=='job_failed' else 'succeeded',
                progress_stage='completed',attempts=1,started_at='start',finished_at='end'))
        if path=='/api/v1/collections':return httpx.Response(200,json=[{'id':'c'}])
        if path=='/api/v1/collections/c/get':
            ids=[] if outcome=='missing_vectors' else completed
            return httpx.Response(200,json={'ids':['chunk-'+str(i) for i in ids], 'metadatas':[{'document_id':i} for i in ids]})
        if path.startswith('/api/documents/'):
            doc=int(path.rsplit('/',1)[-1])
            return ok(dict(status='ready',chunks=[{'stable_chunk_id':'chunk-'+str(doc)}],
                entity_count=0,relation_count=0,current_version=1))
        if path=='/api/search':
            assert submitted==completed==[1,2]
            # End the mocked scenario here, before QA/Research; no real external calls.
            return httpx.Response(503,json={})
        pytest.fail('Unexpected request: '+path)
    original=httpx.Client
    monkeypatch.setattr(gate.httpx,'Client',lambda **kw: original(**kw,transport=httpx.MockTransport(respond)))
    pdf=tmp_path/'fixture.pdf';pdf.write_bytes(b'test-only-upload')
    output=tmp_path/'result.json'
    monkeypatch.setattr(sys,'argv',['gate','--pdf-a',str(pdf),'--pdf-b',str(pdf),
        '--chroma-url','http://chroma','--output',str(output)])
    assert gate.main()==1
    result=json.loads(output.read_text())
    assert result['environment']['embedding']['loaded'] is False
    assert result['environment']['embedding']['ready'] is False
    assert result['qa_requests']==result['research_requests']==0
    if outcome=='ready':
        assert submitted==[1,2] and result['steps']['Post-warmup Embedding Assertion']=='PASS'
        assert result['steps']['Storage Ready']=='PASS'
    else:
        assert submitted==[1] and not any(path=='/api/search' for _,path in calls)
        assert result['steps'].get('Post-warmup Embedding Assertion')=='FAIL' or outcome=='job_failed'
