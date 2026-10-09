"""C0 source reconstruction only: checksum-matched PDFs, same parser/current chunker."""
import os
os.environ.update(LLM_API_KEY='',GRAPH_EXTRACTION_ENABLED='false',HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1')
import json,hashlib,sys,types,re,statistics
from pathlib import Path
from importlib.metadata import version
R=Path(__file__).resolve().parents[2];O=R/'artifacts/evaluation_v2/c0';O.mkdir(exist_ok=True)
from app.services.parsing.pdf_parser import PdfParser
from app.services.chunking.text_chunker import TextChunker
from app.services.indexing.hash_service import hash_text
from transformers import AutoTokenizer
sha=lambda b:hashlib.sha256(b).hexdigest()
source=json.loads((R/'artifacts/evaluation_v2/b4/corpus.json').read_text());manifest=json.loads((R/'benchmarks/real_research/v2/corpus_manifest.json').read_text());rows=source['rows'];ids=source['ids']
result={'parser':'PdfParser / pypdf extract_text default','pypdf_version':version('pypdf'),'reconstructed_chunk_count':0,'documents':[],'chunks':[]}
for doc in manifest['documents']:
 raw=(R/'benchmarks/real_research/papers'/doc['filename']).read_bytes();assert sha(raw)==doc['sha256']
 parsed=PdfParser().parse(doc['filename'],raw);chunks=TextChunker(700,100).chunk(parsed)
 frozen=sorted([(sid,row) for sid,row in zip(ids,rows) if row['metadata']['document_id']==doc['document_id']],key=lambda item:item[1]['metadata']['chunk_index'])
 assert len(chunks)==len(frozen)==doc['chunk_count'],doc['paper_id']
 pages=[];offset=0
 for sec in parsed.sections:
  assert parsed.text[offset:offset+len(sec.text)]==sec.text
  pages.append({'page':sec.page_number,'section':sec.section_title,'start':offset,'end':offset+len(sec.text),'text':sec.text});offset+=len(sec.text)+2
 for ch,(sid,row) in zip(chunks,frozen):
  m=row['metadata'];assert ch.text==row['document'] and ch.chunk_hash==m['chunk_hash'] and ch.page_number==m['page_number'] and (ch.section_title or '')==m['section_title'],sid
  page=next(p for p in pages if p['page']==ch.page_number)
  starts=[];pos=0
  while True:
   pos=page['text'].find(ch.text,pos)
   if pos<0:break
   starts.append(pos+page['start']);pos+=1
  result['chunks'].append({'chunk_id':sid,'document_id':doc['document_id'],'document_version_id':doc['document_version_id'],'page':ch.page_number,'section':ch.section_title,'ordinal':ch.chunk_index,'text':ch.text,'raw_span_candidates':starts,'source_text_hash':sha(parsed.text.encode()),'length':len(ch.text)})
 result['documents'].append({'document_id':doc['document_id'],'document_version_id':doc['document_version_id'],'paper_id':doc['paper_id'],'source_sha256':doc['sha256'],'text_hash':sha(parsed.text.encode()),'text':parsed.text,'pages':pages,'chunk_count':len(chunks),'page_count':doc['page_count']})
 result['reconstructed_chunk_count']+=len(chunks);print('SOURCE VERIFIED',doc['paper_id'],len(chunks),flush=True)
assert result['reconstructed_chunk_count']==3837
tokenizer=AutoTokenizer.from_pretrained('BAAI/bge-m3',revision='5617a9f61b028005a4858fdac845db406aefb181',cache_dir='/models/model_cache',local_files_only=True)
lengths=[len(t) for t in tokenizer([c['text'] for c in result['chunks']],truncation=False)['input_ids']]
for c,n in zip(result['chunks'],lengths):c['m3_token_count']=n
(O/'source_reconstruction.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
print('C0 SOURCE COMPLETE',len(result['chunks']),flush=True)
