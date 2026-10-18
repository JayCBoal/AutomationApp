"""
The workflow diagram (docs/WORKFLOWS_PHASE2.md), in a real browser against a real server: Diagram | Outline
and remembering it, what boxes and lines show, selecting, Find, editing by dragging from box to box, and a
run drawn live.
"""
import pytest

from app.models import Job, WorkflowItem, WorkflowPrerequisite

LONG = "Load_general_ledger_postings_for_all_operating_companies_and_intercompany_items"


@pytest.fixture
def flow(seed, db):
    """
    FLOW, made of Simulate jobs: Extract; Load (a long name) once Extract has succeeded; Report once
    Load gave return codes 0-4, or Extract failed (Any). With links=False, the jobs wait for nothing.
    """
    def _make(links=True, wait=0):
        jobs = {}
        for key in ("SIM_EXTRACT", "SIM_LOAD", "SIM_REPORT"):
            seed.step(seed.job(key), 1, "SIMULATE", title="Pretend", WaitSeconds=str(wait if key == "SIM_EXTRACT" else 0))
        db.commit()
        for key in ("SIM_EXTRACT", "SIM_LOAD", "SIM_REPORT"):
            jobs[key] = db.query(Job).filter(Job.JobKey == key).one()
        workflow = seed._add(Job(JobKey="FLOW", JobType="WORKFLOW", Description="Three jobs"))
        extract = seed._add(WorkflowItem(workflow=workflow, ItemName="Extract", job=jobs["SIM_EXTRACT"], ItemOrder=1))
        load = seed._add(WorkflowItem(workflow=workflow, ItemName=LONG, job=jobs["SIM_LOAD"], ItemOrder=2))
        report = seed._add(WorkflowItem(workflow=workflow, ItemName="Report", job=jobs["SIM_REPORT"], ItemOrder=3,
                                        JoinRule="ANY" if links else "ALL"))
        if links:
            seed._add(WorkflowPrerequisite(item=load, target=extract, Test="SUCCESS"))
            seed._add(WorkflowPrerequisite(item=report, target=load, Test="RC", ReturnCodes="0-4"))
            seed._add(WorkflowPrerequisite(item=report, target=extract, Test="FAILED"))
        db.commit()
    return _make


def boxes(page, canvas="#diagram"):
    page.locator(f"{canvas} .wf-box").first.wait_for()
    return page.locator(f"{canvas} .wf-box")


def box_text(box):
    """A box's name, put back together from its wrapped lines."""
    return "".join(t.text_content() for t in box.locator("text:not(.wf-sub)").all())


def shown_in_outline(page, count):
    page.wait_for_function("n => [...document.querySelectorAll('#outline .wf-item')].filter(e => e.offsetParent).length === n", arg=count)


def drag(page, source, target):
    a, b = source.bounding_box(), target.bounding_box()
    page.mouse.move(a["x"] + a["width"] / 2, a["y"] + a["height"] / 2)
    page.mouse.down()
    page.mouse.move(a["x"] + a["width"] / 2 + 20, a["y"] + a["height"] / 2 + 10, steps=3)
    page.mouse.move(b["x"] + b["width"] / 2, b["y"] + b["height"] / 2, steps=5)
    page.mouse.up()


def test_the_diagram_is_shown_first_and_draws_every_job_and_prerequisite(page, flow):
    flow()
    page.goto("/ui/workflow.html?key=FLOW")
    assert boxes(page).count() == 3
    assert [box_text(b) for b in boxes(page).all()] == ["Extract", LONG, "Report"]       # never cut short
    tests = sorted(line.get_attribute("data-test") for line in page.locator("#diagram .wf-line").all())
    assert tests == ["FAILED", "RC", "SUCCESS"]
    assert "RC 0-4" in page.locator('#diagram .wf-line[data-test="RC"]').text_content()
    assert page.locator("#diagram .wf-any").count() == 1
    assert "waits until Extract failed" in page.locator('#diagram .wf-line[data-test="FAILED"] title').first.text_content()
    assert not page.locator("#outline .wf-item").first.is_visible()


def test_the_view_last_used_is_remembered(page, flow):
    flow()
    page.goto("/ui/workflow.html?key=FLOW")
    boxes(page)
    page.locator("#view-outline").click()
    page.locator("#outline .wf-needs").first.wait_for()
    page.reload()
    page.locator("#outline .wf-needs").first.wait_for()
    assert not page.locator("#diagram").is_visible()
    page.locator("#view-diagram").click()
    page.reload()
    assert boxes(page).count() == 3


def test_selecting_a_box_or_a_line_shows_it_beside_the_diagram(page, flow):
    flow()
    page.goto("/ui/workflow.html?key=FLOW")
    boxes(page).nth(2).click()
    shown_in_outline(page, 1)
    shown = page.locator("#side .wf-item:visible")
    assert shown.count() == 1 and "Report" in shown.inner_text()
    assert "After" in shown.locator(".wf-needs").inner_text()
    page.locator('#diagram .wf-line[data-test="SUCCESS"] .wf-hit').last.dispatch_event("click")
    page.wait_for_function("name => document.querySelector('#side .wf-item[data-name=\"' + name + '\"]')?.offsetParent", arg=LONG)
    assert LONG in page.locator("#side .wf-item:visible").inner_text()
    assert page.locator("#diagram .wf-selected").count() == 0                 # the line is selected, not a box


def test_find_highlights_the_jobs_it_matches(page, flow):
    flow()
    page.goto("/ui/workflow.html?key=FLOW")
    boxes(page)
    page.locator("#find").fill("ledger")
    assert page.locator("#find-count").inner_text() == "1 found"
    page.wait_for_function("() => document.querySelectorAll('#diagram .wf-found').length === 1")
    page.locator("#find-results button").click()
    assert LONG in page.locator("#side .wf-item:visible").inner_text()
    page.locator("#find").fill("nothing like it")
    assert "No job here" in page.locator("#find-count").inner_text()


def test_direction_and_zoom_change_the_drawing(page, flow):
    flow()
    page.goto("/ui/workflow.html?key=FLOW")
    first, last = boxes(page).nth(0).bounding_box(), boxes(page).nth(2).bounding_box()
    assert last["x"] > first["x"]                                             # left to right
    page.locator("#direction-down").click()
    page.wait_for_function("() => { const b = document.querySelectorAll('#diagram .wf-box rect');"
                           " return b.length && Number(b[b.length - 1].getAttribute('y')) > Number(b[0].getAttribute('y')) + 40; }")
    width = page.locator("#diagram svg").bounding_box()["width"]
    page.locator("#zoom-in").click()
    page.wait_for_function(f"() => document.querySelector('#diagram svg').getBoundingClientRect().width > {width + 10}")


def test_dragging_from_box_to_box_adds_a_prerequisite_that_is_saved(page, flow, db):
    flow(links=False)
    page.goto("/ui/workflow.html?key=FLOW")
    boxes(page)
    page.locator("#edit-button").click()
    drag(page, boxes(page).nth(0), boxes(page).nth(2))
    page.wait_for_function("() => document.querySelectorAll('#diagram .wf-line').length === 1")
    side = page.locator("#side .wf-item:visible")
    assert side.locator(".item-name").input_value() == "Report"            # the job that now waits is shown beside
    side.locator(".prereq-test").select_option("ENDED")                       # the new line's test, changed beside it
    page.wait_for_function("() => document.querySelector('#diagram .wf-line')?.dataset.test === 'ENDED'")
    page.locator("#submit-button").click()
    page.locator("#save-notice").wait_for()
    db.expire_all()
    report = next(i for i in db.query(Job).filter(Job.JobKey == "FLOW").one().items if i.ItemName == "Report")
    assert [(p.target.ItemName, p.Test) for p in report.prerequisites] == [("Extract", "ENDED")]


def test_editing_keeps_changes_across_diagram_and_outline(page, flow):
    flow(links=False)
    page.goto("/ui/workflow.html?key=FLOW")
    boxes(page)
    page.locator("#edit-button").click()
    page.locator("#add-job").click()
    side = page.locator("#side .wf-item:visible")
    side.locator(".item-job").fill("SIM_REPORT")
    side.locator(".item-name").fill("Report_again")
    page.wait_for_function("() => document.querySelectorAll('#diagram .wf-box').length === 4")
    page.locator("#view-outline").click()
    shown_in_outline(page, 4)
    page.locator("#view-diagram").click()
    assert "Report_again" in [box_text(b) for b in boxes(page).all()]
    assert page.locator("#submit-button").is_enabled()


def test_a_run_is_drawn_on_the_diagram_live(page, flow):
    flow(wait=3)
    page.goto("/ui/workflow.html?key=FLOW")
    boxes(page)
    page.locator("#run-button").click()
    page.wait_for_function("() => document.querySelector('#run-diagram .wf-box[data-name=\"Extract\"]')?.dataset.status === 'RUNNING'",
                           timeout=30000)
    page.wait_for_function("() => ['Succeeded', 'Failed'].some(w => (document.querySelector('#run-status')?.textContent || '').startsWith(w))",
                           timeout=60000)
    page.wait_for_function("() => document.querySelector('#run-diagram .wf-box[data-name=\"Report\"]')?.dataset.status === 'SUCCESS'")
    statuses = [b.get_attribute("data-status") for b in boxes(page, "#run-diagram").all()]
    assert statuses == ["SUCCESS", "SUCCESS", "SUCCESS"]
    assert page.locator("#run-diagram .wf-line").count() == 3
    boxes(page, "#run-diagram").nth(0).click()
    assert page.locator("#run-side a", has_text="Its log").is_visible()


def test_a_selected_line_is_removed_with_delete(page, flow, db):
    flow()
    page.goto("/ui/workflow.html?key=FLOW")
    boxes(page)
    page.locator("#edit-button").click()
    page.locator('#diagram .wf-line[data-test="FAILED"] .wf-hit').last.dispatch_event("click")
    assert page.locator("#side .wf-item:visible .remove-item").inner_text() == "Remove this job"
    page.keyboard.press("Delete")
    page.wait_for_function("() => document.querySelectorAll('#diagram .wf-line').length === 2")
    page.locator("#submit-button").click()
    page.locator("#save-notice").wait_for()
    db.expire_all()
    report = next(i for i in db.query(Job).filter(Job.JobKey == "FLOW").one().items if i.ItemName == "Report")
    assert [(p.target.ItemName, p.Test) for p in report.prerequisites] == [(LONG, "RC")]


def test_pointing_at_a_line_shows_an_x_that_removes_it(page, flow):
    flow()
    page.goto("/ui/workflow.html?key=FLOW")
    boxes(page)
    assert page.locator("#diagram .wf-line-remove").count() == 0                # only while editing
    page.locator("#edit-button").click()
    page.wait_for_function("() => document.querySelectorAll('#diagram .wf-line-remove').length === 3")
    remover = page.locator('#diagram .wf-line[data-test="SUCCESS"] .wf-line-remove')
    assert "Remove this line" in remover.locator("title").text_content()
    assert remover.get_attribute("opacity") == "0"                             # hidden until the line is pointed at
    page.locator('#diagram .wf-line[data-test="SUCCESS"] .wf-hit').last.dispatch_event("pointerenter")
    assert remover.get_attribute("opacity") == "1"
    remover.dispatch_event("click")
    page.wait_for_function("() => document.querySelectorAll('#diagram .wf-line').length === 2")
    assert page.locator("#submit-button").inner_text() == "Save" and page.locator("#submit-button").is_enabled()


def test_a_jobs_prerequisites_are_in_their_own_box_with_starts_when_under_them(page, flow):
    flow()
    page.goto("/ui/workflow.html?key=FLOW")
    boxes(page)
    page.locator("#edit-button").click()
    boxes(page).nth(1).click()
    shown_in_outline(page, 1)
    box = page.locator("#side .wf-item:visible fieldset.wf-prereqs")
    assert box.locator("legend").text_content() == "Prerequisites"
    assert box.locator(".item-join").is_disabled()                             # one prerequisite: All or Any doesn't matter
    assert "Job in this workflow" in box.inner_text() and "Start rule" in box.inner_text()
    assert box.locator(".item-join option:checked").inner_text() == "When all prerequisites are satisfied"
    assert box.locator('.item-join option[value="CUSTOM"]').is_disabled()       # not built yet
    boxes(page).nth(2).click()
    page.wait_for_function("() => document.querySelector('#side .wf-item[data-name=\"Report\"]')?.offsetParent")
    box = page.locator("#side .wf-item:visible fieldset.wf-prereqs")
    assert box.locator(".item-join").is_enabled() and box.locator(".item-join").input_value() == "ANY"
