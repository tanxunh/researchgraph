from __future__ import annotations

from app.services.indexing.hash_service import normalize_entity_name


class EntityNormalizer:
    def normalize(self, name: str) -> str:
        return normalize_entity_name(name)
