"""
The control file: what a job's run keeps, as it goes, so a later attempt can pick up where it stopped
(docs/WORKFLOWS_PHASE7.md, proposal 1).

It is a small file on the host that ran the job, beside the job log (<RunID>.control next to <RunID>.log),
removed with it. Nothing sends it anywhere, and the runner never writes the database. It is not the
operations spool: the spool is an audit trail that is delivered in the background, and nothing a
workflow acts on may depend on it.

One JSON record per line, written and flushed as each thing happens, so a killed runner leaves it right.
Each record names the step it is about by its place in the job: the step number, and the pass number of
each loop around it ("3.1|2.1" is step 3.1 in pass 2 of a loop and pass 1 of the loop inside). Records:

    job          the run's anchors: when it started, its business date
    values       the ${...} values the job used, by key; a secret's by name only (engine/run_values.py)
    resumed      this attempt picked up another run's record; that run's records follow, copied
    begin        a step started
    end          a step ended; done says whether the job went on past it, with its outputs
    failed       a step failed, and what it knew about its effect (engine/step_catalog.py), with its number and title
    branch       the branch an If took
    files        the files a For Each File matched, as matched then
    pass_begin   a loop's pass started (with the file it is on, for a For Each File)
    pass_end     a loop's pass ended
    file_begin   a file step started on a file
    file_end     a file step finished with a file

A later record about the same thing replaces an earlier one. A secret's value never goes in: only the
step outputs a later step could read, with the job's secret values masked.
"""
import json
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from engine import job_log

CONTROL_SUFFIX = ".control"


def control_name(log_file: str) -> str:
    """The control file's name within the host's folder, from the job log's: <date>/<RunID>.control."""
    stem = log_file[:-len(".log")] if log_file.endswith(".log") else log_file
    return stem + CONTROL_SUFFIX


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _masked(value: Any) -> Any:
    """The value with the job's secrets masked, whatever it is made of."""
    if isinstance(value, str):
        return job_log.mask(value)
    if isinstance(value, dict):
        return {name: _masked(item) for name, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_masked(item) for item in value]
    return value


class NullControl:
    """Stands in where a run has no control file to write (its log could not be kept as a file)."""
    path = None

    def write(self, event: str, **fields: Any) -> None:
        pass

    def close(self) -> None:
        pass


class ControlWriter:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self._file = open(path, "a", encoding="utf-8", buffering=1)      # each line is on disk as it is written

    def write(self, event: str, **fields: Any) -> None:
        record = {"e": event, "at": _now(), **{name: _masked(value) for name, value in fields.items()}}
        self._file.write(json.dumps(record, default=str) + "\n")
        self._file.flush()

    def copy_of(self, records: Iterable[Dict[str, Any]]) -> None:
        """Writes another attempt's records as they were, so this file alone holds the whole story."""
        for record in records:
            self._file.write(json.dumps(record, default=str) + "\n")
        self._file.flush()

    def close(self) -> None:
        self._file.close()


class ControlRecord:
    """A control file read back: what an earlier attempt finished, and where it stopped."""

    def __init__(self, records: List[Dict[str, Any]], path: Optional[Path] = None):
        self.records = records
        self.path = path                                   # the file it was read from, so a successful pick-up can remove it
        self._last: Dict[tuple, Dict[str, Any]] = {}       # the latest record about each thing
        self._files: Dict[str, Dict[str, Dict[str, Any]]] = {}
        for record in records:
            self._learn(record)

    @classmethod
    def read(cls, path: Path) -> "ControlRecord":
        """Reads the file. A last line cut short by a killed runner is passed over."""
        records = []
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                records.append(json.loads(line))
            except ValueError:
                continue
        return cls(records, path)

    def _learn(self, record: Dict[str, Any]) -> None:
        event, key = record.get("e"), record.get("key")
        if event in ("begin", "end", "failed"):
            self._last[("step", key)] = record
        elif event in ("branch", "files"):
            self._last[(event, key)] = record
        elif event in ("pass_begin", "pass_end"):
            self._last[("pass", key, record.get("n"))] = record
        elif event in ("file_begin", "file_end"):
            self._files.setdefault(key, {})[record["src"]] = record
        elif event in ("job", "values"):
            self._last[(event,)] = record

    # ---------- The run ----------

    @property
    def job(self) -> Dict[str, Any]:
        return self._last.get(("job",), {})

    @property
    def values(self) -> Dict[str, Dict[str, Any]]:
        """The ${...} values the latest attempt used, as {key: {"value": text} or {"secret": true}}."""
        return self._last.get(("values",), {}).get("values", {})

    @property
    def business_date(self) -> Optional[date]:
        text = self.job.get("business_date")
        return date.fromisoformat(text) if text else None

    @property
    def started(self) -> Optional[datetime]:
        text = self.job.get("started")
        return datetime.fromisoformat(text) if text else None

    def ended_steps(self) -> List[Dict[str, Any]]:
        """Every step that ended with the job going on past it, in the order they ended, for their outputs."""
        return [r for r in self.records if r.get("e") == "end" and r.get("done")
                and self._last.get(("step", r["key"])) is r]

    # ---------- Steps ----------

    def finished(self, key: str) -> Optional[Dict[str, Any]]:
        """The step's end record, if it ended with the job going on and has not been started again since."""
        last = self._last.get(("step", key))
        return last if last and last["e"] == "end" and last.get("done") else None

    def failure(self, key: str) -> Optional[Dict[str, Any]]:
        """What the step knew when it failed, if its latest record is a failure."""
        last = self._last.get(("step", key))
        return last if last and last["e"] == "failed" else None

    def open_failure(self) -> Optional[Dict[str, Any]]:
        """The failure the attempt stopped on: its latest step failure that no later record of that step replaced."""
        for record in reversed(self.records):
            if record.get("e") == "failed" and self._last.get(("step", record["key"])) is record:
                return record
        return None

    def branch(self, key: str) -> Optional[str]:
        record = self._last.get(("branch", key))
        return record["branch"] if record else None

    def files(self, key: str) -> Optional[List[str]]:
        record = self._last.get(("files", key))
        return record["files"] if record else None

    # ---------- Loops ----------

    def passes_ended(self, key: str) -> int:
        """How many passes of the loop ended, counting from the first."""
        ended = 0
        while self._last.get(("pass", key, ended + 1), {}).get("e") == "pass_end":
            ended += 1
        return ended

    def open_pass(self, key: str) -> Optional[Dict[str, Any]]:
        """The pass that had started when the attempt stopped, if one had."""
        record = self._last.get(("pass", key, self.passes_ended(key) + 1))
        return record if record and record["e"] == "pass_begin" else None

    # ---------- Files of a file step ----------

    def file_records(self, key: str) -> Dict[str, Dict[str, Any]]:
        """The latest record for each source file the step handled, by source path."""
        return self._files.get(key, {})


class Journal:
    """
    A file step's view of the control file: it notes each file as it begins and ends, and, when the run
    resumes, learns what the earlier attempt did with each (engine/handlers).
    """

    def __init__(self, writer, before: Optional[ControlRecord], key: str):
        self.writer, self.key = writer, key
        self._before = before.file_records(key) if before else {}

    def previous(self, source: str) -> Optional[Dict[str, Any]]:
        """What the earlier attempt noted about this source file: a file_begin or a file_end record."""
        return self._before.get(source)

    def finished_earlier(self) -> List[Dict[str, Any]]:
        """The files the earlier attempt finished, whether or not they are still at their source."""
        return [r for r in self._before.values() if r["e"] == "file_end"]

    def unfinished_earlier(self) -> List[Dict[str, Any]]:
        """The files the earlier attempt had begun and not finished: it stopped in the middle of them."""
        return [r for r in self._before.values() if r["e"] == "file_begin"]

    def begin(self, source: str, dest: Optional[str], size: Optional[int], checksum: Optional[str] = None) -> None:
        self.writer.write("file_begin", key=self.key, src=source, dest=dest, size=size, checksum=checksum)

    def end(self, source: str, dest: Optional[str], size: Optional[int], checksum: Optional[str] = None) -> None:
        self.writer.write("file_end", key=self.key, src=source, dest=dest, size=size, checksum=checksum)


class NullJournal(Journal):
    """For a step with no control file behind it: remembers nothing and notes nothing."""

    def __init__(self):
        self.writer, self.key, self._before = NullControl(), "", {}

