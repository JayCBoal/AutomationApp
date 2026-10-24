#!/usr/bin/env python3
"""
Delivers telemetry spool files to AutoApp.

The runner posts its records as it goes. This module holds the posting code it
uses, and a command that sends whatever was left behind, for example because
the API was unreachable while a job ran:

    python3 -m engine.spool_delivery --spool-dir ./spool --api-url http://autoapp:8000

Without an API address the records are loaded straight into the database named
by DATABASE_URL, which is convenient on a development machine.

Loading is safe to repeat: records already in the database are skipped.
"""
import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable, Dict, List, Tuple

RECORDS_ROUTE = "/api/v1/telemetry/records"
DELIVERED_FOLDER = "delivered"


class DeliveryError(Exception):
    """The records did not reach AutoApp, or were refused."""


def post_records(api_url: str, records: List[Dict[str, Any]], timeout: float = 10) -> Dict[str, Any]:
    """Posts records to the API. Raises DeliveryError on any failure."""
    request = urllib.request.Request(
        api_url.rstrip("/") + RECORDS_ROUTE,
        data=json.dumps({"records": records}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        raise DeliveryError(f"AutoApp refused the records (HTTP {e.code}): {body}") from e
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise DeliveryError(f"Could not reach AutoApp at {api_url}: {e}") from e


def read_spool_file(path: Path) -> List[Dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def mark_delivered(path: Path) -> Path:
    """Moves a spool file into the 'delivered' subfolder, so it is kept but not sent again."""
    target_dir = path.parent / DELIVERED_FOLDER
    target_dir.mkdir(exist_ok=True)
    target = target_dir / path.name
    os.replace(path, target)
    return target


def sweep(spool_dir: str, send: Callable[[List[Dict[str, Any]]], Any]) -> Tuple[List[Path], Dict[Path, str]]:
    """
    Sends every completed spool file in the folder, oldest first.
    Returns the files delivered and, for each file that was not, the reason.
    Files still being written (.jsonl.tmp) are left alone.
    """
    delivered: List[Path] = []
    failed: Dict[Path, str] = {}
    spool_files = sorted(Path(spool_dir).glob("*.jsonl"), key=lambda p: (p.stat().st_mtime, p.name))
    for spool_file in spool_files:
        try:
            send(read_spool_file(spool_file))
        except Exception as e:
            failed[spool_file] = str(e)
            continue
        delivered.append(mark_delivered(spool_file))
    return delivered, failed


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
