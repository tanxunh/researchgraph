"""C0 derived anchors first; saved DEV misses inspected only after anchor construction."""
import sys,types,json,hashlib,csv,re,math,inspect,unicodedata
from pathlib import Path
from collections import Counter
R=Path(__file__).resolve().parents[2];B=R/'benchmarks/real_research/v2';O=R/'artifacts/evaluation_v2/c0'
sys.path.insert(0,str(R/'backend'));pkg=types.ModuleType('app.services.evaluation');pkg.__path__=[str(R/'backend/app/services/evaluation')];sys.modules['app.services.evaluation']=pkg
from app.services.evaluation.portable_gold import normalize,matches,coverage,NORMALIZATION_VERSION
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
hashtext=lambda s:hashlib.sha256(s.encode()).hexdigest()
protected=json.loads((R/'artifacts/evaluation_v2/b6/protocol.json').read_text(encoding='utf-8'))['protected_hashes']
for name,h in protected.items():assert sha(R/name)==h,name
source=json.loads((O/'source_reconstruction.json').read_text(encoding='utf-8'));chunks=source['chunks'];byid={c['chunk_id']:c for c in chunks};docs={d['document_id']:d for d in source['documents']}
queries=[json.loads(l) for l in (B/'queries_dev.jsonl').read_text(encoding='utf-8').splitlines() if l.strip()]
assert len(queries)==35 and len(chunks)==3837
for c in chunks:
 pos=c['raw_span_candidates'];c['document_char_start']=pos[0] if len(pos)==1 else None;c['document_char_end']=pos[0]+len(c['text']) if len(pos)==1 else None
anchors=[];mapping={};rows=[]
for q in queries:
 for i,g in enumerate(q['gold_evidence']):
  c=byid[g['chunk_id']];d=docs[g['document_id']]
  assert g['document_id'] in q['document_scope'] and c['document_version_id']==g['document_version_id']==d['document_version_id'] and c['page']==g['page'] and c['section']==g['section']
  a={'anchor_id':q['query_id']+':G'+str(i+1),'query_id':q['query_id'],'query_type':q['query_type'],'original_gold_chunk_id':g['chunk_id'],'paper_id':g['paper_id'],'document_id':g['document_id'],'document_version':g['document_version_id'],'document_version_id':g['document_version_id'],'version_identity_kind':'immutable DocumentVersion primary key; not revision ordinal','page':g['page'],'section':g['section'],'anchor_text':c['text'],'normalized_anchor_text':normalize(c['text']),'anchor_text_hash':hashtext(normalize(c['text'])),'raw_anchor_text_hash':hashtext(c['text']),'document_char_start':c['document_char_start'],'document_char_end':c['document_char_end'],'source_text_hash':c['source_text_hash'],'source_pdf_sha256':d['source_sha256'],'source_method':'EXACT_SPAN' if c['document_char_start'] is not None else 'CHUNK_TEXT_FALLBACK','span_selection':'full reviewed Gold chunk; no narrower approved exact span','ambiguous':len(c['raw_span_candidates'])!=1}
  if a['source_method']=='EXACT_SPAN':assert d['text'][a['document_char_start']:a['document_char_end']]==a['anchor_text']
  # Repeated full text across the document cannot override the original unique page+offset.
  a['document_text_occurrences']=d['text'].count(c['text']);a['ambiguous_text_location']=a['document_text_occurrences']>1
  candidates=[ch for ch in chunks if matches(a,ch)];mapping[a['anchor_id']]=[ch['chunk_id'] for ch in candidates]
  rows.append({'anchor_id':a['anchor_id'],'query_id':q['query_id'],'original_gold_chunk_id':g['chunk_id'],'document_id':g['document_id'],'document_version_id':g['document_version_id'],'page':g['page'],'source_method':a['source_method'],'document_char_start':a['document_char_start'],'document_char_end':a['document_char_end'],'matched_chunk_ids':json.dumps(mapping[a['anchor_id']]),'match_count':len(candidates),'original_recovered':g['chunk_id'] in mapping[a['anchor_id']],'ambiguous':a['ambiguous']})
  anchors.append(a)
normalization={'version':NORMALIZATION_VERSION,'function_sha256':hashtext(inspect.getsource(normalize)),'unicode_version':unicodedata.unidata_version,'rules':'NFC then whitespace collapse and strip; case, punctuation, scientific identifiers and hyphens retained'}
contract={'status':'DERIVED_ONLY','source_dev_sha256':sha(B/'queries_dev.jsonl'),'normalization':normalization,'coordinate_system':'zero-based Unicode codepoints, half-open offsets in PdfParser full_text (nonempty stripped pages joined by two LF)','matching':'same document/version; exact source hash for offsets; intersection / anchor raw length >=0.50. Text fallback requires same page or section and no ambiguous location; longest contiguous exact normalized substring / normalized anchor length >=0.50. No bag-of-words or fuzzy matching.','threshold':0.5,'denominator':'Original Query-Gold units; any matching retrieved chunk counts once per anchor; no denominator expansion','evidence_scope':'Full human-reviewed chunk texts, no semantic labels or narrower spans invented','anchors':anchors}
assert not (B/'dev_gold_portable_anchors.json').exists()
(B/'dev_gold_portable_anchors.json').write_text(json.dumps(contract,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
with (B/'c0_anchor_mapping_audit.csv').open('w',encoding='utf-8',newline='') as f:w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
(O/'current_mapping.json').write_text(json.dumps(mapping,indent=2)+'\n',encoding='utf-8')
def distribution(values,qs):
 v=sorted(values);return {name:v[max(0,math.ceil(p*len(v))-1)] for name,p in qs.items()}
lengths=distribution([c['length'] for c in chunks],{'min':0,'p25':.25,'median':.5,'p75':.75,'p95':.95,'max':1})
tokens=distribution([c['m3_token_count'] for c in chunks],{'min':0,'median':.5,'p95':.95,'max':1})
structure=[]
for d in source['documents']:
 pages=d['pages'];text=d['text']
 structure.append({'document_id':d['document_id'],'pages':len(pages),'page_metadata':True,'section_metadata_count':sum(bool(p['section']) for p in pages),'double_lf_pages':sum('\n\n' in p['text'] for p in pages),'heading_like_lines':len(re.findall(r'(?m)^\s*(?:[IVX]+\.|\d+\.)\s+[A-Z][^\n]{0,90}$',text)),'table_mentions':len(re.findall(r'\bTABLE\s+[IVX\d]+',text)),'caption_mentions':len(re.findall(r'\b(?:Fig\.|Figure)\s*\d+',text)),'reference_heading':bool(re.search(r'(?i)\bREFERENCES\b',text))})
# Sample selection uses only source text/location/type, never retrieval outcomes.
unique=list({a['original_gold_chunk_id']:a for a in anchors}.values());selected=[]
def add(a,reason):
 for item in selected:
  if item['anchor']['original_gold_chunk_id']==a['original_gold_chunk_id']:item['reasons'].append(reason);return
 selected.append({'anchor':a,'reasons':[reason]})
add(min(unique,key=lambda a:len(a['anchor_text'])),'shortest available reviewed Gold (699 chars; no truly short Gold)')
add(max(unique,key=lambda a:len(a['anchor_text'])),'longest available reviewed Gold (700 chars)')
def boundary(a):
 p=next(p for p in docs[a['document_id']]['pages'] if p['page']==a['page']);return min(a['document_char_start']-p['start'],p['end']-a['document_char_end'])
for a in sorted(unique,key=boundary)[:3]:add(a,'nearest page boundary; no chunk crosses pages')
for a in sorted(unique,key=lambda a:sum(a['anchor_text'].count(c) for c in '=()???'),reverse=True)[:3]:add(a,'highest formula/punctuation signal among reviewed Gold')
for a in unique:
 if a['query_type']=='cross_document':add(a,'cross-document ownership check')
 if len(selected)>=12:break
for item in selected:
 item['matched_chunks']=[byid[sid] for sid in mapping[item['anchor']['anchor_id']]]
(O/'false_positive_samples.json').write_text(json.dumps(selected,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
# Anchor file has now been fixed, before opening saved DEV retrieval outcomes.
run=json.loads((R/'artifacts/evaluation_v2/b6/m3.json').read_text(encoding='utf-8'));cases={c['query_id']:c for c in run['cases']};miss=[]
for a in anchors:
 c=cases[a['query_id']];miss20=a['original_gold_chunk_id'] not in c['hybrid'][:20];miss50=a['original_gold_chunk_id'] not in c['hybrid'][:50]
 if not miss20 and not miss50:continue
 ch=byid[a['original_gold_chunk_id']];neighbors=[n for n in chunks if n['document_id']==ch['document_id'] and abs(n['ordinal']-ch['ordinal'])==1]
 miss.append({'anchor_id':a['anchor_id'],'query_id':a['query_id'],'question':next(q['query'] for q in queries if q['query_id']==a['query_id']),'miss_top20':miss20,'miss_top50':miss50,'anchor':a,'neighbors':neighbors,'diagnosis':'PENDING_INSPECTION'})
(O/'miss_review.json').write_text(json.dumps(miss,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
audit={'status':'PENDING_MANUAL_TEXT_INSPECTION','gold_units':len(anchors),'unique_gold_chunks':len(unique),'schema':{'document_id':55,'document_version_id':55,'chunk_id':55,'page':sum(a['page'] is not None for a in anchors),'section_non_null':sum(a['section'] is not None for a in anchors),'offsets_in_original_gold':0,'text_in_original_gold':0,'authoritative_chunk_text_available':55},'backward':{'mapped':sum(r['original_recovered'] for r in rows),'unmapped':sum(not r['original_recovered'] for r in rows),'ambiguous':sum(r['ambiguous'] for r in rows),'mapping_count_distribution':dict(Counter(r['match_count'] for r in rows))},'normalization':normalization,'anchor_file_sha256':sha(B/'dev_gold_portable_anchors.json'),'chunk_count':3837,'character_distribution':lengths,'m3_token_distribution':tokens,'token_measurement':'Pinned BGE-M3 tokenizer, no truncation, includes special tokens. Stored token_count is only max(1,len(text)//2).','structure':structure,'sample_count':len(selected),'protected_hashes':protected,'source_reconstruction':'All30 PDF checksums matched frozen manifest; same PdfParser/TextChunker reproduced all3837 texts, hashes, pages and ordinals exactly. Full text reconstructed from immutable raw sources, not asserted to be a stored DocumentVersion full-text column.'}
(O/'chunking_audit.json').write_text(json.dumps(audit,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps({k:audit[k] for k in ['gold_units','unique_gold_chunks','backward','character_distribution','m3_token_distribution','sample_count']}));print('MISS UNITS',len(miss),sum(m['miss_top20'] for m in miss),sum(m['miss_top50'] for m in miss))
