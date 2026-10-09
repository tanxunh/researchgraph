import sys,json,platform,hashlib,sqlite3,pickle,inspect
from pathlib import Path
from importlib import metadata
import numpy,chromadb,hnswlib
from chromadb.segment.impl.vector.local_persistent_hnsw import PersistentLocalHnswSegment
from chromadb.segment.impl.vector.local_hnsw import LocalHnswSegment
from chromadb.segment.impl.vector.hnsw_params import HnswParams
p=Path(sys.argv[1]);out=Path(sys.argv[2]);r={'python':sys.version,'architecture':platform.machine(),'platform':platform.platform(),'packages':{},'hnsw_binary_sha256':hashlib.sha256(Path(hnswlib.__file__).read_bytes()).hexdigest(),'hnsw_binary_file':Path(hnswlib.__file__).name,'files':{},'sqlite':{},'pickle':{},'sources':{}}
for package in ['chromadb','chroma-hnswlib','hnswlib','numpy']:
 try:r['packages'][package]=metadata.version(package)
 except metadata.PackageNotFoundError:r['packages'][package]='NOT INSTALLED'
r['chromadb_import_version']=getattr(chromadb,'__version__','UNKNOWN')
r['chromadb_import_path']=chromadb.__file__
for f in sorted(p.rglob('*')):
 if f.is_file():r['files'][str(f.relative_to(p))]={'bytes':f.stat().st_size,'sha256':hashlib.sha256(f.read_bytes()).hexdigest()}
con=sqlite3.connect('file:'+str(p/'chroma.sqlite3')+'?mode=ro',uri=True);con.row_factory=sqlite3.Row
for table in ['collections','collection_metadata','segments','segment_metadata','embeddings_queue','max_seq_id','embeddings']:
 columns=[x[1] for x in con.execute(f'pragma table_info({table})')];r['sqlite'][table]={'columns':columns}
 if not columns:continue
 rows=con.execute(f'SELECT * FROM {table}').fetchall()
 r['sqlite'][table]['count']=len(rows)
 if table=='embeddings_queue':
  seq=[dict(row) for row in rows];r['sqlite'][table]['operations']={str(k):sum(row.get('operation')==k for row in seq) for k in sorted({row.get('operation') for row in seq})};r['sqlite'][table]['sequence']=[{k:row.get(k) for k in ['seq_id','operation','topic','id','encoding','created_at']} for row in seq]
 elif table=='embeddings':r['sqlite'][table]['sequence']=[dict(row) for row in rows]
 else:r['sqlite'][table]['rows']=[dict(row) for row in rows]
con.close()
for f in p.glob('*/index_metadata.pickle'):
 obj=pickle.loads(f.read_bytes());d=obj.__dict__;r['pickle'][str(f.relative_to(p))]={k:v for k,v in d.items() if k not in ['id_to_label','label_to_id','id_to_seq_id']};mapping=d.get('id_to_label',{});seq=sorted(mapping,key=mapping.get);r['pickle'][str(f.relative_to(p))].update(label_count=len(seq),insertion_sequence=seq,sequence_sha256=hashlib.sha256(json.dumps(seq).encode()).hexdigest())
for cls,names in [(PersistentLocalHnswSegment,['_init_index','_persist','_apply_batch','_write_records']),(LocalHnswSegment,['_init_index','_write_records','query_vectors'])]:
 for n in names:r['sources'][cls.__name__+'.'+n]=inspect.getsource(getattr(cls,n))
r['sources']['HnswParams']=inspect.getsource(HnswParams)
def enc(x):
 if isinstance(x,bytes):return {'hex':x.hex()}
 return str(x)
out.write_text(json.dumps(r,indent=2,default=enc));print(json.dumps({k:r[k] for k in ['python','architecture','packages','hnsw_binary_sha256']}));print('FORENSICS SAVED',out)
