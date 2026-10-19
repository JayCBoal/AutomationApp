"""
Conditions in the web interface (docs/WORKFLOWS_PHASE4.md), in a real browser against a real
server: a Custom rule written with the builder and as text, checked as it is typed; a rename
carried into the rule; the completion rules; a run explaining its decisions; the condition box
on a step's condition in the job editor.
"""
import pytest

from app.models import Job, WorkflowItem, WorkflowPrerequisite


@pytest.fixture(autouse=True)
def outline_view(page):
    page.add_init_script("localStorage.setItem('autoapp.workflow.view', 'outline')")


@pytest.fixture
def jobs(seed, db):
    """LOAD (return code 4, a success), CHECK, REPORT; and FLOW: Load and Check, then Report after Load."""
    for key, params in (("LOAD", {"ReturnCode": "4"}), ("CHECK", {}), ("REPORT", {})):
        job = seed.job(key)
        job.SuccessReturnCodes = "0,4" if key == "LOAD" else None
        seed.step(job, 1, "SIMULATE", title="Pretend", **params)
    load, check, report = (db.query(Job).filter(Job.JobKey == k).one() for k in ("LOAD", "CHECK", "REPORT"))
    flow = seed._add(Job(JobKey="FLOW", JobType="WORKFLOW"))
    first = seed._add(WorkflowItem(workflow=flow, ItemName="Load", job=load, ItemOrder=1))
    seed._add(WorkflowItem(workflow=flow, ItemName="Check", job=check, ItemOrder=2))
    third = seed._add(WorkflowItem(workflow=flow, ItemName="Report", job=report, ItemOrder=3))
    seed._add(WorkflowPrerequisite(item=third, target=first, Test="SUCCESS"))
    db.commit()


def report_item(page):
    return page.locator(".wf-item[data-name='Report']")


def save(page):
    page.locator("#submit-button").click()
    page.locator("#save-notice").wait_for()


def test_a_custom_rule_starts_from_what_the_job_waited_for_and_is_built_with_rows(page, jobs, db):
    page.goto("/ui/workflow.html?key=FLOW")
    page.locator("#edit-button").click()
    item = report_item(page)
    item.locator(".item-join").select_option("CUSTOM")
    box = item.locator(".cond-box")
    assert box.locator(".cond-written").inner_text() == "%{Load.Succeeded}"     # from its prerequisite

    box.locator(".cond-group-join").select_option("OR")                        # Match any of the following
    box.locator(".cond-add-row").click()
    box.locator(".cond-subject").nth(1).select_option("%{Check.ReturnCode}")
    box.locator(".cond-op").nth(1).select_option(">=")
    box.locator(".cond-value").nth(1).fill("4")
    assert box.locator(".cond-written").inner_text() == "%{Load.Succeeded} OR %{Check.ReturnCode} >= 4"

    save(page)
    db.expire_all()
    report = db.query(WorkflowItem).filter(WorkflowItem.ItemName == "Report").one()
    assert (report.JoinRule, report.StartRule) == ("CUSTOM", "%{Load.Succeeded} OR %{Check.ReturnCode} >= 4")
    assert sorted((p.target.ItemName, p.Test) for p in report.prerequisites) == [("Check", "RULE"), ("Load", "RULE")]
    assert "Starts when its Custom rule holds" in report_item(page).locator(".wf-needs").inner_text()


def test_a_rule_typed_as_text_is_checked_as_it_is_typed_and_a_rename_follows(page, jobs, db):
    page.goto("/ui/workflow.html?key=FLOW")
    page.locator("#edit-button").click()
    item = report_item(page)
    item.locator(".item-join").select_option("CUSTOM")
    box = item.locator(".cond-box")
    box.locator(".cond-text-tab").click()
    box.locator(".cond-input").fill("%{Lod.Succeeded} AND")
    page.wait_for_function("() => document.querySelector('.wf-item[data-name=\"Report\"] .cond-problems')?.textContent.includes('no job in this workflow is named Lod')")
    box.locator(".cond-input").fill("%{Load.Succeeded} AND %{Load.Reason} IS NULL")
    box.locator(".cond-builder-tab").click()                                  # IS NULL: the builder cannot show it
    assert "Edited as text" in box.locator(".cond-as-text").inner_text()

    page.locator(".wf-item[data-name='Load'] .item-name").fill("Extract")
    page.locator(".wf-item[data-name='Extract'] .item-name").blur()
    assert box.locator(".cond-input").input_value() == "%{Extract.Succeeded} AND %{Extract.Reason} IS NULL"
    save(page)
    db.expire_all()
    assert db.query(WorkflowItem).filter(WorkflowItem.ItemName == "Report").one().StartRule == \
        "%{Extract.Succeeded} AND %{Extract.Reason} IS NULL"


def test_completion_rules_are_set_and_a_run_explains_its_decisions(page, jobs, db):
    page.goto("/ui/workflow.html?key=FLOW")
    page.locator("#edit-button").click()
    report_item(page).locator(".item-join").select_option("CUSTOM")
    report_item(page).locator(".cond-box .cond-subject").first.select_option("%{Load.ReturnCode}")
    report_item(page).locator(".cond-box .cond-op").first.select_option("=")
    report_item(page).locator(".cond-box .cond-value").first.fill("0")         # Load gives 4: Report does not run
    page.locator("#succeeds-choice").select_option("RULE")
    panel = page.locator("#completion-panel")
    panel.locator(".cond-subject").first.select_option("%{Check.Succeeded}")
    page.locator("#return-code-from").select_option("Load")
    save(page)
    db.expire_all()
    flow = db.query(Job).filter(Job.JobKey == "FLOW").one()
    assert (flow.SucceedsWhen, flow.ReturnCodeFrom) == ("%{Check.Succeeded}", "Load")

    page.locator("#run-button").click()
    page.wait_for_function(
        "() => ['Succeeded', 'Failed'].some(w => (document.querySelector('#run-status')?.textContent || '').startsWith(w))",
        timeout=60000)
    assert page.locator("#run-status").inner_text().startswith("Succeeded")
    assert "Succeeds when held" in page.locator(".run-succeeds-when").inner_text()
    assert page.locator("#run-items .wf-row[data-name='Report'] .run-rule-words").inner_text() == "Custom rule did not hold"


def test_explain_now_works_a_rule_out_with_a_past_run(page, jobs, db):
    page.goto("/ui/workflow.html?key=FLOW")
    page.locator("#run-button").click()
    page.wait_for_function(
        "() => ['Succeeded', 'Failed'].some(w => (document.querySelector('#run-status')?.textContent || '').startsWith(w))",
        timeout=60000)
    page.locator("#run-panel button.link:has-text('Close')").click()
    page.locator("#edit-button").click()
    item = report_item(page)
    item.locator(".item-join").select_option("CUSTOM")
    box = item.locator(".cond-box")
    box.locator(".cond-text-tab").click()
    box.locator(".cond-input").fill("%{Load.ReturnCode} = 4 OR %{Check.Failed}")
    box.locator(".cond-explain-button").click()
    tree = box.locator(".cond-tree li")
    tree.first.wait_for()
    assert tree.all_inner_texts() == ["holds (any of): %{Load.ReturnCode} = 4 OR %{Check.Failed}",
                                      "holds: %{Load.ReturnCode} = 4", "does not hold: %{Check.Failed}"]


def test_a_steps_condition_has_the_builder_and_the_names_it_can_use(page, seed, db):
    job = seed.job("BRANCHY")
    seed.step(job, 1, "CHECK_FILES", title="Check files", name="Check_files", Location="incoming/*.csv")
    seed.step(job, 2, "IF", title="If any", Condition="%{Check_files.FileCount} > 0")
    db.commit()
    page.goto("/ui/job.html?key=BRANCHY")
    page.locator("#edit-button").click()
    step = page.locator(".step").nth(1)
    step.locator(".expander").click()
    box = step.locator(".cond-box").first
    assert box.locator(".cond-written").inner_text() == "%{Check_files.FileCount} > 0"
    box.locator(".cond-op").first.select_option(">=")
    assert box.locator(".cond-written").inner_text() == "%{Check_files.FileCount} >= 0"
    box.locator(".cond-help-toggle").click()
    assert "FileCount" in box.locator(".cond-help").inner_text()


def test_groups_nest_to_any_depth_each_written_in_brackets(page, jobs):
    page.goto("/ui/workflow.html?key=FLOW")
    page.locator("#edit-button").click()
    item = report_item(page)
    item.locator(".item-join").select_option("CUSTOM")
    box = item.locator(".cond-box")
    box.locator(".cond-add-group").first.click()                 # inside "all": a group of "any"
    assert box.locator(".cond-group-join").nth(1).input_value() == "OR"
    inner = box.locator(".cond-line-row").nth(1)
    inner.locator(".cond-subject").select_option("%{Check.Succeeded}")
    box.locator(".cond-add-row").nth(0).click()                  # + Condition in the inner group (its buttons come first)
    box.locator(".cond-line-row").nth(2).locator(".cond-subject").select_option("%{Check.ReturnCode}")
    box.locator(".cond-line-row").nth(2).locator(".cond-op").select_option("=")
    box.locator(".cond-line-row").nth(2).locator(".cond-value").fill("4")
    assert box.locator(".cond-written").inner_text() == "%{Load.Succeeded} AND (%{Check.Succeeded} OR %{Check.ReturnCode} = 4)"

    box.locator(".cond-text-tab").click()                        # three levels, typed, open in the builder
    box.locator(".cond-input").fill("%{Load.Failed} OR (%{Check.Succeeded} AND (%{Load.ReturnCode} = 4 OR %{Load.ReturnCode} = 8))")
    box.locator(".cond-builder-tab").click()
    assert box.locator(".cond-head").count() == 3
    assert [s.input_value() for s in box.locator(".cond-group-join").all()] == ["OR", "AND", "OR"]


def test_nested_rows_wrap_to_stay_inside_the_job_pane(page, jobs):
    page.add_init_script("localStorage.setItem('autoapp.workflow.view', 'diagram')")
    page.goto("/ui/workflow.html?key=FLOW")
    page.locator("#diagram .wf-box").first.wait_for()
    page.locator("#edit-button").click()
    page.locator("#diagram .wf-box[data-name='Report']").click()
    item = page.locator("#side .wf-item:visible")
    item.locator(".item-join").select_option("CUSTOM")
    box = item.locator(".cond-box")
    box.locator(".cond-text-tab").click()
    box.locator(".cond-input").fill("%{Load.Failed} OR (%{Check.Succeeded} AND (%{Load.ReturnCode} = 4 OR (%{Load.FileCount} > 1 AND %{Check.Ended})))")
    box.locator(".cond-builder-tab").click()
    pane = page.locator("#side").bounding_box()
    for link in box.locator(".cond-remove-row").all():
        edge = link.bounding_box()
        assert edge["x"] + edge["width"] <= pane["x"] + pane["width"], "a Remove link sticks out of the pane"
