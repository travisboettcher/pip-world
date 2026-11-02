"""World content: item kinds, starter belongings, and defaults for seeds and food."""

KINDS = ("tool", "material", "food", "seed")
SEED_DEFAULTS = {"grow_minutes": 1440,  # a crop takes about a day: a plot gives one harvest a day, so replanting forever cannot flood the pantry
                 "yield": 3, "food_value": 0.4}
FOOD_DEFAULT = 0.3  # hunger restored by a food item with no explicit food_value

STARTER_ITEMS = [
    {"name": "tomato seeds", "qty": 3, "kind": "seed", "description": "a paper packet of tomato seeds",
     "attrs": {"crop": "tomatoes", "grow_minutes": 1440, "yield": 3, "food_value": 0.5}},
    {"name": "carrot seeds", "qty": 3, "kind": "seed", "description": "a paper packet of carrot seeds",
     "attrs": {"crop": "carrots", "grow_minutes": 1080, "yield": 3, "food_value": 0.4}},
]


def normalize_attrs(name: str, kind: str, attrs: dict | None) -> dict:
    a = dict(attrs or {})
    if kind == "seed":
        base = name.lower().strip()
        for suffix in (" seeds", " seed"):
            base = base.removesuffix(suffix)
        a.setdefault("crop", base or name)
        for k, v in SEED_DEFAULTS.items():
            a.setdefault(k, v)
    elif kind == "food":
        a.setdefault("food_value", FOOD_DEFAULT)
    return a


SEEDS_PER_FOOD = 2  # packets of seed saved from one piece of a crop's fruit


def seed_packet_for(food_name: str) -> dict | None:
    """The starter seed packet for the crop `food_name` is the fruit of (tomatoes, carrots), if any."""
    from .state import name_key  # state imports this module
    want = name_key(food_name)
    return next((s for s in STARTER_ITEMS if name_key(s["attrs"]["crop"]) == want), None)
