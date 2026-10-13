"""
/api/v1/jobs/init: the payload an agent would pull before running a job.

These call the route function directly with a throwaway database session.
They do not go through HTTP; that needs the httpx package and comes later.
"""
import pytest
from fastapi import HTTPException

from app.routers.jobs import initialize_job
from app.schemas import JobInitRequest


@pytest.fixture(autouse=True)
def working_root(tmp_path, monkeypatch):
    """The API reads the working root from the environment, as a deployed server would."""
    monkeypatch.setenv("AUTOAPP_WORKING_ROOT", str(tmp_path / "work"))
    return tmp_path / "work"


def init(db, job_key, instance_id="INST_1"):
    return initialize_job(JobInitRequest(job_key=job_key, instance_id=instance_id), db)


def test_returns_steps_in_order_with_locations_resolved(db, seed, working_root):
    endpoint = seed.endpoint("LEGAL_EXTRACTS", "/apps/legal/outbox", "${Pattern}",
                             application=seed.application("LEGAL_APP"))
    job = seed.job("DEV-LOAD", Pattern="*.csv")
    seed.step(job, 2, title="Second", Source="incoming/*.csv", Dest="archive/${SYS:INSTANCE_ID}")
    seed.step(job, 1, title="First", SourceEndpoint="LEGAL_EXTRACTS", Dest="incoming")

    response = init(db, "DEV-LOAD", instance_id="INST_9")

    work = working_root / "DEV-LOAD"
    first, second = response.steps
    assert response.job_id == job.MasterObject_id
    assert response.working_folder == str(work)
    assert [first.title, second.title] == ["First", "Second"]
    assert first.handler_class == "COPY_FILES"
    defaults = {"Move": False, "CreateFolder": True, "Checksum": False, "AllowNoFiles": False}
    assert first.parameters == {**defaults, "Source": "/apps/legal/outbox/*.csv", "Dest": str(work / "incoming")}
    assert first.source_endpoint_id == endpoint.id
    assert second.parameters == {**defaults, "Source": str(work / "incoming" / "*.csv"),
                                 "Dest": str(work / "archive" / "INST_9")}
    assert second.source_endpoint_id is None


def test_unknown_job_key_is_404(db, seed):
    seed.job("DEV-LOAD")

    with pytest.raises(HTTPException) as error:
        init(db, "DEV-NOPE")

    assert error.value.status_code == 404


def test_unresolved_placeholder_is_422_and_names_the_step(db, seed):
    job = seed.job("DEV-LOAD")
    seed.step(job, 1, title="Collect", Source="${NoSuchVariable}/in", Dest="out")

    with pytest.raises(HTTPException) as error:
        init(db, "DEV-LOAD")

    assert error.value.status_code == 422
    assert "Collect" in error.value.detail
    assert "${NoSuchVariable}" in error.value.detail


def test_raw_path_outside_the_working_folder_is_422(db, seed):
    job = seed.job("DEV-LOAD")
    seed.step(job, 1, Source="/etc/*.conf", Dest="out")

    with pytest.raises(HTTPException) as error:
        init(db, "DEV-LOAD")

    assert error.value.status_code == 422
    assert "outside the job's working folder" in error.value.detail


def test_the_key_picks_the_right_job(db, seed):
    seed.step(seed.job("DEV-LOAD-A"), 1, Source="a", Dest="out")
    job_b = seed.job("DEV-LOAD-B")
    seed.step(job_b, 1, Source="b", Dest="out")

    response = init(db, "DEV-LOAD-B")

    assert response.job_id == job_b.MasterObject_id
    assert response.steps[0].parameters["Source"].endswith("DEV-LOAD-B/b")
