"""B4-only model contracts and validation. No production provider changes."""
from dataclasses import dataclass, asdict
import numpy as np
from app.services.evaluation.query_instruction import fingerprint
from app.services.evaluation.ann_exactness import fidelity
from app.services.evaluation.metrics import score_ranking

@dataclass(frozen=True)
class EmbeddingConfig:
    key: str
    model: str
    revision: str
    dimension: int
    max_length: int
    query_prefix: str
    document_prefix: str = ""
    pooling: str = "CLS"
    normalization: bool = True
    license: str = "MIT"
    batch_size: int = 16

    def text(self, text, query):
        return (self.query_prefix if query else self.document_prefix) + text

    def identity(self, corpus_hash, chunking):
        return {**asdict(self), "query_strategy":"official_instruction" if self.query_prefix else "raw",
                "document_strategy":"raw", "distance_metric":"squared_l2", "n_results":200,
                "search_ef":10, "HNSW":{"M":16,"construction_ef":100,"num_threads":16,
                "resize_factor":1.2,"batch_size":100,"sync_threshold":1000},
                "chunking_config_hash":fingerprint(chunking), "corpus_manifest_hash":corpus_hash,
                "cpu_torch_threads":4}

CONFIGS = {
 "zh":EmbeddingConfig("zh","BAAI/bge-small-zh-v1.5","7999e1d3359715c523056ef9478215996d62a620",512,512,"为这个句子生成表示以用于检索相关文章："),
 "en":EmbeddingConfig("en","BAAI/bge-small-en-v1.5","5c38ec7c405ec4b44b94cc5a9bb96e735b38267a",384,512,"Represent this sentence for searching relevant passages: "),
 "m3":EmbeddingConfig("m3","BAAI/bge-m3","5617a9f61b028005a4858fdac845db406aefb181",1024,8192,"",batch_size=4),
}
VECTOR_METADATA = {"embedding_model","embedding_provider","embedding_dimension","embedding_version"}

def validate_vectors(ids, vectors, expected_ids, dimension):
    x=np.asarray(vectors)
    if len(ids)!=len(set(ids)) or set(ids)!=set(expected_ids):
        raise ValueError("index_membership_mismatch")
    if x.shape!=(len(ids),dimension) or not np.isfinite(x).all():
        raise ValueError("vector_dimension_or_finite_mismatch")
    norms=np.linalg.norm(x,axis=1)
    if not np.allclose(norms,1,atol=1e-5):
        raise ValueError("vector_normalization_mismatch")
    return {"chunks":len(ids),"missing":0,"extra":0,"duplicate":0,"mismatch":0,
            "dimension":dimension,"all_finite":True,"norm_min":float(norms.min()),
            "norm_max":float(norms.max()),"norm_mean":float(norms.mean())}

def validate_payload(ids, metas, docs, expected):
    for sid,meta,doc in zip(ids,metas,docs):
        if sid not in expected or meta!=expected[sid]["metadata"] or doc!=expected[sid]["document"]:
            raise ValueError("metadata_or_text_identity_mismatch")

def ann_diagnostic(cases):
    import statistics
    out={f"Top{k}":statistics.mean(fidelity(c["ids"],c["exact"],min(k,len(c["exact"]))) for c in cases) for k in (20,50,100)}
    ann=statistics.mean(score_ranking(c["ids"],c["gold"],50)["Recall"] for c in cases)
    exact=statistics.mean(score_ranking(c["exact"],c["gold"],50)["Recall"] for c in cases)
    out.update(ann_cr50=ann,exact_cr50=exact,gap_pp=100*(exact-ann),
               ann_confound=out["Top50"]<.98 or abs(exact-ann)>.02+1e-12)
    return out

