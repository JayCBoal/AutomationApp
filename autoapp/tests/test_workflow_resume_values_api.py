"""
The plan and the API of a workflow's Resume values (docs/WORKFLOWS_PHASE7.md, step 4b-2): values listed by level, the
jobs that keep their values named, edits checked and put in the Audit Log, and Refresh and Edit passed on.
"""
import json

import pytest

from core.models import Audit
from test_launches import follow, get, post     # noqa: F401
from test_workflow_reopen import run_workflow
from test_workflow_runner import flow, results, sim, start    # noqa: F401  (fixtures)


@pytest.fixture
def valued(seed, flow, live_api, db):
    """Extract succeeds; Load fails while the workflow's Fail is True; Report waits for Load."""
    load, extract, report = seed.job("LOAD"), seed.job("EXTRACT"), seed.job("REPORT")
    seed.step(load, 1, "SIMULATE", title="Load", Fail="${Fail}", Messages="Region ${Region}")
    seed.step(extract, 1, "SIMULATE", title="Extract", Fail="False")
    seed.step(report, 1, "SIMULATE", title="Report", Fail="False")
    workflow = flow("WF", [("Extract", extract), ("Load", load, ["Extract"]), ("Report", report, ["Load"])])
    seed.set_vars(workflow, Fail="True", Region="EU")
    db.commit()
    return run_workflow(live_api, "WF", "UI-V1")


def plan_of(api, run):
    return get(f"{api}/api/v1/runs/{run['run_id']}/rerun-plan").json()


def rerun(api, run, kind="resume", **body):
    return post(f"{api}/api/v1/runs/{run['run_id']}/rerun", json={"kind": kind, **body})


def test_the_plan_lists_the_workflows_values_and_names_the_jobs_that_keep_theirs(valued, live_api):
    plan = plan_of(live_api, valued)

    workflow = next(l for l in plan["value_levels"] if l["kind"] == "workflow")
    assert (workflow["path"], workflow["name"]) == ("", "WF")
    assert {v["key"]: v["value"] for v in workflow["values"]} == {"Fail": "True", "Region": "EU"}
    assert plan["kept_jobs"] == ["Extract"]
    assert "not been decided" in plan["values_note"]


def test_a_value_the_job_got_from_the_workflow_is_listed_once(valued, live_api):
    plan = plan_of(live_api, valued)

    jobs = [l for l in plan["value_levels"] if l["kind"] == "job"]

    assert all(v["key"] not in ("Fail", "Region") for l in jobs for v in l["values"])


def test_an_edit_reaches_the_resumed_job_and_goes_in_the_audit_log(valued, live_api, db):
    response = rerun(live_api, valued, level_edits={"": {"workflow": {"Fail": "False"}}})
    assert response.status_code == 202, response.text
    _, run = follow(live_api, response.json())

    assert run["status"] == "SUCCESS"
    rows = db.query(Audit).filter(Audit.Action == "JOB_RESUMED_WITH_EDITS").all()
    assert len(rows) == 1
    assert json.loads(rows[0].Details)["changes"] == ["Resumed 'WF' with variable Fail changed from 'True' to 'False'."]


def test_an_edit_of_something_the_run_does_not_have_is_refused_and_nothing_is_recorded(valued, live_api, db):
    refused = rerun(live_api, valued, level_edits={"": {"workflow": {"Nope": "x"}}},
                    job_edits={"Report": {"Region": "x"}})

    assert refused.status_code == 422
    assert "Nope is not a variable of workflow 'WF'" in refused.text and "'Report' does not go on" in refused.text
    assert db.query(Audit).filter(Audit.Action == "JOB_RESUMED_WITH_EDITS").count() == 0


def test_a_restart_takes_no_values_choice(valued, live_api):
    refused = rerun(live_api, valued, kind="restart", refresh_values=True)

    assert refused.status_code == 422 and "restart reads them all again" in refused.text


def test_the_plan_says_which_values_now_read_differently_and_a_refresh_uses_them(valued, live_api, db):
    from core.models import Variable
    db.query(Variable).filter(Variable.VarName == "Fail").one().VarValue = "False"
    db.commit()

    workflow = next(l for l in plan_of(live_api, valued)["value_levels"] if l["kind"] == "workflow")
    assert workflow["changes"] == [{"key": "Fail", "was": "True", "now": "False"}]

    response = rerun(live_api, valued, refresh_values=True)
    assert response.status_code == 202, response.text
    assert follow(live_api, response.json())[1]["status"] == "SUCCESS"
