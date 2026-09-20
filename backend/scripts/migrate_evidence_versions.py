"""Run from backend: python -m scripts.migrate_evidence_versions."""
import json

from app.core.database import engine
from app.migrations.evidence_versions import upgrade


def main():
    try:
        print(json.dumps(upgrade(engine)))
    except Exception as exc:
        print(json.dumps({"code": 1, "message": "Migration failed; keep writers stopped and inspect schema before retry.",
                          "error_type": type(exc).__name__}))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
