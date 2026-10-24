"""
Whether a Reaction may Resume a workflow run (docs/WORKFLOWS_PHASE7.md, step 5a-1): core.reopen_tree.automatic_problem
is the one rule, the operator's Resume with nobody there to decide. One refusal refuses the whole workflow.
"""
from core.models import WorkflowItem
from core.reopen_tree import automatic_problem
from test_frames_engine import tree     # noqa: F401  (fixture)
from test_workflow_reopen import fix, framed, two_stage
from test_workflow_runner import flow, results, run_flow, sim, start    # noqa: F401  (fixtures)


def test_a_failed_job_with_a_record_may_be_resumed(sim, flow, run_flow, db):
    two_stage(sim, flow)
    _, run, _, _ = run_flow("WF")
    assert automatic_problem(db, run) is None


def test_a_failed_job_inside_a_failed_frame_may_be_resumed(sim, tree, run_flow, db):
    framed(sim, tree, db)
    _, run, _, _ = run_flow("TOP")
    assert automatic_problem(db, run) is None


def test_a_run_with_nothing_to_pick_up_is_passed_over(sim, flow, run_flow, db):
    two_stage(sim, flow)
    _, run, _, _ = run_flow("WF")
    fix(db, "LOAD")
    run_flow("WF")
    ok_run, _, _ = results(db, "WF")
    assert "nothing to pick up" in automatic_problem(db, ok_run)


def test_a_workflow_edited_since_is_passed_over(sim, flow, run_flow, db):
    two_stage(sim, flow)
    _, run, _, _ = run_flow("WF")
    db.query(WorkflowItem).filter(WorkflowItem.ItemName == "Report").delete()
    db.commit()
    assert "'Report' is no longer in it" in automatic_problem(db, run)


def test_a_failed_job_whose_record_is_gone_is_passed_over(sim, flow, run_flow, db):
    two_stage(sim, flow)
    _, run, items, _ = run_flow("WF")
    items["Load"].child_run.LogFile = "gone/none.log"
    db.commit()
    why = automatic_problem(db, run)
    assert why and "'Load'" in why


def test_a_failed_step_of_unknown_effect_passes_over_the_whole_workflow(sim, flow, run_flow, db, tmp_path):
    from test_reruns import make_unknown
    two_stage(sim, flow)
    _, run, items, _ = run_flow("WF")
    make_unknown(tmp_path, items["Load"].child_run.RunID)
    why = automatic_problem(db, run)
    assert why and "'Load'" in why and "cannot tell whether it changed anything" in why
