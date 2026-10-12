"""
Shared pytest fixtures.

Every test gets its own throwaway SQLite database inside pytest's per-test
temp folder (tmp_path), so tests never touch autoapp.db or each other.
"""
import json
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import (
    Application, Base, Entity, Job, JobStep, JobStepParameter, Process, StepType, Variable
)


@pytest.fixture
def db_url(tmp_path):
    return f"sqlite:///{tmp_path / 'autoapp_test.db'}"


@pytest.fixture
def db(db_url):
    engine = create_engine(db_url)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()
    engine.dispose()


class Seeder:
    """Small helpers for inserting just the rows a test needs."""

    def __init__(self, db):
        self.db = db

    def _add(self, obj):
        self.db.add(obj)
        self.db.flush()
        return obj

    def set_vars(self, owner, **variables):
        for name, value in variables.items():
            self.db.add(Variable(MasterObject_id=owner.MasterObject_id, VarName=name, VarValue=value))
        self.db.flush()

    def process(self, name="DEV-TEST-PROC", **variables):
        proc = self._add(Process(Name=name))
        self.set_vars(proc, **variables)
        return proc

    def job(self, process, name="TEST_JOB", **variables):
        job = self._add(Job(process_id=process.MasterObject_id, Name=name, JobKey=f"{process.Name}--{name}"))
        self.set_vars(job, **variables)
        return job

    def entity(self, name, **variables):
        entity = self._add(Entity(Name=name, Abbr=name[:10]))
        self.set_vars(entity, **variables)
        return entity

    def application(self, name, **variables):
        app = self._add(Application(Name=name, Abbr=name[:10]))
        self.set_vars(app, **variables)
        return app

    def step_type(self, code="COPY_FILES", name="Copy Files"):
        existing = self.db.query(StepType).filter(StepType.HandlerClass == code).first()
        return existing or self._add(StepType(TypeName=name, HandlerClass=code))

    def step(self, job, order, code="COPY_FILES", title=None, **params):
        step = self._add(JobStep(
            job_id=job.MasterObject_id,
            StepType_id=self.step_type(code, code).id,
            StepOrder=order,
            Title=title or f"Step {order}",
        ))
        for name, value in params.items():
            self.db.add(JobStepParameter(job_step_id=step.id, ParamName=name, ParamValue=value))
        self.db.flush()
        return step


@pytest.fixture
def seed(db):
    return Seeder(db)


def read_spool(spool_dir) -> list:
    """Returns every record from the completed (.jsonl) spool files in a folder."""
    records = []
    for spool_file in sorted(Path(spool_dir).glob("*.jsonl")):
        for line in spool_file.read_text().splitlines():
            records.append(json.loads(line))
    return records


@pytest.fixture
def spool_records():
    return read_spool
