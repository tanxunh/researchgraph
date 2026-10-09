"""One process / one existing graph / six effective EF values. No encoding or insertion."""
import os,sys,json,hashlib,time,statistics,platform,types,traceback
from pathlib import Path
from datetime import datetime,timezone
os.environ.update(ANONYMIZED_TELEMETRY='false',LLM_API_KEY='',GRAPH_EXTRACTION_ENABLED='false')
ROOT=Path(__file__).resolve().parents[2];BASE=ROOT/'benchmarks/real_research/v2';OUT=ROOT/'artifacts/evaluation_v2';OUT.mkdir(parents=True,exist_ok=True)
# Original Chroma server image lacks application SQL dependencies: load pure evaluation modules only.
pkg=types.ModuleType('app.services.evaluation');pkg.__path__=[str(ROOT/'backend/app/services/evaluation')];sys.modules['app.services.evaluation']=pkg
import numpy as np
import chromadb
from chromadb.config import Settings
from chromadb.segment import VectorReader
from importlib.metadata import version
from app.services.evaluation.ann_exactness import vector_fingerprint
from app.services.evaluation.ef_sweep import EFS,QUALITY,round_order,sweep_summary,comparisons

def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def save(path,value):
    tmp=path.with_suffix('.tmp');tmp.write_text(json.dumps(value,indent=2,default=str)+'\n');tmp.replace(path)

def run():
    target=OUT/'b2_ef_sweep.json';assert not target.exists(),'completed_sweep_exists'
    integrity=json.loads((BASE/'results/v2a_integrity.json').read_text());manifest=json.loads((BASE/'results/v2b21_stable_index_manifest.json').read_text());closure=json.loads((BASE/'results/v2b21_ann_reproducibility.json').read_text());snapshot=ROOT/manifest['snapshot_path']
    protected={**integrity['production_hashes'],**{f'benchmarks/real_research/v2/queries_{s}.jsonl':integrity[f'{s}_sha256'] for s in ['dev','test']},'benchmarks/real_research/v2/results/v2b2_ann_exactness.json':closure['existing_b2_result_sha256']}
    def check_files():
        for name,digest in protected.items():assert sha(ROOT/name)==digest,name
        for name,digest in manifest['graph_hashes'].items():assert sha(snapshot/name)==digest,name
    check_files()
    assert chromadb.__version__=='0.5.23' and version('chroma-hnswlib')=='0.7.6'
    frozen=json.loads((BASE/'results/v2b2_ann_exactness.json').read_text());exact=next(e for e in frozen['experiments'] if e['backend']=='exact');exact_cases={c['query_id']:c for c in exact['cases']['global']}
    export=json.loads((ROOT/'.tmp/v2b2/export.json').read_text());queries=[json.loads(line) for line in (BASE/'queries_dev.jsonl').read_text().splitlines() if line.strip()];assert queries==export['queries'] and len(queries)==35
    data=np.load(ROOT/'.tmp/v2b2/vectors.npz');qv=data['query_vectors'];assert vector_fingerprint([q['query_id'] for q in queries],qv)==export['query_vector_fingerprint'];vectors=qv.tolist()
    t=time.perf_counter();client=chromadb.PersistentClient(path=str(snapshot),settings=Settings(anonymized_telemetry=False));collection=client.get_collection(export['collection'],embedding_function=None)
    stored=collection.get(include=['embeddings','metadatas','documents']);assert collection.count()==3837
    assert vector_fingerprint(stored['ids'],stored['embeddings'])==manifest['identity']['vector_fingerprint']
    meta={sid:{'metadata':stored['metadatas'][i],'document':stored['documents'][i]} for i,sid in enumerate(stored['ids'])};assert hashlib.sha256(json.dumps(meta,sort_keys=True).encode()).hexdigest()==manifest['metadata_text_hash']
    def search(i):return collection.query(query_embeddings=[vectors[i]],n_results=200,include=['distances'])['ids'][0]
    search(0);segment=client._server._manager.get_segment(collection.id,VectorReader);index=segment._index
    seq=sorted(segment._id_to_label,key=segment._id_to_label.get)
    assert hashlib.sha256(json.dumps(seq).encode()).hexdigest()==manifest['label_sequence_hash']
    assert segment._params.M==16 and segment._params.construction_ef==100 and segment._params.space=='l2'
    assert len(seq)==3800 and len(segment._curr_batch._ids_to_records)==37
    cold_ms=(time.perf_counter()-t)*1000
    graph_object=id(index);mapping=dict(segment._id_to_label)
    def assert_graph():
        assert id(segment._index)==graph_object and segment._id_to_label==mapping and len(segment._curr_batch._ids_to_records)==37
        check_files()
    previous={q['query_id']:q['ids'] for q in closure['reload']['queries']}
    rows={ef:[] for ef in EFS}
    for ef in EFS:
        index.set_ef(ef);assert index.ef==ef
        for i,q in enumerate(queries):
            ids=search(i)
            if ef==10:assert ids==previous[q['query_id']],'stable_graph_baseline_mismatch'
            rows[ef].append({'query_id':q['query_id'],'query_type':q['query_type'],'gold':[g['chunk_id'] for g in q['gold_evidence']],'ids':ids,'exact':exact_cases[q['query_id']]['ids'][:100],'latency_ms':[]})
        assert_graph()
    report={'status':'RUNNING','started_utc':datetime.now(timezone.utc).isoformat(),'identity':manifest,'runtime':{'python':sys.version,'numpy':np.__version__,'chroma':chromadb.__version__,'chroma_hnswlib':version('chroma-hnswlib'),'architecture':platform.machine(),'params':vars(segment._params)},'protocol':{'efs':EFS,'track':'global','n_results':200,'warmup_queries_per_ef':35,'rounds':5,'timed_queries_per_ef':175,'round_schedule':[round_order(i) for i in range(5)],'latency':'local Chroma collection.query including Python/SQLite/ANN+pending brute-force merge; query vectors precomputed, no embedding/model load, no HTTP, no SQL authority work; post-query metric calculation excluded','index_load_ms_excluded':cold_ms,'exact_source':'benchmarks/real_research/v2/results/v2b2_ann_exactness.json','exact_sha256':closure['existing_b2_result_sha256'],'near_tie_adjustments':False},'exact':exact['tracks']['global']['overall'],'cases':rows,'protected_hashes':protected}
    for round_no in range(5):
        for ef in round_order(round_no):
            index.set_ef(ef);assert index.ef==ef
            for i,q in enumerate(queries):
                t=time.perf_counter_ns();ids=search(i);elapsed=(time.perf_counter_ns()-t)/1e6
                assert ids==rows[ef][i]['ids'] and index.ef==ef,'ranking_changed_within_group'
                rows[ef][i]['latency_ms'].append(elapsed)
            assert_graph()
            print('ROUND',round_no+1,'EF',ef,'COMPLETE',flush=True)
        save(OUT/'b2_ef_sweep.progress.json',report)
    summaries={ef:sweep_summary(rows[ef]) for ef in EFS};report['results']=[]
    for ef in EFS:
        summary=summaries[ef];report['results'].append({'ef':ef,'effective_ef':ef,'metrics':summary,**comparisons(summary,summaries[10],report['exact']),'by_type':{ty:sweep_summary([c for c in rows[ef] if c['query_type']==ty]) for ty in sorted({q['query_type'] for q in queries})}})
    report['quality_identical_all_ef']=all(all(summaries[ef][key]==summaries[10][key] for key in QUALITY) for ef in EFS)
    report['ranking_identical_all_ef']=all(all(c['ids']==base['ids'] for c,base in zip(rows[ef],rows[10])) for ef in EFS)
    index.set_ef(10);assert_graph();assert index.ef==10
    report.update(status='COMPLETE',finished_utc=datetime.now(timezone.utc).isoformat(),integrity={'same_graph_verified':True,'stored_vectors_unchanged':True,'test_bytes_hash_only':True,'test_ranking_read':False,'test_run':False,'production_defaults_changed':False,'effective_ef_restored_to_10':True})
    save(target,report);print('SWEEP COMPLETE',json.dumps(report['results']),flush=True)

if __name__=='__main__':
    try:run()
    except Exception as exc:
        save(OUT/f'b2_ef_sweep_failure_{time.time_ns()}.json',{'status':'FAILED','type':type(exc).__name__,'error':str(exc)});raise
