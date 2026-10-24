"""
Alerts, their messages and the mail settings over HTTP, and the time Whens, Mark as late and Notify saved with a
job's Reactions (docs/WORKFLOWS_PHASE8.md, step 6). Sending itself is tested in test_alerts.py.
"""
import pytest

from core.models import Alert, AlertDelivery, Audit
from test_reactions_api import a_workflow, act, reaction, steps_job, use

ALERTS = "/api/v1/alerts"
JOBS = "/api/v1/jobs"


def alert_body(name="Ops", **more):
    return {"name": name, "subject": "%{Alert.Job} is late", "message": "Why: %{Alert.Why}\n%{Alert.Link}",
            "recipients": ["ops@example.com", "boss@example.com"], **more}


def timed(when, kind, *actions, **settings):
    return {**reaction(when, *actions, section="ALSO"), "time_kind": kind, **settings}


# ---------- Alerts ----------

def test_an_alert_is_added_read_back_changed_and_deleted(client, db):
    assert client.post(ALERTS, json=alert_body(description="Who hears about lateness")).status_code == 201
    one = client.get(f"{ALERTS}/Ops").json()
    assert one["recipients"] == ["ops@example.com", "boss@example.com"] and one["used_by"] == []
    assert one["description"] == "Who hears about lateness"

    changed = client.put(f"{ALERTS}/Ops", json={"recipients": "one@example.com; two@example.com"})
    assert changed.status_code == 200 and changed.json()["recipients"] == ["one@example.com", "two@example.com"]
    assert changed.json()["subject"] == "%{Alert.Job} is late"          # left out, so unchanged

    assert client.delete(f"{ALERTS}/Ops").status_code == 204
    assert client.get(f"{ALERTS}/Ops").status_code == 404
    db.expire_all()
    actions = [a.Action for a in db.query(Audit).order_by(Audit.id)]
    assert actions == ["ALERT_CREATED", "ALERT_CHANGED", "ALERT_DELETED"]


@pytest.mark.parametrize("change, words", [
    ({"name": ""}, "name"),
    ({"subject": ""}, "subject"),
    ({"message": "  "}, "message"),
    ({"recipients": []}, "at least one recipient"),
    ({"recipients": ["not an address"]}, "is not an email address"),
    ({"message": "Hello %{Alert.Colour}"}, "not something an alert can say"),
])
def test_an_alert_that_cannot_work_is_refused_and_says_why(client, change, words):
    response = client.post(ALERTS, json={**alert_body(), **change})
    assert response.status_code == 422 and words in response.json()["detail"]


def test_two_alerts_cannot_share_a_name(client):
    assert client.post(ALERTS, json=alert_body()).status_code == 201
    assert client.post(ALERTS, json=alert_body()).status_code == 409


def test_send_a_test_queues_a_message_marked_as_a_test(client, db):
    client.post(ALERTS, json=alert_body())
    answer = client.post(f"{ALERTS}/Ops/test")
    assert answer.status_code == 200 and answer.json()["is_test"] and answer.json()["status"] == "PENDING"
    assert answer.json()["subject"].startswith("[Test] EXAMPLE_JOB is late")
    listed = client.get("/api/v1/alert-deliveries", params={"status": "pending", "alert": "Ops"}).json()
    assert [d["id"] for d in listed] == [answer.json()["id"]]
    assert client.post(f"{ALERTS}/Nobody/test").status_code == 404


def test_deliveries_come_newest_first_and_survive_the_alert_being_deleted(client, db):
    client.post(ALERTS, json=alert_body())
    first = client.post(f"{ALERTS}/Ops/test").json()["id"]
    second = client.post(f"{ALERTS}/Ops/test").json()["id"]
    assert client.delete(f"{ALERTS}/Ops").status_code == 204
    listed = client.get("/api/v1/alert-deliveries").json()
    assert [d["id"] for d in listed] == [second, first] and listed[0]["alert"] == "Ops"
    assert db.query(AlertDelivery).count() == 2


# ---------- Mail settings ----------

def test_mail_settings_start_empty_and_are_saved(client, db):
    assert client.get("/api/v1/mail-settings").json()["configured"] is False
    saved = client.put("/api/v1/mail-settings", json={"host": "localhost", "port": 8025,
                                                       "sender": "autoapp@example.com", "use_tls": False})
    assert saved.status_code == 200 and saved.json()["configured"] and saved.json()["port"] == 8025
    assert client.get("/api/v1/mail-settings").json()["host"] == "localhost"


@pytest.mark.parametrize("change, words", [
    ({"host": ""}, "host name"), ({"port": 0}, "port"), ({"sender": "nobody"}, "address mail is sent from"),
    ({"credential": "NO-SUCH"}, "no credential called"),
])
def test_mail_settings_that_cannot_work_are_refused(client, change, words):
    body = {"host": "localhost", "port": 25, "sender": "autoapp@example.com", **change}
    response = client.put("/api/v1/mail-settings", json=body)
    assert response.status_code == 422 and words in response.json()["detail"]


# ---------- Time Whens, Mark as late and Notify in a job's Reactions ----------

def test_time_whens_notify_and_mark_as_late_are_saved_and_read_back(client, db):
    client.post(ALERTS, json=alert_body())
    reactions = [timed("RUNS_LONGER_THAN", "HISTORY", act("MARK_AS_LATE"), act("NOTIFY", alert="Ops"), percent=50),
                 timed("NOT_ENDED_BY", "CLOCK", act("NOTIFY", alert="Ops"), clock_time="03:00"),
                 reaction("FAILED", act("NOTIFY", alert="Ops", skip_if_cause_late=True), section="ALSO")]
    assert client.post(JOBS, json=steps_job("SLOWISH", reactions)).status_code == 201
    saved = client.get(f"{JOBS}/SLOWISH").json()["reactions"]
    longer, not_ended, failed = saved
    assert (longer["when"], longer["time_kind"], longer["percent"], longer["run_count"]) == \
        ("RUNS_LONGER_THAN", "HISTORY", 50, 10)             # 10 earlier runs unless said
    assert [a["action"] for a in longer["actions"]] == ["MARK_AS_LATE", "NOTIFY"]
    assert (not_ended["time_kind"], not_ended["clock_time"], not_ended["minutes"]) == ("CLOCK", "03:00", None)
    assert failed["actions"][0]["skip_if_cause_late"] is True and failed["actions"][0]["alert"] == "Ops"
    assert client.get(f"{ALERTS}/Ops").json()["used_by"] == ["'SLOWISH'"]
    assert client.delete(f"{ALERTS}/Ops").status_code == 409        # a Reaction names it


@pytest.mark.parametrize("entry, words", [
    (reaction("NOT_ENDED_BY", act("NOTIFY", alert="Ops")), "belongs under Also"),
    (timed("NOT_STARTED_BY", "AFTER_START", act("NOTIFY", alert="Ops"), minutes=30), "need a workflow"),
    (timed("NOT_ENDED_BY", "AFTER_READY", act("NOTIFY", alert="Ops"), minutes=30), "need a workflow"),
    (timed("NOT_ENDED_BY", "CLOCK", act("NOTIFY", alert="Ops"), clock_time="25:00"), "hours and minutes"),
    (timed("RUNS_LONGER_THAN", "CLOCK", act("NOTIFY", alert="Ops"), clock_time="03:00"), "cannot be given as"),
    (timed("RUNS_LONGER_THAN", "LENGTH", act("NOTIFY", alert="Ops")), "minutes greater than zero"),
    (timed("RUNS_LONGER_THAN", "HISTORY", act("NOTIFY", alert="Ops"), percent=50, run_count=2), "at least 3"),
    (timed("NOT_ENDED_BY", "CLOCK", act("RERUN", max_times=1), clock_time="03:00"), "belongs under What happens next"),
    (reaction("FAILED", act("MARK_AS_LATE"), section="ALSO"), "only a missed time makes a run late"),
    (reaction("FAILED", act("NOTIFY", alert="Nobody"), section="ALSO"), "must name an alert that exists"),
    (reaction("FAILED", act("NOTIFY", alert="Ops")), "belongs under Also"),
])
def test_a_reaction_that_cannot_work_is_refused_and_says_why(client, entry, words):
    client.post(ALERTS, json=alert_body())
    response = client.post(JOBS, json=steps_job("BAD", [entry]))
    assert response.status_code == 422 and words in response.json()["detail"], response.text


def test_not_started_by_and_within_minutes_of_being_ready_are_offered_in_a_workflow(client, seed, db):
    seed.step(seed.job("LOAD"), 1, "SIMULATE", title="Pretend")
    seed.step(seed.job("REPORT"), 1, "SIMULATE", title="Pretend")
    db.commit()
    client.post(ALERTS, json=alert_body())
    own = [timed("NOT_STARTED_BY", "AFTER_START", act("MARK_AS_LATE"), act("NOTIFY", alert="Ops"), minutes=120),
           timed("NOT_ENDED_BY", "AFTER_READY", act("NOTIFY", alert="Ops"), minutes=30)]
    items = [use("LOAD", "Load"), use("REPORT", "Report", after=["Load"], reactions_overridden=True, reactions=own)]
    response = client.post(JOBS, json=a_workflow("NIGHTLY", items))
    assert response.status_code == 201, response.text
    saved = client.get(f"{JOBS}/NIGHTLY").json()["items"][1]["reactions"]
    assert [(r["when"], r["time_kind"], r["minutes"]) for r in saved] == [
        ("NOT_STARTED_BY", "AFTER_START", 120), ("NOT_ENDED_BY", "AFTER_READY", 30)]
    assert client.get(f"{ALERTS}/Ops").json()["used_by"] == ["'Report' in 'NIGHTLY'"]
