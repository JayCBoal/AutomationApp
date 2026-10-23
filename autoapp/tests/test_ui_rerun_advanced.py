"""
The Advanced… dialog on the Rerun panel (docs/WORKFLOWS_PHASE7.md, step 6e): choosing items for a workflow run one by
one or by a shortcut, what the dialog says about the choices before anything runs, and choosing a step for a job on its own.
"""
import pytest

from test_control_file import gated_job, put_gate
from test_ui_rerun_workflow import failed_run, outline_view, wait_for_status    # noqa: F401  (fixtures)
from test_workflow_reopen import fix
from test_workflow_runner import flow, sim    # noqa: F401  (fixtures)


def open_advanced(page):
    page.locator("#rerun-button").click()
    page.locator("#rerun-advanced-open").click()
    page.locator("#rerun-advanced").wait_for()


def row(page, path):
    return page.locator(f"#rerun-choices tr[data-path='{path}']")


def test_advanced_lists_every_item_and_run_waits_until_something_is_chosen(failed_run):
    page = failed_run
    open_advanced(page)

    assert page.locator("#rerun-choices tr").count() == 3
    assert page.locator("#rerun-advanced-run").is_disabled()
    row(page, "Load").locator("select").select_option("restart")
    page.wait_for_function("() => document.querySelector('#rerun-advanced-run').disabled === false")
    assert "Load" in page.locator("#rerun-items").inner_text()


def test_from_a_chosen_job_runs_it_and_what_waits_for_it(failed_run, db):
    page = failed_run
    fix(db, "LOAD")
    open_advanced(page)

    page.get_by_label("From the jobs chosen, and everything that waits for them").check()
    row(page, "Load").locator("input[type=checkbox]").check()
    page.wait_for_function("() => document.querySelector('#rerun-items')?.textContent.includes('Report')")
    assert "Extract" not in page.locator("#rerun-items").inner_text()
    page.locator("#rerun-advanced-run").click()

    wait_for_status(page, "Succeeded")
    states = page.locator("#run-items .wf-state").all_inner_texts()
    assert not states[0].endswith("attempt 2") and states[1].endswith("attempt 2")


def test_only_the_chosen_jobs_warns_that_what_follows_may_be_out_of_date(failed_run):
    page = failed_run
    open_advanced(page)

    page.get_by_label("Only the jobs chosen").check()
    assert "out of date" in page.locator("#rerun-only-warning").inner_text()


def test_bypassing_a_failed_job_lets_what_waits_for_it_go_on(failed_run):
    page = failed_run
    open_advanced(page)

    row(page, "Load").locator("select").select_option("bypass")
    page.wait_for_function("() => document.querySelector('#rerun-items')?.textContent.includes('bypassed')")
    page.locator("#rerun-advanced-run").click()

    wait_for_status(page, "Succeeded")


def test_a_wait_can_be_ignored_for_one_restart_and_the_dialog_says_it_holds_again_next_time(failed_run):
    page = failed_run
    open_advanced(page)

    row(page, "Load").locator("select").select_option("restart")
    row(page, "Load").locator(".rerun-waits input[type=checkbox]").check()
    page.wait_for_function("() => document.querySelector('#rerun-advanced')?.textContent.includes('this restart only')")


def test_back_returns_to_the_plain_choices(failed_run):
    page = failed_run
    open_advanced(page)

    page.locator("#rerun-advanced-back").click()
    page.locator("#rerun-resume").wait_for(state="visible")
    page.locator("#rerun-advanced").wait_for(state="detached")


# ---------- A job on its own ----------

@pytest.fixture
def gated(seed, endpoints, db):
    gated_job(seed, name="DEV-RES", gates=("a", "b"))
    db.commit()


def test_a_job_on_its_own_can_start_at_a_chosen_step(page, gated, tmp_path):
    page.goto("/ui/run.html?key=DEV-RES")
    page.locator("#run-check .status").wait_for()
    page.locator("#run-button").click()
    page.wait_for_function("() => document.querySelector('#run-outcome')?.textContent === 'Failed'", timeout=30000)
    put_gate(tmp_path, "a.ok", job="DEV-RES")
    put_gate(tmp_path, "b.ok", job="DEV-RES")

    page.locator("#rerun-button").click()
    page.locator("#rerun-advanced-open").click()
    page.locator("#rerun-steps").wait_for()
    assert page.locator("#rerun-advanced-run").is_disabled()
    page.locator(".rerun-step[data-step='1'] input[type=radio]").check()
    page.wait_for_function("() => document.querySelector('#rerun-summary')?.textContent.includes('starts at step 1')")
    page.locator("#rerun-advanced-run").click()

    page.wait_for_function("() => document.querySelector('#run-outcome')?.textContent === 'Succeeded'", timeout=30000)
    assert "starting at step 1" in page.locator("#job-log").inner_text()


def test_the_restarts_list_and_audit_log_say_which_item_was_bypassed(failed_run, db):
    from app.models import Audit
    page = failed_run
    open_advanced(page)
    row(page, "Load").locator("select").select_option("bypass")
    page.wait_for_function("() => document.querySelector('#rerun-advanced-run').disabled === false")
    page.locator("#rerun-advanced-run").click()
    wait_for_status(page, "Succeeded")

    page.reload()
    page.wait_for_selector("#restarts-box li", timeout=30000)
    assert "Bypassed 'Load'." in page.locator("#restarts-box").inner_text()
    said = " ".join(a.Details for a in db.query(Audit).filter(Audit.Action == "JOB_RERUN_ADVANCED"))
    assert "bypassed 'Load'" in said


def test_a_workflow_that_succeeded_offers_advanced_only(page, sim, flow):
    flow("WF", [("Extract", sim("EXTRACT")), ("Load", sim("LOAD"), ["Extract"])])
    page.goto("/ui/workflow.html?key=WF")
    page.locator("#run-button").click()
    wait_for_status(page, "Succeeded")

    page.locator("#rerun-button").click()
    page.locator("#rerun-advanced-open").wait_for()

    assert page.locator("#rerun-resume").is_disabled() and page.locator("#rerun-restart").is_disabled()
    page.locator("#rerun-advanced-open").click()
    page.locator("#rerun-advanced").wait_for()
    row(page, "Load").locator("select").select_option("restart")
    page.wait_for_function("() => document.querySelector('#rerun-advanced-run').disabled === false")
    page.locator("#rerun-advanced-run").click()
    page.wait_for_function("() => document.querySelector('#run-items')?.textContent.includes('attempt 2')", timeout=60000)



def test_an_item_that_did_not_run_waits_its_turn_unless_it_is_left_not_run(failed_run):
    page = failed_run
    open_advanced(page)
    report = row(page, "Report").locator("select")

    assert report.locator("option:checked").inner_text() == "Run when its waits are met"
    assert row(page, "Extract").locator("option:checked").inner_text() == "Leave as it ended"
    row(page, "Load").locator("select").select_option("bypass")
    page.wait_for_function("() => document.querySelector('#rerun-items')?.textContent.includes('Report')")

    report.select_option("leave")
    page.wait_for_function("() => !document.querySelector('#rerun-items').textContent.includes('Report')")
    report.select_option("")
    page.wait_for_function("() => document.querySelector('#rerun-items').textContent.includes('Report')")
    page.locator("#rerun-advanced-run").click()

    wait_for_status(page, "Succeeded")      # Report ran: the whole workflow succeeded
