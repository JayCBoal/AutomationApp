"""
Alerts, the messages they send, and the mail settings, as the API reads and saves them (docs/WORKFLOWS_PHASE8.md,
proposals 6 to 8). The Alerts page and the Alert deliveries page call this through app/routers/alerts.py.

Rules, checked on saving:
  - An alert has a name (up to 100 characters, not used by another), a subject, a message, and 1 to 50 recipients,
    each an email address. The subject and message may use ${...} values and %{Alert.Job}, %{Alert.Workflow},
    %{Alert.Outcome}, %{Alert.Why}, %{Alert.Deadline}, %{Alert.Link} and %{Alert.Time}.
  - An alert that a Reaction names cannot be deleted: the page says which.
  - Mail settings are one row: the host, the port, the sender's address, whether to use TLS, and the credential that
    holds the login (its name is the user, its secret the password).
"""
import json
import re
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.alert_outbox import FACT_NAMES, FACT_PATTERN, addresses
from app.job_store import JobStoreError
from core.models import Alert, AlertDelivery, AlertRecipient, Audit, Credential, Job, MailSetting, ReactionAction, \
    WorkflowItem, utcnow

EDITOR_NAME = "web interface"
MAX_RECIPIENTS = 50
ADDRESS_PATTERN = re.compile(r"^[^@\s,;]+@[^@\s,;]+\.[^@\s,;]+$")
MAX_DELIVERIES = 500


# ---------- Alerts ----------

def find(db: Session, name: str) -> Alert:
    alert = db.query(Alert).filter(Alert.Name == name).first()
    if alert is None:
        raise JobStoreError(f"There is no alert called '{name}'.", 404)
    return alert


def used_by(db: Session, alert: Alert) -> List[str]:
    """Whose Reactions name the alert, in words: "'FINANCE_DAILY'" or "'Load' in 'FINANCE_DAILY'"."""
    found = []
    for action in db.query(ReactionAction).filter(ReactionAction.Alert_id == alert.id):
        reaction = action.reaction
        if reaction.Job_MasterObject_id:
            found.append(repr(db.get(Job, reaction.Job_MasterObject_id).JobKey))
        else:
            item = db.get(WorkflowItem, reaction.Item_id)
            found.append(f"'{item.ItemName}' in '{item.workflow.JobKey}'")
    return sorted(set(found))


def describe(db: Session, alert: Alert) -> Dict[str, Any]:
    return {"name": alert.Name, "description": alert.Description, "subject": alert.Subject, "message": alert.Message,
            "recipients": addresses(alert), "used_by": used_by(db, alert)}


def search(db: Session) -> List[Dict[str, Any]]:
    return [describe(db, a) for a in db.query(Alert).order_by(Alert.Name)]


def create(db: Session, payload: Dict[str, Any]) -> Alert:
    values = _checked(db, payload, None)
    alert = Alert(Name=values["name"])
    _fill(alert, values)
    db.add(alert)
    _audit(db, "ALERT_CREATED", values["name"], [f"Added the alert '{values['name']}'."])
    db.commit()
    return alert


def update(db: Session, name: str, payload: Dict[str, Any]) -> Alert:
    alert = find(db, name)
    values = _checked(db, {**describe(db, alert), **payload}, alert)
    changes = _changes(alert, values)
    alert.Name = values["name"]
    _fill(alert, values)
    if changes:
        _audit(db, "ALERT_CHANGED", values["name"], changes)
    db.commit()
    return alert


def delete(db: Session, name: str) -> None:
    alert = find(db, name)
    users = used_by(db, alert)
    if users:
        raise JobStoreError(f"The alert '{name}' is named by {', '.join(users)}. Change those Reactions first.", 409)
    db.delete(alert)
    _audit(db, "ALERT_DELETED", name, [f"Deleted the alert '{name}'."])
    db.commit()


def _checked(db: Session, payload: Dict[str, Any], current: Optional[Alert]) -> Dict[str, Any]:
    """The alert's values as saved, or a JobStoreError saying what is wrong."""
    name = (payload.get("name") or "").strip()
    subject = (payload.get("subject") or "").strip()
    message = (payload.get("message") or "").strip()
    if not name or len(name) > 100:
        raise JobStoreError("Give the alert a name of 1 to 100 characters.")
    other = db.query(Alert).filter(Alert.Name == name).first()
    if other is not None and other is not current:
        raise JobStoreError(f"There is already an alert called '{name}'.", 409)
    if not subject or len(subject) > 255:
        raise JobStoreError("Give the alert a subject of 1 to 255 characters.")
    if not message:
        raise JobStoreError("Give the alert a message.")
    for text in (subject, message):
        _check_facts(text)
    return {"name": name, "description": (payload.get("description") or "").strip() or None, "subject": subject,
            "message": message, "recipients": _checked_recipients(payload.get("recipients"))}


def _check_facts(text: str) -> None:
    for fact in FACT_PATTERN.findall(text):
        if fact not in FACT_NAMES:
            raise JobStoreError(f"'%{{Alert.{fact}}}' is not something an alert can say. "
                                f"Use one of: {', '.join('%{Alert.' + n + '}' for n in FACT_NAMES)}.")


def _checked_recipients(given: Any) -> List[str]:
    if isinstance(given, str):
        given = re.split(r"[,;\s]+", given)
    wanted = []
    for address in (a.strip() for a in (given or [])):
        if address and address not in wanted:
            wanted.append(address)
    if not wanted:
        raise JobStoreError("Give the alert at least one recipient's email address.")
    if len(wanted) > MAX_RECIPIENTS:
        raise JobStoreError(f"An alert has at most {MAX_RECIPIENTS} recipients.")
    for address in wanted:
        if not ADDRESS_PATTERN.match(address) or len(address) > 255:
            raise JobStoreError(f"'{address}' is not an email address. Write it as name@example.com.")
    return wanted


def _fill(alert: Alert, values: Dict[str, Any]) -> None:
    alert.Description, alert.Subject, alert.Message = values["description"], values["subject"], values["message"]
    if addresses(alert) != values["recipients"]:
        alert.recipients.clear()
        alert.recipients.extend(AlertRecipient(RecipientOrder=n, Address=a)
                                for n, a in enumerate(values["recipients"], start=1))


def _changes(alert: Alert, values: Dict[str, Any]) -> List[str]:
    before = {"name": alert.Name, "description": alert.Description, "subject": alert.Subject,
              "message": alert.Message, "recipients": addresses(alert)}
    return [f"Changed the {field} of '{alert.Name}'." for field in before if before[field] != values[field]]


def _audit(db: Session, action: str, name: str, changes: List[str]) -> None:
    db.add(Audit(MasterObject_id=None, Action=action, PerformedBy=EDITOR_NAME,
                 Details=json.dumps({"alert": name, "changes": changes})))


# ---------- The messages ----------

def deliveries(db: Session, status: Optional[str], alert: Optional[str], limit: int) -> List[Dict[str, Any]]:
    """Alert deliveries, newest first, optionally of one status (PENDING, SENT, FAILED) or one alert."""
    query = db.query(AlertDelivery)
    if status:
        query = query.filter(AlertDelivery.Status == status.upper())
    if alert:
        query = query.filter(AlertDelivery.AlertName == alert)
    rows = query.order_by(AlertDelivery.id.desc()).limit(min(limit, MAX_DELIVERIES))
    return [delivery_out(d) for d in rows]


def delivery_out(d: AlertDelivery) -> Dict[str, Any]:
    return {"id": d.id, "alert": d.AlertName, "run_id": d.RunID, "workflow_path": d.WorkflowPath,
            "recipients": d.Recipients, "subject": d.Subject, "body": d.Body, "is_test": bool(d.IsTest),
            "status": d.Status, "attempts": d.Attempts, "error": d.LastError, "created": d.CreatedDateTime,
            "sent": d.SentDateTime}


# ---------- Mail settings ----------

def mail_settings(db: Session) -> Dict[str, Any]:
    row = db.get(MailSetting, 1)
    if row is None:
        return {"configured": False, "host": "", "port": 25, "sender": "", "use_tls": False, "credential": None}
    return {"configured": True, "host": row.Host, "port": row.Port, "sender": row.SenderAddress,
            "use_tls": bool(row.UseTls), "credential": row.credential.Name if row.credential else None}


def save_mail_settings(db: Session, payload: Dict[str, Any]) -> Dict[str, Any]:
    host = (payload.get("host") or "").strip()
    sender = (payload.get("sender") or "").strip()
    port = payload.get("port")
    if not host:
        raise JobStoreError("Give the mail server's host name.")
    if not isinstance(port, int) or not 1 <= port <= 65535:
        raise JobStoreError("The mail server's port is a number from 1 to 65535.")
    if not ADDRESS_PATTERN.match(sender):
        raise JobStoreError("Give the address mail is sent from, like autoapp@example.com.")
    credential = _credential(db, payload.get("credential"))
    row = db.get(MailSetting, 1) or MailSetting(id=1)
    row.Host, row.Port, row.SenderAddress, row.UseTls = host, port, sender, bool(payload.get("use_tls"))
    row.Credential_MasterObject_id = credential.MasterObject_id if credential else None
    db.add(row)
    _audit(db, "MAIL_SETTINGS_CHANGED", "mail settings", [f"Mail is sent through {host}:{port}, from {sender}."])
    db.commit()
    return mail_settings(db)


def _credential(db: Session, name: Optional[str]) -> Optional[Credential]:
    if not (name or "").strip():
        return None
    found = db.query(Credential).filter(Credential.Name == name.strip()).first()
    if found is None:
        raise JobStoreError(f"There is no credential called '{name}'. Add it first, or leave the login empty.")
    return found
