"""
A Reaction resumes a failed workflow (docs/WORKFLOWS_PHASE7.md, step 5a): a frame by its parent's Reaction, and a
workflow run on its own by its own. What succeeded stays; what cannot be picked up is passed over for the next Reaction.
"""
import threading
import time

from core.models import JobRun
from app.run_restarts import restarts_for
from engine.reactions import RESTART, RESUME
from test_control_file import gated_job, put_gate
from test_frames_engine import tree     # noqa: F401  (fixture)
from test_reaction_resume import messages, unknown_job
from test_workflow_reactions import events, react
from test_workflow_runner import flow, results, run_flow, sim, start    # noqa: F401  (fixtures)
from core.models import WorkflowPrerequisite


def open_gate_after_first_failure(tmp_path, job="RES"):
    """The gate file appears once the first attempt has failed for want of it, however slowly it got started."""
    def _wait_then_open():
        deadline = time.time() + 90
        while time.time() < deadline:
            if any("No files matched" in path.read_text(errors="ignore") for path in (tmp_path / "logs").rglob("*.log")):
                break
            time.sleep(0.1)
        put_gate(tmp_path, "a.ok", job=job)
    timer = threading.Thread(target=_wait_then_open)
    timer.start()
    return timer


def test_a_frame_is_resumed_by_its_parents_reaction(seed, endpoints, db, tree, sim, run_flow, tmp_path):
    top, made = tree("TOP", {"Frame": {"Gate": gated_job(seed), "Push": sim("PUSH")}})
    gate, push = made["Frame"].job.items
    db.add(WorkflowPrerequisite(item=push, target=gate, Test="SUCCESS"))
    db.commit()
    made["Frame"].ReactionsOverridden = True
    react(db, made["Frame"], "FAILED", ("RERUN", {"MaxTimes": 2, "WaitSeconds": 4, "RerunMode": RESUME}))
    timer = open_gate_after_first_failure(tmp_path)

    code, run, items, log = run_flow("TOP")
    timer.join()

    inner_run, inner, inner_log = results(db, "TOP.Frame")
    first_frame = db.query(JobRun).filter(JobRun.JobKey == "TOP.Frame").order_by(JobRun.id).all()
    assert code == 0, log
    assert (items["Frame"].Status, items["Frame"].Attempt) == ("SUCCESS", 2)
    assert len(first_frame) == 1 and items["Frame"].ChildRun_id == inner_run.id          # the same run, reopened
    assert {n: (i.Status, i.Attempt) for n, i in inner.items()} == {"Gate": ("SUCCESS", 2), "Push": ("SUCCESS", 1)}
    assert "Rerunning Frame from where it failed" in log and "rerun 1 of at most 2" in log
    assert inner_run.FileCount == 3                                                       # Collect was not run again
    assert items["Frame"].child_run.FileCount == 3


def test_a_frame_with_a_step_of_unknown_effect_is_passed_over_for_the_next_reaction(seed, db, tree, run_flow):
    top, made = tree("TOP", {"Frame": {"Post": unknown_job(seed, db)}})
    made["Frame"].ReactionsOverridden = True
    react(db, made["Frame"], "FAILED", ("RERUN", {"MaxTimes": 1, "RerunMode": RESUME}), order=1)
    react(db, made["Frame"], "FAILED", ("RERUN", {"MaxTimes": 1, "RerunMode": RESTART}), order=2)

    code, run, items, log = run_flow("TOP")

    assert code == 1
    assert ("RERUN", "NOT_FIRED") in events(db) and ("RERUN", "TOOK_EFFECT") in events(db)
    assert any("'Post'" in m and "cannot tell whether it changed anything" in m for m in messages(db))
    assert items["Frame"].Attempt == 2
    assert db.query(JobRun).filter(JobRun.JobKey == "TOP.Frame").count() == 2             # a restart is a new run


# ---------- A workflow run on its own, by its own Reaction (step 5a-3) ----------

def unsure_job(seed, key="UNSURE"):
    job = seed.job(key)
    seed.step(job, 1, "SIMULATE", title="Post", Fail="True", EffectUnknown="True")
    return job


def test_a_workflow_on_its_own_is_resumed_by_its_own_reaction_in_the_same_run(seed, endpoints, db, flow, sim, run_flow, tmp_path):
    wf = flow("WF", [("Gate", gated_job(seed)), ("Report", sim("REPORT"), ["Gate"])])
    react(db, wf, "FAILED", ("RERUN", {"MaxTimes": 1, "WaitSeconds": 4, "RerunMode": RESUME}))
    timer = open_gate_after_first_failure(tmp_path)

    code, run, items, log = run_flow("WF")
    timer.join()

    assert code == 0, log
    assert db.query(JobRun).filter(JobRun.JobKey == "WF").count() == 1                    # the same run, reopened
    assert (run.Status, run.Attempt) == ("SUCCESS", 2)
    assert (items["Gate"].Status, items["Gate"].Attempt, items["Report"].Status) == ("SUCCESS", 2, "SUCCESS")
    assert run.FileCount == 3                                                             # Collect was not run again
    assert log.count("picked up again (resume)") == 1                                     # no line is written twice
    listed = restarts_for(db, run)                                                        # the Restarts box and the count
    assert [(r.kind, r.by) for r in listed] == [("RESUME", "a Reaction")]
    assert "picked up again (resume)" in log and "Rerunning the job from where it failed" in log


def test_a_workflow_with_a_step_of_unknown_effect_is_passed_over_and_the_restart_makes_a_new_run(seed, db, flow, run_flow):
    wf = flow("WF", [("Post", unsure_job(seed))])
    react(db, wf, "FAILED", ("RERUN", {"MaxTimes": 1, "RerunMode": RESUME}), order=1)
    react(db, wf, "FAILED", ("RERUN", {"MaxTimes": 1, "RerunMode": RESTART}), order=2)

    code, run, items, log = run_flow("WF")

    runs = db.query(JobRun).filter(JobRun.JobKey == "WF").order_by(JobRun.id).all()
    assert code == 1
    assert events(db)[:2] == [("RERUN", "NOT_FIRED"), ("RERUN", "TOOK_EFFECT")]
    assert len(runs) == 2 and runs[0].SchedulerInstanceID == runs[1].SchedulerInstanceID  # a restart: a new run, same instance
    assert (runs[0].Attempt, runs[1].Attempt) == (1, 2)
    assert "cannot tell whether it changed anything" in "\n".join(messages(db))
