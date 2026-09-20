"""Run from backend: python -m scripts.source_gc [--repair] [--ids-jsonl PATH]."""
import argparse
import json
from contextlib import nullcontext

from app.core.database import SessionLocal
from app.services.indexing.source_gc import SourceGarbageCollector


def main():
    parser = argparse.ArgumentParser(description="Detect/delete local source blobs unreferenced by every version.")
    parser.add_argument("--repair", action="store_true")
    parser.add_argument("--ids-jsonl")
    args = parser.parse_args()
    output = open(args.ids_jsonl, "w", encoding="utf-8") if args.ids_jsonl else nullcontext(None)
    try:
        with output as stream, SessionLocal() as db:
            emit = (lambda row: stream.write(json.dumps(row) + "\n")) if stream else None
            print(json.dumps(SourceGarbageCollector(db).run(args.repair, emit), indent=2))
    except Exception as exc:
        print(json.dumps({"code": 1, "message": "Source GC failed; restore storage/database and retry.",
                          "error_type": type(exc).__name__}))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
