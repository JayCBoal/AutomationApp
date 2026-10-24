"""
DEV-LATE_SAMPLE (docs/WORKFLOWS_PHASE8.md, step 7): the walk-through in the seed comment. Extract is cut from 150 seconds
to 3, and the workflow runner's clock goes 60 times faster (tests/fast_runner.py), so "1 minute" is one second.
"""
import subprocess
import sys
from pathlib import Path

import pytest

from app.models import AlertDelivery, JobRun, JobStepParameter, ReactionEvent, WorkflowRunItem
from conftest import AUTOAPP_DIR, subprocess_env
from create_dev_db import load_seed

KEY = "DEV-LATE_SAMPLE"


@pytest.fixture
def sample_run(db, db_url, tmp_path):
    load_seed(db)
    extract = db.query(JobStepParameter).filter_by(job_step_id=58, ParamName="WaitSeconds").one()
    extract.ParamValue = "3"
    db.commit()
    env = {**subprocess_env(db_url), "AUTOAPP_WORKFLOW_POLL_SECONDS": "0.1", "AUTOAPP_TEST_CLOCK_SPEED": "60"}
    done = subprocess.run([sys.executable, str(Path(__file__).with_name("fast_runner.py")), "--job-key", KEY,
                           "--instance-id", "LATE_1", "--spool-dir", str(tmp_path / "spool"),
                           "--working-root", str(tmp_path / "work")],
                          cwd=AUTOAPP_DIR, env=env, capture_output=True, text=True, timeout=120)
    assert done.returncode == 0, done.stdout[-3000:] + done.stderr[-2000:]
    db.expire_all()
    run = db.query(JobRun).filter(JobRun.JobKey == KEY, JobRun.ParentRun_id.is_(None)).one()
    return run, {i.ItemName: i for i in db.query(WorkflowRunItem).filter_by(WorkflowRun_id=run.id)}


def test_the_sample_marks_extract_and_transform_late_and_tells_the_operators_once(sample_run, db):
    run, items = sample_run

    assert {name: item.Status for name, item in items.items()} == {"Extract": "SUCCESS", "Transform": "SUCCESS", "Load": "SUCCESS"}
    assert items["Extract"].LateDateTime is not None and "longer than 1m" in items["Extract"].LateReason
    assert items["Transform"].LateDateTime is not None
    assert items["Load"].LateDateTime is None

    (delivery,) = db.query(AlertDelivery).all()
    assert delivery.AlertName == "DEV-LATE_ALERT" and delivery.WorkflowPath == "Extract"
    assert delivery.Recipients == "operators@example.test" and delivery.Subject == "Extract is late"

    skipped = [e for e in db.query(ReactionEvent) if e.WorkflowPath == "Transform" and e.Action == "NOTIFY"]
    assert [e.Result for e in skipped] == ["NOT_FIRED"]
