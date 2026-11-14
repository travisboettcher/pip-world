"""The agent's stats (docs/DESIGN-world-packs.md, phase 3): the needs a world declares in its pack's stats.json, not two the engine knows.

Each stat says where it starts, how it changes an hour (and asleep, resting or at work), when it raises an alert, which way is good, how
low a value counts as "low" (so the world spares it), and what restores it: `eat` (food, or a plain meal), `rest`, `sleep`. The engine
keeps every declared stat in the `stats` table, decays them, raises their alerts, and shows them; `state.agent()` still carries each by
name (`a["hunger"]`), and `state.update_agent(hunger=...)` still sets it. Code that needs a role asks for it (`restored_by("eat")`,
`tiring()`) rather than naming a stat.
"""
from . import world_pack


def declared(settings=None) -> dict:
    """{name: definition} for the world's stats, with any overrides the settings carry (`Settings.stats`, for tests and tuning: one
    that names a stat the world hasn't adds it)."""
    base = (world_pack.load(settings) if settings is not None else world_pack.active()).data("stats")
    over = getattr(settings, "stats", None) or {}
    return {name: {**base.get(name, {}), **over.get(name, {})} for name in {**base, **over}}


def restored_by(action: str, settings=None) -> list[str]:
    """The stats an action restores: `eat` (food), `rest`, `sleep`."""
    return [n for n, d in declared(settings).items() if action in d.get("restored_by", ())]


def tiring(settings=None) -> str | None:
    """The stat that work wears down and that tiredness reads (the one marked `tires`), if the world has one."""
    return next((n for n, d in declared(settings).items() if d.get("tires")), None)


def good_sign(d: dict) -> int:
    """+1 when more of this stat is better (energy), -1 when less is (hunger)."""
    return 1 if d.get("good", "high") == "high" else -1


def is_low(d: dict, value: float) -> bool:
    """On the stat's bad side, past its `low_at` (the world doesn't make it worse)."""
    if "low_at" not in d:
        return False
    return value <= d["low_at"] if good_sign(d) > 0 else value >= d["low_at"]


def alerting(d: dict, value: float) -> bool:
    a = d.get("alert") or {}
    return ("above" in a and value >= a["above"]) or ("below" in a and value <= a["below"])


def rate(d: dict, activity: str, working: bool, away: bool = False) -> float:
    """How fast a stat changes an hour, given what the agent is doing (and, with `away_per_hour`, whether it is out of its home)."""
    r = d["away_per_hour"] if away and "away_per_hour" in d else d.get("per_hour", 0.0)
    if activity == "sleeping":
        r = d["asleep_per_hour"] if "asleep_per_hour" in d else r * d.get("asleep_factor", 1)
    elif activity == "resting" and "resting_per_hour" in d:
        r = d["resting_per_hour"]
    if working:
        r += d.get("working_per_hour", 0.0)
    return r


def low(state) -> bool:
    """Whether any of the agent's stats is on its low side."""
    a = state.agent()
    return any(is_low(d, a[n]) for n, d in declared(state.s).items() if n in a)


def bounded(d: dict, value: float) -> float:
    """Within what the world may push a stat to (`floor`, `ceiling`) and 0..1."""
    return max(d.get("floor", 0.0), min(d.get("ceiling", 1.0), value))


def line(state) -> str:
    """The stats for a prompt: "hunger 0.2, energy 0.9"."""
    a = state.agent()
    return ", ".join(f"{d.get('label', n)} {a[n]:.1f}" for n, d in declared(state.s).items() if n in a)


def prompt_line(state) -> str:
    """The stats for the agent's own prompt: "hunger 0.20 (1=starving), energy 0.90 (0=exhausted)"."""
    a = state.agent()
    return ", ".join(f"{d.get('label', n)} {a[n]:.2f}" + (f" ({d['scale']})" if d.get("scale") else "")
                     for n, d in declared(state.s).items() if n in a)


def tiredness(state) -> float:
    """The tiring stat's value (1.0 if the world has none), for the work dice."""
    t = tiring(state.s)
    return state.agent()[t] if t else 1.0


def tired(state, value: float | None = None) -> bool:
    """Whether the agent is too tired to work well (the tiring stat below its `tired_below`)."""
    t = tiring(state.s)
    if not t:
        return False
    return (tiredness(state) if value is None else value) < declared(state.s)[t].get("tired_below", 0.0)


def values(state) -> dict:
    """{name: value} for every stat."""
    a = state.agent()
    return {n: a[n] for n in declared(state.s) if n in a}
