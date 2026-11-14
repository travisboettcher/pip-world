"""Stakes (docs/DESIGN-world-packs.md, phase 6): what happens when one of the agent's stats runs out.

A pack marks a stat with `at_zero`, an outcome the engine knows, for when the stat reaches its bad end (0 for one where high is good, 1
for one where low is good):
- `knocked_out`: whatever the agent was doing ends, it comes to at home `out_hours` later (4 by default), and the stat is back at
  `recovers_to` (by default a little past its low side);
- `weak`: whatever the agent was doing ends, and until the stat is off its low side again it can only eat, rest, sleep, talk and think.
Nothing is permanent: no death, no lost memory. A world hurts the agent through any stat (modules' `affect`, a happening's `harm`), and
the engine checks each turn of the world. Pip's world marks none, so nothing here ever happens there.
"""
import json
import time

from . import stats as stats_mod

OUTCOMES = ("knocked_out", "weak")
OUT_HOURS = 4
END = 0.001                                                      # how near the bad end counts as reaching it
WEAK_TOOLS = {"eat", "rest", "sleep", "say", "note_to_self", "recall", "feel"}   # what a weak agent can still do: recover, talk, think


def bad_end(d: dict) -> float:
    return 0.0 if stats_mod.good_sign(d) > 0 else 1.0


def at_end(d: dict, value: float) -> bool:
    """The stat has run out."""
    return round(abs(value - bad_end(d)), 9) <= END


def recovers_to(d: dict) -> float:
    """Where a knockout leaves the stat: `recovers_to`, else a little past its low side (or 0.3 from its bad end)."""
    if "recovers_to" in d:
        return d["recovers_to"]
    return d["low_at"] + stats_mod.good_sign(d) * 0.1 if "low_at" in d else bad_end(d) + stats_mod.good_sign(d) * 0.3


def recovered(d: dict, value: float) -> bool:
    """Off its low side again (or, with no `low_at`, 0.2 from its bad end)."""
    return not stats_mod.is_low(d, value) if "low_at" in d else round(abs(value - bad_end(d)), 9) >= 0.2


def condition(state) -> dict | None:
    """What a stat running out has left the agent in: {outcome, stat, label, since, until?}, or None."""
    raw = state.meta("stakes")
    return json.loads(raw) if raw else None


def out(state, now: float | None = None) -> bool:
    """Knocked out, and not come to yet."""
    c = condition(state)
    return bool(c and c["outcome"] == "knocked_out" and (now or time.time()) < c["until"])


def weak(state) -> bool:
    c = condition(state)
    return bool(c and c["outcome"] == "weak")


def allowed(state, tool: str) -> bool:
    """Whether the agent can use a tool as it is: anything, unless weak (then only eating, resting, sleeping, talking and thinking)."""
    return tool in WEAK_TOOLS or not weak(state)


async def _stop(state, settings) -> None:
    """End whatever the agent was doing: a module's session (it hears it was cut short), a walk."""
    sess = state.session()
    if not sess:
        return
    if sess["kind"] == "module":
        from . import modules
        await modules.end_session(state, settings, modules.runner_for(settings), interrupted=True)
    else:
        state.end_session()


async def step(state, settings, now: float | None = None) -> bool:
    """A turn of the world: a stat that has run out takes effect, or the agent recovers. True when the agent should hear of it."""
    now = now or time.time()
    declared, a, cur = stats_mod.declared(settings), state.agent(), condition(state)
    if cur:
        d = declared.get(cur["stat"])
        if d is None or (cur["outcome"] == "weak" and recovered(d, a[cur["stat"]])) or (cur["outcome"] == "knocked_out" and now >= cur["until"]):
            state.set_meta(stakes="")
            state.log("recovered", outcome=cur["outcome"], stat=cur["stat"], label=cur["label"])
            return True
        return False
    for name, d in declared.items():
        if d.get("at_zero") not in OUTCOMES or name not in a or not at_end(d, a[name]):
            continue
        from . import places
        await _stop(state, settings)
        c = {"outcome": d["at_zero"], "stat": name, "label": d.get("label", name), "since": now}
        if c["outcome"] == "knocked_out":
            c["until"] = now + d.get("out_hours", OUT_HOURS) * 3600
            state.update_agent(**{name: stats_mod.bounded(d, recovers_to(d))}, location=places.HOME, activity="sleeping", description="out cold")
            state.set_meta(sleep_started=now, sleep_until=c["until"])
        else:
            state.update_agent(activity="resting", description="too weak to do much")
        state.set_meta(stakes=json.dumps(c))
        state.log("stakes", outcome=c["outcome"], stat=name, label=c["label"], place=a["location"],
                  **({"hours": d.get("out_hours", OUT_HOURS)} if c["outcome"] == "knocked_out" else {}))
        return True
    return False


def perception(state) -> list[str]:
    """What the agent is told while weak."""
    c = condition(state)
    if not c or c["outcome"] != "weak":
        return []
    return [f"Your {c['label']} ran out: you are too weak to do anything but eat, rest, sleep, talk and think until it recovers."]


def moment(d: dict) -> str:
    """A stat running out, or recovering from it, as a line for the agent's day."""
    if d.get("outcome") == "knocked_out":
        return f"Your {d['label']} ran out and you were knocked out; you came to at home"
    return f"Your {d['label']} ran out and you grew too weak to do much"
