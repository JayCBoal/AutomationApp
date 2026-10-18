"""
Reactions, Disable here and Kill in the web interface (docs/WORKFLOWS_PHASE3.md), in a real
browser against a real server: the Reactions box on the job page, a use's override and Disable
here on the workflow page, a run showing what Reactions did, and Kill.
"""
import pytest

from app.models import Job, Reaction, ReactionAction, WorkflowItem, WorkflowPrerequisite


@pytest.fixture(autouse=True)
def outline_view(page):
    page.add_init_script("localStorage.setItem('autoapp.workflow.view', 'outline')")


@pytest.fixture
def jobs(seed, db):
    """LOAD (return code 'code'), REPORT, SLOW (waits 30 seconds); and FLOW: Load, then Report after it."""
    def _make(code=0):
        for key, params in (("LOAD", {"ReturnCode": str(code)}), ("REPORT", {}), ("SLOW", {"WaitSeconds": "30"})):
            seed.step(seed.job(key), 1, "SIMULATE", title="Pretend", **params)
        load, report = (db.query(Job).filter(Job.JobKey == k).one() for k in ("LOAD", "REPORT"))
        flow = seed._add(Job(JobKey="FLOW", JobType="WORKFLOW"))
        first = seed._add(WorkflowItem(workflow=flow, ItemName="Load", job=load, ItemOrder=1))
        second = seed._add(WorkflowItem(workflow=flow, ItemName="Report", job=report, ItemOrder=2))
        seed._add(WorkflowPrerequisite(item=second, target=first, Test="SUCCESS"))
        db.commit()
        return load
    return _make


def wait_for_run_end(page, timeout=60000):
    page.wait_for_function(
        "() => ['Succeeded', 'Failed'].some(w => (document.querySelector('#run-status')?.textContent || '').startsWith(w))",
        timeout=timeout)


def test_reactions_are_made_on_the_job_page_and_read_in_words(page, jobs, db):
    jobs()
    page.goto("/ui/job.html?key=LOAD")
    page.locator("#edit-button").click()
    box = page.locator("#reactions-panel")
    box.locator(".add-reaction").first.click()                    # What happens next: rerun, by default
    box.locator(".reaction-when").select_option("RC")
    box.locator(".reaction-codes").fill("8")
    box.locator(".reaction-times").fill("2")
    box.locator(".add-reaction").first.click()
    box.locator(".reaction-action").nth(1).select_option("COUNT_AS_SUCCEEDED")
    # Only what a job can do on its own is offered
    offered = box.locator(".reaction-action").first.locator("option").all_inner_texts()
    assert offered == ["Count as succeeded", "Count as failed", "Rerun this job"]

    page.locator("#submit-button").click()
    page.locator("#save-notice").wait_for()

    assert box.locator(".reaction-list li").all_inner_texts() == [
        "When its return code is 8: rerun this job, at most 2 times.", "When it fails: count as succeeded."]
    db.expire_all()
    load = db.query(Job).filter(Job.JobKey == "LOAD").one()
    assert [(r.WhenTest, r.WhenReturnCodes, [a.Action for a in r.actions]) for r in load.reactions] == [
        ("RC", "8", ["RERUN"]), ("FAILED", None, ["COUNT_AS_SUCCEEDED"])]


def test_a_use_shows_its_jobs_reactions_and_can_override_them_and_be_disabled_here(page, jobs, db):
    load = jobs()
    reaction = Reaction(Job_MasterObject_id=load.MasterObject_id, WhenTest="FAILED")
    reaction.actions.append(ReactionAction(Action="COUNT_AS_SUCCEEDED"))
    db.add(reaction)
    db.commit()
    page.goto("/ui/workflow.html?key=FLOW")
    assert "When it fails: count as succeeded. (from the job)" in page.locator("#outline").inner_text()

    page.locator("#edit-button").click()
    page.locator(".override-reactions").first.click()
    entry = page.locator(".wf-item-reactions").first
    entry.locator(".reaction-action").first.select_option("SKIP_BRANCH")
    page.locator(".item-disabled-here").nth(1).select_option("PASS_THROUGH")
    page.locator("#submit-button").click()
    page.locator("#save-notice").wait_for()

    outline = page.locator("#outline").inner_text()
    assert "When it fails: skip the rest of the branch." in outline and "(from the job)" not in outline
    assert page.locator(".disabled-here").nth(1).inner_text() == "Disabled here: passes through"
    db.expire_all()
    items = {i.ItemName: i for i in db.query(Job).filter(Job.JobKey == "FLOW").one().items}
    assert items["Load"].ReactionsOverridden and [a.Action for a in items["Load"].reactions[0].actions] == ["SKIP_BRANCH"]
    assert items["Report"].DisabledHere == "PASS_THROUGH"


def test_a_run_shows_a_job_counted_as_succeeded_and_the_reactions_that_fired(page, jobs, db):
    load = jobs(code=4)
    reaction = Reaction(Job_MasterObject_id=load.MasterObject_id, WhenTest="RC", WhenReturnCodes="4")
    reaction.actions.append(ReactionAction(Action="COUNT_AS_SUCCEEDED"))
    db.add(reaction)
    db.commit()
    page.goto("/ui/workflow.html?key=FLOW")
    page.locator("#run-button").click()
    wait_for_run_end(page)

    states = page.locator("#run-items .wf-state").all_inner_texts()
    assert states == ["Succeeded (counted; it failed) · return code 4", "Succeeded · return code 0"]
    page.locator("#run-reactions summary").click()
    assert "Load: 'Load' counted as succeeded." in page.locator("#run-reactions").inner_text()


def test_kill_and_cancel_from_the_workflow_page(page, seed, jobs, db):
    jobs()
    slow = db.query(Job).filter(Job.JobKey == "SLOW").one()
    flow = seed._add(Job(JobKey="SLOW_FLOW", JobType="WORKFLOW"))
    seed._add(WorkflowItem(workflow=flow, ItemName="Slow", job=slow, ItemOrder=1))
    db.commit()
    page.goto("/ui/workflow.html?key=SLOW_FLOW")
    page.locator("#run-button").click()
    page.wait_for_function("() => document.querySelector('#run-items .wf-state')?.textContent === 'Running'", timeout=30000)
    page.once("dialog", lambda dialog: dialog.accept())
    page.locator("#kill-run-button").click()
    wait_for_run_end(page)
    assert page.locator("#run-status").inner_text() == "Failed (killed)"
    assert page.locator("#run-items .wf-state").first.inner_text() == "Failed: killed"


def test_kill_from_the_run_job_page(page, jobs):
    jobs()
    page.goto("/ui/run.html?key=SLOW")
    page.locator("#run-check .status").wait_for()
    page.locator("#run-button").click()
    page.locator("#kill-button").wait_for(timeout=30000)
    page.once("dialog", lambda dialog: dialog.accept())
    page.locator("#kill-button").click()
    page.wait_for_function("() => (document.querySelector('#run-outcome')?.textContent || '').startsWith('Failed')", timeout=30000)


def test_the_diagram_marks_reactions_disable_here_and_draws_rerun_from_back_upstream(page, jobs, db):
    jobs()
    flow = db.query(Job).filter(Job.JobKey == "FLOW").one()
    load, report = sorted(flow.items, key=lambda i: i.ItemOrder)
    report.ReactionsOverridden = True
    reaction = Reaction(Item_id=report.id, WhenTest="FAILED")
    reaction.actions.append(ReactionAction(Action="RERUN_FROM", MaxTimes=2, TargetItem_id=load.id))
    db.add(reaction)
    load.DisabledHere = "STOP"
    db.commit()
    page.add_init_script("localStorage.setItem('autoapp.workflow.view', 'diagram')")
    page.goto("/ui/workflow.html?key=FLOW")
    page.locator("#diagram .wf-rerun").wait_for()

    rerun = page.locator("#diagram .wf-rerun")
    assert (rerun.get_attribute("data-from"), rerun.get_attribute("data-to")) == (str(page.evaluate(
        "() => document.querySelector('#diagram .wf-box[data-name=Report]').dataset.id")), page.evaluate(
        "() => document.querySelector('#diagram .wf-box[data-name=Load]').dataset.id"))
    assert "rerun from Load, at most 2 times" in rerun.locator("title").text_content()
    assert page.locator("#diagram .wf-box[data-name=Load]").get_attribute("data-disabled-here") == "STOP"
    report_tips = page.locator("#diagram .wf-box[data-name=Report] g title").all_text_contents()
    assert any(t.startswith("Its own Reactions here: When it fails: rerun from Load") for t in report_tips)
