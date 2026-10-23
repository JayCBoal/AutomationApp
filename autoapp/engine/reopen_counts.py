"""
When an operator reset a run's automatic retry counts (docs/WORKFLOWS_PHASE7.md, step 6c). The counts of a run are
rebuilt from its Reaction events each time it is reopened, so a reset must outlast the restart that made it: its
restart record says so, and the rebuild counts only the events after the latest reset. A run embedded in another is
reset with the run at the top of its tree.
"""
import json
from datetime import datetime
from typing import List, Optional

from sqlalchemy.orm import Session

from app.models import JobRun, RunRestart


def reset_at(db: Session, run: JobRun) -> Optional[datetime]:
    """When the counts of this run were last reset, by a restart of it or of a workflow around it; None if never."""
    run_ids: List[str] = []
    while run is not None:
        run_ids.append(run.RunID)
        run = db.get(JobRun, run.ParentRun_id) if run.ParentRun_id else None
    rows = db.query(RunRestart).filter(RunRestart.RunID.in_(run_ids)).all()
    times = [row.ChosenDateTime for row in rows if json.loads(row.Details or "{}").get("counts_reset")]
    return max(times) if times else None
