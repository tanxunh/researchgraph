"""Run existing forward migrations in order, with application writers stopped."""
import json
from app.core.database import engine
from app.migrations.evidence_versions import upgrade as evidence_versions
from app.migrations.async_index_jobs import upgrade as async_jobs
from app.migrations.index_job_created_at import upgrade as job_created_at


def main():
    try:
        for upgrade in (evidence_versions, async_jobs, job_created_at):
            print(json.dumps(upgrade(engine)))
    except Exception as exc:
        print(json.dumps({"status": "failed", "error_type": type(exc).__name__,
                          "message": "Keep writers stopped; inspect schema and rerun migrations."}))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
