"""Layouts: places built from parts (docs/DESIGN-modules.md, "Parts and layouts", step 5).

A **part** is a module whose `on_build(ctx)` returns shapes and anchors in its own coordinates, given `ctx["params"]` (its manifest's
defaults, overridden by the layout), `ctx["season"]` and `ctx["seed"]`. A **place** module's `on_build` returns the ground plan of one
place (`manifest["place"]`): parts by name, each with params, a position, a turn (degrees about the vertical) and a role, plus shapes and
anchors of its own. Here the engine builds a live place: it runs each distinct part once, moves every copy into place (geometry.place),
checks the total, and keeps the result on the place's module. It rebuilds when the season turns or a part it uses changes. The scene view
then sends the built shapes and anchors, and the browser draws them with one generic renderer (web/world/layout.js) instead of a hand-
written template. Anchors from the layout are where module objects go (modules.objects_for).
"""
import hashlib
import json
import time

from . import geometry
from .geometry import Bad

PLACE_SHAPES_MAX = 3000
PARTS_MAX = 80


def season(settings, now: float) -> str:
    from .happenings import season_of
    return season_of(now, settings.hemisphere)


def seed_of(*keys) -> int:
    return int(hashlib.sha256("|".join(map(str, keys)).encode()).hexdigest()[:8], 16)


def part_named(state, name: str, waiting: bool = False) -> dict | None:
    """The live part with this name; with `waiting`, a part still waiting for approval will do (for a dry run)."""
    rows = [m for m in state.modules() if m["kind"] == "part" and m["name"] == name]
    live = [m for m in rows if m["status"] == "live"]
    pending = [m for m in rows if m["status"] in ("waiting", "proposed")] if waiting else []
    return (live or pending or [None])[-1]


async def build_part(runner, m: dict, params: dict, season_: str, seed: int) -> dict:
    """One part, built with these params (over its manifest's defaults). Raises Bad with what went wrong."""
    res = await runner.run(m["source"], "on_build", {"params": {**m["manifest"].get("params", {}), **params}, "season": season_, "seed": seed})
    if not res.get("ok"):
        raise Bad(f"part {m['name']}: {res.get('error', 'it failed')}")
    if res.get("missing"):
        raise Bad(f"part {m['name']} has no on_build")
    try:
        return geometry.built(res["result"])
    except Bad as e:
        raise Bad(f"part {m['name']}: {e}") from None


def _plan(spec) -> dict:
    """A place's on_build result, checked: {"parts": [{part, params?, at, turn?, role?}], "shapes": [...], "anchors": [...]}."""
    if not isinstance(spec, dict) or not isinstance(spec.get("parts", []), list):
        raise Bad("a place's on_build returns {\"parts\": [...], \"shapes\": [...], \"anchors\": [...]}")
    parts = spec.get("parts", [])
    if len(parts) > PARTS_MAX:
        raise Bad(f"a place has at most {PARTS_MAX} parts")
    out = []
    for i, p in enumerate(parts):
        if not isinstance(p, dict) or not isinstance(p.get("part"), str):
            raise Bad(f"part entry {i}: needs `part` (a part's name) and `at`")
        params = p.get("params", {})
        if not isinstance(params, dict) or not all(isinstance(v, (int, float, str, bool)) for v in params.values()):
            raise Bad(f"part entry {i}: `params` maps names to plain values")
        role = str(p.get("role") or f"{p['part']}-{i}").lower()
        out.append({"part": p["part"], "params": params, "at": geometry._vec(p.get("at"), f"part entry {i}: at"),
                    "turn": geometry._num(p.get("turn", 0), f"part entry {i}: turn", -360, 360), "role": geometry.re.sub(r"[^a-z0-9-]", "-", role)[:40]})
    shapes, anchors = spec.get("shapes") or [], spec.get("anchors") or []
    if not isinstance(shapes, list) or not isinstance(anchors, list) or len(anchors) > geometry.ANCHORS_MAX:
        raise Bad(f"`shapes` and `anchors` are lists (at most {geometry.ANCHORS_MAX} anchors)")
    own = {"shapes": [geometry.shape(x, i) for i, x in enumerate(shapes)], "anchors": [geometry.anchor(a, i) for i, a in enumerate(anchors)]}
    return {"parts": out, "own": own}


async def build_place(state, settings, runner, m: dict, now: float, waiting: bool = False) -> dict:
    """A place module's layout, built: {"shapes", "anchors", "parts" (name -> module id), "season", "version"}. Raises Bad."""
    s = season(settings, now)
    res = await runner.run(m["source"], "on_build", {"params": {}, "season": s, "seed": seed_of(m["manifest"]["place"]), "place": m["manifest"]["place"]})
    if not res.get("ok"):
        raise Bad(f"{m['name']}: {res.get('error', 'it failed')}")
    plan = _plan(res.get("result"))
    shapes, anchors, used, cache = list(plan["own"]["shapes"]), list(plan["own"]["anchors"]), {}, {}
    for i, entry in enumerate(plan["parts"]):
        part = part_named(state, entry["part"], waiting)
        if not part:
            raise Bad(f"there is no part called {entry['part']!r}")
        used[part["name"]] = part["id"]
        key = (part["id"], json.dumps(entry["params"], sort_keys=True))
        if key not in cache:
            cache[key] = await build_part(runner, part, entry["params"], s, seed_of(m["manifest"]["place"], part["name"], key[1]))
        moved = geometry.place(cache[key], entry["at"], entry["turn"], entry["role"])
        shapes += moved["shapes"]
        anchors += moved["anchors"]
        if len(shapes) > PLACE_SHAPES_MAX:
            raise Bad(f"a place has at most {PLACE_SHAPES_MAX} shapes")
    ids = [a["id"] for a in anchors]
    if len(ids) != len(set(ids)):
        raise Bad("two anchors share an id: give parts their own roles")
    return {"shapes": shapes, "anchors": anchors, "parts": used, "season": s, "version": m["version"]}


def place_module(state, key: str) -> dict | None:
    """The live place module that lays out this place, if there is one."""
    return next((m for m in reversed(state.modules("live")) if m["kind"] == "place" and m["manifest"].get("place") == key), None)


def stale(state, settings, m: dict, now: float) -> bool:
    b = m["built"]
    if not b or "error" in b or b.get("version") != m["version"] or b.get("season") != season(settings, now):
        return True
    return any((part_named(state, name) or {}).get("id") != mid for name, mid in b.get("parts", {}).items())


async def step(state, settings, runner, now: float | None = None) -> int:
    """Build or rebuild every live place whose layout is missing or out of date. Returns how many were built."""
    if runner is None:
        return 0
    now, n = now or time.time(), 0
    for m in state.modules("live"):
        if m["kind"] != "place" or not stale(state, settings, m, now) or m["built"].get("failed_at", 0) > now - 3600:
            continue
        try:
            built = await build_place(state, settings, runner, m, now)
        except Bad as e:
            state.update_module(m["id"], built={**m["built"], "error": str(e)[:300], "failed_at": now})
            state.log("layout_failed", name=m["name"], place=m["manifest"]["place"], error=str(e)[:300])
            continue
        state.update_module(m["id"], built=built)
        state.log("layout_built", name=m["name"], place=m["manifest"]["place"], shapes=len(built["shapes"]), anchors=len(built["anchors"]))
        n += 1
    return n


def for_scene(state, key: str) -> dict | None:
    """What the browser draws for a place laid out by a module: its shapes and anchors (None: the place keeps its hand-written scene)."""
    m = place_module(state, key)
    b = m["built"] if m else None
    if not b or "shapes" not in b:
        return None
    return {"shapes": b["shapes"], "anchors": b["anchors"], "module": m["name"], "version": b["version"]}


def anchors_for(state, key: str):
    """A laid-out place's anchors, or None (the template's manifest applies)."""
    lay = for_scene(state, key)
    return tuple(lay["anchors"]) if lay else None
