"""
Outside dependencies in the web interface (docs/WORKFLOWS_PHASE5.md, steps 4 and 5), in a real browser against a
real server: editing what a job waits for outside its workflow, the dashed boxes at the edges of the diagram, Needed
by, the condition box with outside names and time windows, and a run showing what it waited for.
"""
import pytest

from core.models import Job, WorkflowItem, WorkflowPrerequisite
from conftest import wait_for_search          # noqa: F401


@pytest.fixture(autouse=True)
def clear_view(page):
    page.add_init_script("localStorage.removeItem('autoapp.workflow.view')")


@pytest.fixture
def two(seed, db, tmp_path):
    """UP, with Extract; DOWN, with Load, which waits for UP's Extract. An endpoint INBOUND_ORDERS on this server."""
    for key in ("SIM_EXTRACT", "SIM_LOAD"):
        seed.step(seed.job(key), 1, "SIMULATE", title="Pretend")
    seed.endpoint("INBOUND_ORDERS", tmp_path / "in", "*.csv")
    db.commit()
    extract_job, load_job = (db.query(Job).filter(Job.JobKey == k).one() for k in ("SIM_EXTRACT", "SIM_LOAD"))
    up = seed._add(Job(JobKey="UP", JobType="WORKFLOW"))
    extract = seed._add(WorkflowItem(workflow=up, ItemName="Extract", job=extract_job, ItemOrder=1))
    down = seed._add(Job(JobKey="DOWN", JobType="WORKFLOW"))
    load = seed._add(WorkflowItem(workflow=down, ItemName="Load", job=load_job, ItemOrder=1))
    seed._add(WorkflowPrerequisite(item=load, Kind="OTHER_JOB", TargetName="UP.Extract", target=extract, WaitMode="MINUTES",
                                   WaitMinutes=30))
    db.commit()


def outline(page):
    page.locator("#view-outline").click()


def test_a_job_is_given_things_to_wait_for_outside_and_they_are_saved(page, two, db):
    page.goto("/ui/workflow.html?key=DOWN")
    outline(page)
    page.locator("#edit-button").click()
    page.locator(".add-outside-files").click()
    row = page.locator(".wf-outside-row").nth(1)
    row.locator(".outside-endpoint").fill("INBOUND_ORDERS")
    row.locator(".outside-pattern").fill("orders_*.csv")
    row.locator(".outside-min-age").fill("60")
    row.locator(".outside-wait-mode").select_option("NONE")
    page.locator(".add-outside-time").click()
    time_row = page.locator(".wf-outside-row").nth(2)
    time_row.locator(".cond-text-tab").click()
    time_row.locator(".cond-input").fill("%{Now.Time} BETWEEN '06:00' AND '18:00'")
    time_row.locator(".outside-wait-mode").select_option("MINUTES")
    time_row.locator(".outside-wait-minutes").fill("90")
    time_row.locator(".outside-required").uncheck()

    page.locator("#submit-button").click()
    page.locator("#save-notice").wait_for()

    assert page.locator("#save-notice").inner_text().startswith("Saved.")
    db.expire_all()
    load = db.query(WorkflowItem).filter(WorkflowItem.ItemName == "Load").one()
    rows = {p.TargetName: p for p in load.prerequisites}
    assert set(rows) == {"UP.Extract", "INBOUND_ORDERS", "Time"}
    files, window = rows["INBOUND_ORDERS"], rows["Time"]
    assert (files.Kind, files.endpoint.Name, files.FilePattern, files.MinAgeSeconds, files.WaitMode) == (
        "ENDPOINT", "INBOUND_ORDERS", "orders_*.csv", 60, "NONE")
    assert (window.Kind, window.TimeCondition, window.WaitMinutes, window.Required) == (
        "TIME", "%{Now.Time} BETWEEN '06:00' AND '18:00'", 90, False)
    words = page.locator(".wf-outside-words").inner_text()
    assert "files at INBOUND_ORDERS" in words and "each unchanged for 60 s" in words and "Optional; waits up to 90 minutes" in words


def test_the_job_box_offers_the_jobs_of_the_workflow_named(page, two):
    page.goto("/ui/workflow.html?key=DOWN")
    outline(page)
    page.locator("#edit-button").click()
    options = page.locator(".wf-outside-row").first.locator(".outside-job option")
    options.nth(1).wait_for(state="attached")
    assert [o.inner_text() for o in options.all()] == ["the workflow as a whole", "Extract"]


def test_a_wait_with_no_limit_warns_and_an_optional_one_needs_a_limit(page, two):
    page.goto("/ui/workflow.html?key=DOWN")
    outline(page)
    page.locator("#edit-button").click()
    row = page.locator(".wf-outside-row").first
    row.locator(".outside-wait-mode").select_option("NONE")
    assert "waits for ever" in row.locator(".outside-no-limit").inner_text()
    row.locator(".outside-required").uncheck()
    assert "needs one" in row.locator(".outside-optional-limit").inner_text()
    row.locator(".outside-no-limit").wait_for(state="hidden")


def test_a_refused_save_says_why(page_expecting_refusals, two):
    page = page_expecting_refusals
    page.goto("/ui/workflow.html?key=DOWN")
    outline(page)
    page.locator("#edit-button").click()
    page.locator(".outside-workflow").fill("NOPE")
    page.locator("#submit-button").click()
    page.locator("#page-error").wait_for()
    assert "which does not exist" in page.locator("#page-error").inner_text()


def test_the_diagram_draws_what_a_job_waits_for_outside_and_who_needs_it(page, two):
    page.goto("/ui/workflow.html?key=DOWN")
    page.locator("#diagram .wf-box").first.wait_for()
    outside = page.locator("#diagram .wf-box.wf-outside")
    assert outside.count() == 1
    assert outside.first.get_attribute("data-outside") == "JOB"
    assert "UP.Extract" in outside.first.text_content() and "in workflow UP" in outside.first.text_content()
    assert "EXTERNAL" in outside.first.text_content()
    assert "EXTERNAL" not in page.locator("#diagram .wf-box:not(.wf-outside)").first.text_content()
    page.goto("/ui/workflow.html?key=UP")
    needed = page.locator("#diagram .wf-box.wf-outside").first
    needed.wait_for()
    assert needed.get_attribute("data-outside") == "NEEDED"
    assert "Load" in needed.text_content() and "in workflow DOWN" in needed.text_content()
    assert page.locator('#diagram .wf-line[data-test="NEEDED"]').count() == 1


def test_files_and_times_are_icons_until_non_executable_dependencies_are_shown(page, two, seed, db):
    load = db.query(WorkflowItem).filter(WorkflowItem.ItemName == "Load").one()
    seed._add(WorkflowPrerequisite(item=load, Kind="TIME", TargetName="Window", TimeCondition="%{Now.Time} > '06:00'"))
    db.commit()
    page.goto("/ui/workflow.html?key=DOWN")
    page.locator("#diagram .wf-box.wf-outside").first.wait_for()
    assert not page.locator("#show-conditions").is_checked() and page.locator("#show-external").is_checked()
    assert [b.get_attribute("data-outside") for b in page.locator("#diagram .wf-box.wf-outside").all()] == ["JOB"]
    assert page.locator("#diagram .wf-box title", has_text="Waits for Window").count() == 1
    page.locator("#show-conditions").check()
    page.wait_for_function("() => document.querySelectorAll('#diagram .wf-box.wf-outside').length === 2")
    page.locator("#show-conditions").uncheck()
    page.locator("#show-external").uncheck()
    page.wait_for_function("() => !document.querySelector('#diagram .wf-box.wf-outside')")
    assert page.locator("#diagram .wf-box title", has_text="Waits for UP.Extract").count() == 1


def test_external_references_can_be_folded_into_icons_in_the_header_of_their_box(page, two):
    page.goto("/ui/workflow.html?key=DOWN")
    page.locator("#diagram .wf-box.wf-outside").first.wait_for()
    page.locator("#show-external").uncheck()
    page.wait_for_function("() => !document.querySelector('#diagram .wf-box.wf-outside')")
    assert page.locator("#diagram .wf-box").count() == 1
    assert page.locator("#diagram .wf-box title", has_text="Waits for UP.Extract").count() == 1
    page.reload()                                           # remembered in this browser
    page.locator("#diagram .wf-box").first.wait_for()
    assert not page.locator("#show-external").is_checked() and page.locator("#diagram .wf-box.wf-outside").count() == 0
    page.goto("/ui/workflow.html?key=UP")
    page.locator("#diagram .wf-box").first.wait_for()
    assert page.locator("#diagram .wf-box title", has_text="Needed by Load in workflow DOWN").count() == 1
    assert page.locator("#diagram .wf-line").count() == 0


def test_clicking_a_box_outside_opens_that_workflow(page, two):
    page.goto("/ui/workflow.html?key=DOWN")
    page.locator("#diagram .wf-box.wf-outside").first.click()
    page.wait_for_url("**/workflow.html?key=UP")
    page.locator("#diagram .wf-box").first.wait_for()


def test_the_outline_says_who_needs_a_job_and_what_it_waits_for_outside(page, two):
    page.goto("/ui/workflow.html?key=UP")
    outline(page)
    assert "Needed by" in page.locator(".wf-needed-by").inner_text()
    assert "Load in DOWN" in page.locator(".wf-needed-by").inner_text()
    page.goto("/ui/workflow.html?key=DOWN")
    outline(page)
    assert "UP.Extract (job Extract in workflow UP) succeeded" in page.locator("#outline .wf-needs").first.inner_text()
    assert "Required; waits up to 30 minutes" in page.locator(".wf-outside-words").inner_text()


def test_files_and_a_time_are_dashed_boxes_with_their_own_icons(page, two, seed, db):
    page.add_init_script("localStorage.setItem('autoapp.workflow.conditions', 'shown')")
    load = db.query(WorkflowItem).filter(WorkflowItem.ItemName == "Load").one()
    endpoint = db.query(WorkflowPrerequisite).filter(WorkflowPrerequisite.Kind == "OTHER_JOB").count()
    assert endpoint == 1
    from core.models import Endpoint
    inbound = db.query(Endpoint).filter(Endpoint.Name == "INBOUND_ORDERS").one()
    seed._add(WorkflowPrerequisite(item=load, Kind="ENDPOINT", TargetName="INBOUND_ORDERS",
                                   Endpoint_MasterObject_id=inbound.MasterObject_id, MinAgeSeconds=60))
    seed._add(WorkflowPrerequisite(item=load, Kind="TIME", TargetName="Window", TimeCondition="%{Now.Time} > '06:00'"))
    seed._add(WorkflowPrerequisite(item=load, Kind="TIME", TargetName="Day", TimeCondition="%{Now.Weekday} = 'Monday'"))
    db.commit()
    page.goto("/ui/workflow.html?key=DOWN")
    page.locator("#diagram .wf-box").first.wait_for()
    kinds = sorted(b.get_attribute("data-outside") for b in page.locator("#diagram .wf-box.wf-outside").all())
    assert kinds == ["FILES", "JOB", "TIME", "TIME"]
    assert [t for t in (b.text_content() for b in page.locator("#diagram .wf-box.wf-outside").all()) if "EXTERNAL" in t]
    assert any("FILES" in b.text_content() for b in page.locator('#diagram .wf-box[data-outside="FILES"]').all())
    assert all("EXTERNAL" not in b.text_content() for b in page.locator('#diagram .wf-box[data-outside="TIME"]').all())
    tests = sorted(line.get_attribute("data-test") for line in page.locator("#diagram .wf-line").all())
    assert tests == ["FILES", "SUCCESS", "TIME", "TIME"]
    page.locator("#diagram .wf-box.wf-outside[data-outside=TIME] >> nth=0").click()          # selects the job they belong to
    page.locator("#side").wait_for(state="visible")


# ---------- The condition box ----------

def open_rule(page):
    page.goto("/ui/workflow.html?key=DOWN")
    outline(page)
    page.locator("#edit-button").click()
    page.locator(".item-join").select_option("CUSTOM")
    return page.locator(".wf-rule")


def test_the_condition_box_offers_the_outside_names_and_the_time(page, two):
    rule = open_rule(page)
    rule.locator(".cond-help-toggle").click()
    help_text = rule.locator(".cond-help").inner_text()
    assert "UP.Extract" in help_text and "Now" in help_text
    for output in ("Time", "Date", "Weekday"):
        assert output in help_text
    rule.locator(".cond-text-tab").click()
    rule.locator(".cond-input").fill("%{UP.Extract.Succeeded} AND %{Now.Weekday} <> 'Sunday'")
    page.wait_for_timeout(800)
    assert rule.locator(".cond-problems").is_hidden()


def test_a_rule_naming_an_unknown_outside_name_is_flagged_as_typed(page, two):
    rule = open_rule(page)
    rule.locator(".cond-text-tab").click()
    rule.locator(".cond-input").fill("%{UP.Nothing.Succeeded}")
    rule.locator(".cond-problems").wait_for()
    assert "no job in this workflow is named" in rule.locator(".cond-problems").inner_text()


def test_the_builder_shows_a_window_across_midnight(page, two):
    rule = open_rule(page)
    rule.locator(".cond-text-tab").click()
    rule.locator(".cond-input").fill("%{Now.Time} IN WINDOW '18:00' TO '06:00'")
    rule.locator(".cond-builder-tab").click()
    row = rule.locator(".cond-row").first
    assert row.locator(".cond-op").input_value() == "WINDOW"
    assert (row.locator(".cond-value").input_value(), row.locator(".cond-value2").input_value()) == ("18:00", "06:00")
    assert row.locator(".cond-next-day").is_visible()
    row.locator(".cond-value2").fill("23:00")
    row.locator(".cond-next-day").wait_for(state="hidden")
    assert rule.locator(".cond-written").inner_text() == "%{Now.Time} IN WINDOW '18:00' TO '23:00'"


def test_the_builder_shows_between_and_keeps_its_and(page, two):
    rule = open_rule(page)
    rule.locator(".cond-text-tab").click()
    rule.locator(".cond-input").fill("%{Now.Time} BETWEEN '06:00' AND '18:00' AND %{UP.Extract.Succeeded}")
    rule.locator(".cond-builder-tab").click()
    rows = rule.locator(".cond-row")
    assert rows.count() == 2
    assert rows.first.locator(".cond-op").input_value() == "BETWEEN"
    assert rows.nth(1).locator(".cond-subject").input_value() == "%{UP.Extract.Succeeded}"


# ---------- A run ----------

def test_a_run_shows_what_the_job_waited_for_outside(page, seed, db):
    page.add_init_script("localStorage.setItem('autoapp.workflow.conditions', 'shown')")
    seed.step(seed.job("SIM_TIMED"), 1, "SIMULATE", title="Pretend")
    db.commit()
    job = db.query(Job).filter(Job.JobKey == "SIM_TIMED").one()
    flow = seed._add(Job(JobKey="TIMED", JobType="WORKFLOW"))
    item = seed._add(WorkflowItem(workflow=flow, ItemName="Report", job=job, ItemOrder=1))
    seed._add(WorkflowPrerequisite(item=item, Kind="TIME", TargetName="Window", TimeCondition="%{Now.Date} > '2000-01-01'"))
    db.commit()
    page.goto("/ui/workflow.html?key=TIMED")
    page.locator("#run-button").click()
    page.wait_for_function(
        "() => (document.querySelector('#run-status')?.textContent || '').startsWith('Succeeded')", timeout=60000)
    box = page.locator("#run-diagram .wf-box.wf-outside")
    box.wait_for()
    assert box.get_attribute("data-outside") == "TIME" and box.get_attribute("data-status") == "SUCCESS"
    page.locator("#run-diagram .wf-box:not(.wf-outside)").click()
    held = page.locator("#run-side .run-outside")
    held.wait_for()
    assert "held:" in held.inner_text() and "is true" in held.inner_text()
