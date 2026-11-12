"""Gathering: timed sessions at the woods and the junkyard (see DESIGN-places.md).

Like work and reading, a gather is a real-time session. When it ends the engine rolls a haul from the place's loot
table - the table is the world, the GM only narrates it - shifted a little by Pip's skill, and shrunk by how picked-over
the place is (a stock that sessions draw down and time refills). Finds go to the inventory and are remembered per place
(`place_finds`), so Pip can later ask where to get something.
"""
import random
import time

from . import place_kinds as kinds
from . import projects as proj
from . import world as world_content
from .text import clip

# name, kind, weight, (min qty, max qty), description, attrs
def loot() -> dict:
    """The built-in places' find tables (the world pack's items.json)."""
    return world_content.finds()


def __getattr__(name):            # the old names: WOODS, JUNKYARD, LOOT, VERB, from the active world
    if name == "LOOT":
        return loot()
    if name == "VERB":
        return world_content.gerunds()
    if name in ("WOODS", "JUNKYARD"):
        return loot().get(name.lower(), [])
    raise AttributeError(name)


RARE_WEIGHT = 6          # items at or below this weight are "rare": skill helps find them
SESSION_MINUTES = (15, 60)
MINUTES_PER_FIND = 10    # one draw from the table per this many minutes (before depletion)
CAPACITY = 120           # minutes of good gathering a place holds
REGEN_PER_HOUR = 15
FULL_YIELD_AT = 60       # stock at or above this gives full yield
MIN_YIELD = 0.2
MAX_DRAWS = 8
GLIMPSE = 4              # things seen on a look around


def _meta_key(place: str) -> tuple[str, str]:
    return f"stock:{place}", f"stock_at:{place}"


def _invented(state, place: str) -> dict | None:
    """The places-table record for a real invented place that has something to gather (see invented_places.py)."""
    rec = state.place_row(place) if place not in loot() else None
    return rec if rec and rec["status"] == "real" and rec["loot"] and "gather" in rec["verbs"] else None


def loot_for(state, place: str) -> list | None:
    """The loot table for a place: the woods' and junkyard's, or an invented place's own (None: nothing to gather)."""
    if place in loot():
        return loot()[place]
    rec = _invented(state, place)
    return [(n, k, w, tuple(q), d, a) for n, k, w, q, d, a in rec["loot"]] if rec else None


def verb_for(state, place: str) -> str:
    """What gathering is called here: 'foraging', 'scavenging', or the invented place's own ('rummaging')."""
    rec = _invented(state, place)
    return world_content.gerunds().get(place) or (rec["verbs"]["gather"][1] if rec else None) or "gathering"


def _kind(state, place: str):
    rec = _invented(state, place)
    return kinds.KINDS[rec["kind"]] if rec else None


def session_for(state, place: str) -> tuple[int, int]:
    k = _kind(state, place)
    return k.session if k else SESSION_MINUTES


def _capacity(state, place: str) -> tuple[float, float]:
    k = _kind(state, place)
    return (k.capacity, k.refill) if k else (CAPACITY, REGEN_PER_HOUR)


def full_yield_at(state, place: str) -> float:
    """Stock at or above this gives a full haul (half of a small place's capacity, so a shop isn't always bare)."""
    return min(FULL_YIELD_AT, _capacity(state, place)[0] / 2)


def stock(state, place: str, now: float | None = None) -> float:
    """How much is left to gather here, refilled by time since the last visit."""
    now = now or time.time()
    capacity, refill = _capacity(state, place)
    raw_key, at_key = _meta_key(place)
    raw = state.meta(raw_key)
    if raw is None:
        return float(capacity)
    at = float(state.meta(at_key) or now)
    return min(float(capacity), float(raw) + max(0.0, now - at) / 3600 * refill)


def yield_factor(level: float, full: float = FULL_YIELD_AT) -> float:
    return max(MIN_YIELD, min(1.0, level / full))


def draw(rng: random.Random, place: str, minutes: float, factor: float, skill: float,
         table: list | None = None) -> list[tuple[str, str, int, str, dict]]:
    """The haul: (name, kind, qty, description, attrs). Weighted draws; skill nudges rare finds up; stock shrinks the count."""
    table = table or loot()[place]
    n = max(0, min(MAX_DRAWS, round(minutes / MINUTES_PER_FIND * factor + rng.uniform(-0.5, 0.5))))
    weights = [w * (1 + 0.15 * skill) if w <= RARE_WEIGHT else w for _, _, w, _, _, _ in table]
    found: dict[str, list] = {}
    for _ in range(n):
        name, kind, _, (lo, hi), desc, attrs = rng.choices(table, weights=weights)[0]
        qty = max(1, round(rng.randint(lo, hi) * (0.5 + 0.5 * factor)))
        if name in found:
            found[name][2] += qty
        else:
            found[name] = [name, kind, qty, desc, attrs]
    return [tuple(v) for v in found.values()]


def glimpse(rng: random.Random, place: str, n: int = GLIMPSE, table: list | None = None) -> list[str]:
    """What can be seen on a look around: a few kinds of thing from the table, nothing taken."""
    names = [item[0] for item in table or loot()[place]]
    return rng.sample(names, min(n, len(names)))


def fallback_text(place_label: str, minutes: int, found: list, depleted: bool) -> str:
    if not found:
        return f"You spend about {minutes} minutes at {place_label} and come away with nothing" + (
            ": it's been picked over." if depleted else ".")
    return (f"You spend about {minutes} minutes at {place_label} and find "
            + ", ".join(f"{q} {n}" for n, _, q, _, _ in found) + (", though it's getting picked over." if depleted else "."))


async def resolve(state, settings, gm, rng: random.Random, now: float | None = None,
                  interrupted: bool = False) -> dict | None:
    """Finish the current gather session (on time, or cut short). Returns the logged `gathered` event data."""
    from . import places  # places imports sleep; avoid a cycle at import time
    sess = state.session()
    if not sess or sess["kind"] != "gather":
        return None
    now = now or time.time()
    state.end_session()
    place = sess["target"]
    table = loot_for(state, place)
    if not table:
        return None
    minutes = sess["minutes"]
    if interrupted:
        minutes = min(minutes, max(0.0, now - sess["started_at"]) * settings.work_speed / 60)
    level = stock(state, place, now)
    factor = yield_factor(level, full_yield_at(state, place))
    have = state.abilities()
    skill = (proj.level(have.get("handiness", 0)) + proj.level(have.get("patience", 0))) / 2
    found = draw(rng, place, minutes, factor, skill, table)
    raw_key, at_key = _meta_key(place)
    state.set_meta(**{raw_key: max(0.0, level - minutes), at_key: now})
    state.add_ability_xp({"handiness": minutes * 0.5, "patience": minutes * 0.5})
    for name, kind, qty, desc, attrs in found:
        state.add_item(name, qty, kind, desc, attrs)
        state.add_find(place, name, now)
    depleted = factor < 0.5
    label = places.label(place)
    text = None
    if gm and not interrupted:
        text = await gm.narrate_haul(label, round(minutes), [(n, q) for n, _, q, _, _ in found], depleted)
    text = text or fallback_text(label, round(minutes), found, depleted)
    shop = _kind(state, place)
    account = {n: q for n, _, q, _, _ in found} if shop and shop.shop_hours else {}
    if account:  # a shop's haul goes on account: nothing is owed yet, and the economy will inherit the list
        owed = state.place_row(place)["on_account"]
        state.update_place(place, on_account={**owed, **{n: owed.get(n, 0) + q for n, q in account.items()}})
        text = f"{clip(text, 320)} It's on account at {label}: they're happy for you to settle up later."
    if state.agent()["activity"] == "gathering":
        state.update_agent(activity="idle", description=f"just back from {verb_for(state, place)} at {label}")
    data = {"place": place, "label": label, "minutes": round(minutes), "items": [{"name": n, "qty": q} for n, _, q, _, _ in found],
            "text": clip(text, 400), "depleted": depleted, "stock": round(max(0.0, level - minutes)),
            "interrupted": interrupted, **({"on_account": account} if account else {})}
    state.log("gathered", **data)
    return data
