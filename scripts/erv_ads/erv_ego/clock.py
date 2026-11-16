"""Time sources for secMark / message age.

SimClock maps CARLA simulation time onto UTC with a fixed epoch, so every
process attached to the same CARLA world (scenario runner, a separate ERV
broadcaster, ego node) agrees on secMark without NTP. WallClock is for real
hardware in the loop (OBUs stamp secMark from GNSS time).
"""

from __future__ import annotations

import time
from datetime import datetime, timezone

DEFAULT_SIM_EPOCH = datetime(2026, 1, 1, tzinfo=timezone.utc).timestamp()


class Clock:
    def utc_s(self) -> float:
        raise NotImplementedError

    def sec_mark(self) -> int:
        return int(round(self.utc_s() * 1000.0)) % 60000


class SimClock(Clock):
    def __init__(self, epoch_utc_s: float = DEFAULT_SIM_EPOCH):
        self.epoch = epoch_utc_s
        self.sim_s = 0.0

    def set_sim_time(self, elapsed_seconds: float) -> None:
        self.sim_s = float(elapsed_seconds)

    def utc_s(self) -> float:
        return self.epoch + self.sim_s


class WallClock(Clock):
    def utc_s(self) -> float:
        return time.time()


def sec_mark_age_ms(now_sec_mark: int, msg_sec_mark: int) -> int:
    """Age of a message in ms, handling minute wrap. Negative = from the future."""
    d = (now_sec_mark - msg_sec_mark) % 60000
    return d - 60000 if d > 30000 else d


def make_clock(kind: str, epoch_utc_s: float = DEFAULT_SIM_EPOCH) -> Clock:
    return WallClock() if kind == "wall" else SimClock(epoch_utc_s)
