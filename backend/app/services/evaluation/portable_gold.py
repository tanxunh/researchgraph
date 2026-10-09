"""C0 deterministic portability. Original annotations are never changed."""
import re, unicodedata
from difflib import SequenceMatcher
NORMALIZATION_VERSION = "nfc-whitespace-v1"
COVERAGE_THRESHOLD = 0.50

def normalize(text):
    return re.sub(r"\s+", " ", unicodedata.normalize("NFC", text)).strip()

def coverage(anchor, chunk):
    if any(anchor[k] != chunk[k] for k in ("document_id", "document_version_id")) or anchor.get("ambiguous"):
        return 0.0
    a, b = anchor.get("document_char_start"), anchor.get("document_char_end")
    c, d = chunk.get("document_char_start"), chunk.get("document_char_end")
    if None not in (a, b, c, d):
        if anchor["source_text_hash"] != chunk["source_text_hash"] or b <= a or d <= c:
            return 0.0
        return max(0, min(b, d) - max(a, c)) / (b - a)
    if anchor.get("page") is not None:
        if anchor["page"] != chunk.get("page"): return 0.0
    elif anchor.get("section"):
        if anchor["section"] != chunk.get("section"): return 0.0
    else:
        return 0.0
    if anchor.get("ambiguous_text_location"): return 0.0
    a, b = normalize(anchor["anchor_text"]), normalize(chunk["text"])
    if not a: return 0.0
    return SequenceMatcher(None, a, b, autojunk=False).find_longest_match(0, len(a), 0, len(b)).size / len(a)

def matches(anchor, chunk):
    return coverage(anchor, chunk) >= COVERAGE_THRESHOLD

def recalled_units(anchors, mapping, retrieved):
    return sum(bool(set(retrieved) & set(mapping[a["anchor_id"]])) for a in anchors)
