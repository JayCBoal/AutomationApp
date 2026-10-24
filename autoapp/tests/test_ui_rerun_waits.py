"""
What Ignore a prerequisite and Reset counts leave on the run pages (docs/WORKFLOWS_PHASE7.md, step 6c): the line an
operator ignored is drawn struck through on the run diagram, and the Restarts list says what was released.
"""
from core.models import JobRun
from test_workflow_runner import flow, sim    # noqa: F401  (fixtures)


def test_an_ignored_line_is_struck_through_on_the_run_diagram_and_the_list_says_why(page, sim, flow, db):
    flow("WF", [("A", sim("A", fail=True)), ("Load", sim("LOAD"), ["A"])])
    page.goto("/ui/workflow.html?key=WF")
    page.locator("#run-button").click()
    page.wait_for_function("() => document.querySelector('#run-status')?.textContent.startsWith('Failed')", timeout=60000)
    run_id = db.query(JobRun).filter(JobRun.JobKey == "WF").one().RunID

    answer = page.request.post(f"/api/v1/runs/{run_id}/rerun", data={
        "kind": "advanced", "items": {"Load": "restart"}, "ignore": {"Load": ["A"]}, "reset_counts": True})
    assert answer.ok, answer.text()
    page.wait_for_timeout(3000)
    page.goto(f"/ui/workflow.html?key=WF&run={run_id}")

    page.wait_for_selector(".wf-line-ignored", timeout=60000)
    assert page.locator(".wf-line-ignored").count() == 1
    page.wait_for_selector("#restarts-box li", timeout=30000)
    text = page.locator("#restarts-box").inner_text() if page.locator("#restarts-box").count() else ""
    assert "Ignored the wait of 'A' for 'Load'." in text and "Reset the retry counts." in text
