"""
Alerts (docs/WORKFLOWS_PHASE8.md, step 5): Notify writes a message into the outbox, the sender sends it by SMTP to the
test mail server (demo/mail_sink), and a mail server that is down costs nothing. The model is tested in test_alerts_model.py.
"""
import sys
from pathlib import Path

import pytest

from app import mail_sender
from app.alert_outbox import queue, queue_test, facts_for_run, Facts
from app.models import Alert, AlertDelivery, AlertRecipient, JobRun, MailSetting, ReactionEvent, Variable
from test_job_clock import run_alone  # noqa: F401 (fixture)
from test_telemetry_ingest import ROUTE
from test_workflow_clock import run_clocked, timed  # noqa: F401 (fixture)
from test_workflow_reactions import react
from test_workflow_runner import flow, results, sim  # noqa: F401 (fixtures)

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "demo" / "mail_sink"))
import sink  # noqa: E402


@pytest.fixture
def mail(db, tmp_path):
    """A running test mail server, and the mail settings pointing at it. Returns (the folder it keeps messages in, settings)."""
    folder = tmp_path / "mail"
    smtp, web = sink.serve(folder, 0, 0)
    settings = MailSetting(id=1, Host="127.0.0.1", Port=smtp.server_address[1], SenderAddress="autoapp@example.com")
    db.add(settings)
    db.commit()
    yield folder, settings, web
    smtp.shutdown(), web.shutdown()


def an_alert(db, name="Ops", subject="%{Alert.Job} is late", message="Why: %{Alert.Why}\nRun: %{Alert.Link}", to=("a@example.com", "b@example.com")):
    alert = Alert(Name=name, Subject=subject, Message=message)
    for position, address in enumerate(to, start=1):
        alert.recipients.append(AlertRecipient(RecipientOrder=position, Address=address))
    db.add(alert)
    db.commit()
    return alert


def a_run(db, key="J1"):
    run = JobRun(RunID="r-" + key, JobKey=key, SchedulerInstanceID="I1", Status="FAILED")
    db.add(run)
    db.commit()
    return run


def test_a_message_is_copied_into_the_outbox_with_the_runs_facts_filled_in(db):
    alert = an_alert(db)
    delivery = queue(db, alert, facts_for_run(a_run(db), "J1 failed"))
    db.commit()
    assert (delivery.Status, delivery.Attempts, delivery.IsTest) == ("PENDING", 0, False)
    assert delivery.Subject == "J1 is late"
    assert "Why: J1 failed" in delivery.Body and "/ui/log.html?run=r-J1" in delivery.Body
    assert delivery.Recipients == "a@example.com, b@example.com"


def test_a_message_can_use_the_jobs_variables_and_leaves_an_unknown_one_as_written(db, seed):
    job = seed.job("VARJOB", Team="Ops team")
    db.commit()
    alert = an_alert(db, message="Tell ${Team} about %{Alert.Nothing}")
    run = a_run(db, "VARJOB")
    run.Job_MasterObject_id = job.MasterObject_id
    db.commit()
    assert queue(db, alert, facts_for_run(run, "x")).Body == "Tell Ops team about %{Alert.Nothing}"


def test_a_test_message_says_it_is_a_test(db):
    delivery = queue_test(db, an_alert(db))
    assert delivery.IsTest and delivery.Subject.startswith("[Test] ")


def test_the_sender_sends_by_smtp_and_the_test_mail_server_keeps_the_message(db, mail):
    folder, _, _ = mail
    delivery = queue(db, an_alert(db), Facts(job="Nightly", why="it was late", link="x"))
    db.commit()

    assert mail_sender.send_pending(db) == 1

    db.refresh(delivery)
    assert (delivery.Status, delivery.Attempts) == ("SENT", 1) and delivery.SentDateTime is not None
    (subject_to,) = [(m[3], m[2]) for m in sink.read_messages(folder)]
    assert subject_to == ("Nightly is late", "a@example.com, b@example.com")
    assert "Nightly is late" in sink.page(folder)


def test_a_mail_server_that_is_down_is_tried_again_and_then_the_failure_is_shown(db, mail, monkeypatch):
    _, settings, _ = mail
    settings.Port = 1                       # nothing listens there
    delivery = queue(db, an_alert(db), Facts(job="J"))
    db.commit()
    monkeypatch.setattr(mail_sender, "RETRY_AFTER_SECONDS", 0)

    for expected in ("PENDING", "PENDING", "FAILED"):
        mail_sender.send_pending(db)
        db.refresh(delivery)
        assert delivery.Status == expected
    assert delivery.Attempts == 3 and delivery.LastError and delivery.NextAttemptDateTime is None
    assert mail_sender.send_pending(db) == 0         # a failed message is not tried again


def test_a_failed_try_waits_before_the_next(db, mail):
    _, settings, _ = mail
    settings.Port = 1
    delivery = queue(db, an_alert(db), Facts(job="J"))
    db.commit()
    mail_sender.send_pending(db)
    assert mail_sender.send_pending(db) == 0         # not yet due
    db.refresh(delivery)
    assert delivery.Attempts == 1 and delivery.Status == "PENDING"


def test_no_mail_settings_means_failed_with_words_that_say_what_to_do(db, monkeypatch):
    monkeypatch.setattr(mail_sender, "MAX_TRIES", 1)
    delivery = queue(db, an_alert(db), Facts(job="J"))
    db.commit()
    mail_sender.send_pending(db)
    db.refresh(delivery)
    assert delivery.Status == "FAILED" and "mail settings" in delivery.LastError


def test_an_alert_without_recipients_fails_and_says_so(db, mail, monkeypatch):
    monkeypatch.setattr(mail_sender, "MAX_TRIES", 1)
    delivery = queue(db, an_alert(db, to=()), Facts(job="J"))
    db.commit()
    mail_sender.send_pending(db)
    db.refresh(delivery)
    assert delivery.Status == "FAILED" and "no recipients" in delivery.LastError


def test_a_job_failing_in_a_workflow_notifies_and_a_job_succeeding_does_not(sim, flow, run_clocked, db):
    bad, good = sim("BADONE", code=3, fail=True), sim("GOODONE")
    alert = an_alert(db)
    react(db, bad, "FAILED", ("NOTIFY", {"Alert_id": alert.id}), section="ALSO")
    react(db, good, "FAILED", ("NOTIFY", {"Alert_id": alert.id}), section="ALSO")
    flow("NOTIFYFLOW", [("Bad", bad), ("Good", good)])

    code, run, items, log = run_clocked("NOTIFYFLOW")

    (delivery,) = db.query(AlertDelivery).all()
    assert delivery.Status == "PENDING" and delivery.Subject == "Bad is late" and delivery.WorkflowPath == "Bad"
    assert "failed with return code 3" in delivery.Body
    (event,) = [e for e in db.query(ReactionEvent) if e.Action == "NOTIFY"]
    assert event.Result == "TOOK_EFFECT" and "queued" in event.Message


def test_a_time_notify_in_a_workflow_queues_the_message_and_skips_when_a_job_it_waited_for_was_late(sim, flow, run_clocked, db):
    slow, after = sim("SLOWUP", wait=8), sim("AFTERUP")
    alert = an_alert(db, subject="%{Alert.Job} late by %{Alert.Deadline}")
    timed(db, slow, "NOT_ENDED_BY", "AFTER_START", ("MARK_AS_LATE", {}), ("NOTIFY", {"Alert_id": alert.id}), minutes=20)
    timed(db, after, "NOT_STARTED_BY", "AFTER_START", ("NOTIFY", {"Alert_id": alert.id, "SkipIfCauseLate": True}), minutes=30)
    flow("TIMEDNOTIFY", [("Slow", slow), ("After", after, ["Slow"])])

    code, run, items, log = run_clocked("TIMEDNOTIFY")

    (delivery,) = db.query(AlertDelivery).all()
    assert delivery.WorkflowPath == "Slow" and delivery.Subject.startswith("Slow late by ")
    skipped = [e for e in db.query(ReactionEvent) if e.WorkflowPath == "After"]
    assert [(e.Result) for e in skipped] == ["NOT_FIRED"] and "a job it waited for was late" in skipped[0].Message


def test_a_job_on_its_own_notifies_through_its_telemetry_and_the_server_queues_it(sim, run_alone, client, db, tmp_path, spool_records):
    bad = sim("ALONEBAD", code=2, fail=True)
    alert = an_alert(db)
    react(db, bad, "FAILED", ("NOTIFY", {"Alert_id": alert.id}), section="ALSO")

    code, records, _, log = run_alone("ALONEBAD")

    notified = [r for r in records if r["Record"] == "REACTION" and r["Action"] == "NOTIFY"]
    assert len(notified) == 1 and notified[0]["Result"] == "TOOK_EFFECT"
    assert client.post(ROUTE, json={"records": records}).status_code == 201
    assert client.post(ROUTE, json={"records": records}).status_code == 201         # delivered twice: queued once
    db.expire_all()
    (delivery,) = db.query(AlertDelivery).all()
    assert delivery.Subject == "ALONEBAD is late" and delivery.RunID == notified[0]["RunID"]



def test_the_test_mail_server_keeps_a_message_with_a_line_of_one_full_stop_and_refuses_what_it_does_not_know(tmp_path):
    import smtplib
    smtp, web = sink.serve(tmp_path / "m", 0, 0)
    try:
        with smtplib.SMTP("127.0.0.1", smtp.server_address[1]) as client:
            client.sendmail("a@x.com", ["b@x.com"], "Subject: Dots\r\n\r\nbefore\r\n.\r\nafter\r\n")
            assert client.docmd("VRFY b")[0] == 502
        (message,) = sink.read_messages(tmp_path / "m")
        assert message[3] == "Dots" and "." in message[4].splitlines()
    finally:
        smtp.shutdown(), web.shutdown()
