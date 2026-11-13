"""What a place holds (docs/DESIGN-world-packs.md, phase 5a): its find table, how picked over it is, and a glimpse of it.

Place data any feature may use: gathering (a module since 0.36.0) takes from it, a shop's shelves show it. A place's table is the world
pack's items.json `finds` for a built-in place, or an invented place's own. Its stock is drawn down by use and refilled by time, at the
rates of the place's kind (or the defaults below for a built-in place).
"""
import random
import time

from . import place_kinds as kinds
from . import world as world_content

SESSION_MINUTES = (15, 60)
CAPACITY = 120           # minutes of good gathering a place holds
REGEN_PER_HOUR = 15
FULL_YIELD_AT = 60       # stock at or above this gives full yield
MIN_YIELD = 0.2
GLIMPSE = 4              # things seen on a look around


def loot() -> dict:
    """The built-in places' find tables (the world pack's items.json): {place: [(name, kind, weight, (min, max), description, attrs)]}."""
    return world_content.finds()


def _meta_key(place: str) -> tuple[str, str]:
    return f"stock:{place}", f"stock_at:{place}"


def _invented(state, place: str) -> dict | None:
    """The places-table record for a real invented place that has something to find (see invented_places.py)."""
    rec = state.place_row(place) if place not in loot() else None
    return rec if rec and rec["status"] == "real" and rec["loot"] and "gather" in rec["verbs"] else None


def loot_for(state, place: str) -> list | None:
    """The find table for a place: a built-in place's, or an invented place's own (None: nothing to find)."""
    if place in loot():
        return loot()[place]
    rec = _invented(state, place)
    return [(n, k, w, tuple(q), d, a) for n, k, w, q, d, a in rec["loot"]] if rec else None


def goods(state, place: str) -> list:
    """What a place holds: its find table, or (a market, which has nothing to gather) a trading place's own stock."""
    table = loot_for(state, place)
    if table:
        return table
    rec = state.place_row(place)
    if rec and rec["status"] == "real" and kinds.KINDS.get(rec["kind"]) and kinds.KINDS[rec["kind"]].trades:
        return [(n, k, w, tuple(q), d, a) for n, k, w, q, d, a in rec["loot"]]
    return []


def verb_for(state, place: str) -> str:
    """What gathering is called here: 'foraging', 'scavenging', or the invented place's own ('rummaging')."""
    rec = _invented(state, place)
    return world_content.gerunds().get(place) or (rec["verbs"]["gather"][1] if rec else None) or "gathering"


def kind_of(state, place: str):
    """The place kind of an invented place with something to find (None for a built-in place)."""
    rec = _invented(state, place)
    return kinds.KINDS[rec["kind"]] if rec else None


def session_for(state, place: str) -> tuple[int, int]:
    k = kind_of(state, place)
    return k.session if k else SESSION_MINUTES


def capacity(state, place: str) -> tuple[float, float]:
    """(How much a place holds, how much comes back an hour)."""
    k = kind_of(state, place)
    return (k.capacity, k.refill) if k else (CAPACITY, REGEN_PER_HOUR)


def full_yield_at(state, place: str) -> float:
    """Stock at or above this gives a full haul (half of a small place's capacity, so a shop isn't always bare)."""
    return min(FULL_YIELD_AT, capacity(state, place)[0] / 2)


def stock(state, place: str, now: float | None = None) -> float:
    """How much is left here, refilled by time since it was last drawn down."""
    now = now or time.time()
    most, refill = capacity(state, place)
    raw_key, at_key = _meta_key(place)
    raw = state.meta(raw_key)
    if raw is None:
        return float(most)
    at = float(state.meta(at_key) or now)
    return min(float(most), float(raw) + max(0.0, now - at) / 3600 * refill)


def deplete(state, place: str, amount: float, now: float | None = None) -> float:
    """Draw a place's stock down by `amount` (never below nothing). Returns what is left."""
    now = now or time.time()
    left = max(0.0, stock(state, place, now) - amount)
    raw_key, at_key = _meta_key(place)
    state.set_meta(**{raw_key: left, at_key: now})
    return left


def yield_factor(level: float, full: float = FULL_YIELD_AT) -> float:
    return max(MIN_YIELD, min(1.0, level / full))


def glimpse(rng: random.Random, place: str, n: int = GLIMPSE, table: list | None = None) -> list[str]:
    """What can be seen on a look around: a few kinds of thing from the table, nothing taken."""
    names = [item[0] for item in table or loot()[place]]
    return rng.sample(names, min(n, len(names)))
