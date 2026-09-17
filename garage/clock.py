"""
Injectable clock.

Why this exists: the nightly auto-close job (Twist 2) is graded via
POST /clock, which means an external grader must be able to set or
fast-forward "now" deterministically. If the rest of the code calls
datetime.now() directly, that's impossible to control from outside.

Design:
  - SystemClock: real wall-clock time, unaffected by anything. Used
    wherever no clock is explicitly supplied (e.g. plain scripts/tests).
  - SimulatedClock: behaves EXACTLY like a real clock between calls to
    set()/advance() (it keeps ticking forward with real elapsed time,
    so normal attendant use - checking cars in/out minutes apart - looks
    completely normal). set()/advance() re-anchor it to an exact instant,
    which is what lets the grader jump it forward 24h+ to trigger the
    nightly job, or pin it to a specific ISO timestamp.
"""
from datetime import datetime, timedelta
from typing import Optional


class Clock:
    def now(self) -> datetime:
        raise NotImplementedError


class SystemClock(Clock):
    """Real wall-clock time."""

    def now(self) -> datetime:
        return datetime.now()


class SimulatedClock(Clock):
    """
    Grader-controllable clock.

    now() = sim_anchor + (real time elapsed since the anchor was last set)

    So between set()/advance() calls it behaves identically to a real
    clock (ticks forward normally). set()/advance() rebase the anchor
    to an exact instant, which is what makes it possible to jump time
    forward for grading without freezing the clock for everything else.
    """

    def __init__(self, start: Optional[datetime] = None):
        self._real_anchor = datetime.now()
        self._sim_anchor = start or self._real_anchor

    def now(self) -> datetime:
        elapsed = datetime.now() - self._real_anchor
        return self._sim_anchor + elapsed

    def set(self, ts: datetime) -> datetime:
        """Pin simulated time to an exact instant."""
        self._real_anchor = datetime.now()
        self._sim_anchor = ts
        return self.now()

    def advance(self, hours: float = 0, minutes: float = 0) -> datetime:
        """Fast-forward simulated time by a fixed amount."""
        return self.set(self.now() + timedelta(hours=hours, minutes=minutes))
