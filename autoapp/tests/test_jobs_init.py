"""
/api/v1/jobs/init: the payload an agent would pull before running a job.

These call the route function directly with a throwaway database session.
They do not go through HTTP; that needs the httpx package and comes later.
"""
import pytest
from fastapi import HTTPException

from app.routers.jobs import initialize_job
from app.schemas import JobInitRequest


def init(db, job_key, instance_id="INST_1"):
    return initialize_job(JobInitRequest(job_key=job_key, instance_id=instance_id), db)


def test_returns_steps_in_order_with_parameters_resolved(db, seed):
    proc = seed.process("DEV-PROC", Inbound="/data/in")
    job = seed.job(proc, "LOAD", Pattern="*.csv")
    seed.step(job, 2, title="Second", Source="${Inbound}/done", Dest="/data/out")
    seed.step(job, 1, title="First", Source="${Inbound}/${Pattern}", Dest="/archive/${SYS:INSTANCE_ID}")

    response = init(db, "DEV-PROC--LOAD", instance_id="INST_9")

    assert response.job_id == job.MasterObject_id
    assert response.process_id == proc.MasterObject_id
    assert [s.title for s in response.steps] == ["First", "Second"]
    assert response.steps[0].handler_class == "COPY_FILES"
    assert response.steps[0].parameters == {"Source": "/data/in/*.csv", "Dest": "/archive/INST_9"}


def test_unknown_job_key_is_404(db, seed):
    seed.job(seed.process("DEV-PROC"), "LOAD")

    with pytest.raises(HTTPException) as error:
        init(db, "DEV-PROC--NOPE")

    assert error.value.status_code == 404


def test_unresolved_placeholder_is_422_and_names_the_parameter(db, seed):
    job = seed.job(seed.process("DEV-PROC"), "LOAD")
    seed.step(job, 1, Source="${NoSuchVariable}/in", Dest="/out")

    with pytest.raises(HTTPException) as error:
        init(db, "DEV-PROC--LOAD")

    assert error.value.status_code == 422
    assert "Source" in error.value.detail
    assert "${NoSuchVariable}" in error.value.detail


def test_job_is_found_by_key_not_by_name(db, seed):
    """Two processes each have a job called LOAD; the key picks the right one."""
    seed.step(seed.job(seed.process("DEV-PROC-A"), "LOAD"), 1, Source="/a", Dest="/out")
    job_b = seed.job(seed.process("DEV-PROC-B"), "LOAD")
    seed.step(job_b, 1, Source="/b", Dest="/out")

    response = init(db, "DEV-PROC-B--LOAD")

    assert response.job_id == job_b.MasterObject_id
    assert response.steps[0].parameters["Source"] == "/b"
