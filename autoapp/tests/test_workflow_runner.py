"""
Running workflows (docs/WORKFLOWS_PHASE1.md, step 3), and the Simulate step and return codes
that make them easy to try: each test builds a workflow of Simulate jobs and runs it the way
a scheduler would, with engine.runner as a separate process.
"""
import subprocess
import sys
import time

import pytest

from app.log_agent import run_log
from app.models import Job, JobRun, Operation, Variable, WorkflowItem, WorkflowPrerequisite, WorkflowRunItem, utcnow
from conftest import AUTOAPP_DIR, subprocess_env


@pytest.fixture
def sim(seed):
    """A job of one Simulate step: sim('A', code=4, fail=True, wait=1, success='0,4')."""
    def _make(key, code=0, fail=False, wait=0, success=None, messages=None):
        job = seed.job(key)
        job.SuccessReturnCodes = success
        params = {"ReturnCode": str(code), "Fail": str(fail), "WaitSeconds": str(wait)}
        if messages:
            params["Messages"] = messages
        seed.step(job, 1, "SIMULATE", title=f"Simulate {key}", **params)
        return job
    return _make


@pytest.fixture
def flow(seed, db):
    """A workflow made from (name, job, after, join) entries; after: names (succeeded) or (name, test[, codes])."""
    def _make(key, entries):
        workflow = seed._add(Job(JobKey=key, JobType="WORKFLOW"))
        items = {}
        for position, (name, job, *rest) in enumerate(entries, start=1):
            join = rest[1] if len(rest) > 1 else "ALL"
            items[name] = seed._add(WorkflowItem(workflow=workflow, ItemName=name, job=job, JoinRule=join,
                                                 ItemOrder=position))
        for name, job, *rest in entries:
            for p in (rest[0] if rest else []):
                target, test, *codes = (p, "SUCCESS") if isinstance(p, str) else p
                seed._add(WorkflowPrerequisite(item=items[name], target=items[target], Test=test,
                                               ReturnCodes=codes[0] if codes else None))
        db.commit()
        return workflow
    return _make


def start(db_url, tmp_path, job_key, instance="WF_1"):
    env = {**subprocess_env(db_url), "AUTOAPP_WORKFLOW_POLL_SECONDS": "0.2"}
    return subprocess.Popen([sys.executable, "-m", "engine.runner", "--job-key", job_key, "--instance-id", instance,
                             "--spool-dir", str(tmp_path / "spool"), "--working-root", str(tmp_path / "work")],
                            cwd=AUTOAPP_DIR, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)


@pytest.fixture
def run_flow(db, db_url, tmp_path):
    """Runs a workflow to the end. Returns (exit code, its run, {name: its run item}, its log)."""
    def _run(job_key):
        db.commit()
        process = start(db_url, tmp_path, job_key)
        output, _ = process.communicate(timeout=120)
        assert process.returncode in (0, 1), output
        return (process.returncode, *results(db, job_key))
    return _run


def results(db, job_key):
    db.commit()
    db.expire_all()
    run = db.query(JobRun).filter(JobRun.JobKey == job_key, JobRun.JobType == "WORKFLOW").order_by(JobRun.id.desc()).first()
    items = {i.ItemName: i for i in db.query(WorkflowRunItem).filter(WorkflowRunItem.WorkflowRun_id == run.id)}
    log = "\n".join(run_log(run))
    return run, items, log


def states(items):
    return {name: (i.Status, i.Reason, i.ReturnCode) for name, i in items.items()}


# ---------- Running in the right order ----------

def test_jobs_run_after_what_they_wait_for_and_in_parallel_otherwise(sim, flow, run_flow, db):
    a, b, c, d = sim("A"), sim("B", wait=1), sim("C", wait=1), sim("D")
    flow("FAN", [("Start", a), ("Left", b, ["Start"]), ("Right", c, ["Start"]), ("Join", d, ["Left", "Right"])])

    code, run, items, log = run_flow("FAN")

    assert code == 0, log
    assert (run.Status, run.Reason, run.ReturnCode, run.JobType) == ("SUCCESS", None, 0, "WORKFLOW")
    assert {s for s, _, _ in states(items).values()} == {"SUCCESS"}
    left, right, join = items["Left"].child_run, items["Right"].child_run, items["Join"].child_run
    assert right.StartedDateTime < left.EndedDateTime and left.StartedDateTime < right.EndedDateTime   # side by side
    assert join.StartedDateTime >= max(left.EndedDateTime, right.EndedDateTime)
    assert (join.ParentRun_id, join.WorkflowPath, join.Attempt, join.JobType) == (run.id, "Join", 1, "STEPS")
    assert "Started 'Join' (job 'D')." in log and "Workflow 'FAN' completed successfully." in log


def test_a_failure_makes_what_needed_success_not_run_and_lets_failure_paths_run(sim, flow, run_flow):
    a, b, c, d = sim("A", fail=True), sim("B"), sim("C"), sim("D")
    flow("PATHS", [("Load", a), ("Report", b, ["Load"]), ("Alert", c, [("Load", "FAILED")]),
                   ("Cleanup", d, [("Report", "ENDED")])])

    code, run, items, log = run_flow("PATHS")

    assert code == 0, log                       # the failure path ran: the failure was handled
    assert (run.Status, run.Reason) == ("SUCCESS", None)
    assert "1 job failed, and what waits for it ran: Load." in log
    assert states(items) == {"Load": ("FAILED", "ERROR", 1), "Report": ("NOT_RUN", "PREREQUISITES_NOT_MET", None),
                             "Alert": ("SUCCESS", None, 0), "Cleanup": ("SUCCESS", None, 0)}
    assert "'Report' will not run: it waits for 'Load' to succeed, and 'Load' failed with return code 1." in log


def test_any_starts_a_job_when_one_of_its_prerequisites_holds(sim, flow, run_flow):
    flow("EITHER", [("Primary", sim("A", fail=True)), ("Backup", sim("B")),
                    ("Publish", sim("C"), ["Primary", "Backup"], "ANY")])
    code, run, items, log = run_flow("EITHER")
    assert items["Publish"].Status == "SUCCESS"
    assert run.Status == "SUCCESS"           # Publish could do without Primary, and ran: handled


def test_a_failure_nothing_ran_after_fails_the_workflow(sim, flow, run_flow):
    flow("CHAIN", [("A", sim("A", fail=True)), ("B", sim("B"), ["A"])])
    code, run, items, log = run_flow("CHAIN")
    assert code == 1
    assert (run.Status, run.Reason) == ("FAILED", "JOB_FAILED")
    assert run.ErrorMessage == "1 job failed with nothing that waits for it run: A."
    assert items["B"].Status == "NOT_RUN"         # not counted against the workflow; A's failure is


def test_a_failure_on_a_failure_path_fails_the_workflow(sim, flow, run_flow):
    flow("PATH", [("Load", sim("A", fail=True)), ("Alert", sim("B", fail=True), [("Load", "FAILED")])])
    code, run, items, log = run_flow("PATH")
    assert code == 1
    assert run.ErrorMessage == "1 job failed with nothing that waits for it run: Alert."


# ---------- Return codes ----------

def test_return_codes_decide_success_and_which_paths_run(sim, flow, run_flow):
    flow("CODES", [("Check", sim("A", code=4, success="0, 4")), ("On4", sim("B"), [("Check", "RC", "4")]),
                   ("On8", sim("C"), [("Check", "RC", "8-10")])])
    code, run, items, log = run_flow("CODES")
    assert code == 0, log
    assert states(items) == {"Check": ("SUCCESS", None, 4), "On4": ("SUCCESS", None, 0),
                             "On8": ("NOT_RUN", "PREREQUISITES_NOT_MET", None)}
    assert "it waits for 'Check' to give return code 8-10, and 'Check' succeeded with return code 4" in log


def test_a_job_whose_return_code_is_not_a_success_code_fails(sim, run_runner, load_spool, db):
    sim("ODD", code=3, messages="Pretending to work\nStill pretending")
    result = run_runner("ODD")
    assert result.returncode == 1                       # the exit code a scheduler sees is still 0 or 1
    load_spool()
    run = db.query(JobRun).filter(JobRun.JobKey == "ODD").one()
    assert (run.Status, run.ReturnCode, run.Reason) == ("FAILED", 3, "RETURN_CODE")
    assert "ended with return code 3, which its Success return codes (0) do not include" in run.ErrorMessage
    assert "Pretending to work" in result.stdout


def test_a_job_whose_return_code_is_a_success_code_succeeds(sim, run_runner, load_spool, db):
    sim("FINE", code=3, success="0-3")
    assert run_runner("FINE").returncode == 0
    load_spool()
    run = db.query(JobRun).filter(JobRun.JobKey == "FINE").one()
    assert (run.Status, run.ReturnCode, run.Reason) == ("SUCCESS", 3, None)


# ---------- The Set Return Code step ----------

def test_set_return_code_carries_on_and_the_last_one_run_wins(seed, endpoints, run_runner, load_spool, db):
    job = seed.job("CODES")
    job.SuccessReturnCodes = "0, 4"
    seed.step(job, 1, "SET_RETURN_CODE", title="First", ReturnCode="8")
    seed.step(job, 2, "SET_RETURN_CODE", title="Second", ReturnCode="4", Message="No files arrived")
    seed.step(job, 3, title="Still runs", SourceEndpoint="LEGAL_EXTRACTS", Dest="incoming")
    result = run_runner("CODES")

    assert result.returncode == 0
    assert "Return code set to 4: No files arrived" in result.stdout
    assert "Step 3: Still runs" in result.stdout                    # the job carried on after setting it
    load_spool()
    operations = db.query(Operation).filter(Operation.OpType == "SET_RETURN_CODE").all()
    assert [o.OpStatus for o in operations] == ["SUCCESS", "SUCCESS"]       # one record for each, for the trace
    run = db.query(JobRun).filter(JobRun.JobKey == "CODES").one()
    assert (run.Status, run.ReturnCode) == ("SUCCESS", 4)


def test_a_return_code_set_that_is_not_a_success_code_fails_the_job(seed, run_runner, load_spool, db):
    job = seed.job("BAD_CODE")
    seed.step(job, 1, "SET_RETURN_CODE", ReturnCode="8")
    assert run_runner("BAD_CODE").returncode == 1
    load_spool()
    run = db.query(JobRun).filter(JobRun.JobKey == "BAD_CODE").one()
    assert (run.Status, run.ReturnCode, run.Reason) == ("FAILED", 8, "RETURN_CODE")


def test_set_return_code_inside_an_if_lets_a_job_choose_its_own_code(seed, run_runner, load_spool, db):
    job = seed.job("CHOOSE", Mode="B")
    choice = seed.step(job, 1, "IF", title="Which code", Condition="${Mode} = 'A'")
    then = seed.step(job, 1, "THEN", parent=choice)
    seed.step(job, 1, "SET_RETURN_CODE", parent=then, ReturnCode="2")
    otherwise = seed.step(job, 2, "ELSE", parent=choice)
    seed.step(job, 1, "SET_RETURN_CODE", parent=otherwise, ReturnCode="3")
    job.SuccessReturnCodes = "0-3"
    assert run_runner("CHOOSE").returncode == 0
    load_spool()
    assert db.query(JobRun).filter(JobRun.JobKey == "CHOOSE").one().ReturnCode == 3


def test_set_return_code_masks_a_secret_in_its_message(seed, run_runner, db):
    job = seed.job("SECRET_CODE")
    db.add(Variable(MasterObject_id=job.MasterObject_id, VarName="Token", VarValue="s3cr3t-t0ken", IsSecret=True))
    seed.step(job, 1, "SET_RETURN_CODE", ReturnCode="0", Message="Token was ${Token}")
    result = run_runner("SECRET_CODE")
    assert "Return code set to 0: Token was ********" in result.stdout
    assert "s3cr3t-t0ken" not in result.stdout + result.stderr


def test_set_return_code_refuses_a_code_below_0(seed, run_runner, load_spool, db):
    job = seed.job("NEGATIVE")
    seed.step(job, 1, "SET_RETURN_CODE", ReturnCode="-1")
    result = run_runner("NEGATIVE")
    assert result.returncode == 1
    assert "ReturnCode cannot be below 0." in result.stderr


# ---------- Cancelling, nesting, refusing ----------

def test_cancel_starts_nothing_more_and_lets_running_jobs_finish(sim, flow, db, db_url, tmp_path):
    flow("LONG", [("Slow", sim("A", wait=3)), ("After", sim("B"), ["Slow"])])
    process = start(db_url, tmp_path, "LONG")
    deadline = time.time() + 60
    while time.time() < deadline:
        db.expire_all()
        item = db.query(WorkflowRunItem).filter(WorkflowRunItem.ItemName == "Slow").first()
        if item and item.Status == "RUNNING":
            break
        time.sleep(0.2)
    run = db.query(JobRun).filter(JobRun.JobKey == "LONG").one()
    run.CancelRequestedDateTime = utcnow()
    db.commit()
    process.communicate(timeout=60)

    run, items, log = results(db, "LONG")
    assert process.returncode == 1
    assert (run.Status, run.Reason) == ("FAILED", "CANCELLED")
    assert run.ErrorMessage == "Cancelled: 1 job did not start: After."
    assert states(items) == {"Slow": ("SUCCESS", None, 0), "After": ("NOT_RUN", "CANCELLED", None)}
    assert "Cancel asked for" in log


def test_a_workflow_can_run_another_and_each_run_points_to_the_one_above(sim, flow, run_flow, db):
    inner = flow("INNER", [("Step", sim("X"))])
    flow("OUTER", [("Inner", inner), ("Last", sim("Y"), ["Inner"])])
    code, run, items, log = run_flow("OUTER")
    assert code == 0, log
    inner_run = items["Inner"].child_run
    assert (inner_run.JobType, inner_run.ParentRun_id, inner_run.WorkflowPath) == ("WORKFLOW", run.id, "Inner")
    step_run = db.query(JobRun).filter(JobRun.JobKey == "X").one()
    assert (step_run.ParentRun_id, step_run.WorkflowPath) == (inner_run.id, "Inner/Step")


def test_a_workflow_that_cannot_run_fails_at_once_saying_why(sim, flow, run_flow, db):
    off = flow("OFF", [("Only", sim("A"))])
    off.IsActive = False
    db.commit()
    code, run, items, log = run_flow("OFF")
    assert code == 1 and items == {}
    assert (run.Status, run.Reason) == ("FAILED", "ERROR")
    assert run.ErrorMessage == "The workflow cannot run: Workflow 'OFF' is disabled."


def test_a_disabled_job_ends_disabled_and_what_needs_its_success_does_not_run(sim, flow, run_flow, db):
    off = sim("A")
    off.IsActive = False
    flow("FLOW", [("Off", off), ("After", sim("B"), ["Off"]), ("Tidy", sim("C"), [("Off", "ENDED")]),
                  ("Other", sim("D"))])
    code, run, items, log = run_flow("FLOW")
    assert code == 0, log
    assert {name: item.Status for name, item in items.items()} == {
        "Off": "DISABLED", "After": "NOT_RUN", "Tidy": "SUCCESS", "Other": "SUCCESS"}
    assert db.query(JobRun).filter(JobRun.JobKey == "A").count() == 0          # never started
    assert "'Off' is disabled (job 'A'), so it does not run." in log
    assert "'After' will not run: it waits for 'Off' to succeed, and 'Off' is disabled." in log


def test_a_job_that_would_fail_its_own_check_fails_when_its_turn_comes(sim, flow, run_flow, seed, db):
    broken = seed.job("BROKEN")
    seed.step(broken, 1, Source="nowhere/*.csv", Dest="out")
    flow("FLOW", [("First", sim("A")), ("Broken", broken, ["First"]), ("Next", sim("B"), ["Broken"])])
    code, run, items, log = run_flow("FLOW")
    assert code == 1
    assert [items[n].Status for n in ("First", "Broken", "Next")] == ["SUCCESS", "FAILED", "NOT_RUN"]
    assert items["Broken"].child_run.Status == "FAILED"
