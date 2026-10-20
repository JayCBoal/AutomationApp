"""
Frames (docs/WORKFLOWS_PHASE6.md) in a real browser against a real server: building a workflow with workflows and
jobs embedded in it, the diagram with frames around their jobs (fold and unfold, lines across), and a run drawn
with what is inside each frame.
"""
import pytest

from app.models import Job, WorkflowItem, WorkflowPrerequisite
from test_frames_engine import tree, waits_in_tree                          # noqa: F401  (a fixture and a helper)
from test_workflow_runner import sim                                         # noqa: F401  (a fixture)
from test_ui_workflow_diagram import boxes
from test_ui_workflows import wait_for_run_end


@pytest.fixture
def month_end(sim, tree, db):
    """MONTH_END: FX; a frame Extract with US and EU; a frame Transform (after Extract) whose Enrich also waits for FX."""
    top, made = tree("MONTH_END", {"FX": sim("FX"), "Extract": {"US": sim("US"), "EU": sim("EU")},
                                   "Transform": {"Enrich": sim("ENRICH"), "Other": sim("OTHER")}})
    transform = made["Transform"].job
    db.add(WorkflowPrerequisite(item=made["Transform"], target=made["Extract"], Test="SUCCESS", Kind="JOB"))
    db.add(waits_in_tree(next(i for i in transform.items if i.ItemName == "Enrich"), made["FX"]))
    db.commit()
    return top


def box(page, name):
    return page.locator(f'#diagram .wf-box[data-name="{name}"]')


# ---------- Building ----------

def test_a_workflow_with_a_frame_and_jobs_in_it_is_built_in_the_outline_and_saved(page, db):
    page.add_init_script("localStorage.setItem('autoapp.workflow.view', 'outline')")
    page.goto("/ui/workflow.html?new")
    page.locator("#workflow-key").fill("NEW_TREE")
    page.locator("#add-new-workflow").click()
    page.locator(".item-name").first.fill("Extract")
    page.locator(".add-inside-job").first.click()
    page.locator(".add-inside-job").first.click()
    page.wait_for_function("() => document.querySelectorAll('#outline .wf-item').length === 3")
    items = page.locator("#outline .wf-item")
    assert [items.nth(i).get_attribute("data-depth") for i in range(3)] == ["0", "1", "1"]       # the jobs are indented under the frame
    page.locator("#submit-button").click()

    page.locator("#save-notice").wait_for()

    assert page.locator("#save-notice").inner_text().startswith("Saved.")
    db.expire_all()
    keys = sorted(k for (k,) in db.query(Job.JobKey).filter(Job.JobKey.like("NEW_TREE%")))
    assert keys == ["NEW_TREE", "NEW_TREE.Extract", "NEW_TREE.Extract.Job", "NEW_TREE.Extract.Job2"]
    assert db.query(Job).filter(Job.JobKey == "NEW_TREE.Extract").one().Owner_MasterObject_id is not None
    page.reload()
    page.wait_for_function("() => document.querySelectorAll('#outline .wf-item').length === 3")
    assert page.locator("#outline .wf-item").nth(1).get_attribute("data-depth") == "1"


def test_a_frame_can_hold_a_frame_and_removing_the_outer_one_removes_what_is_inside(page, db):
    page.add_init_script("localStorage.setItem('autoapp.workflow.view', 'outline')")
    page.goto("/ui/workflow.html?new")
    page.locator("#workflow-key").fill("DEEP")
    page.locator("#add-new-workflow").click()
    page.locator(".add-inside-workflow").first.click()
    page.locator(".add-inside-job").nth(1).click()
    page.wait_for_function("() => document.querySelectorAll('#outline .wf-item').length === 3")
    assert [e.get_attribute("data-depth") for e in page.locator("#outline .wf-item").all()] == ["0", "1", "2"]

    page.locator(".remove-item").first.click()

    page.wait_for_function("() => document.querySelectorAll('#outline .wf-item').length === 0")


# ---------- The diagram ----------

def test_the_diagram_draws_a_frame_around_its_jobs_and_lines_cross_its_border(page, month_end):
    page.goto("/ui/workflow.html?key=MONTH_END")
    boxes(page)

    assert page.locator("#diagram .wf-frame").count() == 2
    frame, us, eu = page.locator('#diagram .wf-frame[data-name="Extract"] rect').first.bounding_box(), box(page, "US").bounding_box(), box(page, "EU").bounding_box()
    assert frame["x"] <= us["x"] and us["x"] + us["width"] <= frame["x"] + frame["width"]
    assert frame["y"] <= us["y"] and eu["y"] + eu["height"] <= frame["y"] + frame["height"]
    # Extract to Transform (a frame to a frame), and FX to Enrich (from outside the frame into it)
    tests = [l.get_attribute("data-test") for l in page.locator("#diagram .wf-line").all()]
    assert tests.count("SUCCESS") == 2


def test_a_frame_folds_into_one_box_and_opens_again(page, month_end):
    page.goto("/ui/workflow.html?key=MONTH_END")
    boxes(page)
    names = lambda: sorted(b.get_attribute("data-name") for b in page.locator("#diagram .wf-box").all())
    assert "US" in names()

    page.locator('#diagram .wf-frame[data-name="Extract"] .wf-fold').click()

    page.wait_for_function("() => !document.querySelector('#diagram .wf-box[data-name=\"US\"]')")
    assert "Extract" in names() and "US" not in names() and "EU" not in names()
    assert page.locator('#diagram .wf-box[data-name="Extract"] .wf-fold').count() == 1
    assert page.locator("#diagram .wf-line").count() == 2                 # the line from Extract still ends on its box
    page.locator('#diagram .wf-box[data-name="Extract"]').dblclick()
    page.wait_for_function("() => document.querySelector('#diagram .wf-box[data-name=\"US\"]')")


def test_selecting_a_frame_shows_it_beside_the_diagram(page, month_end):
    page.goto("/ui/workflow.html?key=MONTH_END")
    boxes(page)

    page.locator('#diagram .wf-frame[data-name="Transform"] .wf-frame-head').click()

    page.wait_for_function("() => document.querySelector('#side .wf-item:not([style*=\"display: none\"])')")
    assert "Transform" in page.locator("#side .wf-item:visible .wf-row").first.inner_text()


# ---------- A run ----------

def test_a_run_is_drawn_with_its_frames_and_what_is_inside_them(page, month_end):
    page.goto("/ui/workflow.html?key=MONTH_END")
    page.locator("#run-button").click()
    page.locator("#run-diagram .wf-frame").first.wait_for(timeout=30000)
    wait_for_run_end(page)

    page.wait_for_function("() => document.querySelectorAll('#run-diagram .wf-box[data-status=\"SUCCESS\"]').length >= 5")
    names = sorted(b.get_attribute("data-name") for b in page.locator("#run-diagram .wf-box:not(.wf-frame)").all())
    assert names == sorted(["FX", "US", "EU", "Enrich", "Other"])
    assert page.locator("#run-diagram .wf-frame").count() == 2
    assert page.locator("#run-diagram .wf-frame").first.get_attribute("data-status") == "SUCCESS"
    page.locator("#view-outline").click()
    rows = page.locator("#run-items .wf-row")
    paths = [r.get_attribute("data-path") for r in rows.all()]
    assert "Transform/Enrich" in paths and "Extract/US" in paths
    assert [r.get_attribute("style") for r in rows.all() if r.get_attribute("data-path") == "Extract/US"][0].startswith("margin-left: 22px")


# ---------- Workflows of their own, opened inline; Find through everything ----------

def test_a_workflow_of_its_own_is_one_box_that_opens_inline_read_only(page, month_end, db, seed, sim):
    shared = seed._add(Job(JobKey="DEV_SHARED", JobType="WORKFLOW"))
    seed._add(WorkflowItem(workflow=shared, ItemName="Summary", job=sim("SUMMARY"), ItemOrder=1))
    seed._add(WorkflowItem(workflow=month_end, ItemName="Reporting", job=shared, ItemOrder=9))
    db.commit()
    page.goto("/ui/workflow.html?key=MONTH_END")
    boxes(page)
    assert page.locator('#diagram .wf-box[data-name="Summary"]').count() == 0
    assert page.locator('#diagram .wf-box[data-name="Reporting"] .wf-fold').count() == 1

    page.locator('#diagram .wf-box[data-name="Reporting"] .wf-fold').click()

    page.wait_for_function("() => document.querySelector('#diagram .wf-box[data-name=\"Summary\"]')")
    inner = page.locator('#diagram .wf-box[data-name="Summary"]')
    assert inner.get_attribute("data-href").endswith("workflow.html?key=DEV_SHARED")           # a click opens its own page
    assert page.locator('#diagram .wf-frame[data-name="Reporting"]').get_attribute("class").endswith("wf-shared")


def test_find_looks_inside_frames_and_workflows_of_their_own_and_says_where(page, month_end, db, seed, sim):
    shared = seed._add(Job(JobKey="DEV_SHARED", JobType="WORKFLOW"))
    seed._add(WorkflowItem(workflow=shared, ItemName="Hidden_summary", job=sim("SUMMARY"), ItemOrder=1))
    seed._add(WorkflowItem(workflow=month_end, ItemName="Reporting", job=shared, ItemOrder=9))
    db.commit()
    page.goto("/ui/workflow.html?key=MONTH_END")
    boxes(page)
    page.locator('#diagram .wf-frame[data-name="Transform"] .wf-fold').click()           # Enrich is now folded away

    page.locator("#find").fill("rich")

    page.wait_for_function("() => document.querySelectorAll('#find-results button').length === 1")
    assert page.locator("#find-results button").inner_text() == "Transform / Enrich"
    assert "1 match inside" in page.locator('#diagram .wf-box[data-name="Transform"]').text_content()
    page.locator("#find-results button").click()                                          # Show matches: opens the way
    page.wait_for_function("() => document.querySelector('#diagram .wf-box[data-name=\"Enrich\"]')")
    page.locator("#find").fill("hidden")
    page.wait_for_function("() => document.querySelectorAll('#find-results button').length === 1")
    assert page.locator("#find-results button").inner_text() == "Reporting / Hidden_summary"
    page.locator("#find-results button").click()
    page.wait_for_function("() => document.querySelector('#diagram .wf-box[data-name=\"Hidden_summary\"]')")
    assert page.locator('#diagram .wf-box[data-name="Hidden_summary"] .wf-found').count() == 1


def test_a_workflow_others_wait_for_as_a_whole_shows_who_needs_it(page, month_end, db, seed, sim):
    other = seed._add(Job(JobKey="DOWNSTREAM", JobType="WORKFLOW"))
    late = seed._add(WorkflowItem(workflow=other, ItemName="Late", job=sim("LATE"), ItemOrder=1))
    seed._add(WorkflowPrerequisite(item=late, Kind="OTHER_JOB", target_workflow=month_end, TargetName="MONTH_END", Test="SUCCESS"))
    db.commit()

    page.goto("/ui/workflow.html?key=MONTH_END")

    page.locator("#workflow-needed-by").wait_for()
    assert "Late in DOWNSTREAM" in page.locator("#workflow-needed-by").inner_text()
    page.goto("/ui/workflow.html?key=DOWNSTREAM")
    page.locator("#workflow-key").wait_for()
    assert page.locator("#workflow-needed-by").count() == 1 and not page.locator("#workflow-needed-by").is_visible()


def test_an_embedded_job_opens_on_its_own_page_with_a_note_and_a_locked_key(page, month_end, db):
    us = db.query(Job).filter(Job.JobKey == "US").one()
    us.Owner_MasterObject_id = db.query(Job).filter(Job.JobKey == "MONTH_END.Extract").one().MasterObject_id      # embedded in Extract
    db.commit()
    page.goto("/ui/job.html?key=US")

    page.locator("#embedded-banner").wait_for()
    assert "Embedded in the workflow" in page.locator("#embedded-banner").inner_text()
    page.locator("#edit-button").click()
    assert page.locator("#job-key").is_disabled()
    assert not page.locator("#delete-button").is_visible()
    page.locator("#job-description").fill("The US extract")
    with page.expect_response(lambda r: "/api/v1/jobs/" in r.url and r.request.method == "PUT"):
        page.locator("#submit-button").click()
    page.locator("#save-notice").wait_for()
    db.expire_all()
    assert db.query(Job).filter(Job.JobKey == "US").one().Description == "The US extract"


def test_a_saved_tree_is_changed_in_place_one_save_covers_the_frames(page, month_end, db):
    page.add_init_script("localStorage.setItem('autoapp.workflow.view', 'outline')")
    page.goto("/ui/workflow.html?key=MONTH_END")
    page.locator("#edit-button").click()
    assert page.locator("#submit-button").is_disabled()                        # nothing changed yet: a round trip changes nothing

    extract = page.locator('#outline .wf-item[data-name="Extract"]')
    extract.locator(".add-inside-job").click()                                 # add a job inside a frame
    extract.locator(".item-name").fill("Pull")                                 # and rename it
    page.locator("#submit-button").click()
    page.locator("#save-notice").wait_for()

    notice = page.locator("#save-notice").inner_text()
    assert "renamed from 'Extract'" in notice and "Added 'Job' (embedded job)" in notice, notice
    db.expire_all()
    keys = sorted(k for (k,) in db.query(Job.JobKey).filter(Job.JobKey.like("MONTH_END.%")))
    assert keys == ["MONTH_END.Pull", "MONTH_END.Pull.Job", "MONTH_END.Transform"]          # the key followed the new name
    page.reload()
    page.locator('#outline .wf-item[data-name="Pull"]').wait_for()
    page.locator("#edit-button").click()
    assert page.locator("#submit-button").is_disabled()                        # and what was saved reads back unchanged
