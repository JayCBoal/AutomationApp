"""
Reactions (docs/WORKFLOWS.md, "Reactions"; docs/WORKFLOWS_PHASE3.md): what happens after a
job ends, chosen by how it ended.

This module only judges: which entries hold, which decisions take effect, which side effects
fire. Whoever ran the job carries them out: the job runner for a job on its own, the workflow
runner for a job in a workflow.

  - Every entry is judged against what actually happened (the job's own outcome, before any
    Count as), so no entry's actions change what a later one sees.
  - What happens next (NEXT): in order, the first entry that holds decides. An entry whose
    rerun has used up its "at most N times" is passed over, and the next that holds decides
    ("rerun twice, then count as failed"). So is one that cannot be carried out (a Resume
    after a failure whose effect is unknown, docs/WORKFLOWS_PHASE7.md, proposal 13).
  - Also (ALSO): every entry that holds fires its side effects.
"""
import subprocess
import sys
import uuid
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, List, Optional, Tuple

from core import return_codes
from core.clock_rules import KINDS_FOR, TimeRule

AUTOAPP_DIR = Path(__file__).resolve().parents[1]
REACTION_SCHEDULER = "AutoApp reaction"

RESTART, RESUME = "RESTART", "RESUME"
LIMITED = ("RERUN", "RERUN_FROM")
SIDE_EFFECTS = ("START_WORKFLOW",)
NOTIFYING = ("NOTIFY",)         # also under Also, carried out when a job ends; the sender sends it (app/mail_sender.py)
ONLY_IN_WORKFLOWS = ("RERUN_FROM", "SKIP", "SKIP_BRANCH", "KILL_WORKFLOW")
# Carried out in this order when one entry has several
ORDER = ("COUNT_AS_SUCCEEDED", "COUNT_AS_FAILED", "SKIP", "SKIP_BRANCH", "RERUN", "RERUN_FROM", "KILL_WORKFLOW")

WORDS = {"COUNT_AS_SUCCEEDED": "count as succeeded", "COUNT_AS_FAILED": "count as failed", "RERUN": "rerun",
         "RERUN_FROM": "rerun from", "SKIP": "skip", "SKIP_BRANCH": "skip the rest of the branch",
         "KILL_WORKFLOW": "kill the workflow", "START_WORKFLOW": "start workflow", "MARK_AS_LATE": "mark as late",
         "NOTIFY": "notify"}
WHEN_WORDS = {"SUCCESS": "it succeeded", "FAILED": "it failed", "ENDED": "it ended", "RC": "its return code is",
              "NOT_STARTED_BY": "it has not started by its time", "NOT_ENDED_BY": "it has not ended by its time",
              "RUNS_LONGER_THAN": "it runs longer than its limit"}
WHEN_WORDS_OF_END = {"SUCCESS": "the job succeeded", "FAILED": "the job failed"}
TIME_TESTS = tuple(KINDS_FOR)      # judged while the run goes on, by the runner's clock


@dataclass
class Act:
    """One action of an entry, as the runners see it: read once, when the run starts."""
    id: Optional[int]
    action: str
    max_times: int = 1
    wait_seconds: int = 0
    target_item: Optional[str] = None       # a job in the workflow, by its name there
    target_job: Optional[str] = None        # the workflow START_WORKFLOW starts, by its key
    mode: str = RESTART                     # RERUN: from the beginning, or from where the job failed
    alert_id: Optional[int] = None          # NOTIFY: the alert that says who is told and what
    alert_name: Optional[str] = None
    skip_if_cause_late: bool = False        # NOTIFY: do not send when a job this one waited for was late

    def words(self) -> str:
        target = self.target_item or self.target_job or self.alert_name
        return WORDS[self.action] + (f" '{target}'" if target else "") + (
            " from where it failed" if self.action == "RERUN" and self.mode == RESUME else "")

    @property
    def resumes(self) -> bool:
        return self.action == "RERUN" and self.mode == RESUME


@dataclass
class Rule:
    """One entry: when it holds, and what it does."""
    id: Optional[int]
    section: str
    test: str
    codes: Optional[str]
    actions: List[Act]
    time: Optional[TimeRule] = None         # a time When: how its time is given

    def when_words(self) -> str:
        return WHEN_WORDS[self.test] + (f" {self.codes}" if self.test == "RC" else "")


@dataclass
class Verdict:
    decisions: List[Act] = field(default_factory=list)
    side_effects: List[Act] = field(default_factory=list)
    used_up: List[Act] = field(default_factory=list)        # reruns passed over: their limit was reached
    not_fired: List[Tuple[Act, str]] = field(default_factory=list)  # passed over because they cannot be carried out: why
    deciding: Optional[Rule] = None

    def first(self, *actions: str) -> Optional[Act]:
        return next((a for a in self.decisions if a.action in actions), None)


def read_rules(job, item=None) -> List[Rule]:
    """A job's Reactions; for a use in a workflow that overrides them, the use's own."""
    reactions = item.reactions if item is not None and item.ReactionsOverridden else job.reactions
    return [Rule(r.id, r.Section, r.WhenTest, r.WhenReturnCodes, [_act(a) for a in r.actions], _time_rule(r))
            for r in reactions]


def _time_rule(reaction) -> Optional[TimeRule]:
    if reaction.WhenTest not in TIME_TESTS:
        return None
    return TimeRule(reaction.WhenTest, reaction.WhenTimeKind, reaction.WhenClockTime, reaction.WhenMinutes,
                    reaction.WhenPercent, reaction.WhenRunCount)


def _act(action) -> Act:
    return Act(action.id, action.Action, max_times=action.MaxTimes or 1, wait_seconds=action.WaitSeconds or 0,
               target_item=action.target_item.ItemName if action.target_item else None,
               target_job=action.target_job.JobKey if action.target_job else None,
               mode=action.RerunMode or RESTART, alert_id=action.Alert_id,
               alert_name=action.alert.Name if action.alert else None, skip_if_cause_late=bool(action.SkipIfCauseLate))


def holds(rule: Rule, status: str, code: Optional[int]) -> bool:
    """Whether an entry's When holds for a job that ended so. A time When is judged by the clock, never at the end."""
    if rule.test in TIME_TESTS:
        return False
    if rule.test == "ENDED":
        return True
    if rule.test == "SUCCESS":
        return status == "SUCCESS"
    if rule.test == "FAILED":
        return status == "FAILED"
    return return_codes.matches(code, rule.codes)


def judge(rules: List[Rule], status: str, code: Optional[int], times_used: Callable[[Act], int],
          in_workflow: bool, cannot: Optional[Callable[[Act], Optional[str]]] = None) -> Verdict:
    """
    What happens after a job ended with status and code. times_used says how often a rerun already ran.
    cannot says why an action cannot be carried out now (None if it can): a Resume with nothing to
    resume from. Such an entry is passed over as one at its limit is.
    """
    verdict = Verdict()
    for rule in rules:
        if not holds(rule, status, code):
            continue
        verdict.side_effects += [a for a in rule.actions if a.action in SIDE_EFFECTS + NOTIFYING]
        if rule.section != "NEXT" or verdict.deciding:
            continue
        decisions = [a for a in rule.actions
                     if a.action not in SIDE_EFFECTS + NOTIFYING and (in_workflow or a.action not in ONLY_IN_WORKFLOWS)]
        used_up = [a for a in decisions if a.action in LIMITED and times_used(a) >= a.max_times]
        if used_up:
            verdict.used_up += used_up
            continue
        refused = [(a, cannot(a)) for a in decisions if cannot and cannot(a)]
        if refused:
            verdict.not_fired += refused
            continue
        if decisions:
            verdict.decisions = sorted(decisions, key=lambda a: ORDER.index(a.action))
            verdict.deciding = rule
    return verdict


class OwnReactions:
    """
    A job's Reactions to its own end, carried out by the runner that ran it: for a job, or a
    workflow, run on its own. Count as, Rerun this job and Start a workflow apply; the rest
    need a workflow around the job. Kept for the whole run, so "at most N times" counts across
    its attempts.
    """
    def __init__(self, rules: List[Rule], options: dict):
        self.rules, self.options = rules, options
        self.used: Counter = Counter()
        self.rerun: Optional[Act] = None        # set when the job is to run again
        self.run_id: Optional[str] = None       # the run just judged, which a Resume picks up
        self.control_path: Optional[Path] = None    # its control file,
        self.record = None                      # read back when a Resume is judged (core.control_file.ControlRecord),
        self.totals: Tuple[int, int] = (0, 0)   # and the files and bytes it delivered: the next attempt need not wait for the database

    def after(self, status: str, code: Optional[int], record: Callable[[Act, str, str], None],
              resume_problem: Optional[Callable[[], Optional[str]]] = None) -> str:
        """
        Judges how the job ended; returns the status it ends with. record(act, result, message) keeps each.
        resume_problem says why this run cannot be picked up, or None if it can.
        """
        self.rerun = None
        problem = resume_problem() if resume_problem and any(r.resumes for rule in self.rules for r in rule.actions) else None
        cannot = (lambda act: problem if act.resumes else None) if resume_problem else None
        verdict = judge(self.rules, status, code, lambda act: self.used[act.id], in_workflow=False, cannot=cannot)
        for act in verdict.used_up:
            record(act, "LIMIT_REACHED", f"{act.words().capitalize()} has already run {act.max_times} time(s), "
                                         f"its limit, so the next Reaction that holds applies.")
        for act, why in verdict.not_fired:
            record(act, "NOT_FIRED", f"{act.words().capitalize()} was not carried out: {why}")
        counted = status
        for act in verdict.decisions:
            if act.action == "RERUN":
                self.used[act.id] += 1
                self.rerun = act
                wait = f" after {act.wait_seconds} s" if act.wait_seconds else ""
                how = "from where it failed" if act.resumes and resume_problem else "from the beginning"
                record(act, "TOOK_EFFECT", f"Rerunning the job {how}{wait} (rerun {self.used[act.id]} of at most "
                                           f"{act.max_times}), as its Reactions say.")
            else:
                counted = "SUCCESS" if act.action == "COUNT_AS_SUCCEEDED" else "FAILED"
                record(act, "TOOK_EFFECT", f"Counted as {'succeeded' if counted == 'SUCCESS' else 'failed'}, "
                                           f"as its Reactions say ({verdict.deciding.when_words()}).")
        for act in verdict.side_effects:
            if act.action == "NOTIFY":      # the server queues the message when this record reaches it
                record(act, "TOOK_EFFECT", f"Alert '{act.alert_name}' queued: {WHEN_WORDS_OF_END.get(status, 'the job ended')}.")
                continue
            instance = start_workflow(act.target_job, **self.options)
            record(act, "TOOK_EFFECT", f"Started workflow '{act.target_job}', instance {instance}.")
        return counted


def start_workflow(job_key: str, spool_dir: str, api_url: Optional[str] = None, working_root: Optional[str] = None,
                   log_level: Optional[str] = None) -> str:
    """Starts a workflow as a new run of its own, as the Run Job page would, and returns its instance ID."""
    instance = f"REACTION-{uuid.uuid4().hex[:12]}"
    command = [sys.executable, "-m", "engine.runner", "--job-key", job_key, "--instance-id", instance,
               "--scheduler", REACTION_SCHEDULER, "--spool-dir", spool_dir]
    for option, value in (("--api-url", api_url), ("--working-root", working_root), ("--log-level", log_level)):
        if value:
            command += [option, value]
    subprocess.Popen(command, cwd=AUTOAPP_DIR, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     stdin=subprocess.DEVNULL, start_new_session=True)
    return instance
