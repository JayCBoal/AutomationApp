"""
Reading job logs from the hosts that ran the jobs, as a WLA asks its agents for them.

A run's log is a file on the host that ran it (engine/log_files.py); the run's record says which
host, and where the file is there. The server never opens a log itself: it asks that host's
agent. AutoApp has no agents, so LocalAgent stands in for one: it reads the host's folder under
the log root on this machine. A real agent, reached over the network, would take its place
behind agent_for() and offer the same three things.

Logs older than the Settings page's "Keep job logs for" are removed by their agents
(remove_old_logs); the run's record keeps when, so its log page can say so.
"""
from datetime import timedelta
from pathlib import Path
from typing import List, Optional

from sqlalchemy.orm import Session

from app.models import JobRun, utcnow
from engine import log_files, settings


class LocalAgent:
    """The agent of one host, standing in: its job logs are a folder on this machine."""

    def __init__(self, host: Optional[str]):
        self.host = host or "unknown"
        self.folder = log_files.host_folder(host)

    def _path(self, log_file: str) -> Optional[Path]:
        """The file, if the name stays inside the host's folder (a record cannot point elsewhere)."""
        path = (self.folder / log_file).resolve()
        return path if path.is_relative_to(self.folder.resolve()) else None

    def read_lines(self, log_file: str) -> Optional[List[str]]:
        """The log's lines, or None if the host has no such file."""
        path = self._path(log_file)
        if path is None or not path.is_file():
            return None
        return path.read_text(encoding="utf-8", errors="replace").splitlines()

    def remove(self, log_file: str) -> None:
        """Removes the log, and its day's folder once that is empty. A log already gone is no problem."""
        path = self._path(log_file)
        if path is None:
            return
        path.unlink(missing_ok=True)
        if path.parent != self.folder and path.parent.is_dir() and not any(path.parent.iterdir()):
            path.parent.rmdir()


def agent_for(host: Optional[str]) -> LocalAgent:
    return LocalAgent(host)


def run_log(run: JobRun) -> List[str]:
    """A run's job log as far as it has been written, from its host. Empty if it has none to give."""
    if not run.LogFile or run.LogRemovedDateTime is not None:
        return []
    return agent_for(run.Host).read_lines(run.LogFile) or []


def log_note(run: JobRun) -> Optional[str]:
    """Why a run shows no log, in words, when it should have one."""
    if run.LogRemovedDateTime is not None:
        return f"This run's log was removed on {run.LogRemovedDateTime:%Y-%m-%d}, as older than the Settings page allows."
    if run.LogFile and agent_for(run.Host).read_lines(run.LogFile) is None:
        return f"Host '{run.Host or 'unknown'}' has no log file for this run (it was looking for {run.LogFile})."
    return None


def remove_old_logs(db: Session) -> int:
    """
    Removes the logs of runs that ended longer ago than the setting allows, and records when.
    Returns how many were removed. Runs still going keep theirs, however old.
    """
    days = settings.current(db, "LogRetentionDays")
    if days == "FOREVER":
        return 0
    cutoff = utcnow() - timedelta(days=int(days))
    old = (db.query(JobRun).filter(JobRun.LogFile.isnot(None), JobRun.LogRemovedDateTime.is_(None),
                                   JobRun.EndedDateTime.isnot(None), JobRun.EndedDateTime < cutoff).all())
    for run in old:
        agent_for(run.Host).remove(run.LogFile)
        run.LogRemovedDateTime = utcnow()
    db.commit()
    return len(old)
