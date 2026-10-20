"""Renaming a job: what it leaves behind (history, working folder), the refusal while it runs, and moving the folder."""
import pytest

from app.models import Audit, Job, JobRun

ROUTE = "/api/v1/jobs"


@pytest.fixture
def work(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOAPP_WORKING_ROOT", str(tmp_path / "work"))
    return tmp_path / "work"


@pytest.fixture
def job(db, seed, work):
    job = seed.job("DEV-LOAD")
    db.commit()
    return job


def ran(db, job, status="SUCCESS", run_id="r1"):
    db.add(JobRun(RunID=run_id, JobKey=job.JobKey, Job_MasterObject_id=job.MasterObject_id,
                  SchedulerInstanceID=run_id, Status=status))
    db.commit()


def rename(client, new_key, **extra):
    return client.put(f"{ROUTE}/DEV-LOAD", json={"job_key": new_key, **extra})


def make_folder(work, key="DEV-LOAD"):
    (work / key).mkdir(parents=True)
    (work / key / "kept.csv").write_text("id\n1")


def test_a_job_with_no_history_and_no_folder_needs_no_warning(client, job):
    facts = client.get(f"{ROUTE}/DEV-LOAD/rename-facts").json()

    assert facts == {"run_count": 0, "running": False, "working_folder": None,
                     "can_move_folder": False, "needs_warning": False}


def test_a_job_with_history_or_a_folder_needs_a_warning(client, db, job, work):
    ran(db, job)
    make_folder(work)

    facts = client.get(f"{ROUTE}/DEV-LOAD/rename-facts").json()

    assert facts["needs_warning"] and facts["run_count"] == 1
    assert facts["working_folder"] == str(work / "DEV-LOAD") and facts["can_move_folder"]


def test_history_alone_needs_a_warning_but_offers_no_move(client, db, job):
    ran(db, job)

    facts = client.get(f"{ROUTE}/DEV-LOAD/rename-facts").json()

    assert facts["needs_warning"] and not facts["can_move_folder"]


def test_the_folder_move_is_not_offered_while_the_job_runs(client, db, job, work):
    ran(db, job, status="RUNNING")
    make_folder(work)

    facts = client.get(f"{ROUTE}/DEV-LOAD/rename-facts").json()

    assert facts["running"] and not facts["can_move_folder"]


def test_a_rename_is_refused_while_the_job_runs(client, db, job):
    ran(db, job, status="RUNNING")

    response = rename(client, "DEV-OTHER")

    assert response.status_code == 409 and "is running" in response.json()["detail"]
    assert db.query(Job).filter(Job.JobKey == "DEV-LOAD").count() == 1


def test_a_rename_leaves_the_working_folder_unless_asked_to_move_it(client, db, job, work):
    make_folder(work)

    assert rename(client, "DEV-NEW").status_code == 200

    assert (work / "DEV-LOAD" / "kept.csv").exists() and not (work / "DEV-NEW").exists()


def test_a_rename_can_move_the_working_folder_with_it(client, db, job, work):
    make_folder(work)

    response = rename(client, "DEV-NEW", move_working_folder=True)

    assert response.status_code == 200
    assert "Moved the working folder with the job." in response.json()["changes"]
    assert (work / "DEV-NEW" / "kept.csv").exists() and not (work / "DEV-LOAD").exists()
    audit = db.query(Audit).order_by(Audit.id.desc()).first()
    assert "Moved the working folder" in audit.Details


def test_moving_the_folder_is_refused_when_the_new_folder_exists_and_nothing_changes(client, db, job, work):
    make_folder(work)
    make_folder(work, "DEV-NEW")

    response = rename(client, "DEV-NEW", move_working_folder=True)

    assert response.status_code == 409 and "already exists" in response.json()["detail"]
    assert db.query(Job).filter(Job.JobKey == "DEV-LOAD").count() == 1
    assert (work / "DEV-LOAD" / "kept.csv").exists()


def test_asking_to_move_a_folder_that_is_not_here_just_renames(client, db, job, work):
    response = rename(client, "DEV-NEW", move_working_folder=True)

    assert response.status_code == 200
    assert "Moved the working folder with the job." not in response.json()["changes"]
