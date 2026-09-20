"""Thin contract adapter over already-authoritatively-validated retrieval results."""
from pydantic import ValidationError

from app.schemas.evidence import Evidence


class EvidenceBuilder:
    def __init__(self, max_count: int = 20, max_characters: int = 12000):
        self.max_count = max_count
        self.max_characters = max_characters

    def build(self, search: dict) -> list[Evidence]:
        results = search.get("results", [])
        if not isinstance(results, list):
            return []
        evidence, seen, used = [], set(), 0
        for item in results:
            if not isinstance(item, dict) or item.get("missing"):
                continue
            try:
                document, location = item["document"], item["location"]
                version_id = item["document_version_id"]
                if document.get("version_id", version_id) != version_id:
                    continue
                entry = Evidence(
                    evidence_id=f"C{len(evidence) + 1}",
                    document_id=document["id"], document_version_id=version_id,
                    document_version=document["version"],
                    chunk_id=item["chunk_id"], document_title=document["title"],
                    page=location["page_number"], section=location["section_title"],
                    ordinal=location["ordinal"], content=item["text"],
                    source_type=item["source_type"],
                    source_reference=f"document-version:{version_id}",
                    source_snapshot_available=item.get("source_snapshot_available", False),
                    retrieval_source=search.get("mode", "unknown"),
                    retrieval_score=item.get("scores", {}).get("fusion_score"),
                )
                if not entry.content.strip() or not entry.chunk_id.strip():
                    continue
            except (KeyError, TypeError, AttributeError, ValidationError):
                continue
            identity = (entry.document_id, *entry.locator)
            if identity in seen:
                continue
            # Bound the actual rendered evidence, including metadata. Never silently
            # truncate a source and later present it as the complete cited chunk.
            size = len(entry.context()) + 2
            if used + size > self.max_characters:
                continue
            if len(evidence) >= self.max_count:
                break
            evidence.append(entry)
            seen.add(identity)
            used += size
        return evidence

    @staticmethod
    def public_search(search: dict, evidence: list[Evidence]) -> dict:
        """Preserve legacy search diagnostics, limited to prompt-admitted evidence."""
        admitted = {(entry.document_id, *entry.locator): entry for entry in evidence}
        results, seen = [], set()
        candidates = search.get("results", [])
        for item in candidates if isinstance(candidates, list) else []:
            if not isinstance(item, dict) or not isinstance(item.get("document"), dict):
                continue
            document = item["document"]
            key = (document.get("id"), item.get("document_version_id"), item.get("chunk_id"))
            try:
                entry = admitted.get(key)
            except TypeError:
                continue
            if entry is None or key in seen:
                continue
            seen.add(key)
            results.append({**item, "document": {**document, "source_uri": entry.source_reference}})
        return {**search, "results": results}
