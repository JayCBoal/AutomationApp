"""
The sender (docs/WORKFLOWS_PHASE8.md, proposals 7 and 8): takes PENDING rows from the alert outbox, sends each by SMTP
with Python's own smtplib, and records SENT, or FAILED with the reason once its tries are used up. It always sends by
SMTP; in development the mail settings point at the test mail server (demo/mail_sink).

It runs inside the server, a pass every few seconds (run_sender_forever). A failed try is put off and tried again, so
a mail server that is down for a minute loses nothing.

The login, if the mail server needs one: the credential named in the mail settings. Its name is the user name and its
secret is the password.
"""
import asyncio
import logging
import smtplib
from datetime import timedelta
from email.message import EmailMessage
from typing import List, Optional

from sqlalchemy.orm import Session

from app.models import AlertDelivery, MailSetting, utcnow

logger = logging.getLogger("autoapp.mail")

MAX_TRIES = 3
RETRY_AFTER_SECONDS = 60
PASS_SECONDS = 5
SMTP_TIMEOUT_SECONDS = 20
BATCH = 20


def build_message(settings: MailSetting, delivery: AlertDelivery) -> EmailMessage:
    message = EmailMessage()
    message["From"] = settings.SenderAddress
    message["To"] = delivery.Recipients
    message["Subject"] = delivery.Subject
    message["X-AutoApp-Alert"] = delivery.AlertName
    message.set_content(delivery.Body)
    return message


def _login(settings: MailSetting) -> Optional[tuple]:
    credential = settings.credential
    if credential is None or not credential.SecretData:
        return None
    return credential.Name, credential.SecretData


def send(settings: MailSetting, delivery: AlertDelivery) -> None:
    """Sends one message. Raises if the mail server cannot be reached or refuses it."""
    to = [a.strip() for a in delivery.Recipients.split(",") if a.strip()]
    if not to:
        raise ValueError("The alert has no recipients. Add an email address to it.")
    with smtplib.SMTP(settings.Host, settings.Port, timeout=SMTP_TIMEOUT_SECONDS) as server:
        if settings.UseTls:
            server.starttls()
        login = _login(settings)
        if login:
            server.login(*login)
        server.send_message(build_message(settings, delivery), from_addr=settings.SenderAddress, to_addrs=to)


def _fail(delivery: AlertDelivery, reason: str) -> None:
    delivery.Attempts += 1
    delivery.LastError = reason
    if delivery.Attempts >= MAX_TRIES:
        delivery.Status, delivery.NextAttemptDateTime = "FAILED", None
    else:
        delivery.NextAttemptDateTime = utcnow() + timedelta(seconds=RETRY_AFTER_SECONDS)


def due(db: Session) -> List[AlertDelivery]:
    now = utcnow()
    rows = db.query(AlertDelivery).filter(AlertDelivery.Status == "PENDING").order_by(AlertDelivery.id).all()
    return [r for r in rows if r.NextAttemptDateTime is None or r.NextAttemptDateTime <= now][:BATCH]


def send_pending(db: Session) -> int:
    """One pass over the outbox. Returns how many messages it tried."""
    rows = due(db)
    settings = db.get(MailSetting, 1) if rows else None
    for delivery in rows:
        if settings is None:
            _fail(delivery, "No mail server is set up. Open the mail settings and give its host and port.")
            continue
        try:
            send(settings, delivery)
        except Exception as problem:
            _fail(delivery, f"{type(problem).__name__}: {problem}")
            logger.warning("Alert '%s' not sent (try %s of %s): %s", delivery.AlertName, delivery.Attempts, MAX_TRIES, problem)
        else:
            delivery.Attempts += 1
            delivery.Status, delivery.SentDateTime, delivery.LastError = "SENT", utcnow(), None
    db.commit()
    return len(rows)


async def run_sender_forever(open_session) -> None:
    """The server's background task. open_session gives a database session; each pass uses a fresh one."""
    while True:
        try:
            await asyncio.to_thread(_one_pass, open_session)
        except Exception as problem:
            logger.warning("The mail sender's pass failed: %s", str(problem).splitlines()[0] if str(problem) else problem)
        await asyncio.sleep(PASS_SECONDS)


def _one_pass(open_session) -> None:
    sessions = open_session()
    db = next(sessions)
    try:
        send_pending(db)
    finally:
        sessions.close()
