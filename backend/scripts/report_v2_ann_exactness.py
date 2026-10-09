"""Render the completed DEV-only ANN audit; append ledger without dropping prior rows."""
import csv,json
from pathlib import Path
R=Path(__file__).resolve().parents[2];B=R/'benchmarks/real_research/v2';r=json.loads((B/'results/v2b2_ann_exactness.json').read_text())
assert r['status']=='COMPLETE'
experiments=r['experiments'];selected=next(e for e in experiments if e['ef_search']==r['selected_ef'] and e['backend']!='exact')
path=B/'experiments.csv'
with path.open(encoding='utf-8',newline='') as f:
    reader=csv.DictReader(f);fields=list(reader.fieldnames);old=list(reader)
existing={row['experiment_id'] for row in old};new=[]
for e in experiments:
    m=e['tracks']['global']['overall'];types=e['tracks']['global']['by_type']
    row=dict(experiment_id=e['id'],phase='V2-B2',status='COMPLETE',split='dev',backend=e['backend'],ef_search=e['ef_search'],effective_ef=e.get('effective_ef'),model=r['identity']['model'],model_revision=r['identity']['revision'],embedding_dimension=512,pooling='CLS',normalization='ON',metric='l2 / exact dot',query_encoding='raw',document_encoding='raw',corpus_hash=r['identity']['corpus_hash'],vector_fingerprint=r['identity']['vector_fingerprint'],namespace=e['namespace'],dense_k=200,bm25_k=0,rerank_k=0,dev_sha256=r['dev_sha256'],test_sha256=r['test_sha256'],notes=r['latency_scope'])
    for k in [10,20,50,100]:row[f'ann_fidelity_{k}']=m[f'fidelity@{k}']
    for key,metric in [('dense_r10','Recall@10'),('dense_mrr10','MRR@10'),('dense_cr20','CR@20'),('dense_cr50','CR@50'),('p50','p50'),('p95','p95')]:row[key]=m[metric]
    for prefix,ty in [('semantic','semantic'),('crossdoc','cross_document'),('multihop','multi_hop')]:row[prefix+'_cr50']=types[ty]['CR@50']
    if row['experiment_id'] not in existing:new.append(row)
for row in new:
    for key in row:
        if key not in fields:fields.append(key)
if new:
    temp=path.with_suffix('.csv.tmp')
    with temp.open('w',encoding='utf-8',newline='') as f:
        w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(old+new)
    temp.replace(path)
lines=['## B2 ANN Exactness','','Status: COMPLETE. DEV-only audit; no B3 instruction/model experiment.','',
'### Exact reference implementation','',
'Exhaustive float64 dot-product ranking of the original3837 stored float32 vectors, deterministic locator tie-break. No corpus re-encoding. Query vectors computed once using the unchanged raw BGE encoding. Original stored-vector and query-vector fingerprints saved in the local export; corpus/vector/model/encoding identity accompanies every experiment namespace.',
'',
'Dot and cosine agree at every evaluated Top100 for all35 Global and35 Scoped cases. Full Global rankings agree exactly for '+str(r['ranking_agreement']['global']['full_order_equal_queries'])+'/35; remaining differences occur below100 with slightly non-unit float32 vectors. Scoped full rankings agree35/35. Do not claim bit-identical exhaustive order.',
'',
'### Effective ef_search and index safety','',
'Chroma0.5.23 PersistentLocalHnswSegment loads HNSW and calls index.set_ef(search_ef); it reads hnsw:search_ef from segment metadata. No supported public per-query ef argument is used. This evaluation invokes the backend set_ef on the isolated in-process index and asserts index.ef before/after queries; changing metadata alone is not used.',
'',
'A stopped baseline volume was mounted read-only and copied to a34,366,261-byte isolated PersistentClient snapshot. All configurations share the same loaded graph, including its persisted buffer/replay behavior. No graph rebuilding or corpus encoding confound. Snapshot vectors must match the exported fingerprint; ef10 rankings must match the original service rankings for all Global/Scoped queries. Both checks passed. Each run has a unique identity hash containing model/revision/pooling/normalization/metric/ef/corpus/vector hash. Baseline volume is never opened for writing by the experiment.',
'',
'### Acquisition depth and measurement protocol','',
'Primary acquisition is n_results=200, matching frozen Dense source retrieval; Top10/20/50/100 are prefixes of that response. Direct n_results=K fidelity probes are separately reported because requested result depth can affect HNSW exploration. Selection concerns the primary frozen retrieval path, not a claim about every smaller public API request.',
'',
'Warm up each query/config/track, then retain all3 timed repetitions (105 samples per config per track). Search-only latency: no query encoding, model loading or index loading. Exact is in-memory exhaustive sort; ANN includes local Chroma query/filter overhead, not HTTP. These are different backend costs, not total production latency. Small scopes use min(K,available count) as the fidelity denominator; Global always uses K.',
'',
'Index cold load: '+str(round(r['index_load_ms'],3))+' ms. Model cold load: '+str(round(r['model_load_ms'],3))+' ms.','',
'### ANN Fidelity and Gold metrics','']
for track in ['global','scoped']:
    lines += ['#### '+track,'','|Backend|Fidelity10|20|50|100|Hit5|R5|R10|MRR10|CR20|CR50|p50 ms|p95 ms|','|---|'+'---:|'*13]
    for e in experiments:
        m=e['tracks'][track]['overall'];vals=[e['backend']]+[f'{100*m[k]:.2f}' for k in ['fidelity@10','fidelity@20','fidelity@50','fidelity@100','Hit@5','Recall@5','Recall@10']]+[f'{m["MRR@10"]:.4f}']+[f'{100*m[k]:.2f}' for k in ['CR@20','CR@50']]+[f'{m[k]:.3f}' for k in ['p50','p95']]
        lines.append('|'+'|'.join(vals)+'|')
    lines += ['','Direct n_results=K fidelity (separate from primary200 acquisition):','','|Backend|K10|K20|K50|K100|','|---|---:|---:|---:|---:|']
    for e in experiments[1:]:lines.append('|'+e['backend']+'|'+'|'.join(f'{100*e["direct_n_results_fidelity"][track][str(k)]:.2f}' for k in [10,20,50,100])+'|')
    lines.append('')
lines+=['### Query-type diagnostic','','|Type|Backend|R10|CR20|CR50|','|---|---|---:|---:|---:|']
for ty in ['semantic','cross_document','multi_hop']:
    shown=set()
    for e in [experiments[0],experiments[1],selected]:
        if e['backend'] in shown:continue
        shown.add(e['backend']);m=e['tracks']['global']['by_type'][ty];lines.append('|'+ty+'|'+e['backend']+'|'+'|'.join(f'{100*m[k]:.2f}' for k in ['Recall@10','CR@20','CR@50'])+'|')
lines+=['','Cross-document n=7; diagnostic only, no strong generalization claim.','','### Error cases','',
'Global Exact Top20 gold excluded by ef10: '+str(r['gold_loss']['global']['20'])+' query-gold units. Top50: '+str(r['gold_loss']['global']['50'])+'.',
'Export: benchmarks/real_research/v2/ann_exactness_error_cases.csv. Exact gold rank is exhaustive; missing ANN rank means absent from returned200, not absent from the corpus. All DEV Gold units are retained, with global/scoped track labels. Top10/20/50 overlap counts and rankings are also saved per experiment.','',
'### Conclusion','',
'Selected ef_search: '+str(r['selected_ef'])+'. '+r['selection_rule'],
'No production configuration changed. ef256 runs only if ef128 primary Global Top50 fidelity is below99%. Any small Gold recall change must be distinguished from ANN fidelity and from embedding/model quality.','',
'### Integrity and regression','',
'DEV hash unchanged: '+r['dev_sha256'],
'TEST hash unchanged: '+r['test_sha256'],
'TEST retrieval NOT RUN; TEST ranking NOT READ; Gold/instruction/normalization/pooling/chunking/BM25/RRF/reranker unchanged. No external LLM. B3 NOT STARTED.','']
doc=R/'docs/evaluation_v2_embedding_optimization.md';s=doc.read_text();marker='## B2 ANN Exactness';assert marker not in s;s+='\n'+'\n'.join(lines);doc.write_text(s,encoding='utf-8')
print('Ledger and B2 report saved')
