"""World content from the pack's items.json (docs/DESIGN-world-packs.md, phase 2): item kinds, starting belongings, defaults for seeds and
food, and what can be found where. The engine reads them through these functions; the old constant names (`KINDS`, `STARTER_ITEMS`...)
still answer, from the active world."""
from . import world_pack


def items() -> dict:
    return world_pack.active().data("items")


def kinds() -> tuple:
    """The kinds an item can be (tool, material, food, seed in Pip's world)."""
    return tuple(items().get("kinds", ()))


def seed_defaults() -> dict:
    return items().get("seed_defaults", {})


def food_default() -> float:
    """Hunger restored by a food item with no food_value of its own."""
    return items().get("food_default", 0.3)


def starter_items() -> list:
    """What the agent starts with (given once ever, so what's used up doesn't come back on a restart)."""
    return items().get("start", [])


def seeds_per_food() -> int:
    """Packets of seed saved from one piece of a crop's fruit."""
    return items().get("seeds_per_food", 2)


def finds() -> dict:
    """What can be found where: {place: [(name, kind, weight, (least, most), description, attrs)]}."""
    return {place: [(n, k, w, tuple(q), d, a) for n, k, w, q, d, a in table] for place, table in items().get("finds", {}).items()}


def gerunds() -> dict:
    """What gathering at a built-in place is called ("foraging")."""
    return items().get("gerunds", {})


def normalize_attrs(name: str, kind: str, attrs: dict | None) -> dict:
    a = dict(attrs or {})
    if kind == "seed":
        base = name.lower().strip()
        for suffix in (" seeds", " seed"):
            base = base.removesuffix(suffix)
        a.setdefault("crop", base or name)
        for k, v in seed_defaults().items():
            a.setdefault(k, v)
    elif kind == "food":
        a.setdefault("food_value", food_default())
    return a


def seed_packet_for(food_name: str) -> dict | None:
    """The starting seed packet for the crop `food_name` is the fruit of (tomatoes, carrots), if any."""
    from .state import name_key  # state imports this module
    want = name_key(food_name)
    return next((s for s in starter_items() if name_key(s["attrs"]["crop"]) == want), None)


_OLD = {"KINDS": kinds, "SEED_DEFAULTS": seed_defaults, "FOOD_DEFAULT": food_default, "STARTER_ITEMS": starter_items,
        "SEEDS_PER_FOOD": seeds_per_food}


def __getattr__(name):            # the old constant names, read from the active world
    if name in _OLD:
        return _OLD[name]()
    raise AttributeError(name)
