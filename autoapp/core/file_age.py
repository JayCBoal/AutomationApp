"""
How long files have been left alone. One function for both users: an endpoint prerequisite in a
workflow (docs/WORKFLOWS_PHASE5.md, "a file is old enough when nothing has changed it for N
seconds"), and Check Files when its minimum age is built.
"""
import os
import time
from typing import List, Optional


def unchanged_for(path: str, seconds: int, moment: Optional[float] = None) -> bool:
    """Whether nothing has changed the file for at least this many seconds, as of moment (time.time() if left out)."""
    moment = time.time() if moment is None else moment
    return moment - os.path.getmtime(path) >= seconds


def too_new(paths: List[str], seconds: int, moment: Optional[float] = None) -> List[str]:
    """The files among paths that have been changed within the last seconds, in the order given."""
    return [path for path in paths if not unchanged_for(path, seconds, moment)]
