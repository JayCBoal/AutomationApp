"""
Job logs as files, kept on the host that ran the job, as a WLA's agent keeps them.

Each run's log is <log root>/<host>/<YYYY-MM-DD>/<RunID>.log, the date being the day the run
started (UTC). The run's record keeps its host (JobRuns.Host) and the part after the host's
folder (JobRuns.LogFile); the server reads a log by asking that host's agent for it
(app/log_agent.py). AutoApp has no agents: every host's folder is under one log root on this
machine, and a stand-in agent reads it.

The log root is the AUTOAPP_LOG_ROOT environment variable, or the logs folder beside the
runner. The runner and the server must agree on it.
"""
import os
import re
import socket
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from engine import job_log

DEFAULT_ROOT = Path(__file__).resolve().parents[1] / "logs"


def log_root() -> Path:
    return Path(os.environ.get("AUTOAPP_LOG_ROOT") or DEFAULT_ROOT)


def this_host() -> str:
    return socket.gethostname()


def host_folder(host: Optional[str]) -> Path:
    """The folder a host keeps its job logs in. A run with no host recorded counts as 'unknown'."""
    name = re.sub(r"[^A-Za-z0-9._-]", "_", host or "") or "unknown"
    return log_root() / name


def new_log_file(run_id: str, started: Optional[datetime] = None) -> str:
    """Where a run's log goes, within its host's folder: <YYYY-MM-DD>/<RunID>.log."""
    started = started or datetime.now(timezone.utc)
    return f"{started:%Y-%m-%d}/{run_id}.log"


def start(run_id: str) -> Optional[str]:
    """
    Starts writing the job log to its file on this host, and returns where it is within the host's
    log folder, for the run's record. A log that cannot be written is said so, and the run goes on.
    """
    log_file = new_log_file(run_id)
    try:
        job_log.write_to(host_folder(this_host()) / log_file)
    except OSError as e:
        job_log.warning(f"The job log cannot be kept as a file ({e}); it is only printed.")
        return None
    return log_file
