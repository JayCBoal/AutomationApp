"""
Judging Reactions (engine/reactions.py): which entry decides, which side effects fire, and
"at most N times". Carrying them out is tested with the runners.
"""
from core.reactions import Act, Rule, judge


def rule(section, test, *actions, codes=None):
    return Rule(None, section, test, codes, list(actions))


def never_used(_act):
    return 0


def test_the_first_next_entry_that_holds_decides():
    rerun, fail = Act(1, "RERUN", max_times=2), Act(2, "COUNT_AS_FAILED")
    rules = [rule("NEXT", "RC", rerun, codes="8"), rule("NEXT", "FAILED", fail)]

    assert judge(rules, "FAILED", 8, never_used, in_workflow=True).decisions == [rerun]
    assert judge(rules, "FAILED", 3, never_used, in_workflow=True).decisions == [fail]
    assert judge(rules, "SUCCESS", 0, never_used, in_workflow=True).decisions == []


def test_every_entry_that_holds_fires_its_side_effects_whichever_decides():
    """The design's example: notify ops on any failure, rerun on 8, otherwise kill the workflow."""
    start_a, start_b = Act(1, "START_WORKFLOW", target_job="OPS_ALERT"), Act(2, "START_WORKFLOW", target_job="AUDIT")
    rerun, kill = Act(3, "RERUN", max_times=2), Act(4, "KILL_WORKFLOW")
    rules = [rule("ALSO", "FAILED", start_a), rule("NEXT", "RC", rerun, codes="8"), rule("NEXT", "FAILED", kill),
             rule("ALSO", "ENDED", start_b)]

    verdict = judge(rules, "FAILED", 8, never_used, in_workflow=True)
    assert (verdict.decisions, verdict.side_effects) == ([rerun], [start_a, start_b])


def test_a_rerun_that_has_used_up_its_limit_passes_to_the_next_entry_that_holds():
    rerun, fail = Act(1, "RERUN", max_times=2), Act(2, "COUNT_AS_FAILED")
    rules = [rule("NEXT", "FAILED", rerun), rule("NEXT", "FAILED", fail)]

    assert judge(rules, "FAILED", 1, lambda act: 1, in_workflow=True).decisions == [rerun]
    verdict = judge(rules, "FAILED", 1, lambda act: 2, in_workflow=True)
    assert (verdict.decisions, verdict.used_up) == ([fail], [rerun])


def test_an_entry_is_judged_on_what_happened_not_on_an_earlier_count_as():
    """Counting a failure as succeeded does not make a later 'it succeeded' entry hold."""
    count, start = Act(1, "COUNT_AS_SUCCEEDED"), Act(2, "START_WORKFLOW", target_job="AFTER_SUCCESS")
    rules = [rule("NEXT", "RC", count, codes="4"), rule("ALSO", "SUCCESS", start)]

    verdict = judge(rules, "FAILED", 4, never_used, in_workflow=True)
    assert (verdict.decisions, verdict.side_effects) == ([count], [])


def test_on_its_own_a_job_leaves_out_what_only_a_workflow_can_do():
    skip, count = Act(1, "SKIP_BRANCH"), Act(2, "COUNT_AS_FAILED")
    rules = [rule("NEXT", "FAILED", skip, count)]

    assert judge(rules, "FAILED", 1, never_used, in_workflow=False).decisions == [count]
    assert judge(rules, "FAILED", 1, never_used, in_workflow=True).decisions == [count, skip]


def test_return_codes_and_ended_hold_as_a_prerequisites_do():
    act = Act(1, "COUNT_AS_SUCCEEDED")
    assert judge([rule("NEXT", "RC", act, codes="0-4")], "FAILED", 3, never_used, True).decisions == [act]
    assert judge([rule("NEXT", "RC", act, codes="0-4")], "FAILED", 5, never_used, True).decisions == []
    assert judge([rule("NEXT", "ENDED", act)], "SUCCESS", 0, never_used, True).decisions == [act]
