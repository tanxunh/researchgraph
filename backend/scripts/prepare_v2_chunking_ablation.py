"""Generate all C1 corpora before any BM25/model execution. No PDF parsing."""
import sys, types, json, hashlib, statistics
from pathlib import Path
R=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(R/'backend'))
pkg=types.ModuleType('app.services.evaluation');pkg.__path__=[str(R/'backend/app/services/evaluation')];sys.modules['app.services.evaluation']=pkg
from app.services.evaluation.chunking_ablation import CONFIGS, fingerprint, sentence_windows
from app.services.evaluation.portable_gold import matches
from app.services.chunking.text_chunker import TextChunker
O=R/'artifacts/evaluation_v2/c1';O.mkdir(parents=True,exist_ok=True)
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def save(p,v):p.write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
paths=['benchmarks/real_research/v2/'+n for n in ['queries_dev.jsonl','queries_test.jsonl','dev_gold_portable_anchors.json','corpus_manifest.json','final_dense_config.json']]
paths+=['artifacts/evaluation_v2/c0/source_reconstruction.json','backend/app/services/chunking/text_chunker.py','backend/app/services/evaluation/portable_gold.py','backend/app/services/indexing/bm25_index.py','backend/app/services/retrieval/fusion_ranker.py','backend/app/services/retrieval/reranker.py']
protected={p:sha(R/p) for p in paths}
protocol={'configs':CONFIGS,'protected_hashes':protected,'selection_order':['hybrid_CR50','hybrid_CR30','hybrid_CR20','hybrid_R10','hybrid_MRR10','gain_loss','cross_document','duplicates','cost'],'only_DEV':True,'mapping_threshold':0.5,'reranker_after_all_primary':True}
if (O/'protocol.json').exists():assert json.loads((O/'protocol.json').read_text())==protocol
else:save(O/'protocol.json',protocol)
source=json.loads((R/paths[5]).read_text(encoding='utf-8'))
anchors=json.loads((R/paths[2]).read_text(encoding='utf-8'))['anchors']
assert len(anchors)==55 and len(source['documents'])==30
reports={}
for key,cfg in CONFIGS.items():
    chunks=[];errors=[];ch=fingerprint(cfg);seen_pages=set()
    for doc in source['documents']:
        for page in doc['pages']:
            text=page['text']; assert doc['text'][page['start']:page['end']]==text
            seen_pages.add((doc['document_id'],page['page']))
            if key=='C':windows=list(sentence_windows(text))
            else:
                windows=[]
                for raw in TextChunker(cfg['target'],100)._windows(text):
                    raw=raw.strip();positions=[];pos=text.find(raw)
                    while pos>=0:
                        positions.append(pos);pos=text.find(raw,pos+1)
                    if len(positions)!=1:errors.append({'document_id':doc['document_id'],'page':page['page'],'locations':len(positions),'text':raw})
                    windows.append((positions[0] if positions else None,raw))
            for offset,raw in windows:
                if offset is None:continue
                start=page['start']+offset
                sid='c1-'+key.lower()+'-'+ch[:12]+'-'+fingerprint([doc['document_id'],doc['document_version_id'],page['page'],start,raw])[:24]
                if key=='BASE':
                    originals=[c for c in source['chunks'] if c['document_id']==doc['document_id'] and c['page']==page['page'] and c['text']==raw]
                    assert len(originals)==1;sid=originals[0]['chunk_id']
                chunks.append(dict(chunk_id=sid,document_id=doc['document_id'],document_version_id=doc['document_version_id'],page=page['page'],section=page.get('section'),text=raw,document_char_start=start,document_char_end=start+len(raw),source_text_hash=doc['text_hash']))
    mapping={a['anchor_id']:[c['chunk_id'] for c in chunks if matches(a,c)] for a in anchors}
    counts=[len(v) for v in mapping.values()];unmapped=[k for k,v in mapping.items() if not v]
    actual_pages={(c['document_id'],c['page']) for c in chunks}
    report=dict(config=cfg,chunking_config_hash=ch,chunk_count=len(chunks),documents=len({c['document_id'] for c in chunks}),pages=len(actual_pages),missing_pages=sorted(seen_pages-actual_pages),extra_pages=sorted(actual_pages-seen_pages),duplicate_ids=len(chunks)-len({c['chunk_id'] for c in chunks}),empty_chunks=sum(not c['text'] for c in chunks),integrity_errors=errors,mapped=55-len(unmapped),unmapped=unmapped,ambiguous=len(errors),multiplicity=dict(one=counts.count(1),two=counts.count(2),three_or_more=sum(n>=3 for n in counts),mean=statistics.mean(counts),median=statistics.median(counts),max=max(counts)))
    report['status']='GATE_PASS' if not errors and not unmapped and not report['missing_pages'] and not report['duplicate_ids'] and report['pages']==432 else 'STOPPED_MAPPING_OR_INTEGRITY'
    save(O/f'{key}_corpus.json',{'chunks':chunks,'mapping':mapping,'audit':report});reports[key]=report
    print(key,report['status'],len(chunks),report['mapped'],report['multiplicity'],flush=True)
for p,h in protected.items():assert sha(R/p)==h
save(O/'mapping_gate.json',reports)
