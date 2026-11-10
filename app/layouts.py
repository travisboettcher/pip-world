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


async def build_place(state, settings, runner, m: dict, now: float, waiting: bool = False, key: str | None = None,
                      details: dict | None = None) -> dict:
    """A place module's layout for one place (its own, or for a kind module, the place named), built: {"shapes", "anchors", "parts"
    (name -> module id), "season", "version", "details"}. Raises Bad."""
    s = season(settings, now)
    key = key or m["manifest"]["place"]
    details = details or {"key": key}
    res = await runner.run(m["source"], "on_build", {"params": {}, "season": s, "seed": seed_of(key), "place": key, "details": details})
    if not res.get("ok"):
        raise Bad(f"{m['name']}: {res.get('error', 'it failed')}")
    plan = _plan(res.get("result"))
    shapes, anchors, used, cache = list(plan["own"]["shapes"]), list(plan["own"]["anchors"]), {}, {}
    for i, entry in enumerate(plan["parts"]):
        part = part_named(state, entry["part"], waiting)
        if not part:
            raise Bad(f"there is no part called {entry['part']!r}")
        used[part["name"]] = part["id"]
        pkey = (part["id"], json.dumps(entry["params"], sort_keys=True))
        if pkey not in cache:
            cache[pkey] = await build_part(runner, part, entry["params"], s, seed_of(key, part["name"], pkey[1]))
        moved = geometry.place(cache[pkey], entry["at"], entry["turn"], entry["role"])
        shapes += moved["shapes"]
        anchors += moved["anchors"]
        if len(shapes) > PLACE_SHAPES_MAX:
            raise Bad(f"a place has at most {PLACE_SHAPES_MAX} shapes")
    ids = [a["id"] for a in anchors]
    if len(ids) != len(set(ids)):
        raise Bad("two anchors share an id: give parts their own roles")
    return {"shapes": shapes, "anchors": anchors, "parts": used, "season": s, "version": m["version"], "details": details}


def place_module(state, key: str) -> dict | None:
    """The live place module that lays out this place by name, if there is one."""
    return next((m for m in reversed(state.modules("live")) if m["kind"] == "place" and m["manifest"].get("place") == key), None)


def kind_module(state, kind: str) -> dict | None:
    """The live place module that lays out every place of a kind (one without a layout of its own), if there is one."""
    return next((m for m in reversed(state.modules("live")) if m["kind"] == "place" and kind in m["manifest"].get("kinds", [])), None)


def live_parts(state) -> list[int]:
    """The ids of the live parts: when they change, a layout that couldn't be built is worth trying again."""
    return sorted(m["id"] for m in state.modules("live") if m["kind"] == "part")


def _stale(state, settings, b: dict, version: int, now: float, details: dict | None = None) -> bool:
    if not b or "error" in b or b.get("version") != version or b.get("season") != season(settings, now):
        return True
    if details is not None and b.get("details") != details:
        return True
    return any((part_named(state, name) or {}).get("id") != mid for name, mid in b.get("parts", {}).items())


def stale(state, settings, m: dict, now: float) -> bool:
    return _stale(state, settings, m["built"], m["version"], now)


def _runner(m: dict, runner):
    """Where a module's code runs: the runner; for a module shipped with the engine, in a local sandbox when there is no runner."""
    from . import modules
    return runner or (modules.LocalRunner() if m["author"] == modules.SHIPPED else None)


def _targets(state, settings, m: dict, now: float) -> list[tuple[str, dict | None]]:
    """The places a place module lays out: its own, or every real place of its kinds without a layout of its own (with their details)."""
    if "kinds" not in m["manifest"]:
        return [(m["manifest"]["place"], None)]
    from . import world_view, worldmap
    return [(p["key"], world_view.place_details(state, settings, p["key"], p["kind"]))
            for p in worldmap.snapshot(state, settings, None, now)["places"]
            if not p["heard_only"] and p["kind"] in m["manifest"]["kinds"] and not place_module(state, p["key"])]


async def step(state, settings, runner, now: float | None = None) -> int:
    """Build or rebuild every live place layout that is missing or out of date. Returns how many were built."""
    now, n = now or time.time(), 0
    parts = live_parts(state)
    for m in state.modules("live"):
        run = _runner(m, runner)
        if m["kind"] != "place" or run is None:
            continue
        for key, details in _targets(state, settings, m, now):
            fresh = state.module(m["id"])["built"]
            b = fresh.get("places", {}).get(key, {}) if details is not None else fresh
            waiting = b.get("failed_at", 0) > now - 3600 and b.get("failed_parts") == parts
            if not _stale(state, settings, b, m["version"], now, details) or waiting:   # a failure waits an hour, unless the parts changed
                continue
            try:
                built = await build_place(state, settings, run, m, now, key=key, details=details)
            except Bad as e:
                built = {**b, "error": str(e)[:300], "failed_at": now, "failed_parts": parts}
                state.log("layout_failed", name=m["name"], place=key, error=str(e)[:300])
            else:
                state.log("layout_built", name=m["name"], place=key, shapes=len(built["shapes"]), anchors=len(built["anchors"]))
                n += 1
            state.update_module(m["id"], built={**fresh, "places": {**fresh.get("places", {}), key: built}} if details is not None else built)
    return n


def for_scene(state, key: str, kind: str | None = None) -> dict | None:
    """What the browser draws for a place laid out by a module: its shapes and anchors (None: the place keeps its hand-written scene).
    A place's own layout comes first; then the layout for its kind."""
    m = place_module(state, key)
    b = m["built"] if m else None
    if not (b and "shapes" in b) and kind:
        m = kind_module(state, kind)
        b = m["built"].get("places", {}).get(key) if m else None
    if not b or "shapes" not in b:
        return None
    return {"shapes": b["shapes"], "anchors": b["anchors"], "module": m["name"], "version": b["version"]}


def anchors_for(state, key: str, kind: str | None = None):
    """A laid-out place's anchors, or None (the template's manifest applies)."""
    lay = for_scene(state, key, kind)
    return tuple(lay["anchors"]) if lay else None
