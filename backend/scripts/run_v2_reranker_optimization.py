"""V2-E: pinned local scoring, cached rank blends, DEV-only evaluation."""
from __future__ import annotations
import argparse, collections, csv, hashlib, inspect, json, math, os, platform, resource, statistics, sys, time, types
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'backend'))
pkg=types.ModuleType('app.services.evaluation');pkg.__path__=[str(ROOT/'backend/app/services/evaluation')];sys.modules['app.services.evaluation']=pkg
from app.services.evaluation.chunking_ablation import score_portable
from app.services.evaluation.evidence_span_repair import fully_contains
B=Path('benchmarks/real_research/v2'); E=Path('artifacts/evaluation_v2/e')
MODELS={'base':('BAAI/bge-reranker-base','465b4b7ddf2be0a020c8ad6e525b9bb1dbb708ae'),'m3':('BAAI/bge-reranker-v2-m3','953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e')}
METRICS=('R@10','MRR@10','R@5','Hit@5')
def read(p):return json.loads((ROOT/p).read_text(encoding='utf-8'))
def write(p,d):
    path=ROOT/p;path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_suffix(path.suffix+'.tmp');tmp.write_text(json.dumps(d,ensure_ascii=False,sort_keys=True,indent=2)+'\n',encoding='utf-8');tmp.replace(path)
def sha(p):
    h=hashlib.sha256()
    with (ROOT/p).open('rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''):h.update(block)
    return h.hexdigest()
def digest(d):return hashlib.sha256(json.dumps(d,sort_keys=True,separators=(',',':')).encode()).hexdigest()
def pct(a,q):
    a=sorted(a);i=(len(a)-1)*q;lo=math.floor(i);hi=math.ceil(i);return a[lo]+(a[hi]-a[lo])*(i-lo)
def stats(a):return {'min':min(a),'median':statistics.median(a),'p95':pct(a,.95),'max':max(a)}
def inputs():
    q=[json.loads(s) for s in (ROOT/B/'queries_dev.jsonl').read_text(encoding='utf-8').splitlines() if s.strip()]
    f=read('artifacts/evaluation_v2/d/fused_rankings.json')['bm25-1.25_k-20']
    c={x['chunk_id']:x for x in read('artifacts/evaluation_v2/c1/BASE_corpus.json')['chunks']}
    mapping=read('artifacts/evaluation_v2/c1r/mappings.json')['BASE']
    assert len(q)==len(f)==35 and len(c)==3837 and len(mapping)==55
    assert [x['query_id'] for x in q]==[x['query_id'] for x in f]
    pools={x['query_id']:x['hybrid'][:20] for x in f}
    assert all(len(v)==len(set(v))==20 for v in pools.values())
    return q,pools,c,mapping

def metrics(rankings,mapping,qs):
    per={q['query_id']:{k:v for k,v in score_portable(rankings[q['query_id']][:10],mapping,q['query_id']).items() if k in METRICS} for q in qs}
    return {k:statistics.mean(x[k] for x in per.values()) for k in METRICS},per

def hits(rankings,mapping,k=10):return {g for g,ids in mapping.items() if set(ids)&set(rankings[g.split(':')[0]][:k])}
def blend(pool,scores,alpha):
    assert alpha in (1.,.75,.5) and len(scores)==len(pool)==20 and len(set(pool))==20
    assert all(math.isfinite(v) for v in scores)
    order=sorted(range(20),key=lambda i:(-scores[i],i)); rr={idx:rank for rank,idx in enumerate(order,1)}
    return [pool[i] for i in sorted(range(20),key=lambda i:(-(alpha/(10+rr[i])+(1-alpha)/(10+i+1)),i))]
def classify(candidate,original,final):
    if not candidate:return 'NOT_IN_TOP20'
    if original and final:return 'STAYED_IN_TOP10'
    if original:return 'DEMOTED_OUT_OF_TOP10'
    if final:return 'PROMOTED_INTO_TOP10'
    return 'CANDIDATE_PRESENT_BUT_STILL_MISSED'
def paired(a,b):
    d=collections.Counter('improved' if a[q]['R@10']>b[q]['R@10'] else 'regressed' if a[q]['R@10']<b[q]['R@10'] else 'unchanged' for q in a)
    return {k:d[k] for k in ('improved','unchanged','regressed')}
def gate(c,b):
    net=c['net'];m=c['metrics'];bm=b['metrics']
    a=net>=2 and m['R@10']>bm['R@10']
    bb=net==1 and m['R@10']>bm['R@10'] and m['MRR@10']>=bm['MRR@10'] and m['R@5']>=bm['R@5'] and c['cross']['R@10']>=b['cross']['R@10'] and c['demotions']<=b['demotions']
    flag=(m['R@10']>bm['R@10'] and bm['MRR@10']-m['MRR@10']>.05) or b['hits5']-c['hits5']>=2
    return {'pass':(a or bb) and not flag,'gate_A':a,'gate_B':bb,'front_safety_flag':flag}

def verify():
    p=read(E/'protocol.json')
    for name,h in p['protected_hashes'].items():assert sha(name)==h, name
    return p

def prepare():
    assert not (ROOT/E/'protocol.json').exists(),'Protocol already exists; refuse overwrite'
    qs,pools,corpus,mapping=inputs()
    units=read(B/'dev_gold_evidence_spans_v2.json')['units'];assert len(units)==55
    for u in units:
        assert u['review_status']=='APPROVED' and u['reviewed_by_human'] is True and u['evidence_text']
        expected=[cid for cid,c in corpus.items() if fully_contains(u,c)]
        assert sorted(expected)==sorted(mapping[u['gold_id']]),u['gold_id']
        assert hashlib.sha256(u['evidence_text'].encode()).hexdigest()==u['evidence_text_hash']
    protected=read('artifacts/evaluation_v2/d/summary.json')['protected_hashes'].copy()
    for path in ['artifacts/evaluation_v2/d/summary.json','artifacts/evaluation_v2/d/fused_rankings.json','artifacts/evaluation_v2/d/protocol.json',str(B/'final_fusion_config.json'),'backend/app/services/retrieval/reranker.py','artifacts/evaluation_v2/b6/protocol.json']:
        protected[path]=sha(path)
    assert sha(B/'final_chunking_config.json')=='008845cdc4c45d8921173138d8b8591fa06d85e44082a5d73627801be3887079'
    assert sha(B/'final_fusion_config.json')=='f1707c358cadd7ceb162119811976ecfa1ea57fe6f40588bbd7a55b479c24360'
    nm,np=metrics(pools,mapping,qs)
    assert abs(nm['R@10']-.5404761904761904)<1e-12 and abs(nm['MRR@10']-.30808390022675736)<1e-12
    cr=statistics.mean(score_portable(pools[q['query_id']],mapping,q['query_id'])['CR@20'] for q in qs)
    assert abs(cr-.7785714285714286)<1e-12
    p={'status':'PREDECLARED','models':MODELS,'alphas':[1.,.75,.5],'blend_k':10,'candidate_depth':20,'final_top_k':10,'max_length':512,'batch_size':8,'device':'cpu','dtype':'float32','torch_threads':4,'interop_threads':1,'semantic_input':'raw DEV query, raw frozen chunk; no metadata or instructions','tie_breaking':'original frozen fusion rank ascending','warmup_queries':1,'measured_rounds':1,'latency_boundary':'production scorer tokenization + forward + score extraction; excludes cold load, retrieval, external audit, rank blending','selection_order':['R@10','MRR@10','R@5','Hit@5','paired_gain_loss','cross_document','demotions','latency_memory','simplicity'],'gate_B_materiality':'Conservative: no cross-document R@10 decline and no demotion-count increase','gate_A':'net >=2 distinct Gold units AND macro R@10 improvement','front_safety':'relative current: MRR drop >.05 with improved R10 OR >=2 lost R5 Gold hits; exclude flagged configs','opportunity':'MATERIAL if replacement gate passes; MINOR if positive R10 net gain below gate; else NOT SUPPORTED','contribution':'MATERIAL if R10 improves and net >=2 vs no rerank; MINOR if positive R10 gain; else NONE','no_test_evaluation':True,'protected_hashes':protected,'candidate_identity_sha256':digest(pools),'no_rerank_metrics':nm,'candidate_CR@20':cr}
    write(E/'protocol.json',p);write(E/'no_rerank.json',{'metrics':nm,'per_query':np,'ranking':{q:v[:10] for q,v in pools.items()},'candidate_CR@20':cr})
    verify();print(json.dumps({'prepared':True,'no_rerank':nm,'CR@20':cr}),flush=True)

def score_model(key):
    p=verify();qs,pools,corpus,mapping=inputs();out=E/(key+'_scores.json')
    assert not (ROOT/out).exists(),'Saved scores already exist; refuse rescore'
    if key=='m3':
        base=read(E/'base_scores.json');assert base['status']=='COMPLETE' and base['audit']['status']=='PASS'
    import torch,transformers,sentence_transformers
    from app.services.retrieval.reranker import CrossEncoderReranker,rerank_candidates
    torch.set_num_threads(4);torch.set_num_interop_threads(1);torch.use_deterministic_algorithms(True)
    name,rev=MODELS[key];scorer=CrossEncoderReranker(name,rev,'cpu','/models/model_cache',True);model=scorer.load()
    assert model.model.config._commit_hash==rev and model.max_length==512
    assert all(x.dtype==torch.float32 for x in model.model.parameters())
    tok=model.tokenizer;cache=Path('/models/model_cache')/('models--'+name.replace('/','--'))/'snapshots'/rev
    files={x.name:sha(x) for x in sorted(cache.iterdir()) if x.is_file()}
    tokenfiles={k:v for k,v in files.items() if 'token' in k or k.endswith('.model')}
    lengths=[];chars=[];pairaudit=[]
    for q in qs:
        for cid in pools[q['query_id']]:
            text=corpus[cid]['text'];n=len(tok(q['query'].strip(),text.strip(),add_special_tokens=True,truncation=False)['input_ids']);lengths.append(n);chars.append(len(text))
            pairaudit.append({'query_id':q['query_id'],'chunk_id':cid,'raw_token_length':n,'truncated':n>512})
    audit={'status':'PENDING','model':name,'revision':rev,'tokenizer_revision':rev,'tokenizer_init_revision':tok.init_kwargs.get('revision'),'files_sha256':files,'model_fingerprint':digest(files),'tokenizer_fingerprint':digest(tokenfiles),'tokenizer_class':type(tok).__name__,'model_class':type(model.model).__name__,'max_length':512,'batch_size':8,'device':'cpu','dtype':'float32','query_passage_order':'query first, passage second','input_preprocessing':'CrossEncoder internal str.strip only; unchanged B6 wrapper','special_tokens':tok.special_tokens_map,'pair_special_token_count':tok.num_special_tokens_to_add(pair=True),'truncation':'longest_first; max_length=512; dynamic batch padding','score_extraction':str(model.default_activation_function),'sort':'descending score, stable original fusion ties','candidate_identity':'scorer sees only text pairs; caller preserves IDs','pairs':700,'truncated_pairs':sum(n>512 for n in lengths),'truncated_percentage':100*sum(n>512 for n in lengths)/700,'chunk_char_lengths':stats(chars),'pair_token_lengths':stats(lengths),'parameter_count':sum(x.numel() for x in model.model.parameters()),'model_disk_bytes':sum(x.stat().st_size for x in cache.iterdir() if x.is_file()),'versions':{'python':platform.python_version(),'torch':torch.__version__,'transformers':transformers.__version__,'sentence_transformers':sentence_transformers.__version__},'collate_source':inspect.getsource(model.smart_batching_collate_text_only),'pairs_detail':pairaudit}
    assert 'longest_first' in audit['collate_source'] and 'max_length=self.max_length' in audit['collate_source']
    # Verify wrapper scores independently against model logits on the first real pair.
    q=qs[0];text=corpus[pools[q['query_id']][0]]['text']
    encoded=tok([q['query'].strip()],[text.strip()],padding=True,truncation='longest_first',return_tensors='pt',max_length=512)
    model.model.eval()
    with torch.inference_mode():
        expected=model.default_activation_function(model.model(**encoded,return_dict=True).logits).view(-1)[0].item()
    actual=scorer.score(q['query'],[text])[0];assert abs(actual-expected)<1e-6
    warm=scorer.score(q['query'],[corpus[c]['text'] for c in pools[q['query_id']]])
    audit['independent_score_check_abs_error']=abs(actual-expected);audit['status']='PASS'
    state={'status':'RUNNING','protocol_sha256':sha(E/'protocol.json'),'audit':audit,'cases':[]};write(out,state)
    for q in qs:
        ids=pools[q['query_id']];texts=[corpus[c]['text'] for c in ids]
        start=time.perf_counter();scores=scorer.score(q['query'],texts);ms=(time.perf_counter()-start)*1000
        assert len(scores)==20 and all(math.isfinite(v) for v in scores)
        if not state['cases']:assert scores==warm,'determinism check failed'
        # Exercise production candidate mapping without another model call.
        class Cached:
            def score(self,query,passages):
                assert query==q['query'] and passages==texts
                return scores
        original=[{'chunk_id':cid,'text':corpus[cid]['text'],'scores':{}} for cid in ids]
        ordered,meta=rerank_candidates(q['query'],original,Cached());assert not meta['reranker_failed']
        pure=blend(ids,scores,1.);assert pure==[x['chunk_id'] for x in ordered] and set(pure)==set(ids)
        state['cases'].append({'query_id':q['query_id'],'candidate_ids':ids,'scores':scores,'reranked':pure,'latency_ms':ms,'score_ties':20-len(set(scores))})
        write(out,state);print(key,q['query_id'],round(ms,2),'ms',len(state['cases']),'/35',flush=True)
    lat=[x['latency_ms'] for x in state['cases']]
    state['latency']={'mean_ms':statistics.mean(lat),'p50_ms':statistics.median(lat),'p95_ms':pct(lat,.95),'pairs_per_second':700/(sum(lat)/1000),'peak_rss_bytes':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024}
    state['status']='COMPLETE';verify();write(out,state)
    print(json.dumps({'complete':key,'latency':state['latency'],'truncated':audit['truncated_pairs']}),flush=True)

if __name__=='__main__':
    a=argparse.ArgumentParser();a.add_argument('action',choices=['prepare','base','m3']);args=a.parse_args()
    prepare() if args.action=='prepare' else score_model(args.action)
