"""World content: item kinds, starter belongings, and defaults for seeds and food."""

KINDS = ("tool", "material", "food", "seed")
SEED_DEFAULTS = {"grow_minutes": 60, "yield": 3, "food_value": 0.4}
FOOD_DEFAULT = 0.3  # hunger restored by a food item with no explicit food_value

STARTER_ITEMS = [
    {"name": "tomato seeds", "qty": 3, "kind": "seed", "description": "a paper packet of tomato seeds",
     "attrs": {"crop": "tomatoes", "grow_minutes": 60, "yield": 3, "food_value": 0.5}},
    {"name": "carrot seeds", "qty": 3, "kind": "seed", "description": "a paper packet of carrot seeds",
     "attrs": {"crop": "carrots", "grow_minutes": 45, "yield": 3, "food_value": 0.4}},
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
