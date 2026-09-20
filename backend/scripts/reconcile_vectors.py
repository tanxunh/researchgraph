"""Run from backend: python -m scripts.reconcile_vectors [--repair] [--ids-jsonl PATH]."""
import argparse
import json
import logging
from contextlib import nullcontext

from app.core.database import SessionLocal
from app.services.indexing.reconciliation import VectorReconciliationService


def main():
    parser = argparse.ArgumentParser(description="Compare current SQL chunks and the configured Chroma collection.")
    parser.add_argument("--repair", action="store_true", help="Delete orphan vectors and publish missing/stale vectors.")
    parser.add_argument("--batch-size", type=int, default=128)
    parser.add_argument("--ids-jsonl", help="Stream every issue ID to this file; stdout samples at most 1000 per kind.")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    output = open(args.ids_jsonl, "w", encoding="utf-8") if args.ids_jsonl else nullcontext(None)
    try:
        with output as stream, SessionLocal() as db:
            emit = (lambda item: stream.write(json.dumps(item) + "\n")) if stream else None
            report = VectorReconciliationService(db, batch_size=args.batch_size).run(args.repair, emit)
            print(json.dumps(report, indent=2))
    except Exception as exc:
        # Do not print connection strings, tokens, or provider response bodies.
        print(json.dumps({"code": 1, "message": "Reconciliation failed; rerun safely after restoring services.",
                          "error_type": type(exc).__name__}))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
