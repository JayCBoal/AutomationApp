"""
The values of a Resume (docs/WORKFLOWS_PHASE7.md, step 2b): a picked-up run uses the ${...} values as the
first attempt had them, unless the operator refreshes them (reads them again) or edits some.
"""
import json

import pytest

from app.models import Audit, Variable
from engine import run_values
from engine.scope_engine import ScopeResolutionEngine
from test_control_file import attempt, control_of, gated_job, log_of, put_gate    # noqa: F401 (attempt is a fixture)
from test_launches import follow, get, post
from test_reruns import run_and_wait


@pytest.fixture
def valued(seed, endpoints, db):
    job = gated_job(seed, name="RES")
    seed.set_vars(job, Region="EU", Prefix="x-${Region}")
    db.add(Variable(MasterObject_id=job.MasterObject_id, VarName="Token", VarValue="s3cret-token", IsSecret=True))
    from app.models import JobStep, JobStepParameter
    report = db.query(JobStep).filter(JobStep.job_id == job.MasterObject_id, JobStep.Title == "Report").one()
    for parameter in db.query(JobStepParameter).filter(JobStepParameter.job_step_id == report.id, JobStepParameter.ParamName == "Messages"):
        parameter.ParamValue = "Region ${Region} prefix ${Prefix} token ${Token}"
    db.commit()
    return job


def change_region(db, value):
    db.query(Variable).filter(Variable.VarName == "Region").one().VarValue = value
    db.commit()


# ---------- What the control file keeps ----------

def test_the_control_file_keeps_the_values_the_job_used_and_a_secret_only_by_name(valued, attempt, tmp_path):
    first, _ = attempt("RES")

    values = control_of(tmp_path, first).values

    assert values["Region"] == {"value": "EU"}
    assert values["Prefix"] == {"value": "x-EU"}                    # with the placeholder inside it filled in
    assert values["Token"] == {"secret": True}
    control_text = next((tmp_path / "logs").rglob(f"{first}.control")).read_text()
    assert "s3cret-token" not in control_text


# ---------- Use as they were, Refresh, Edit ----------

def test_a_resume_uses_the_values_as_they_were_even_if_a_variable_has_changed(valued, db, attempt, tmp_path):
    first, _ = attempt("RES")
    put_gate(tmp_path, "a.ok")
    change_region(db, "US")

    second, resumed = attempt("RES", "--resume-run-id", first)

    assert resumed.returncode == 0, resumed.stderr
    assert "Region EU prefix x-EU" in log_of(tmp_path, second)
    assert "Refreshed" not in log_of(tmp_path, second)


def test_a_refresh_reads_changed_variables_again_and_the_log_says_which_changed(valued, db, attempt, tmp_path):
    first, _ = attempt("RES")
    put_gate(tmp_path, "a.ok")
    change_region(db, "US")

    second, resumed = attempt("RES", "--resume-run-id", first, "--refresh-values")

    assert resumed.returncode == 0, resumed.stderr
    log = log_of(tmp_path, second)
    assert "Region US prefix x-US" in log
    assert "Refreshed Region: it was 'EU', it is now 'US'." in log


def test_an_edit_replaces_one_value_and_leaves_the_others_as_they_were(valued, db, attempt, tmp_path):
    first, _ = attempt("RES")
    put_gate(tmp_path, "a.ok")
    change_region(db, "US")

    second, resumed = attempt("RES", "--resume-run-id", first, "--edit-values", json.dumps({"Region": "AU"}))

    assert resumed.returncode == 0, resumed.stderr
    log = log_of(tmp_path, second)
    assert "Region AU prefix x-EU" in log                           # Prefix keeps the text it had
    assert "Edited Region: it was 'EU', the operator set 'AU'." in log


def test_a_secret_is_read_again_by_a_resume(valued, db, attempt, tmp_path):
    first, _ = attempt("RES")
    put_gate(tmp_path, "a.ok")
    db.query(Variable).filter(Variable.VarName == "Token").one().VarValue = "new-token"
    db.commit()

    second, resumed = attempt("RES", "--resume-run-id", first)

    assert resumed.returncode == 0, resumed.stderr
    assert "token ********" in log_of(tmp_path, second)


# ---------- The scope engine ----------

def test_a_pinned_value_stands_in_for_what_a_placeholder_would_resolve_to(seed, db):
    job = seed.job("PIN", Region="EU")
    db.commit()
    engine = ScopeResolutionEngine(db=db, job_id=job.MasterObject_id, instance_id="I", environment={"HOME": "/h"},
                                   pinned={"Region": "AU", "ENV:HOME": "/old"})
    engine.build_context()

    assert engine.interpolate("${Region} ${ENV:HOME} ${JOB.Region}") == "AU /old EU"
    assert set(engine.used) == {"Region", "ENV:HOME", "JOB.Region"}


# ---------- The API ----------

def test_the_plan_lists_the_values_and_says_which_read_differently_now(live_api, valued, db, tmp_path):
    _, first = run_and_wait(live_api, "RES", "UI-V1")
    url = f"{live_api}/api/v1/runs/{first['run_id']}/rerun-plan"

    plan = get(url).json()
    assert {v["key"]: (v["value"], v["secret"]) for v in plan["values"]}["Region"] == ("EU", False)
    assert {v["key"]: v["secret"] for v in plan["values"]}["Token"] is True
    assert plan["changes"] == []

    change_region(db, "US")
    changes = get(url).json()["changes"]
    assert {c["key"]: (c["was"], c["now"]) for c in changes} == {"Region": ("EU", "US"), "Prefix": ("x-EU", "x-US")}


def test_a_resume_through_the_api_can_refresh_or_edit(live_api, valued, db, tmp_path):
    _, first = run_and_wait(live_api, "RES", "UI-V2")
    put_gate(tmp_path, "a.ok", job="RES")
    change_region(db, "US")

    response = post(f"{live_api}/api/v1/runs/{first['run_id']}/rerun",
                    json={"kind": "resume", "refresh_values": True, "edits": {"Prefix": "p-1"}})
    assert response.status_code == 202, response.text
    _, second = follow(live_api, response.json())

    assert second["status"] == "SUCCESS"
    assert any("Region US prefix p-1" in line for line in second["log"])
    audit = db.query(Audit).filter(Audit.Action == "JOB_RESUMED_WITH_EDITS").one()
    assert "Prefix changed from 'x-EU' to 'p-1'" in audit.Details


def test_a_secret_cannot_be_edited_and_a_restart_takes_no_value_choices(live_api, valued, db):
    _, first = run_and_wait(live_api, "RES", "UI-V3")
    url = f"{live_api}/api/v1/runs/{first['run_id']}/rerun"

    secret = post(url, json={"kind": "resume", "edits": {"Token": "mine"}})
    unused = post(url, json={"kind": "resume", "edits": {"Nope": "1"}})
    restart = post(url, json={"kind": "restart", "refresh_values": True})

    assert secret.status_code == 422 and "always read" in secret.text
    assert unused.status_code == 422 and "was not used" in unused.text
    assert restart.status_code == 422
    assert db.query(Audit).filter(Audit.Action == "JOB_RESUMED_WITH_EDITS").count() == 0


# ---------- The dialog ----------

def run_to_failure(page):
    page.goto("/ui/run.html?key=RES")
    page.locator("#run-check .status").wait_for()
    page.locator("#run-button").click()
    page.wait_for_function("() => document.querySelector('#run-outcome')?.textContent === 'Failed'", timeout=30000)


def test_the_dialog_offers_the_values_and_refresh_says_what_changed(page, valued, db, tmp_path):
    run_to_failure(page)
    change_region(db, "US")
    page.locator("#rerun-button").click()

    assert page.get_by_label("Use as they were").is_checked()
    assert "Region" in page.locator("#rerun-value-list").inner_text()
    assert "a secret" in page.locator("#rerun-value-list").inner_text()
    assert "s3cret-token" not in page.locator("#rerun-values").inner_text()
    assert not page.locator("#rerun-refresh-changes").is_visible()

    page.get_by_label("Refresh").check()
    notice = page.locator("#rerun-refresh-changes").inner_text()
    assert "Region" in notice and "EU" in notice and "US" in notice


def test_an_edit_in_the_dialog_is_used_by_the_resume(page, valued, tmp_path):
    run_to_failure(page)
    put_gate(tmp_path, "a.ok", job="RES")
    page.locator("#rerun-button").click()
    page.get_by_label("Edit").check()
    page.get_by_label("Value of Region").fill("AU")
    page.locator("#rerun-resume").click()

    page.wait_for_function("() => document.querySelector('#run-outcome')?.textContent === 'Succeeded'", timeout=30000)
    page.wait_for_function("() => document.querySelector('#job-log').textContent.includes('Region AU prefix x-EU')")
