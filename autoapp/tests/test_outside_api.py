"""
Workflows Phase 5, step 3: saving a job's prerequisites on something outside its workflow, and what is
refused (docs/WORKFLOWS_PHASE5.md). A workflow is a job of type WORKFLOW saved through /api/v1/jobs.
"""
import pytest

from test_workflows_api import ROUTE, item, save, workflow, working_root          # noqa: F401  (fixtures)


@pytest.fixture
def jobs(seed, db, tmp_path):
    """Jobs to put in workflows, and an endpoint on this server."""
    for key in ("EXT", "LOAD", "REPORT"):
        seed.step(seed.job(key), 1, Source="incoming/*.csv", Dest="outgoing")
    seed.endpoint("INBOUND_ORDERS", tmp_path / "in", "*.csv")
    db.commit()


def outside(kind, target="", **more):
    return {"kind": kind, "target": target, **more}


def other_job(workflow_key="UP", job="Extract", **more):
    return outside("OTHER_JOB", workflow=workflow_key, job=job, **more)


def two_workflows(client):
    """UP, with Extract; DOWN, whose Load waits for UP's Extract."""
    assert save(client, workflow("UP", [item("EXT", "Extract")])).status_code == 201
    down = workflow("DOWN", [item("LOAD", "Load", after=[other_job(wait_mode="MINUTES", wait_minutes=30)])])
    response = save(client, down)
    assert response.status_code == 201, response.text
    return response.json()["job"]


def resave(client, key, items):
    """Saves the workflow again with these items, each keeping the id of the one it replaces (by name)."""
    ids = {i["name"]: i["id"] for i in client.get(f"{ROUTE}/{key}").json()["items"]}
    return client.put(f"{ROUTE}/{key}", json={"job_key": key, "job_type": "WORKFLOW", "items": [
        {**i, **({"id": ids[i["name"]]} if i.get("name") in ids else {})} for i in items]})


def prerequisites(saved, name="Load"):
    return next(i for i in saved["items"] if i["name"] == name)["prerequisites"]


def refusal(response):
    assert response.status_code == 422, response.text
    return response.json()["detail"]


# ---------- Saving and reading ----------

def test_a_job_can_wait_for_a_job_in_another_workflow(client, jobs):
    saved = two_workflows(client)
    (p,) = prerequisites(saved)
    assert (p["kind"], p["target"], p["workflow"], p["job"], p["wait_mode"], p["wait_minutes"], p["required"]) == (
        "OTHER_JOB", "UP.Extract", "UP", "Extract", "MINUTES", 30, True)
    up = client.get(f"{ROUTE}/UP").json()
    assert up["items"][0]["needed_by"] == [{"workflow": "DOWN", "job": "Load"}]


def test_all_four_kinds_of_prerequisite_are_saved_and_read_back(client, jobs):
    save(client, workflow("UP", [item("EXT", "Extract")]))
    after = [{"kind": "JOB", "target": "Prep"},
             other_job(look_back_hours=24, only_after_start=True, test="RC", return_codes="0,4",
                       wait_mode="UNTIL", wait_until="03:00"),
             outside("ENDPOINT", endpoint="INBOUND_ORDERS", min_age_seconds=60, file_pattern="orders_*.csv",
                     wait_mode="NONE"),
             outside("TIME", "Window", time_condition="%{Now.Time} IN WINDOW '18:00' TO '06:00'", required=False,
                     wait_mode="MINUTES", wait_minutes=90, wait_from="CHOSEN", wait_from_target="Prep")]
    saved = save(client, workflow("DOWN", [item("REPORT", "Prep"), item("LOAD", "Load", after=after)])).json()["job"]
    by_name = {p["target"]: p for p in prerequisites(saved)}
    assert set(by_name) == {"Prep", "UP.Extract", "INBOUND_ORDERS", "Window"}
    assert by_name["UP.Extract"]["return_codes"] == "0, 4" and by_name["UP.Extract"]["only_after_start"]
    assert (by_name["INBOUND_ORDERS"]["endpoint"], by_name["INBOUND_ORDERS"]["min_age_seconds"],
            by_name["INBOUND_ORDERS"]["file_pattern"]) == ("INBOUND_ORDERS", 60, "orders_*.csv")
    assert (by_name["Window"]["required"], by_name["Window"]["wait_from_target"]) == (False, "Prep")


def test_saving_again_what_was_read_changes_nothing(client, jobs):
    saved = two_workflows(client)
    again = client.put(f"{ROUTE}/DOWN", json={"job_key": "DOWN", "job_type": "WORKFLOW", "description": "Month end", "items": [
        {"id": i["id"], "name": i["name"], "job_key": i["job_key"], "join": i["join"], "prerequisites": i["prerequisites"]}
        for i in saved["items"]]})
    assert again.status_code == 200 and again.json()["changes"] == []


def test_something_outside_is_named_from_what_it_is_and_numbered_where_names_clash(client, jobs):
    save(client, workflow("UP", [item("EXT", "Extract")]))
    after = [other_job(), other_job(), outside("ENDPOINT", endpoint="INBOUND_ORDERS"),
             outside("TIME", time_condition=ALWAYS), outside("TIME", time_condition=ALWAYS)]
    saved = save(client, workflow("DOWN", [item("LOAD", "Load", after=after)])).json()["job"]
    assert [p["target"] for p in prerequisites(saved)] == ["UP.Extract", "UP.Extract2", "INBOUND_ORDERS", "Time", "Time2"]


ALWAYS = "%{Now.Date} > '2000-01-01'"


def test_a_job_that_cannot_start_can_be_set_to_fail(client, jobs):
    saved = save(client, workflow("DOWN", [item("LOAD", "Load", on_unmet="FAIL")])).json()["job"]
    assert saved["items"][0]["on_unmet"] == "FAIL"
    assert refusal(save(client, workflow("DOWN2", [item("LOAD", "Load", on_unmet="HOLD")]))).startswith("'Load': when it cannot start")


# ---------- What is refused ----------

@pytest.mark.parametrize("prerequisite, words", [
    (other_job("NOPE"), "in the workflow 'NOPE', which does not exist"),
    (other_job("EXT"), "'EXT' is a job, not a workflow"),
    (other_job("UP", "Nothing"), "the workflow 'UP' has no job named 'Nothing'"),
    (other_job("DOWN", "Load"), "a job of this same workflow"),
    (outside("ENDPOINT", endpoint="NOWHERE"), "the endpoint 'NOWHERE', which is not registered"),
    (outside("TIME", time_condition=" "), "the time condition is empty"),
    (outside("TIME", time_condition="1 = 1"), "does not look at the time"),
    (outside("TIME", time_condition="%{Now.Hour} = 1"), "the time has Time, Date, Weekday"),
    (outside("TIME", time_condition=ALWAYS, wait_mode="MINUTES"), "give the number of minutes"),
    (outside("TIME", time_condition=ALWAYS, wait_mode="UNTIL", wait_until="25:00"), "give the time to wait until"),
    (outside("TIME", time_condition=ALWAYS, wait_mode="LATER"), "must be DEFAULT, NONE, MINUTES or UNTIL"),
    (outside("TIME", time_condition=ALWAYS, required=False, wait_mode="NONE"), "needs one"),
    (outside("TIME", time_condition=ALWAYS, wait_from="CHOSEN", wait_from_target="Nobody"), "not another prerequisite"),
    (outside("TIME", "Load", time_condition=ALWAYS), "already used by a job in the workflow"),
    (outside("TIME", "Now", time_condition=ALWAYS), "Now is the time"),
    (outside("TIME", "bad name", time_condition=ALWAYS), "cannot be the name of something it waits for"),
    (other_job(test="MAYBE"), "The test must be SUCCESS, FAILED, ENDED or RC"),
])
def test_a_prerequisite_that_cannot_work_is_refused_saying_why(client, jobs, prerequisite, words):
    save(client, workflow("UP", [item("EXT", "Extract")]))
    detail = refusal(save(client, workflow("DOWN", [item("LOAD", "Load", after=[prerequisite])])))
    assert words in detail


def test_two_things_with_the_same_name_are_refused(client, jobs):
    after = [outside("TIME", "Window", time_condition=ALWAYS), outside("TIME", "Window", time_condition=ALWAYS)]
    assert "both named 'Window'" in refusal(save(client, workflow("DOWN", [item("LOAD", "Load", after=after)])))


def test_a_job_cannot_be_called_now(client, jobs):
    assert "'Now' cannot be the name" in refusal(save(client, workflow("DOWN", [item("LOAD", "Now")])))


def test_waits_that_go_round_between_workflows_are_refused_naming_the_path(client, jobs):
    two_workflows(client)
    detail = refusal(resave(client, "UP", [item("EXT", "Extract", after=[other_job("DOWN", "Load")])]))
    assert "loop between workflows" in detail
    assert "'UP: Extract'" in detail and "'DOWN: Load'" in detail and "which waits for" in detail
    assert "Rerun from" in detail


def test_waiting_for_a_whole_workflow_that_waits_for_you_is_a_loop_too(client, jobs):
    save(client, workflow("UP", [item("EXT", "Extract")]))
    save(client, workflow("DOWN", [item("LOAD", "Load", after=[outside("OTHER_JOB", workflow="UP")])]))
    assert "loop between workflows" in refusal(resave(client, "UP", [item("EXT", "Extract", after=[other_job("DOWN", "Load")])]))


def test_two_workflows_waiting_for_different_jobs_of_each_other_are_not_a_loop(client, jobs):
    save(client, workflow("UP", [item("EXT", "Extract"), item("REPORT", "Report")]))
    save(client, workflow("DOWN", [item("LOAD", "Load", after=[other_job("UP", "Extract")])]))
    assert resave(client, "UP", [item("EXT", "Extract"),
                                 item("REPORT", "Report", after=[other_job("DOWN", "Load")])]).status_code == 200


# ---------- Following the other workflow's job ----------

def test_renaming_the_job_elsewhere_changes_nothing_here(client, jobs):
    two_workflows(client)
    up = client.get(f"{ROUTE}/UP").json()
    renamed = {"job_key": "UP", "job_type": "WORKFLOW", "items": [
        {"id": up["items"][0]["id"], "name": "Extract_all", "job_key": "EXT", "join": "ALL", "prerequisites": []}]}
    assert client.put(f"{ROUTE}/UP", json=renamed).status_code == 200
    (p,) = prerequisites(client.get(f"{ROUTE}/DOWN").json())
    assert (p["workflow"], p["job"]) == ("UP", "Extract_all")


def test_a_job_other_workflows_wait_for_cannot_be_taken_out(client, jobs):
    two_workflows(client)
    emptied = {"job_key": "UP", "job_type": "WORKFLOW", "items": [item("REPORT", "Report")]}
    detail = refusal(client.put(f"{ROUTE}/UP", json=emptied))
    assert "'Extract' cannot be taken out: 'Load' in 'DOWN' waits for it" in detail
    assert [i["name"] for i in client.get(f"{ROUTE}/UP").json()["items"]] == ["Extract"]


def test_a_workflow_others_wait_for_cannot_be_deleted(client, jobs):
    two_workflows(client)
    response = client.delete(f"{ROUTE}/UP")
    assert response.status_code == 409
    assert "'Load' in 'DOWN' waits for it" in response.json()["detail"]
    assert client.delete(f"{ROUTE}/DOWN").status_code == 204
    assert client.delete(f"{ROUTE}/UP").status_code == 204


def test_an_endpoint_a_workflow_waits_for_cannot_be_deleted(client, jobs):
    save(client, workflow("DOWN", [item("LOAD", "Load", after=[outside("ENDPOINT", endpoint="INBOUND_ORDERS")])]))
    response = client.delete("/api/v1/endpoints/INBOUND_ORDERS")
    assert response.status_code == 409 and "DOWN" in response.json()["detail"]


# ---------- Custom rules ----------

def test_a_custom_rule_may_name_the_things_the_job_waits_for_outside(client, jobs):
    save(client, workflow("UP", [item("EXT", "Extract")]))
    rule = "%{UP.Extract.Succeeded} AND %{INBOUND_ORDERS.FileCount} >= 2 AND %{Prep.Ended} AND %{Now.Weekday} <> 'Sunday'"
    after = [other_job(), outside("ENDPOINT", endpoint="INBOUND_ORDERS")]
    saved = save(client, workflow("DOWN", [item("REPORT", "Prep"), item("LOAD", "Load", join="CUSTOM", rule=rule, after=after)]))
    assert saved.status_code == 201, saved.text
    got = [(p["kind"], p["target"], p["test"]) for p in prerequisites(saved.json()["job"])]
    assert got == [("OTHER_JOB", "UP.Extract", "RULE"), ("ENDPOINT", "INBOUND_ORDERS", "SUCCESS"), ("JOB", "Prep", "RULE")]


def test_a_custom_rule_may_not_name_what_another_job_waits_for(client, jobs):
    save(client, workflow("UP", [item("EXT", "Extract")]))
    items = [item("REPORT", "Prep", after=[other_job()]),
             item("LOAD", "Load", join="CUSTOM", rule="%{UP.Extract.Succeeded}")]
    detail = refusal(save(client, workflow("DOWN", items)))
    assert "its Custom rule" in detail and "UP.Extract" in detail


# ---------- The pre-run check ----------

def test_the_check_warns_of_a_wait_with_no_limit_and_stops_files_on_another_site(client, jobs, seed, db):
    entity = seed.entity("ACME")
    site = seed.site("PARTNER", entity)
    seed.endpoint("REMOTE", "/data", "*", site=site)
    db.commit()
    after = [outside("TIME", "Window", time_condition=ALWAYS, wait_mode="NONE"), outside("ENDPOINT", endpoint="REMOTE")]
    assert save(client, workflow("DOWN", [item("LOAD", "Load", after=after)])).status_code == 201
    result = client.get(f"{ROUTE}/DOWN/check").json()
    assert not result["valid"]
    assert any("on Site 'PARTNER'" in p for p in result["problems"])
    assert any("'Load' waits for 'Window' with no limit" in w for w in result["warnings"])
