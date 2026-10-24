#!/usr/bin/env python3
"""
Delivers telemetry spool files to AutoApp.

The runner posts its records as it goes (core/spool.py holds the posting code). This module is
the command that sends whatever was left behind, for example because
the API was unreachable while a job ran:

    python3 -m engine.spool_delivery --spool-dir ./spool --api-url http://autoapp:8000

Without an API address the records are loaded straight into the database named
by DATABASE_URL, which is convenient on a development machine.

Loading is safe to repeat: records already in the database are skipped.
"""
import argparse
import os
import sys
from typing import Any, Dict, List

from core.spool import post_records, sweep


def load_into_database(records: List[Dict[str, Any]]) -> None:
    """Loads records without going through the API."""
    from core.database import SessionLocal
    from app.telemetry_ingest import ingest_records

    db = SessionLocal()
    try:
        ingest_records(db, records)
    finally:
        db.close()


def main():
    parser = argparse.ArgumentParser(description="Deliver AutoApp telemetry spool files")
    parser.add_argument("--spool-dir", default="./spool", help="Folder holding the spool files")
    parser.add_argument("--api-url", default=os.getenv("AUTOAPP_API_URL"),
                        help="Address of the AutoApp API (default: the AUTOAPP_API_URL environment variable). "
                             "If neither is set, records are loaded directly into the database.")
    args = parser.parse_args()

    if args.api_url:
        send = lambda records: post_records(args.api_url, records)
    else:
        send = load_into_database

    delivered, failed = sweep(args.spool_dir, send)
    print(f"Delivered {len(delivered)} spool file(s).")
    for spool_file, reason in failed.items():
        print(f"NOT delivered: {spool_file.name}: {reason}", file=sys.stderr)
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
