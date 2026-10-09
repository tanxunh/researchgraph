"""C1 frozen reranker diagnostic, only after every primary config has terminated."""
from run_v2_chunking_ablation import *
from app.services.retrieval.reranker import CrossEncoderReranker,rerank_candidates
import torch
for key in ('BASE','A','B','C'):
    assert (O/f'{key}_retrieval.json').exists(),'all_primary_configs_must_finish_first'
guard();torch.set_num_threads(4);torch.set_num_interop_threads(1)
queries=[json.loads(l) for l in (B/'queries_dev.jsonl').read_text().splitlines() if l.strip()]
rev='465b4b7ddf2be0a020c8ad6e525b9bb1dbb708ae'
scorer=CrossEncoderReranker('BAAI/bge-reranker-base',rev,'cpu','/models/model_cache',True);scorer.load();assert scorer.model.model.config._commit_hash==rev
for key in ('BASE','A','B','C'):
    target=O/f'{key}_reranked.json'
    if target.exists():continue
    out=json.loads((O/f'{key}_retrieval.json').read_text())
    if out['status']!='COMPLETE':continue
    texts={c['chunk_id']:c['text'] for c in json.loads((O/f'{key}_corpus.json').read_text())['chunks']}
    def rank(i):
        c=out['cases'][i];pool=[dict(chunk_id=s,text=texts[s],scores={}) for s in c['hybrid'][:20]]
        t=time.perf_counter();ordered,meta=rerank_candidates(queries[i]['query'],pool,scorer);ms=(time.perf_counter()-t)*1000
        assert not meta['reranker_failed'] and {r['chunk_id'] for r in ordered}==set(c['hybrid'][:20])
        return [r['chunk_id'] for r in ordered[:10]],ms
    rank(0)
    for i,c in enumerate(out['cases']):
        c['reranked'],c['reranker_ms']=rank(i);c['reranked_e2e_ms']=statistics.median(t['retrieval_ms'] for t in c['timings'])+c['reranker_ms']
        save(O/f'{key}_reranker_progress.json',out)
    guard();save(target,out);print('RERANKED',key,flush=True)
