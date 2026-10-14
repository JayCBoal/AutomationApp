"""GET /api/v1/jobs: the job search, over HTTP."""
import pytest

ROUTE = "/api/v1/jobs"


@pytest.fixture
def jobs(db, seed, endpoints):
    """Three jobs: one that collects and delivers, one that only collects, one disabled with no steps."""
    collect_and_deliver = seed.job("DEV-LEGAL-COLLECT")
    collect_and_deliver.Description = "Collects legal extracts and delivers them to billing"
    seed.step(collect_and_deliver, 1, SourceEndpoint="LEGAL_EXTRACTS", Dest="incoming")
    seed.step(collect_and_deliver, 2, Source="incoming/*.csv", DestEndpoint="BILLING_INBOX", Move="True")
    seed.step(collect_and_deliver, 3, Source="incoming/*.csv", Dest="unused", AllowNoFiles="True").IsActive = False

    pickup = seed.job("dev-billing-pickup")
    pickup.Description = "Picks up from the billing inbox"
    seed.step(pickup, 1, SourceEndpoint="BILLING_INBOX", Dest="to_load", AllowNoFiles="True")

    retired = seed.job("DEV-RETIRED")
    retired.IsActive = False
    db.commit()
    return collect_and_deliver, pickup, retired


def keys(response):
    assert response.status_code == 200, response.text
    return [job["job_key"] for job in response.json()]


def test_jobs_are_listed_in_name_order_whatever_their_case(client, jobs):
    assert keys(client.get(ROUTE)) == ["dev-billing-pickup", "DEV-LEGAL-COLLECT", "DEV-RETIRED"]


def test_each_job_comes_with_its_steps_and_the_endpoints_it_uses(client, jobs):
    by_key = {job["job_key"]: job for job in client.get(ROUTE).json()}

    collect = by_key["DEV-LEGAL-COLLECT"]
    assert collect["description"] == "Collects legal extracts and delivers them to billing"
    assert (collect["active"], collect["step_count"], collect["disabled_step_count"]) == (True, 2, 1)
    assert collect["endpoints"] == ["BILLING_INBOX", "LEGAL_EXTRACTS"]
    assert (collect["modified"] is not None, collect["modified_by"]) == (True, "system")

    retired = by_key["DEV-RETIRED"]
    assert (retired["active"], retired["step_count"], retired["endpoints"], retired["last_run"]) == (False, 0, [], None)


def test_search_by_key_and_description_ignores_case_and_matches_part(client, jobs):
    assert keys(client.get(ROUTE, params={"job_key": "BILLING"})) == ["dev-billing-pickup"]
    assert keys(client.get(ROUTE, params={"job_key": "dev-"})) == ["dev-billing-pickup", "DEV-LEGAL-COLLECT", "DEV-RETIRED"]
    assert keys(client.get(ROUTE, params={"description": "BILLING"})) == ["dev-billing-pickup", "DEV-LEGAL-COLLECT"]
    assert keys(client.get(ROUTE, params={"job_key": "legal", "description": "inbox"})) == []     # criteria combine
    assert keys(client.get(ROUTE, params={"job_key": "nothing-like-this"})) == []


def test_search_by_enabled_or_disabled(client, jobs):
    assert keys(client.get(ROUTE, params={"active": "true"})) == ["dev-billing-pickup", "DEV-LEGAL-COLLECT"]
    assert keys(client.get(ROUTE, params={"active": "false"})) == ["DEV-RETIRED"]


def test_search_by_an_endpoint_the_job_uses(client, jobs):
    assert keys(client.get(ROUTE, params={"endpoint": "legal_ext"})) == ["DEV-LEGAL-COLLECT"]
    assert keys(client.get(ROUTE, params={"endpoint": "BILLING_INBOX"})) == ["dev-billing-pickup", "DEV-LEGAL-COLLECT"]
    # 'incoming' is a working-folder path in these jobs, not an endpoint
    assert keys(client.get(ROUTE, params={"endpoint": "incoming"})) == []


def test_limit_caps_the_number_returned(client, jobs):
    assert keys(client.get(ROUTE, params={"limit": 2})) == ["dev-billing-pickup", "DEV-LEGAL-COLLECT"]
    assert client.get(ROUTE, params={"limit": 501}).status_code == 422


def test_last_run_is_the_most_recent_one(client, db, jobs, outbox, run_runner, load_spool):
    run_runner("DEV-LEGAL-COLLECT", "88421")                    # succeeds
    for leftover in outbox.glob("*.csv"):
        leftover.unlink()
    run_runner("DEV-LEGAL-COLLECT", "88422", "--run-number", "2")    # nothing left to collect: fails
    load_spool()
    db.commit()

    by_key = {job["job_key"]: job for job in client.get(ROUTE).json()}

    last = by_key["DEV-LEGAL-COLLECT"]["last_run"]
    assert (last["status"], last["instance_id"], last["run_number"]) == ("FAILED", "88422", 2)
    assert "No files matched" in last["error"]
    assert last["started"] <= last["ended"]
    assert by_key["dev-billing-pickup"]["last_run"] is None     # this job has never run


def test_an_empty_database_gives_an_empty_list(client):
    assert client.get(ROUTE).json() == []


def test_each_job_says_whether_it_would_run(client, db, seed, jobs, tmp_path, monkeypatch):
    """The same check the runner makes before it starts, made for every job the search returns."""
    monkeypatch.setenv("AUTOAPP_WORKING_ROOT", str(tmp_path / "work"))
    broken = seed.job("DEV-BROKEN")
    seed.step(broken, 1, SourceEndpoint="NO_SUCH_ENDPOINT", Dest="incoming", Mvoe="True")
    seed.step(broken, 2, Source="incoming/*.csv")
    db.commit()

    by_key = {job["job_key"]: job for job in client.get(ROUTE).json()}

    assert (by_key["DEV-LEGAL-COLLECT"]["ready"], by_key["DEV-LEGAL-COLLECT"]["problem_count"]) == (True, 0)
    assert (by_key["dev-billing-pickup"]["ready"], by_key["dev-billing-pickup"]["problem_count"]) == (True, 0)
    assert (by_key["DEV-BROKEN"]["ready"], by_key["DEV-BROKEN"]["problem_count"]) == (False, 2)    # one per step
    assert (by_key["DEV-RETIRED"]["ready"], by_key["DEV-RETIRED"]["problem_count"]) == (False, 2)  # disabled, no steps


def test_the_search_and_the_check_agree_about_a_job(client, db, seed, jobs, tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOAPP_WORKING_ROOT", str(tmp_path / "work"))

    for job in client.get(ROUTE).json():
        check = client.get(f"{ROUTE}/{job['job_key']}/check").json()
        assert (job["ready"], job["problem_count"]) == (check["valid"], len(check["problems"]))


# --- One job ------------------------------------------------------------------------------------

def test_one_job_comes_with_all_its_steps_in_order_and_their_parameters_as_stored(client, db, seed, jobs):
    collect = db.get(type(jobs[0]), jobs[0].MasterObject_id)
    seed.step(collect, 0, title="Runs first", Source="${Folder}/*.csv", Dest="staged")     # added last, ordered first
    db.commit()

    response = client.get(f"{ROUTE}/DEV-LEGAL-COLLECT")

    assert response.status_code == 200
    job = response.json()
    assert (job["job_key"], job["active"]) == ("DEV-LEGAL-COLLECT", True)
    assert job["description"] == "Collects legal extracts and delivers them to billing"
    assert (job["created"] is not None, job["created_by"]) == (True, "system")
    assert [(s["order"], s["title"], s["active"]) for s in job["steps"]] == [
        (0, "Runs first", True), (1, "Step 1", True), (2, "Step 2", True), (3, "Step 3", False)]   # disabled included
    first, collect_step, deliver = job["steps"][0], job["steps"][1], job["steps"][2]
    assert (collect_step["step_type"], collect_step["step_type_name"]) == ("COPY_FILES", "Copy Files")
    assert first["parameters"] == {"Source": "${Folder}/*.csv", "Dest": "staged"}        # placeholder left as written
    assert collect_step["parameters"] == {"SourceEndpoint": "LEGAL_EXTRACTS", "Dest": "incoming"}
    assert deliver["parameters"] == {"Source": "incoming/*.csv", "DestEndpoint": "BILLING_INBOX", "Move": "True"}
    assert isinstance(collect_step["id"], int)


def test_a_job_with_no_steps_has_an_empty_list(client, jobs):
    job = client.get(f"{ROUTE}/DEV-RETIRED").json()

    assert (job["active"], job["steps"]) == (False, [])


def test_one_job_is_found_by_its_exact_key(client, jobs):
    assert client.get(f"{ROUTE}/dev-billing-pickup").status_code == 200
    response = client.get(f"{ROUTE}/DEV-BILLING-PICKUP")            # keys are case-sensitive

    assert response.status_code == 404
    assert response.json()["detail"] == "No job with JobKey 'DEV-BILLING-PICKUP' exists."
