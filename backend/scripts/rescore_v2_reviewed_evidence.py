"""C1R: deterministic human-approval validation and saved-ranking rescoring only."""
import csv,hashlib,json,re,statistics,sys,types
from pathlib import Path
R=Path(__file__).resolve().parents[2];B=R/'benchmarks/real_research/v2';A=R/'artifacts/evaluation_v2';O=A/'c1r'
sys.path.insert(0,str(R/'backend'));pkg=types.ModuleType('app.services.evaluation');pkg.__path__=[str(R/'backend/app/services/evaluation')];sys.modules['app.services.evaluation']=pkg
from app.services.evaluation.evidence_span_repair import resolve_approved_span,fully_contains
from app.services.evaluation.chunking_ablation import score_portable,score_reranked_portable,duplicate_equivalent,fingerprint
from app.services.retrieval.fusion_ranker import FusionRanker

def read(p):return json.loads(p.read_text(encoding='utf-8-sig'))
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def save(p,v):p.write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
def csvsave(p,rows):
    fields=list(dict.fromkeys(k for row in rows for k in row))
    with p.open('w',encoding='utf-8',newline='') as f:
        w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(rows)
def percentile(values,p):
    a=sorted(values);x=(len(a)-1)*p/100;i=int(x);return a[i]+(a[min(i+1,len(a)-1)]-a[i])*(x-i)
def hits(c,m,k):return {a for a,v in m.items() if a.startswith(c['query_id']+':') and set(v)&set(c['hybrid'][:k])}
def mean_metrics(cases,m,path):
    rows=[score_reranked_portable(c['reranked'],c['hybrid'],m,c['query_id']) if path=='reranked' else score_portable(c[path],m,c['query_id']) for c in cases]
    return {key:statistics.mean(row[key] for row in rows) for key in rows[0]}

def main():
    before=read(O/'summary.json');protected=before['protected_hashes']
    for name,h in protected.items():assert sha(R/name)==h,name
    for name in ['benchmarks/real_research/v2/final_dense_config.json','artifacts/evaluation_v2/b6/protocol.json','artifacts/evaluation_v2/c1/summary.json','artifacts/evaluation_v2/c1/protocol.json','benchmarks/real_research/v2/c1r_human_approvals_55.json']:
        protected[name]=sha(R/name)
    annotation=read(B/'dev_gold_evidence_spans_v2.json');approvals=read(B/'c1r_human_approvals_55.json');old=read(B/'dev_gold_portable_anchors.json');source=read(A/'c0/source_reconstruction.json')
    aa={a['anchor_id']:a for a in old['anchors']};dd={d['document_id']:d for d in source['documents']};hh={h['gold_id']:h for h in approvals['decisions']}
    queries=[json.loads(x) for x in (B/'queries_dev.jsonl').read_text(encoding='utf-8').splitlines() if x.strip()];qm={q['query_id']:q for q in queries}
    assert len(queries)==35 and len(hh)==len(approvals['decisions'])==len(annotation['units'])==55
    assert {u['gold_id'] for u in annotation['units']}==set(aa)==set(hh)
    for obj in [annotation,approvals]:
        assert obj['source_dev_sha256']==sha(B/'queries_dev.jsonl') and obj['source_original_anchors_sha256']==sha(B/'dev_gold_portable_anchors.json')
    assert annotation['authoritative_source_sha256']==sha(A/'c0/source_reconstruction.json')
    units=[];failures=[]
    for u in annotation['units']:
        try:
            assert u['query_text']==qm[u['query_id']]['query']
            v=resolve_approved_span(u,hh[u['gold_id']],aa[u['gold_id']],dd[u['document_id']])
            assert v['evidence_text']==hh[v['gold_id']]['evidence_text']
            page,=[p for p in dd[v['document_id']]['pages'] if p['page']==v['page']]
            assert page['start']<=v['document_char_start']<v['document_char_end']<=page['end']
            units.append(v)
        except (ValueError,AssertionError) as e:failures.append({'gold_id':u['gold_id'],'failure_reason':str(e)})
    validation=dict(status='PASS' if not failures else 'ANNOTATION_VALIDATION_FAIL',gold_units=55,reviewed=len(hh),approved=sum(h['review_status']=='APPROVED' for h in hh.values()),needs_discussion=sum(h['review_status']=='NEEDS_DISCUSSION' for h in hh.values()),exact_source_spans=len(units),ambiguous=sum('exact_match_count=' in x['failure_reason'] and 'count=0' not in x['failure_reason'] for x in failures),failures=failures,approval_sha256=sha(B/'c1r_human_approvals_55.json'))
    save(O/'annotation_validation.json',validation)
    if failures:raise ValueError('ANNOTATION_VALIDATION_FAIL')
    # Config and provenance gates before scoring. No embedding/index/retrieval calls.
    protocol=read(A/'c1/protocol.json');dense=read(B/'final_dense_config.json');b6=read(A/'b6/protocol.json')
    for p,h in protocol['protected_hashes'].items():assert sha(R/p)==h,p
    assert (b6['bm25_depth'],b6['dense_depth'],b6['rrf_k'],b6['fusion_pool_capacity'])==(200,200,60,100)
    assert b6['weights']=={'bm25':1,'dense':1} and b6['rerank_depth']==20 and b6['final_k']==10
    assert dense['model']=='BAAI/bge-m3' and dense['dimension']==1024 and dense['revision']=='5617a9f61b028005a4858fdac845db406aefb181'
    corpora={};rankings={};identity={}
    for key in ('BASE','A','B','C'):
        co=read(A/f'c1/{key}_corpus.json');rr=read(A/f'c1/{key}_reranked.json');retr=read(A/f'c1/{key}_retrieval.json')
        cfg=co['audit']['config'];ch=fingerprint(cfg);ns='v2c1-'+key.lower()+'-'+fingerprint({'chunking':ch,'model':dense['model'],'revision':dense['revision'],'dimension':dense['dimension']})[:20]
        assert cfg==protocol['configs'][key] and ch==co['audit']['chunking_config_hash']
        assert rr['status']==retr['status']=='COMPLETE' and rr['namespace']==retr['namespace']==ns
        assert rr['protocol_sha256']==retr['protocol_sha256']==sha(A/'c1/protocol.json')
        chunks={c['chunk_id']:c for c in co['chunks']};assert len(chunks)==len(co['chunks'])==co['audit']['chunk_count']
        for c in chunks.values():
            d=dd[c['document_id']];assert c['document_version_id']==d['document_version_id'] and c['source_text_hash']==d['text_hash']
            assert d['text'][c['document_char_start']:c['document_char_end']]==c['text']
        assert len(rr['cases'])==len(retr['cases'])==35
        assert [c['query_id'] for c in rr['cases']]==[q['query_id'] for q in queries]
        occ={c['chunk_id']:i for i,c in enumerate(co['chunks'])}
        for c,t in zip(rr['cases'],retr['cases']):
            assert c['query_id']==t['query_id'] and c['query_type']==qm[c['query_id']]['query_type']
            for path,depth in [('bm25',200),('dense',200),('hybrid',100)]:
                assert c[path]==t[path] and len(c[path])<=depth and len(c[path])==len(set(c[path])) and set(c[path])<=set(chunks)
            assert len(c['reranked'])==10 and len(set(c['reranked']))==10 and set(c['reranked'])<=set(c['hybrid'][:20])
            tup=lambda ids:[(occ[s],s,0.) for s in ids]
            reconstructed=[x.stable_chunk_id for x in FusionRanker(60).rank(tup(c['dense']),tup(c['bm25']),[],100)]
            assert reconstructed==c['hybrid'],'saved_fusion_identity_mismatch'
        corpora[key]=co;rankings[key]=rr['cases'];identity[key]=dict(status='PASS',chunking_config_hash=ch,index_namespace=ns,ranking_sha256=sha(A/f'c1/{key}_retrieval.json'),reranker_sha256=sha(A/f'c1/{key}_reranked.json'),dense_model_fingerprint=dense['embedding_fingerprint'],vector_artifact_sha256=sha(A/f'c1/{key}_vectors.npz'),query_sha256=sha(B/'queries_dev.jsonl'),fusion='unchanged equal-weight RRF60, dense-first occurrence-ID dedup, Top100; reconstructed from saved input ranks')
    annotation.update(units=units,status='HUMAN_REVIEWED_VALIDATED',reviewed_count=55,approved_count=55,needs_discussion_count=0,approval_source_sha256=validation['approval_sha256'])
    save(B/'dev_gold_evidence_spans_v2.json',annotation)
    # Preserve every original source block in the human packet.
    review=B/'HUMAN_DEV_EVIDENCE_SPAN_REVIEW.md';text=review.read_text(encoding='utf-8');parts=re.split(r'(?m)^## (V2Q\d+:G\d+)\s*$',text)
    assert len(parts)==111
    parts[0]=re.sub(r'(?m)^Status:.*$', 'Status: HUMAN_REVIEWED_VALIDATED — Reviewed:55/55; APPROVED:55; NEEDS_DISCUSSION:0.',parts[0])
    um={u['gold_id']:u for u in units};rebuilt=parts[0]
    for i in range(1,len(parts),2):
        gid,body=parts[i],parts[i+1];source_part=body.split('### Human annotation')[0];u=um[gid]
        rebuilt+='## '+gid+'\n'+source_part+'### Human annotation\n\n'+f"- evidence_start: {u['evidence_start']}\n- evidence_end: {u['evidence_end']}\n- evidence_text_hash: {u['evidence_text_hash']}\n- evidence_text:\n\n```text\n{u['evidence_text']}\n```\n\n- review_status: APPROVED\n- reviewed_by_human: true\n- Reviewer note: Exact human selection persisted in c1r_human_approvals_55.json.\n\n"
    assert [p.split('### Human annotation')[0] for p in re.split(r'(?m)^## V2Q\d+:G\d+\s*$',rebuilt)[1:]]==[parts[i+1].split('### Human annotation')[0] for i in range(1,len(parts),2)]
    review.write_text(rebuilt,encoding='utf-8')
    lengths=[len(u['evidence_text']) for u in units];stats={name:percentile(lengths,p) for name,p in [('min',0),('p25',25),('median',50),('p75',75),('p95',95),('max',100)]};stats.update(mean=statistics.mean(lengths),**{f'gt_{k}':sum(n>k for n in lengths) for k in (450,700,1000)})
    mappings={key:{u['gold_id']:[c['chunk_id'] for c in co['chunks'] if fully_contains(u,c)] for u in units} for key,co in corpora.items()}
    # BASE must recover each span via its original frozen chunk.
    assert all(u['original_gold_chunk_id'] in mappings['BASE'][u['gold_id']] for u in units)
    metrics_rows=[];map_rows=[];gain_rows=[];configs={};c0=read(A/'c0/miss_review.json')
    for key,cases in rankings.items():
        m=mappings[key];counts=[len(v) for v in m.values()];mapping_summary=dict(config=key,mapped=sum(n>0 for n in counts),unmapped=counts.count(0),one=counts.count(1),two=counts.count(2),three_or_more=sum(n>=3 for n in counts),mean_multiplicity=statistics.mean(counts),median=statistics.median(counts),max=max(counts));map_rows.append(mapping_summary)
        cfg={'mapping':mapping_summary,'unmapped_ids':[a for a,v in m.items() if not v],'metrics':{p:mean_metrics(cases,m,p) for p in ('bm25','dense','hybrid','reranked')}}
        for path,values in cfg['metrics'].items():metrics_rows.append(dict(config=key,path=path,**values))
        cross=[c for c in cases if c['query_type']=='cross_document'];cfg['cross_document']=dict(n=len(cross),**mean_metrics(cross,m,'hybrid'))
        cfg['duplicates']={};cfg['gain_loss']={};cfg['c0_categories']={}
        for k in (20,30,50):
            new=set();lost=set()
            for c,b in zip(cases,rankings['BASE']):
                bh=hits(b,mappings['BASE'],k);nh=hits(c,m,k);new.update(nh-bh);lost.update(bh-nh)
            cfg['gain_loss'][str(k)]=dict(recovered=sorted(new),lost=sorted(lost),net=len(new)-len(lost))
            gain_rows.append(dict(config=key,k=k,recovered=len(new),lost=len(lost),net=len(new)-len(lost),recovered_ids=json.dumps(sorted(new)),lost_ids=json.dumps(sorted(lost))))
            if k in (20,50):
                redundant=sum(duplicate_equivalent(c['hybrid'],m,c['query_id'],k) for c in cases)
                dq=sum(any(len(set(c['hybrid'][:k])&set(v))>1 for a,v in m.items() if a.startswith(c['query_id']+':')) for c in cases)
                budget=sum(len(c['hybrid'][:k]) for c in cases)
                cfg['duplicates'][str(k)]=dict(queries_with_multiple_hits=dq,redundant_chunks=redundant,total_candidates=budget,budget_waste_pct=100*redundant/budget)
                cats={}
                for cat in ('BOUNDARY_SPLIT','CHUNK_TOO_BROAD','NOT_CHUNKING_RELATED','UNCLEAR'):
                    historic={x['anchor_id'] for x in c0 if x['diagnosis']==cat and x[f'miss_top{k}']};still=historic-set().union(*(hits(b,mappings['BASE'],k) for b in rankings['BASE']))
                    cats[cat]=dict(historical_miss_count=len(historic),repaired_base_miss_count=len(still),recovered_ids=sorted(new&still),lost_ids=sorted(lost&historic))
                cfg['c0_categories'][str(k)]=cats
        configs[key]=cfg
    ordering=sorted(configs,key=lambda key:tuple(configs[key]['metrics']['hybrid'][m] for m in ('CR@50','CR@30','CR@20','R@10','MRR@10')),reverse=True)
    out=dict(status='OFFLINE_RESCORED_PENDING_DECISION',annotation=validation,annotation_sha256=sha(B/'dev_gold_evidence_spans_v2.json'),span_statistics=stats,configs=configs,metric_order=ordering,identity_checks=identity,protected_hashes=protected,old_C1_status='C1 ORIGINAL PORTABILITY / INVALIDATED BY PORTABILITY AUDIT',old_B_CR50=0.9285714285714286,metric_contract='35-query macro averages; each query denominator retains all original Gold units including zero-mapped units; 55 units total. Reranked candidate recall references pre-rerank Hybrid.',duplicate_contract='A retrieved chunk is redundant if it matches one or more reviewed units but adds no new unit beyond earlier chunks. Chunks contributing a new unit are not wasted. Queries-with-multiple-hits separately counts any repeated unit.',retrieval_run=False,encoding_run=False,test_semantics_read=False)
    for name,h in protected.items():assert sha(R/name)==h,name
    save(O/'mappings.json',mappings);save(O/'summary.json',out);csvsave(B/'c1r_gold_mapping_summary.csv',map_rows);csvsave(B/'c1r_rescored_metrics.csv',metrics_rows);csvsave(B/'c1r_gain_loss.csv',gain_rows)
    print(json.dumps({'stats':stats,'order':ordering,'configs':{k:{'mapping':v['mapping'],'hybrid':v['metrics']['hybrid'],'gains':v['gain_loss'],'cross':v['cross_document'],'duplicates':v['duplicates'],'reranked':v['metrics']['reranked']} for k,v in configs.items()}},indent=2))

if __name__=='__main__':main()
