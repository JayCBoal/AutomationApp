"""
The alert outbox (docs/WORKFLOWS_PHASE8.md, proposals 6 and 7): what Notify does. Notify never sends. It writes the
message into AlertDeliveries as PENDING, and the sender (app/mail_sender.py) sends it later, so no job waits for a mail
server. Everything the message needs is copied into the row as text, so it outlives the alert being edited or deleted.

A message's text may use the values a step can, ${...}, and the run's facts as %{Alert.Job}, %{Alert.Workflow},
%{Alert.Outcome}, %{Alert.Why}, %{Alert.Deadline}, %{Alert.Link}, %{Alert.Time}.
"""
import os
import re
from urllib.parse import urlencode
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from sqlalchemy.orm import Session

from core.models import Alert, AlertDelivery, JobRun, ReactionAction, utcnow

FACT_PATTERN = re.compile(r"%\{Alert\.([A-Za-z]+)\}")
FACT_NAMES = ("Job", "Workflow", "Outcome", "Why", "Deadline", "Link", "Time")
DEFAULT_SERVER_URL = "http://localhost:8000"


@dataclass
class Facts:
    """What a message can say about the run that fired it."""
    job: str = ""
    workflow: str = ""
    outcome: str = ""
    why: str = ""
    deadline: str = ""
    link: str = ""
    run_id: Optional[str] = None
    workflow_path: Optional[str] = None
    job_id: Optional[int] = None
    instance_id: str = ""
    extra: Dict[str, str] = field(default_factory=dict)

    def values(self) -> Dict[str, str]:
        return {"Job": self.job, "Workflow": self.workflow, "Outcome": self.outcome, "Why": self.why,
                "Deadline": self.deadline, "Link": self.link, "Time": utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")}


def run_link(run_id: Optional[str], workflow_key: Optional[str] = None) -> str:
    """
    Where the run's page is: a workflow's own page, or a job's log. AUTOAPP_PUBLIC_URL says how the people told
    reach the server.
    """
    base = os.getenv("AUTOAPP_PUBLIC_URL", DEFAULT_SERVER_URL).rstrip("/")
    if not run_id:
        return base
    if workflow_key:
        return f"{base}/ui/workflow.html?{urlencode({'key': workflow_key, 'run': run_id})}"
    return f"{base}/ui/log.html?{urlencode({'run': run_id})}"


def facts_for_run(run: JobRun, why: str, outcome: Optional[str] = None, workflow_path: Optional[str] = None) -> Facts:
    """The facts of a run that has a JobRun record: a job on its own, or a workflow."""
    workflow_key = run.JobKey if run.JobType == "WORKFLOW" else None
    return Facts(job=run.JobKey, outcome=outcome or run.Status, why=why, link=run_link(run.RunID, workflow_key),
                 run_id=run.RunID, workflow_path=workflow_path, job_id=run.Job_MasterObject_id, instance_id=run.SchedulerInstanceID)


def _fill_in(db: Session, text: str, facts: Facts) -> str:
    """The run's facts first, then the ${...} values of the job; a ${...} that cannot be resolved is left as written."""
    values = facts.values()
    text = FACT_PATTERN.sub(lambda m: values.get(m.group(1), m.group(0)), text)
    if "${" not in text or facts.job_id is None:
        return text
    from engine.scope_engine import ScopeResolutionEngine
    try:
        engine = ScopeResolutionEngine(db=db, job_id=facts.job_id, instance_id=facts.instance_id)
        engine.build_context()
        return engine.interpolate(text)
    except Exception:
        return text


def addresses(alert: Alert) -> List[str]:
    return [r.Address for r in alert.recipients]


def queue(db: Session, alert: Alert, facts: Facts, is_test: bool = False) -> AlertDelivery:
    """Adds the alert's message to the outbox as PENDING. The caller commits."""
    delivery = AlertDelivery(
        Alert_id=alert.id, AlertName=alert.Name, RunID=facts.run_id, WorkflowPath=facts.workflow_path,
        Recipients=", ".join(addresses(alert)), Subject=_fill_in(db, alert.Subject, facts)[:255],
        Body=_fill_in(db, alert.Message, facts), IsTest=is_test, Status="PENDING")
    db.add(delivery)
    return delivery


def queue_test(db: Session, alert: Alert) -> AlertDelivery:
    """Send a test: the alert's own text, with example run facts, marked as a test so nobody takes it for a real one."""
    facts = Facts(job="EXAMPLE_JOB", workflow="EXAMPLE_WORKFLOW", outcome="LATE", why="This is a test message",
                  deadline="03:00", link=run_link(None))
    delivery = queue(db, alert, facts, is_test=True)
    delivery.Subject = ("[Test] " + delivery.Subject)[:255]
    return delivery


def queue_for_action(db: Session, action_id: Optional[int], run: JobRun, why: str) -> Optional[AlertDelivery]:
    """A Notify reported by a job run on its own (it arrives with the job's telemetry): queues the action's alert."""
    action = db.get(ReactionAction, action_id) if action_id else None
    if action is None or action.alert is None:
        return None
    return queue(db, action.alert, facts_for_run(run, why))
