"""Pre-TEST checks use synthetic data only."""
import importlib.util,sys,hashlib
from pathlib import Path
import pytest
SCRIPTS=Path(__file__).resolve().parents[2]/'scripts';sys.path.insert(0,str(SCRIPTS))
import run_v2_final_retrieval as core
import run_v2_final_test as test_runner

def test_once_lock_is_exclusive(tmp_path,monkeypatch):
 monkeypatch.setattr(core,'ROOT',tmp_path)
 core.exclusive_lock('lock.json',{'attempt':1})
 with pytest.raises(FileExistsError):core.exclusive_lock('lock.json',{'attempt':2})
 assert core.read('lock.json')=={'attempt':1}

def test_final_metrics_do_not_relabel_candidate_coverage():
 rank=['wrong']*0+['a','b','c'];mapping={'q:G1':['a','b'],'q:G2':['missing']}
 row={'query_id':'q',**{k:rank for k in ['bm25','dense','hybrid','reranked']}}
 m=core.evaluate([row],mapping)
 assert m['reranked']['metrics']['R@10']==.5
 assert m['hybrid']['metrics']['CR@20']==.5
 assert m['reranked']['Gold_hit_counts']['10']==1
 assert set(m['reranked']['metrics'])==set(core.FINAL)

def fixture():
 text='A source evidence passage.';h=hashlib.sha256(text.encode()).hexdigest();cid='doc-1-chunk-'+h[:24]
 c={'chunk_id':cid,'document_id':1,'document_version_id':2,'text':text,'page':1,'section':None,'source_text_hash':h,'document_char_start':0,'document_char_end':len(text)}
 g={'paper_id':'P001','document_id':1,'document_version_id':2,'chunk_id':cid,'page':1,'section':None}
 qs=[{'query_id':f'T{i}','query':'q','human_verified':True,'query_type':'factual','document_scope':[1],'gold_evidence':[dict(g)]} for i in range(40)]
 rows={cid:{'document':text,'metadata':{'document_id':1,'document_version_id':2,'chunk_hash':h}}};docs={(1,2):{'paper_id':'P001','text_hash':h,'text':text}}
 return qs,{cid:c},rows,docs

def test_gold_validation_is_exact_and_structural():
 data=fixture();mapping,units=test_runner.validate_gold(*data);assert len(mapping)==len(units)==40

@pytest.mark.parametrize('failure',['version','text','duplicate','missing','review','scope','offset'])
def test_structurally_invalid_gold_stops(failure):
 qs,cc,rows,docs=fixture();g=qs[0]['gold_evidence'][0];c=next(iter(cc.values()))
 if failure=='version':g['document_version_id']=9
 if failure=='text':next(iter(rows.values()))['document']='altered'
 if failure=='duplicate':qs[0]['gold_evidence'].append(dict(g))
 if failure=='missing':g['chunk_id']='missing'
 if failure=='review':qs[0]['human_verified']=False
 if failure=='scope':qs[0]['document_scope']=[2]
 if failure=='offset':c['document_char_start']=1
 with pytest.raises((AssertionError,KeyError)):test_runner.validate_gold(qs,cc,rows,docs)
