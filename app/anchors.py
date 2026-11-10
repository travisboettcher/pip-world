"""Anchors: where things modules show can go in a scene (docs/DESIGN-modules.md, "Places and anchors").

Every scene template publishes its anchors in web/world/anchors/<template>.json: walls, surfaces, floors, ground and points to hang from,
each with a centre, the way it faces, its size and tags (free words: inside, back, counter, pip...). A module never names a position; it
asks for an anchor by what it is ({"type": "wall", "tags": ["inside"], "place": "home"}), and this module answers on the server, the same
way every time: matching anchors in their published order (the one named by `near` first), objects packed along each in turn, and what
doesn't fit left out. The browser only draws what it is given.
"""
import json
from functools import lru_cache
from pathlib import Path

TYPES = ("wall", "surface", "floor", "ground", "hang")
UPRIGHT = ("wall",)                                        # drawn flat against the anchor; everything else stands up, facing the viewer
TEMPLATE_OF_KIND = {"home": "home", "neighbor": "neighbor", "market": "market", "shop": "shop", "library": "library",
                    "wild": "outdoors", "yard": "outdoors", "sight": "outdoors"}
GAP = 0.12                                                 # between objects packed along an anchor
LIFT = 0.02                                                # off a wall, so a picture never fights the plaster
DIR = Path(__file__).resolve().parent.parent / "web" / "world" / "anchors"


@lru_cache(maxsize=None)
def manifest(template: str) -> tuple:
    """A template's anchors, in their published order (empty if it publishes none)."""
    path = DIR / f"{template}.json"
    return tuple(json.loads(path.read_text())["anchors"]) if path.is_file() else ()


def for_kind(kind: str) -> tuple:
    return manifest(TEMPLATE_OF_KIND.get(kind, "outdoors"))


def matching(anchors, query: dict) -> list[dict]:
    """The anchors a query may use, in order: the one it names with `near` first, then the rest as published."""
    tags = set(query.get("tags") or [])
    hits = [a for a in anchors if a["type"] == query["type"] and tags <= set(a["tags"])]
    near = query.get("near")
    return sorted(hits, key=lambda a: a["id"] != near) if near else hits


def size(obj: dict) -> tuple[float, float]:
    """An object's width and height: its longest side is `size`; a frame adds two pixels round the picture."""
    pad = 4 if obj.get("frame") else 0
    w, h = len(obj["sprite"]["rows"][0]) + pad, len(obj["sprite"]["rows"]) + pad
    k = obj.get("size", 0.6) / max(w, h)
    return round(w * k, 4), round(h * k, 4)


def _along(normal) -> tuple[float, float, float]:
    """The direction objects are packed in: across a wall (up x normal), or along x on anything level."""
    nx, ny, nz = normal
    return (1.0, 0.0, 0.0) if abs(ny) > 0.5 else (nz, 0.0, -nx)


def place(anchors, objects: list[dict]) -> tuple[list[dict], list[str]]:
    """Pack objects onto anchors. Returns (placed, unplaced): each placed object gets `pos` (its centre), `normal`, `upright`, `w`, `h`
    and `anchor`; each unplaced one, a line saying why."""
    used: dict[str, float] = {}
    placed, unplaced = [], []
    for o in objects:
        w, h = size(o)
        q = o["at"]
        hits = matching(anchors, q)
        spot = next((a for a in hits if used.get(a["id"], 0.0) + w <= a["extent"][0] + 1e-9
                     and (a["type"] not in UPRIGHT or h <= a["extent"][1] + 1e-9)), None)
        if not spot:
            what = " ".join(filter(None, [q["type"], "tagged " + ", ".join(q["tags"]) if q.get("tags") else ""]))
            unplaced.append(f"{o['id']}: " + (f"no room left on any {what} anchor" if hits else f"no {what} anchor here"))
            continue
        start = used.get(spot["id"], 0.0)
        used[spot["id"]] = start + w + GAP
        ax, _, az = _along(spot["normal"])
        offset = -spot["extent"][0] / 2 + start + w / 2
        x, y, z = spot["at"]
        nx, ny, nz = spot["normal"]
        if spot["type"] in UPRIGHT:
            pos = [x + ax * offset + nx * LIFT, y, z + az * offset + nz * LIFT]
        else:
            pos = [x + ax * offset, y + h / 2, z + az * offset]
        placed.append({**o, "w": w, "h": h, "pos": [round(v, 4) for v in pos], "normal": spot["normal"],
                       "upright": spot["type"] in UPRIGHT, "anchor": spot["id"]})
    return placed, unplaced
