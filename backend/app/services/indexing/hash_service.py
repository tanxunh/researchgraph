from __future__ import annotations

import hashlib
import json
import re


def normalized_text(text: str) -> str:
    return "\n".join(line.rstrip() for line in (text or "").strip().splitlines()).strip()


def hash_text(text: str) -> str:
    return hashlib.sha256(normalized_text(text).encode("utf-8")).hexdigest()


def stable_chunk_id(document_id: int, chunk_hash: str, occurrence_index: int = 0) -> str:
    # Preserve existing first-occurrence IDs and vector IDs during migration.
    suffix = f"-occ-{occurrence_index}" if occurrence_index else ""
    return f"doc-{document_id}-chunk-{chunk_hash[:24]}{suffix}"


def chunking_config_hash(settings) -> str:
    config = dict(chunk_size=settings.chunk_size, chunk_overlap=settings.chunk_overlap,
                  splitter_version=settings.chunker_version)
    return hashlib.sha256(json.dumps(config, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def evidence_identity(parsed, settings) -> str:
    source = parsed.raw_source.checksum if parsed.raw_source else "legacy:" + hash_text(parsed.text)
    return hashlib.sha256(json.dumps([source, settings.parser_version,
                                     chunking_config_hash(settings)], separators=(",", ":")).encode()).hexdigest()


def normalize_entity_name(name: str) -> str:
    value = (name or "").strip().lower()
    value = re.sub(r"[，,。.;；:：()（）\[\]{}<>《》\"'`]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()
