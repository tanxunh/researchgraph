"""Run with writers stopped: python -m scripts.migrate_index_job_created_at."""
import json
from app.core.database import engine
from app.migrations.index_job_created_at import upgrade

if __name__ == '__main__':
    try:
        print(json.dumps(upgrade(engine)))
    except Exception as exc:
        print(json.dumps({'status': 'failed', 'error_type': type(exc).__name__,
                          'message': 'Keep writers stopped; inspect schema and rerun migration.'}))
        raise SystemExit(1)
