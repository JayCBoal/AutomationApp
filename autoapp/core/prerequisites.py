"""
Where one prerequisite stands (docs/WORKFLOWS.md, "Prerequisites"): the words the workflow runner
and the outside prerequisites (engine/outside_state.py) share.

  HOLDS      it is met
  WAIT       not yet
  NEVER      it can no longer hold (a job of the workflow ended otherwise); outside ones never are
  TIMED_OUT  it ran out of patience (docs/WORKFLOWS_PHASE5.md, D16)
  SKIPPED    an optional prerequisite that ran out of patience: dropped from the job's check (D101)
"""
from typing import Optional

from core import return_codes

FINAL = ("SUCCESS", "FAILED", "NOT_RUN", "DISABLED", "BYPASSED", "SKIPPED")
HOLDS, NEVER, WAIT, TIMED_OUT, SKIPPED_OPTIONAL = "HOLDS", "NEVER", "WAIT", "TIMED_OUT", "SKIPPED"


def prerequisite_state(test: str, codes: Optional[str], status: str, code: Optional[int]) -> str:
    """HOLDS, NEVER (it can no longer hold) or WAIT, given how the job waited for stands."""
    if status not in FINAL:
        return WAIT
    if status == "BYPASSED":            # treated as succeeded without running (docs/WORKFLOWS.md)
        status, code = "SUCCESS", 0
    if test in ("ENDED", "RULE"):     # RULE: named in a Custom rule, which decides, once it has ended
        return HOLDS                # ended in any way, Not run included, so clean-up jobs still run
    if test == "SUCCESS":
        met = status == "SUCCESS"
    elif test == "FAILED":
        met = status == "FAILED"
    else:
        met = return_codes.matches(code, codes)
    return HOLDS if met else NEVER
