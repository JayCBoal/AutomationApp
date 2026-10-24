"""
The Reactions box with time Whens, Mark as late and Notify (docs/WORKFLOWS_PHASE8.md, step 6), in a real browser: what is
offered on a job and in a workflow, what a time of day works out to, and what is saved.
"""
import pytest
from playwright.sync_api import expect

from core.models import Alert, AlertRecipient, Job, WorkflowItem


@pytest.fixture(autouse=True)
def outline_view(page):
    page.add_init_script("localStorage.setItem('autoapp.workflow.view', 'outline')")


@pytest.fixture
def ops(seed, db):
    """A job, LOAD, and an alert, Ops."""
    seed.step(seed.job("LOAD"), 1, "SIMULATE", title="Pretend")
    alert = Alert(Name="Ops", Subject="%{Alert.Job} is late", Message="Why: %{Alert.Why}")
    alert.recipients.append(AlertRecipient(RecipientOrder=1, Address="ops@example.com"))
    db.add(alert)
    db.commit()


def test_a_time_when_with_mark_as_late_and_notify_is_made_saved_and_read_in_words(page, ops, db):
    page.goto("/ui/job.html?key=LOAD")
    page.locator("#edit-button").click()
    box = page.locator("#reactions-panel")
    box.locator(".add-reaction").nth(1).click()                          # Also: Notify, when it fails, by default
    when = box.locator(".reaction-when")
    # A job on its own is not "not started by": that needs a workflow around it
    assert when.locator("option").all_inner_texts() == [
        "it succeeds", "it fails", "it ends, whatever happened", "its return code is", "it has not ended by", "it runs longer than"]

    when.select_option("NOT_ENDED_BY")
    kinds = box.locator(".reaction-time-kind")
    assert kinds.locator("option").all_inner_texts() == ["a time of day", "minutes after the start"]
    box.locator(".reaction-clock").fill("03:00")
    assert "Works out to 03:00" in box.locator(".reaction-time-help").inner_text()
    actions = box.locator(".reaction-action").first.locator("option").all_inner_texts()
    assert actions == ["Notify", "Mark as late", "Start a workflow"]
    box.locator(".reaction-alert").fill("Ops")
    box.locator(".add-reaction").nth(1).click()
    box.locator(".reaction-when").nth(1).select_option("RUNS_LONGER_THAN")
    box.locator(".reaction-time-kind").nth(1).select_option("HISTORY")
    box.locator(".reaction-percent").nth(1).fill("50")
    box.locator(".reaction-action").nth(1).select_option("MARK_AS_LATE")

    page.locator("#submit-button").click()
    page.locator("#save-notice").wait_for()

    assert box.locator(".reaction-list li").all_inner_texts() == [
        "Also, when it has not ended by 03:00: notify Ops.",
        "Also, when it runs longer than 50% over its average of the last 10 runs: mark as late."]
    db.expire_all()
    saved = db.query(Job).filter(Job.JobKey == "LOAD").one().reactions
    assert [(r.WhenTest, r.WhenTimeKind, r.WhenClockTime, r.WhenPercent, r.WhenRunCount) for r in saved] == [
        ("NOT_ENDED_BY", "CLOCK", "03:00", None, None), ("RUNS_LONGER_THAN", "HISTORY", None, 50, 10)]
    assert [a.alert.Name for a in saved[0].actions] == ["Ops"]


def test_choosing_a_plain_when_takes_mark_as_late_away(page, ops, db):
    page.goto("/ui/job.html?key=LOAD")
    page.locator("#edit-button").click()
    box = page.locator("#reactions-panel")
    box.locator(".add-reaction").nth(1).click()
    box.locator(".reaction-when").select_option("RUNS_LONGER_THAN")
    box.locator(".reaction-action").first.select_option("MARK_AS_LATE")
    expect(box.locator(".reaction-action").first).to_have_value("MARK_AS_LATE")
    box.locator(".reaction-when").select_option("FAILED")
    expect(box.locator(".reaction-action").first).to_have_value("NOTIFY")       # Mark as late is only for a time When
    expect(box.locator(".reaction-time")).to_be_hidden()


def test_a_workflow_use_offers_not_started_by_and_after_being_ready(page, seed, db, ops):
    load = db.query(Job).filter(Job.JobKey == "LOAD").one()
    flow = seed._add(Job(JobKey="FLOW", JobType="WORKFLOW"))
    seed._add(WorkflowItem(workflow=flow, ItemName="Load", job=load, ItemOrder=1))
    db.commit()
    page.goto("/ui/workflow.html?key=FLOW")
    page.locator("#edit-button").click()
    page.locator(".override-reactions").first.click()
    box = page.locator(".wf-item-reactions").first
    box.locator(".add-reaction").nth(1).click()
    box.locator(".reaction-when").select_option("NOT_STARTED_BY")
    assert box.locator(".reaction-time-kind").locator("option").all_inner_texts() == [
        "a time of day", "minutes after the start", "minutes after it is ready"]
    assert box.locator(".reaction-skip-late").is_visible()
