"""Small deterministic intent rules; no model calls or corpus scans."""
from dataclasses import dataclass
import re


@dataclass(frozen=True)
class QueryAnalysis:
    query_type: str
    use_graph: bool
    reason: str


def analyze_query(query: str) -> QueryAnalysis:
    text = " ".join(query.lower().split())
    if re.search(r"比较|共同使用|跨论文|之间关系|\b(compare|compares|comparison|across papers|two papers|both|shared|in common)\b", text):
        return QueryAnalysis("cross_document", True, "comparison_or_shared_relation")
    if re.search(r"全称|是什么|定义|\b(what is|define|stand for)\b", text):
        return QueryAnalysis("factual", False, "definition")
    if re.search(r"哪些论文|哪些方法.*使用|使用了?什么数据集|关系|\b(evaluated on|uses?|used|datasets?|compares with|relationship)\b", text):
        return QueryAnalysis("relational", True, "explicit_relation")
    if re.fullmatch(r"[\w.+-]{1,80}", text):
        return QueryAnalysis("exact_term", False, "single_term")
    return QueryAnalysis("semantic", False, "semantic_default")
