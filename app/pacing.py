"""Pacing policies decide *when* the agent wakes; the loop never decides timing itself.

next_delay(now, last_tick) -> seconds until the next timer wake, or None for no timer.
wakes_on_events -> whether inbox items / stat alerts wake the agent early.
"""
from typing import Protocol

from .config import Settings


class PacingPolicy(Protocol):
    name: str
    wakes_on_events: bool

    def next_delay(self, now: float, last_tick: float) -> float | None: ...


class HeartbeatEvents:
    name = "heartbeat_events"
    wakes_on_events = True

    def __init__(self, s: Settings):
        self.interval = s.heartbeat_seconds

    def next_delay(self, now, last_tick):
        return max(0.0, last_tick + self.interval - now)


class FixedTick:
    name = "fixed_tick"
    wakes_on_events = False

    def __init__(self, s: Settings):
        self.interval = s.tick_seconds

    def next_delay(self, now, last_tick):
        return max(0.0, last_tick + self.interval - now)


class Manual:
    """Only wakes on POST /tick. Zero cost; handy for debugging."""

    name = "manual"
    wakes_on_events = False

    def __init__(self, s: Settings):
        pass

    def next_delay(self, now, last_tick):
        return None


# Add a policy (e.g. viewer_gated in M2) by registering it here.
POLICIES = {"heartbeat_events": HeartbeatEvents, "fixed_tick": FixedTick, "manual": Manual}


def get_policy(s: Settings) -> PacingPolicy:
    try:
        return POLICIES[s.pacing](s)
    except KeyError:
        raise ValueError(f"unknown PACING {s.pacing!r}; options: {sorted(POLICIES)}") from None
