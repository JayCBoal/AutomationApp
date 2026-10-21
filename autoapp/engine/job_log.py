"""
The job log: what the runner prints, and the scheduler captures, while a job runs.

Four levels, chosen with the runner's --log-level or, for one step, with a
LogLevel step parameter:

    DEBUG     everything below, plus internal detail for troubleshooting
    DETAIL    (default) each step's parameters as written and as resolved,
              and every action it took, such as each file copied
    SUMMARY   one line per step saying what it did, plus warnings
    SILENT    errors only

Errors go to stderr and everything else to stdout. Values of variables marked
secret are replaced with ******** wherever they would appear.

Every line written also goes to the run's log file (write_to), masked the same way:
the file is kept on the host that ran the job, and the server reads it from there
(engine/log_files.py).
"""
import logging
import sys
from pathlib import Path
from contextlib import contextmanager
from typing import Iterable, Optional

SUMMARY = 25        # between logging.INFO (20) and logging.WARNING (30)
LEVELS = {"DEBUG": logging.DEBUG, "DETAIL": logging.INFO, "SUMMARY": SUMMARY, "SILENT": logging.ERROR}
DEFAULT_LEVEL = "DETAIL"
MASK = "********"

_logger = logging.getLogger("AutoApp.Job")
_logger.propagate = False
_LABELS = {logging.DEBUG: "DEBUG", logging.INFO: "INFO", SUMMARY: "INFO", logging.WARNING: "WARN", logging.ERROR: "ERROR"}


def level_number(name: Optional[str]) -> int:
    """Converts a level name to its number. Raises ValueError for an unknown name."""
    key = (name or DEFAULT_LEVEL).strip().upper()
    if key not in LEVELS:
        raise ValueError(f"Unknown log level '{name}'. Use one of: {', '.join(LEVELS)}.")
    return LEVELS[key]


class _Formatter(logging.Formatter):
    def format(self, record):
        label = _LABELS.get(record.levelno, record.levelname)
        return f"{self.formatTime(record, '%Y-%m-%d %H:%M:%S')} [{label}] {record.getMessage()}"


class _RedactSecrets(logging.Filter):
    def __init__(self, secrets: Iterable[str]):
        super().__init__()
        # Longest first, so a secret that contains another is masked whole
        self.secrets = sorted({s for s in secrets if s}, key=len, reverse=True)

    def filter(self, record):
        message = record.getMessage()
        for secret in self.secrets:
            message = message.replace(secret, MASK)
        record.msg, record.args = message, ()
        return True


_redact = _RedactSecrets(())


def configure(level: Optional[str] = None, secrets: Iterable[str] = ()) -> None:
    """Sets up the job log for this process. Call once, before the job starts."""
    for handler in list(_logger.handlers):
        _logger.removeHandler(handler)
        handler.close()

    global _redact
    _redact = _RedactSecrets(secrets)
    out = logging.StreamHandler(sys.stdout)
    out.addFilter(lambda record: record.levelno < logging.ERROR)
    err = logging.StreamHandler(sys.stderr)
    err.setLevel(logging.ERROR)
    for handler in (out, err):
        _add(handler)
    _logger.setLevel(level_number(level))


def mask(text: str) -> str:
    """The text with the values of secret variables replaced by ********, as in the log."""
    for secret in _redact.secrets:
        text = text.replace(secret, MASK)
    return text


def write_to(path: Path) -> None:
    """From now on, also writes every line to this file, masked as on screen. Each line is written as it comes."""
    path.parent.mkdir(parents=True, exist_ok=True)
    _add(logging.FileHandler(path, encoding="utf-8"))


def _add(handler: logging.Handler) -> None:
    handler.setFormatter(_Formatter())
    handler.addFilter(_redact)
    _logger.addHandler(handler)


@contextmanager
def level_for_step(level: Optional[str]):
    """Applies a step's own LogLevel while it runs, then restores the job's level."""
    if not level:
        yield
        return
    previous = _logger.level
    _logger.setLevel(level_number(level))
    try:
        yield
    finally:
        _logger.setLevel(previous)


def debug(message: str) -> None:
    _logger.debug(message)


def detail(message: str) -> None:
    _logger.info(message)


def summary(message: str) -> None:
    _logger.log(SUMMARY, message)


def warning(message: str) -> None:
    _logger.warning(message)


def error(message: str) -> None:
    _logger.error(message)
