"""Abilities objects can grant (see DESIGN-abilities.md).

A thing Pip made can give Pip something it cannot otherwise do, but only while the thing works: a running clock tells the exact time, a
running radio brings news. Like `world_effects.py`, this is a small registry: the GM may propose an ability for a finished project (the
`provides` capability), the engine checks it and owns every limit. A stopped or unwound object provides nothing. Adding an ability is one
registry entry here plus the place its result shows up.
"""
import time
from dataclasses import dataclass

DAY = 86400


@dataclass(frozen=True)
class Ability:
    name: str
    help: str                      # told to the GM: what this ability is for
    words: tuple[str, ...] = ()    # at least one must appear in the project's own words
    per_day: int = 0               # uses a day per providing object (0 = unlimited)
    proposable: bool = True        # False: implied by another capability, never proposed by the GM
    min_difficulty: int = 2


ABILITIES: dict[str, Ability] = {a.name: a for a in (
    Ability("time", "the exact time of day (a clock: implied by the timekeeper capability)", proposable=False),
    Ability("news", "a radio or other receiver that brings in short bulletins",
            ("radio", "wireless", "receiver", "receiving", "crystal", "aerial", "antenna", "transmitter"), per_day=3),
)}


def gm_lines() -> str:
    """The sentence the GM design prompt carries: every ability it may propose, and when."""
    listing = "; ".join(f"{a.name} ({a.help})" for a in ABILITIES.values() if a.proposable)
    return ("provides: ONLY if what Pip finished gives it something it could not have without the thing, while the thing works - give "
            f"`ability` as one of: {listing}. For anything else never use it (a pond, a painting or a gift is just itself)")


def allowed(ability, project: dict) -> bool:
    a = ABILITIES.get(ability) if isinstance(ability, str) else None
    if not a or not a.proposable or project["difficulty"] < a.min_difficulty:
        return False
    words = " ".join([project["name"], project.get("goal") or ""] + [st["name"] for st in project.get("stages", [])]).lower()
    return any(w in words for w in a.words)


def providers(state, ability: str, now: float) -> list[dict]:
    """The creations that give `ability` right now (a stopped one gives nothing)."""
    from . import creations as cr
    out = []
    for c in state.creations():
        caps = c["spec"]["capabilities"]
        gives = "timekeeper" in caps if ability == "time" else caps.get("provides", {}).get("ability") == ability
        if gives and cr.running(c, now):
            out.append(c)
    return out


def has(state, ability: str, now: float) -> bool:
    return bool(providers(state, ability, now))


def perception(state, now: float) -> list[str]:
    """The time, told exactly, while a clock runs."""
    from . import creations as cr
    found = providers(state, "time", now)
    if not found:
        return []
    c = found[0]
    shown, off = cr.clock_reading(c, now)
    skew = "" if abs(off) < 1 else f", about {round(abs(off))} min {'fast' if off > 0 else 'slow'}"
    return [f"By your {c['name']} it is {shown}{skew}."]


def news_left(c: dict, now: float) -> int:
    """Bulletins this creation can still bring today (0 for anything that doesn't provide news)."""
    if c["spec"]["capabilities"].get("provides", {}).get("ability") != "news":
        return 0
    used = [t for t in c["runtime"].get("news_log", []) if now - t < DAY]
    return max(0, ABILITIES["news"].per_day - len(used))
