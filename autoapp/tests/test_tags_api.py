"""
Tags through the API: registering, searching, changing and removing tags; tags on
jobs and the other definitions; the Tag criterion of every search; the tag
variables preview; and the settings.
"""
import json

import pytest

from app.models import Audit, Job, JobStepParameter, Tag, Variable


@pytest.fixture
def world(db, seed, tmp_path, monkeypatch):
    """
        Environment            (no variables)
          DEV
        Finance                Ledger = GL01, Region = EU
          Reporting            Region = US
          Payroll
        Ops                    Region = APAC

    DEV-REPORT carries DEV and Finance/Reporting; LEGAL_APP carries Finance.
    """
    monkeypatch.setenv("AUTOAPP_WORKING_ROOT", str(tmp_path / "work"))
    environment = seed.tag("Environment")
    dev = seed.tag("DEV", parent=environment)
    finance = seed.tag("Finance", Ledger="GL01", Region="EU")
    reporting = seed.tag("Reporting", parent=finance, Region="US")
    seed.tag("Payroll", parent=finance)
    seed.tag("Ops", Region="APAC")
    job = seed.job("DEV-REPORT")
    seed.step(job, 1, Source="in/*.csv", Dest="out/${Ledger}")
    seed.job("DEV-OTHER")
    seed.attach(dev, job)
    seed.attach(reporting, job)
    seed.attach(finance, seed.application("LEGAL_APP"))
    db.commit()


def ok(response, status=200):
    assert response.status_code == status, response.text
    return response.json()


# --- Tags as definitions --------------------------------------------------------------------------

def test_tags_are_listed_by_path_so_each_sits_under_its_parent(client, world):
    paths = [t["path"] for t in ok(client.get("/api/v1/tags"))]

    assert paths == ["Environment", "Environment/DEV", "Finance", "Finance/Payroll", "Finance/Reporting", "Ops"]


def test_a_tag_is_found_by_its_path(client, world):
    tag = ok(client.get("/api/v1/tags/Finance/Reporting"))

    assert (tag["name"], tag["path"], tag["parent"]) == ("Reporting", "Finance/Reporting", "Finance")
    assert [(v["name"], v["value"]) for v in tag["variables"]] == [("Region", "US")]
    # what it inherits, and from where; Region is its own, so only Ledger comes from Finance
    assert [(v["name"], v["value"], v["source"]) for v in tag["inherited_variables"]] == [("Ledger", "GL01", "Finance")]
    assert tag["used_by"] == [{"kind": "jobs", "name": "DEV-REPORT"}]


def test_what_uses_a_tag_is_its_children_and_what_carries_it(client, world):
    tag = ok(client.get("/api/v1/tags/Finance"))

    assert tag["used_by"] == [{"kind": "tags", "name": "Finance/Payroll"}, {"kind": "tags", "name": "Finance/Reporting"},
                              {"kind": "applications", "name": "LEGAL_APP"}]


def test_a_tag_is_registered_under_a_parent(client, db, world):
    created = ok(client.post("/api/v1/tags", json={"name": "Audit", "parent": "Finance / Reporting",
                                                   "variables": [{"name": "Keep", "value": "7"}]}), 201)

    assert created["path"] == "Finance/Reporting/Audit"
    tag = ok(client.get("/api/v1/tags/Finance/Reporting/Audit"))
    assert [v["name"] for v in tag["variables"]] == ["Keep"]
    db.commit()
    assert db.query(Audit).filter(Audit.Action == "TAG_CREATED").one()


def test_names_may_repeat_under_different_parents_but_not_under_one(client, world):
    ok(client.post("/api/v1/tags", json={"name": "DEV", "parent": "Finance"}), 201)          # Finance/DEV

    response = client.post("/api/v1/tags", json={"name": "DEV", "parent": "Environment"})
    assert response.status_code == 409
    assert "There is already a tag 'DEV' under Environment" in response.json()["detail"]
    response = client.post("/api/v1/tags", json={"name": "Finance"})
    assert response.status_code == 409 and "at the top level" in response.json()["detail"]


def test_a_tag_name_cannot_hold_a_slash_or_a_full_stop(client, world):
    for name in ("A/B", "A.B", "has space"):
        response = client.post("/api/v1/tags", json={"name": name})
        assert response.status_code == 422, name
        assert "cannot be used" in response.json()["detail"]


def test_a_tag_cannot_be_moved_under_itself_or_its_own_child(client, world):
    for parent in ("Finance", "Finance/Reporting"):
        response = client.put("/api/v1/tags/Finance", json={"parent": parent})
        assert response.status_code == 422, parent
        assert "cannot be its parent" in response.json()["detail"]


def test_moving_a_tag_takes_its_children_and_the_references_to_them(client, db, world, seed):
    job = db.query(Job).filter(Job.JobKey == "DEV-REPORT").one()
    seed.step(job, 2, Source="in/${TAG:Finance/Reporting.Region}", Dest="out")
    db.commit()

    result = ok(client.put("/api/v1/tags/Finance", json={"name": "Money", "parent": "Environment"}))

    assert "Renamed from 'Finance' to 'Money'." in result["changes"]
    assert "Moved under Environment." in result["changes"]
    assert "Updated 1 value that named it." in result["changes"]
    assert ok(client.get("/api/v1/tags/Environment/Money/Reporting"))["path"] == "Environment/Money/Reporting"
    db.expire_all()
    assert db.query(JobStepParameter).filter(JobStepParameter.ParamName == "Source",
                                             JobStepParameter.ParamValue.contains("TAG")).one().ParamValue \
        == "in/${TAG:Environment/Money/Reporting.Region}"


def test_a_tag_in_use_cannot_be_deleted(client, world):
    response = client.delete("/api/v1/tags/Finance")

    assert response.status_code == 409
    assert "Finance / Payroll, Finance / Reporting, LEGAL_APP" in response.json()["detail"]
    assert client.delete("/api/v1/tags/Ops").status_code == 204
    assert client.get("/api/v1/tags/Ops").status_code == 404


# --- Tags on things ---------------------------------------------------------------------------------

def test_every_definition_shows_its_tags(client, world):
    assert ok(client.get("/api/v1/applications/LEGAL_APP"))["tags"] == ["Finance"]
    assert ok(client.get("/api/v1/jobs/DEV-REPORT"))["tags"] == ["Environment/DEV", "Finance/Reporting"]


def test_tags_are_added_and_removed_by_saving_the_list(client, db, world):
    result = ok(client.put("/api/v1/applications/LEGAL_APP", json={"tags": ["Ops", "Environment / DEV"]}))

    assert result["item"]["tags"] == ["Environment/DEV", "Ops"]
    assert result["changes"] == ["Added tags Environment / DEV, Ops.", "Removed tag Finance."]
    db.commit()
    audit = db.query(Audit).filter(Audit.Action == "APPLICATION_UPDATED").one()
    assert "Removed tag Finance." in json.loads(audit.Details)["changes"]


def test_an_unknown_tag_is_refused(client, world):
    response = client.put("/api/v1/applications/LEGAL_APP", json={"tags": ["Nope"]})

    assert response.status_code == 404
    assert "There is no tag 'Nope'" in response.json()["detail"]


def test_a_new_definition_can_carry_tags_from_the_start(client, world):
    ok(client.post("/api/v1/entities", json={"name": "GLOBEX", "abbr": "GLX", "tags": ["Ops"]}), 201)
    ok(client.post("/api/v1/endpoints", json={"name": "OPS_DROP", "path": "/ops", "tags": ["Ops"]}), 201)

    assert ok(client.get("/api/v1/entities/GLOBEX"))["tags"] == ["Ops"]
    assert ok(client.get("/api/v1/endpoints/OPS_DROP"))["tags"] == ["Ops"]


def test_a_tag_does_not_carry_tags(client, world):
    response = client.put("/api/v1/tags/Ops", json={"tags": ["Finance"]})

    assert ok(client.get("/api/v1/tags/Ops")).get("tags") is None
    assert response.status_code == 200          # the list is ignored: a tag's place is its parent


def test_a_jobs_tags_are_saved_with_the_job(client, db, world):
    job = ok(client.get("/api/v1/jobs/DEV-OTHER"))
    body = {"job_key": "DEV-OTHER", "description": job["description"], "active": True, "steps": [],
            "tags": ["Finance/Payroll"]}

    result = ok(client.put("/api/v1/jobs/DEV-OTHER", json=body))

    assert result["job"]["tags"] == ["Finance/Payroll"]
    assert result["changes"] == ["Added tag Finance / Payroll."]
    assert [(v["name"], v["source"]) for v in result["job"]["inherited_variables"]] == [
        ("Ledger", "Finance"), ("Region", "Finance")]


def test_a_job_shows_what_its_tags_give_it_and_where_from(client, world):
    job = ok(client.get("/api/v1/jobs/DEV-REPORT"))

    assert [(v["name"], v["value"], v["source"], v["overridden"]) for v in job["inherited_variables"]] == [
        ("Ledger", "GL01", "Finance", False), ("Region", "US", "Finance/Reporting", False)]


# --- Searching by tag ---------------------------------------------------------------------------

def test_every_search_has_a_tag_criterion_that_includes_child_tags(client, world):
    def keys(response):
        return [row.get("job_key") or row.get("name") for row in ok(response)]

    assert keys(client.get("/api/v1/jobs", params={"tag": "Finance"})) == ["DEV-REPORT"]      # through Reporting
    assert keys(client.get("/api/v1/jobs", params={"tag": "Payroll"})) == []
    assert keys(client.get("/api/v1/applications", params={"tag": "finance"})) == ["LEGAL_APP"]
    assert keys(client.get("/api/v1/applications", params={"tag": "Ops"})) == []
    assert keys(client.get("/api/v1/jobs", params={"tag": "Environment / DEV"})) == ["DEV-REPORT"]


def test_job_search_rows_show_their_tags(client, world):
    rows = {r["job_key"]: r for r in ok(client.get("/api/v1/jobs"))}

    assert rows["DEV-REPORT"]["tags"] == ["Environment/DEV", "Finance/Reporting"]


def test_the_lookups_list_tags_by_path(client, world):
    assert [t["value"] for t in ok(client.get("/api/v1/lookups"))["tags"]] == [
        "Environment", "Environment/DEV", "Finance", "Finance/Payroll", "Finance/Reporting", "Ops"]


# --- What a tag would give, before it is added ------------------------------------------------

def test_the_tag_variables_preview_shows_values_and_where_they_come_from(client, world):
    view = ok(client.get("/api/v1/tag-variables", params={"tag": ["Finance/Reporting"]}))

    assert [(v["name"], v["value"], v["source"]) for v in view["variables"]] == [
        ("Ledger", "GL01", "Finance"), ("Region", "US", "Finance/Reporting")]
    assert view["conflicts"] == []


def test_the_preview_warns_of_a_conflict_before_the_tag_is_added(client, world):
    view = ok(client.get("/api/v1/tag-variables", params={"tag": ["Finance/Reporting", "Ops"]}))

    [conflict] = view["conflicts"]
    assert (conflict["name"], conflict["tags"]) == ("Region", ["Finance/Reporting", "Ops"])
    assert [v["name"] for v in view["variables"]] == ["Ledger"]


def test_the_objects_own_variable_settles_a_conflict_in_the_preview(client, world):
    view = ok(client.get("/api/v1/tag-variables", params={"tag": ["Finance/Reporting", "Ops"], "own": ["Region"]}))

    assert view["conflicts"] == []


def test_the_preview_masks_secrets(client, db, world):
    tag = db.query(Tag).filter(Tag.Name == "Ops").one()
    db.add(Variable(MasterObject_id=tag.MasterObject_id, VarName="Token", VarValue="s3cr3t", IsSecret=True))
    db.commit()

    view = ok(client.get("/api/v1/tag-variables", params={"tag": ["Ops"]}))

    assert {v["name"]: v["value"] for v in view["variables"]}["Token"] == "********"
    assert "s3cr3t" not in json.dumps(view)


def test_the_job_preview_warns_of_a_conflict_the_job_does_not_use(client, world):
    body = {"job_key": "DEV-REPORT", "active": True, "tags": ["Finance/Reporting", "Ops"],
            "steps": [{"title": "Copy", "step_type": "COPY_FILES", "parameters": {"Source": "in/*", "Dest": "out"}}]}

    preview = ok(client.post("/api/v1/jobs/preview", params={"existing_key": "DEV-REPORT"}, json=body))

    assert preview["valid"] is True
    assert len(preview["warnings"]) == 1 and "Variable 'Region'" in preview["warnings"][0]


def test_a_conflict_the_job_uses_stops_it(client, world):
    body = {"job_key": "DEV-REPORT", "active": True, "tags": ["Finance/Reporting", "Ops"],
            "steps": [{"title": "Copy", "step_type": "COPY_FILES",
                       "parameters": {"Source": "in/*", "Dest": "out/${Region}"}}]}

    preview = ok(client.post("/api/v1/jobs/preview", params={"existing_key": "DEV-REPORT"}, json=body))

    assert preview["valid"] is False
    assert any("Variable 'Region' is given different values" in p for p in preview["problems"])
    assert preview["warnings"] == []                 # said once, as the problem


# --- Settings -------------------------------------------------------------------------------------

def test_the_settings_are_listed_with_their_defaults(client, world):
    precedence, retention = ok(client.get("/api/v1/settings"))

    assert (retention["key"], retention["kind"], retention["value"]) == ("LogRetentionDays", "CHOICE", "30")
    assert precedence["key"] == "VariablePrecedence"
    assert precedence["value"] == precedence["default"] == ["ENV", "SYS", "ENTITY", "APP", "ENDPOINT", "TAG", "JOB"]
    assert precedence["changed"] is False


def test_a_setting_is_changed_and_put_back(client, db, world):
    result = ok(client.put("/api/v1/settings/VariablePrecedence",
                           json={"value": ["ENV", "SYS", "ENTITY", "APP", "ENDPOINT", "JOB", "TAG"]}))

    assert result["setting"]["value"][-2:] == ["JOB", "TAG"] and result["setting"]["changed"] is True
    assert result["changes"] == ["Changed Variable precedence from ENV,SYS,ENTITY,APP,ENDPOINT,TAG,JOB "
                                 "to ENV,SYS,ENTITY,APP,ENDPOINT,JOB,TAG."]
    back = ok(client.put("/api/v1/settings/VariablePrecedence", json={"value": "ENV,SYS,ENTITY,APP,ENDPOINT,TAG,JOB"}))
    assert back["setting"]["changed"] is False
    db.commit()
    assert db.query(Audit).filter(Audit.Action == "SETTING_CHANGED").count() == 2


def test_a_setting_that_does_not_fit_is_refused(client, world):
    response = client.put("/api/v1/settings/VariablePrecedence", json={"value": "SYS,JOB,JOB"})

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert "missing: ENV, ENTITY, APP, ENDPOINT, TAG" in detail and "given more than once: JOB" in detail
    assert client.put("/api/v1/settings/NoSuchThing", json={"value": "x"}).status_code == 404
