"""
Test helper: engine.runner with a clock that goes AUTOAPP_TEST_CLOCK_SPEED times faster than real time, so a test of
"30 minutes" takes seconds. AUTOAPP_TEST_CLOCK_SHIFT_MINUTES starts the clock later, as if time had passed. Takes the runner's own arguments. Only the workflow runner's clock (engine.outside.now) is
changed; the job runners it starts are ordinary.
"""
import os
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core import outside
from engine import runner      # noqa: E402

SPEED = float(os.environ.get("AUTOAPP_TEST_CLOCK_SPEED", "1"))
SHIFT = timedelta(minutes=float(os.environ.get("AUTOAPP_TEST_CLOCK_SHIFT_MINUTES", "0")))     # time that passed before it began
BEGAN, BEGAN_REAL = datetime.now() + SHIFT, time.time()
outside.now = lambda: BEGAN + timedelta(seconds=(time.time() - BEGAN_REAL) * SPEED)

if __name__ == "__main__":
    runner.main()
