"""
The Alerts page, the Alert deliveries page and Late in Job History (docs/WORKFLOWS_PHASE8.md, step 6), in a real browser
against a real server. Sending is tested in test_alerts.py.
"""
from datetime import timedelta

import pytest
from playwright.sync_api import expect

from app.models import Alert, AlertDelivery, AlertRecipient, JobRun, MailSetting, utcnow


def an_alert(db, name="Ops"):
    alert = Alert(Name=name, Subject="%{Alert.Job} is late", Message="Why: %{Alert.Why}")
    alert.recipients.append(AlertRecipient(RecipientOrder=1, Address="ops@example.com"))
    db.add(alert)
    db.commit()
    return alert


def test_an_alert_is_added_changed_tested_and_deleted_on_the_alerts_page(page, db):
    page.goto("/ui/alerts.html")
    expect(page.locator("#alerts-summary")).to_contain_text("No alerts yet")
    page.locator("#new-alert").click()
    page.locator("#alert-name").fill("Ops")
    page.locator("#alert-recipients").fill("ops@example.com, boss@example.com")
    page.locator("#alert-subject").fill("%{Alert.Job} is late")
    page.locator("#alert-message").fill("Why: %{Alert.Why}")
    page.locator("#save-alert").click()
    card = page.locator("[data-alert='Ops']")
    expect(card.locator(".alert-recipients")).to_have_text("ops@example.com, boss@example.com")

    card.locator(".edit-alert").click()
    page.locator("#alert-subject").fill("Late: %{Alert.Job}")
    page.locator("#save-alert").click()
    expect(card).to_contain_text("Late: %{Alert.Job}")

    card.locator(".test-alert").click()
    expect(page.locator("#save-notice")).to_contain_text("test message")
    db.expire_all()
    assert [(d.AlertName, d.IsTest, d.Status) for d in db.query(AlertDelivery)] == [("Ops", True, "PENDING")]

    page.once("dialog", lambda dialog: dialog.accept())
    card.locator(".delete-alert").click()
    expect(page.locator("[data-alert='Ops']")).to_have_count(0)


def test_an_alert_that_cannot_work_says_why_on_the_page(page_expecting_refusals, db):
    page = page_expecting_refusals
    page.goto("/ui/alerts.html")
    page.locator("#new-alert").click()
    page.locator("#alert-name").fill("Ops")
    page.locator("#alert-recipients").fill("not an address")
    page.locator("#alert-subject").fill("Late")
    page.locator("#alert-message").fill("Late")
    page.locator("#save-alert").click()
    expect(page.locator("#page-error")).to_contain_text("is not an email address")


def test_the_mail_settings_are_saved_from_the_alerts_page(page, db):
    page.goto("/ui/alerts.html")
    page.locator("#mail-host").fill("localhost")
    page.locator("#mail-port").fill("8025")
    page.locator("#mail-sender").fill("autoapp@example.com")
    page.locator("#save-mail").click()
    expect(page.locator("#save-notice")).to_contain_text("Saved the mail settings")
    db.expire_all()
    row = db.get(MailSetting, 1)
    assert (row.Host, row.Port, row.SenderAddress) == ("localhost", 8025, "autoapp@example.com")


def test_a_used_alert_cannot_be_deleted_and_says_who_names_it(page, db, seed):
    from app.models import Reaction, ReactionAction
    alert = an_alert(db)
    job = seed.job("LOAD")
    reaction = Reaction(Job_MasterObject_id=job.MasterObject_id, Section="ALSO", WhenTest="FAILED")
    reaction.actions.append(ReactionAction(Action="NOTIFY", alert=alert))
    db.add(reaction)
    db.commit()
    page.goto("/ui/alerts.html")
    card = page.locator("[data-alert='Ops']")
    expect(card.locator(".used-by")).to_have_text("'LOAD'")
    expect(card.locator(".delete-alert")).to_be_disabled()


def test_the_deliveries_page_lists_each_message_with_its_result(page, db):
    an_alert(db)
    db.add_all([
        AlertDelivery(AlertName="Ops", Recipients="ops@example.com", Subject="J1 is late", Body="Why: late", Status="SENT",
                      Attempts=1, SentDateTime=utcnow(), RunID="r-1"),
        AlertDelivery(AlertName="Ops", Recipients="ops@example.com", Subject="J2 is late", Body="Why: late", Status="FAILED",
                      Attempts=3, LastError="Connection refused", IsTest=True)])
    db.commit()
    page.goto("/ui/alert_deliveries.html")
    rows = page.locator("tr.delivery")
    expect(rows).to_have_count(2)
    assert rows.nth(0).get_attribute("data-status") == "FAILED"               # newest first
    expect(rows.nth(0)).to_contain_text("Failed after 3 tries")
    expect(rows.nth(0)).to_contain_text("Connection refused")
    expect(rows.nth(1)).to_contain_text("Sent ")

    page.locator("select[name=status]").select_option("SENT")
    page.get_by_role("button", name="Search").click()
    expect(page.locator("tr.delivery")).to_have_count(1)


def test_job_history_marks_a_late_run_and_can_search_for_it(page, db):
    now = utcnow()
    db.add_all([
        JobRun(RunID="r-late", JobKey="SLOWPOKE", SchedulerInstanceID="I1", Status="SUCCESS", StartedDateTime=now - timedelta(hours=2),
               EndedDateTime=now - timedelta(hours=1), LateDateTime=now - timedelta(hours=1, minutes=30),
               LateReason="'SLOWPOKE' has run longer than 30m"),
        JobRun(RunID="r-ok", JobKey="PUNCTUAL", SchedulerInstanceID="I2", Status="SUCCESS", StartedDateTime=now - timedelta(hours=1),
               EndedDateTime=now - timedelta(minutes=50))])
    db.commit()
    page.goto("/ui/history.html")
    expect(page.locator("tbody tr")).to_have_count(2)
    late_row = page.locator("tbody tr", has_text="SLOWPOKE")
    expect(late_row.locator(".tag.late")).to_be_visible()
    expect(late_row.locator(".late-reason")).to_contain_text("has run longer than 30m")
    expect(page.locator("tbody tr", has_text="PUNCTUAL").locator(".tag.late")).to_be_hidden()

    page.locator("select[name=late]").select_option("true")
    page.get_by_role("button", name="Search").click()
    expect(page.locator("tbody tr")).to_have_count(1)
    expect(page.locator("tbody tr")).to_contain_text("SLOWPOKE")
