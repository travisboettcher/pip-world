"""Gathering: timed sessions at the woods and the junkyard (see DESIGN-places.md).

Like work and reading, a gather is a real-time session. When it ends the engine rolls a haul from the place's loot
table - the table is the world, the GM only narrates it - shifted a little by Pip's skill, and shrunk by how picked-over
the place is (a stock that sessions draw down and time refills). Finds go to the inventory and are remembered per place
(`place_finds`), so Pip can later ask where to get something.
"""
import random
import time

from . import projects as proj
from .text import clip

# name, kind, weight, (min qty, max qty), description, attrs
WOODS = [
    ("sticks", "material", 30, (2, 5), "straight, dry sticks", {}),
    ("bark", "material", 12, (1, 3), "curls of birch bark", {}),
    ("resin", "material", 8, (1, 2), "amber lumps of sticky resin", {}),
    ("feathers", "material", 8, (1, 3), "small bird feathers", {}),
    ("wild berries", "food", 15, (2, 4), "tart wild berries", {"food_value": 0.2}),
    ("hazelnuts", "food", 10, (2, 5), "a handful of hazelnuts", {"food_value": 0.15}),
    ("mushrooms", "food", 8, (1, 3), "firm brown mushrooms from the leaf litter", {"food_value": 0.2}),
    ("wild apples", "food", 6, (1, 3), "small, sharp wild apples", {"food_value": 0.25}),
    ("sunflower seeds", "seed", 5, (1, 2), "seeds shaken from a dried head",
     {"crop": "sunflowers", "grow_minutes": 90, "yield": 4, "food_value": 0.3}),
    ("carrot seeds", "seed", 5, (1, 2), "seeds from a wild carrot's dry umbels",
     {"crop": "carrots", "grow_minutes": 45, "yield": 3, "food_value": 0.4}),
    ("pea seeds", "seed", 5, (1, 3), "dry peas rattling in a wild pod",
     {"crop": "peas", "grow_minutes": 50, "yield": 4, "food_value": 0.25}),
    ("radish seeds", "seed", 5, (1, 3), "tiny peppery seeds from a bolted radish",
     {"crop": "radishes", "grow_minutes": 30, "yield": 3, "food_value": 0.2}),
    ("bean seeds", "seed", 4, (1, 2), "a few dry beans from a tangled vine",
     {"crop": "beans", "grow_minutes": 75, "yield": 4, "food_value": 0.3}),
]
JUNKYARD = [
    ("scrap brass", "material", 18, (1, 3), "bent offcuts of brass", {}),
    ("brass wire", "material", 20, (1, 2), "short lengths of brass wire", {}),
    ("copper wire", "material", 12, (1, 3), "tangled copper wire", {}),
    ("springs", "material", 8, (1, 2), "small springs, mostly still springy", {}),
    ("screws and bolts", "material", 14, (2, 6), "a pocketful of screws and bolts", {}),
    ("rusty tin", "material", 10, (1, 2), "sheets of rusty tin", {}),
    ("fine brass gears", "material", 5, (1, 1), "a small, fine brass gear", {}),
    ("clock parts", "material", 4, (1, 1), "odd parts pulled from an old clock", {}),
    ("needle file", "tool", 2, (1, 1), "a slim needle file with a good edge", {}),
    ("tweezers", "tool", 2, (1, 1), "a pair of fine tweezers", {}),
    ("small hammer", "tool", 2, (1, 1), "a small hammer, handle a bit loose", {}),
]
LOOT = {"woods": WOODS, "junkyard": JUNKYARD}
VERB = {"woods": "foraging", "junkyard": "scavenging"}
RARE_WEIGHT = 6          # items at or below this weight are "rare": skill helps find them
SESSION_MINUTES = (15, 60)
MINUTES_PER_FIND = 10    # one draw from the table per this many minutes (before depletion)
CAPACITY = 120           # minutes of good gathering a place holds
REGEN_PER_HOUR = 15
FULL_YIELD_AT = 60       # stock at or above this gives full yield
MIN_YIELD = 0.2
MAX_DRAWS = 8


def _meta_key(place: str) -> tuple[str, str]:
    return f"stock:{place}", f"stock_at:{place}"


def stock(state, place: str, now: float | None = None) -> float:
    """How much is left to gather here, refilled by time since the last visit."""
    now = now or time.time()
    raw_key, at_key = _meta_key(place)
    raw = state.meta(raw_key)
    if raw is None:
        return float(CAPACITY)
    at = float(state.meta(at_key) or now)
    return min(float(CAPACITY), float(raw) + max(0.0, now - at) / 3600 * REGEN_PER_HOUR)


def yield_factor(level: float) -> float:
    return max(MIN_YIELD, min(1.0, level / FULL_YIELD_AT))


def draw(rng: random.Random, place: str, minutes: float, factor: float, skill: float) -> list[tuple[str, str, int, str, dict]]:
    """The haul: (name, kind, qty, description, attrs). Weighted draws; skill nudges rare finds up; stock shrinks the count."""
    table = LOOT[place]
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


def glimpse(rng: random.Random, place: str, n: int = 4) -> list[str]:
    """What can be seen on a look around: a few kinds of thing from the table, nothing taken."""
    names = [item[0] for item in LOOT[place]]
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
    if place not in LOOT:
        return None
    minutes = sess["minutes"]
    if interrupted:
        minutes = min(minutes, max(0.0, now - sess["started_at"]) * settings.work_speed / 60)
    level = stock(state, place, now)
    factor = yield_factor(level)
    have = state.abilities()
    skill = (proj.level(have.get("handiness", 0)) + proj.level(have.get("patience", 0))) / 2
    found = draw(rng, place, minutes, factor, skill)
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
    if state.agent()["activity"] == "gathering":
        state.update_agent(activity="idle", description=f"just back from {VERB[place]} at {label}")
    data = {"place": place, "label": label, "minutes": round(minutes), "items": [{"name": n, "qty": q} for n, _, q, _, _ in found],
            "text": clip(text, 400), "depleted": depleted, "stock": round(max(0.0, level - minutes)),
            "interrupted": interrupted}
    state.log("gathered", **data)
    return data
