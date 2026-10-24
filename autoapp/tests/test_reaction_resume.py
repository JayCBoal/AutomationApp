"""
A Reaction's Rerun this job: Restart from the beginning or Resume from failure (docs/WORKFLOWS_PHASE7.md,
step 3a, proposal 13). Judging, saving over HTTP, and carrying it out by the job runner (a job on its own)
and the workflow runner (a job in a workflow).
"""
import threading

import pytest

from core.models import JobRun, ReactionAction, ReactionEvent
from engine.reactions import RESTART, RESUME, Act, Rule, judge
from test_control_file import gated_job, log_of, put_gate
from test_launches import post  # noqa: F401 (fixtures)
from test_reactions_api import act, reaction, steps_job
from test_workflow_reactions import events, react
from test_workflow_runner import flow, results, run_flow, sim, start  # noqa: F401 (fixtures)


def messages(db):
    db.commit()
    return [e.Message for e in db.query(ReactionEvent).order_by(ReactionEvent.id)]


def open_gate_soon(tmp_path, job="RES", after=1.5):
    """The gate file appears while the Reaction waits to rerun."""
    timer = threading.Timer(after, put_gate, args=(tmp_path, "a.ok"), kwargs={"job": job})
    timer.start()
    return timer


# ---------- Judging ----------

def test_a_resume_that_cannot_be_carried_out_is_passed_over_for_the_next_entry_that_holds():
    resume, fail = Act(1, "RERUN", max_times=2, mode=RESUME), Act(2, "COUNT_AS_FAILED")
    rules = [Rule(None, "NEXT", "FAILED", None, [resume]), Rule(None, "NEXT", "FAILED", None, [fail])]

    verdict = judge(rules, "FAILED", 1, lambda a: 0, in_workflow=False, cannot=lambda a: "no way" if a.resumes else None)
    assert (verdict.decisions, verdict.not_fired) == ([fail], [(resume, "no way")])
    assert judge(rules, "FAILED", 1, lambda a: 0, in_workflow=False, cannot=lambda a: None).decisions == [resume]


def test_an_action_says_in_words_whether_it_resumes():
    assert Act(1, "RERUN", mode=RESUME).words() == "rerun from where it failed"
    assert Act(1, "RERUN", mode=RESTART).words() == "rerun"
    assert Act(1, "RERUN").mode == RESTART


# ---------- Saving ----------

def test_a_new_rerun_defaults_to_resume_and_an_old_one_reads_as_restart(client, db):
    reactions = [reaction("RC", act("RERUN", max_times=2), codes="8"),
                 reaction("RC", act("RERUN", max_times=1, mode="RESTART"), codes="4")]
    assert client.post("/api/v1/jobs", json=steps_job("FLAKY", reactions)).status_code == 201

    saved = client.get("/api/v1/jobs/FLAKY").json()["reactions"]
    assert [r["actions"][0]["mode"] for r in saved] == ["RESUME", "RESTART"]
    db.query(ReactionAction).update({ReactionAction.RerunMode: None})
    db.commit()
    again = client.get("/api/v1/jobs/FLAKY").json()["reactions"]
    assert [r["actions"][0]["mode"] for r in again] == ["RESTART", "RESTART"]


def test_a_rerun_mode_must_be_one_of_the_two(client):
    response = client.post("/api/v1/jobs", json=steps_job(
        "ODD", [reaction("FAILED", act("RERUN", max_times=1, mode="SOMETIMES"))]))
    assert response.status_code == 422 and "RESTART" in response.text and "RESUME" in response.text


# ---------- A job on its own ----------

def alone(seed, db, mode, **settings):
    """The gated job, which fails until its gate file is there, rerunning once after four seconds."""
    job = gated_job(seed)
    react(db, job, "FAILED", ("RERUN", {"MaxTimes": 1, "WaitSeconds": 4, "RerunMode": mode, **settings}))
    return job


def attempts(db):
    db.commit()
    db.expire_all()
    return db.query(JobRun).filter(JobRun.JobKey == "RES").order_by(JobRun.id).all()


def test_a_resume_by_reaction_picks_up_the_job_where_it_failed(seed, endpoints, db, run_runner, load_spool, tmp_path):
    alone(seed, db, RESUME)
    timer = open_gate_soon(tmp_path)

    result = run_runner("RES")
    timer.join()
    load_spool()

    assert result.returncode == 0, result.stdout + result.stderr
    first, second = attempts(db)
    assert (first.Status, second.Status, second.Attempt) == ("FAILED", "SUCCESS", 2)
    assert "Step 1: Collect (COPY_FILES): finished in the earlier attempt" in log_of(tmp_path, second.RunID)
    assert (first.FileCount, second.FileCount) == (2, 3)                  # the second adds up both attempts
    assert "from where it failed" in messages(db)[0]


def test_a_restart_by_reaction_runs_every_step_again(seed, endpoints, db, run_runner, load_spool, tmp_path):
    alone(seed, db, RESTART)
    timer = open_gate_soon(tmp_path)

    result = run_runner("RES")
    timer.join()
    load_spool()

    assert result.returncode == 0, result.stdout + result.stderr
    first, second = attempts(db)
    assert second.Status == "SUCCESS"
    assert "finished in the earlier attempt" not in log_of(tmp_path, second.RunID)
    assert second.FileCount == 3
    assert "from the beginning" in messages(db)[0]


def unknown_job(seed, db, *then):
    job = seed.job("UNSURE")
    seed.step(job, 1, "SIMULATE", title="Post", Fail="True", EffectUnknown="True")
    react(db, job, "FAILED", ("RERUN", {"MaxTimes": 2, "RerunMode": RESUME}), order=1)
    for order, (action, settings) in enumerate(then, start=2):
        react(db, job, "FAILED", (action, settings), order=order)
    return job


def test_a_resume_does_not_fire_after_a_failure_whose_effect_is_unknown(seed, db, run_runner, load_spool):
    unknown_job(seed, db)

    result = run_runner("UNSURE")
    load_spool()

    assert result.returncode == 1
    runs = db.query(JobRun).filter(JobRun.JobKey == "UNSURE").all()
    assert [(r.Status, r.Reason) for r in runs] == [("FAILED", "EFFECT_UNKNOWN")]
    assert events(db) == [("RERUN", "NOT_FIRED")]
    assert "cannot tell whether it changed anything" in messages(db)[0]


def test_a_resume_that_cannot_fire_leaves_the_next_reaction_that_holds_to_decide(seed, db, run_runner, load_spool):
    unknown_job(seed, db, ("COUNT_AS_SUCCEEDED", {}))

    result = run_runner("UNSURE")
    load_spool()

    assert result.returncode == 0
    assert events(db) == [("RERUN", "NOT_FIRED"), ("COUNT_AS_SUCCEEDED", "TOOK_EFFECT")]


def test_a_job_that_failed_on_its_return_code_has_no_step_to_resume(seed, db, run_runner, load_spool):
    job = seed.job("CODED")
    seed.step(job, 1, "SIMULATE", title="Work", ReturnCode="8")
    react(db, job, "FAILED", ("RERUN", {"MaxTimes": 1, "RerunMode": RESUME}))

    run_runner("CODED")
    load_spool()

    assert events(db) == [("RERUN", "NOT_FIRED")]
    assert "Restart from the beginning" in messages(db)[0]


# ---------- A job in a workflow ----------

def test_in_a_workflow_a_resume_by_reaction_picks_up_the_job_and_a_restart_starts_it_over(
        seed, endpoints, db, flow, run_flow, tmp_path):
    gated = alone(seed, db, RESUME)
    flow("PICKUP", [("Gate", gated)])
    # the Reaction belongs to the job, so it applies in the workflow
    timer = open_gate_soon(tmp_path)

    code, run, items, log = run_flow("PICKUP")
    timer.join()

    assert code == 0, log
    assert (items["Gate"].Status, items["Gate"].Attempt) == ("SUCCESS", 2)
    second = items["Gate"].child_run
    assert second.FileCount == 3
    assert "Rerunning Gate from where it failed" in log
    assert "finished in the earlier attempt" in "\n".join(open(next((tmp_path / "logs").rglob(f"{second.RunID}.log"))))


def test_in_a_workflow_a_resume_after_an_unknown_failure_does_not_fire(seed, db, flow, run_flow):
    unsure = unknown_job(seed, db)
    flow("STUCK", [("Post", unsure)])

    code, run, items, log = run_flow("STUCK")

    assert code == 1
    assert (items["Post"].Status, items["Post"].Attempt) == ("FAILED", 1)
    assert events(db) == [("RERUN", "NOT_FIRED")]
    assert "was not carried out" in log
