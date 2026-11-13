"""The world view's data (docs/DESIGN-world-view.md): everything the browser needs to draw the parchment map, in one read-only call.

The map's land is invented in the browser from a world seed (made once, kept in meta) around the engine's own place spots (worldmap.py).
This adds what the drawing needs beyond `/map`: the seed, which places lie by water (so the coast comes close to them), how often Pip has
been to each and since when, the walk in progress with its times, and the hour, season and weather.
"""
import random
import re
from functools import lru_cache
import time
from datetime import datetime

from . import finds
from . import layouts
from . import modules
from . import places
from . import worldmap
from . import stats as stats_mod
from . import world_pack

def coastal() -> re.Pattern:
    """What makes a place by the water, in the world's words (the pack's scene.json `coastal_words`)."""
    return _coastal(tuple(world_pack.active().data("scene").get("coastal_words", ("sea",))))


@lru_cache(maxsize=8)
def _coastal(words: tuple) -> re.Pattern:
    return re.compile(r"\b(" + "|".join(words) + r")\b", re.I)


def seed(state) -> int:
    """The world's seed: made once, then the same forever, so the map always draws the same land."""
    have = state.meta("world_seed")
    if have:
        return int(have)
    new = random.randint(1, 999_999)
    state.set_meta(world_seed=str(new))
    return new


def _words(state, key: str, rows: dict) -> str:
    """What is known about a place, for spotting water: its record, or for a neighbor's home who lives there."""
    rec = rows.get(key)
    if rec:
        return " ".join([rec.get("description") or "", rec.get("blurb") or "", *[m.get("there", "") for m in rec.get("mentions") or []]])
    ch = places.neighbor_at(state, key)
    return f"{ch['about']} {ch['persona']}" if ch else ""


def map_view(state, settings, library, now: float | None = None) -> dict:
    now = now or time.time()
    snap = worldmap.snapshot(state, settings, library, now)
    rows = {r["key"]: r for r in state.place_rows()}
    for p in snap["places"]:
        seen = state.place_visits(p["key"])
        p["first_visited"] = seen["first_ts"] if seen else None
        p["visits"] = seen["count"] if seen else 0
        p["coastal"] = p["key"] != places.HOME and bool(coastal().search(_words(state, p["key"], rows)))
    sess = state.session()
    if snap["pip"]["walking"] and sess:
        snap["pip"]["walking"].update(started_at=sess["started_at"], ends_at=sess["ends_at"])
    return {**snap, "seed": seed(state), "now": moment(state, settings, now)}


def moment(state, settings, now: float) -> dict:
    """The time of day (minutes past midnight), the season and the weather, as the map and the scenes draw them."""
    w = modules.published(state, "weather")
    local = datetime.fromtimestamp(now)
    return {"ts": now, "minutes": local.hour * 60 + local.minute, "season": modules.world_season(state, settings, now),
            "weather": w.get("condition") if isinstance(w, dict) else None}


def _clock(c: dict, now: float) -> dict:
    """A timekeeper's face as minutes past midnight, and whether it is going."""
    from . import creations as cr
    shown = datetime.fromtimestamp(cr.clock_face(c, now))
    return {"minutes": shown.hour * 60 + shown.minute, "running": cr.running(c, now)}


def _picture(w: dict | None) -> dict:
    """A pixel picture's grid, for drawing it in the scene (nothing for a picture without one)."""
    return {"picture": {"rows": w["rows"], "palette": w["palette"]}} if w else {}


def place_details(state, settings, key: str, kind: str) -> dict:
    """What a layout for a kind of place is told about one place: its name and kind, its scene details (walls, roof, palette, setting),
    its props and whether it is by the sea."""
    from . import looks
    known = looks.place_text(state, key)
    scene = looks.place_scene(state, key, kind, known)
    rows = {r["key"]: r for r in state.place_rows()}
    return {"key": key, "label": places.label(key), "kind": kind, "coastal": bool(coastal().search(_words(state, key, rows))),
            "props": list(dict.fromkeys(scene["props"] + looks.props(known))), **{k: v for k, v in scene.items() if k != "props"}}


def scene_view(state, settings, library, place: str | None = None, now: float | None = None) -> dict | None:
    """Everything a scene draws from, for one place (where Pip is, by default): the place, who is there, what is for sale, Pip if it is
    there, and the place's own things (at home: the garden, the creations, the belongings). None if there is no such place."""
    from . import creations as cr
    now = now or time.time()
    reg = places.registry(state, settings, library)
    sess = state.session()
    a = state.agent()
    walking = bool(sess and sess["kind"] == "walk")
    key = place or (sess["target"] if walking else a["location"])
    if key not in reg:
        return None
    p, rows = reg[key], {r["key"]: r for r in state.place_rows()}
    kind = {q["key"]: q["kind"] for q in worldmap.snapshot(state, settings, library, now)["places"]}[key]
    pip_here = a["location"] == key and not walking
    session = None
    if sess:
        session = {k: sess[k] for k in ("kind", "started_at", "ends_at", "target")}
        if sess["kind"] == "module":
            session.update(label=sess["expect"], working=bool(sess["stage"]), **({"project": sess["about"]} if sess["about"] else {}))
        if sess["kind"] in ("work", "experiment"):
            pr = state.project(sess["project_id"])
            session.update(project=pr["name"], stage=pr["stages"][sess["stage"]]["name"] if 0 <= sess["stage"] < len(pr["stages"]) else None)
    from . import looks
    look = lambda c: c.get("look") or looks.fallback(c["name"], c["persona"])           # not chosen yet: drawn from the persona for now
    present = [{"name": c["name"], "kind": c["kind"], "about": c["about"], "look": look(c)} for c in places.company_at(state, key)]
    trade = {}                                          # what live modules add to this place's scene (`scene` facts: booths, a stall, wares)
    for m in state.modules("live"):
        mine = ((m["facts"] or {}).get("scene") or {}).get(key) if isinstance((m["facts"] or {}).get("scene"), dict) else None
        trade.update(mine if isinstance(mine, dict) else {})
    owner = places.neighbor_at(state, key)
    lives_here = None
    if owner:
        lives_here = {"name": owner["name"], "about": owner["about"], "look": look(owner), "wares": [], "market_day": None, "away_at": None,
                      **(trade.get("lives_here") if isinstance(trade.get("lives_here"), dict) else {})}
    by_name = {c["name"]: c for c in state.characters()}
    known = looks.place_text(state, key)
    scene = looks.place_scene(state, key, kind, known)
    booths = [{**b, **({"look": look(by_name[b.get("whose")])} if b.get("whose") in by_name else {})} for b in trade.get("booths") or [] if isinstance(b, dict)]
    out = {
        "place": {"key": key, "label": p.label, "kind": kind, "blurb": p.blurb, "description": (rows.get(key) or {}).get("description") or "",
                  "hours": list(p.hours) if p.hours else None, "open": places.open_now(p, settings, now) if not p.heard else False,
                  "heard_only": p.heard, "coastal": bool(coastal().search(_words(state, key, rows))),
                  "props": list(dict.fromkeys(scene["props"] + looks.props(known))),
                  "scene": {k: v for k, v in scene.items() if k != "props"},
                  "finds": [e[0] for e in finds.loot_for(state, key) or []][:12]},
        "lives_here": lives_here,
        "pip": {"here": pip_here, "where": a["location"], "walking": walking, "activity": a["activity"], "description": a["description"],
                "mood": a["mood"], **{n: round(v, 2) for n, v in stats_mod.values(state).items()}, "asleep": a["activity"] == "sleeping",
                "session": session},
        "present": present, "booths": booths,
        "stall": trade.get("stall") or [],
        "objects": modules.scene_objects(state, key, kind),     # what live modules show here, already placed on anchors
        "layout": layouts.for_scene(state, key, kind),           # a place built from parts by a module, or None (its hand-written scene)
        "facts": {m["name"]: m["facts"] for m in state.modules("live") if m["facts"]},   # what live modules publish (the garden's plots)
        "now": moment(state, settings, now),
    }
    if key == places.HOME:
        out["creations"] = [{"name": c["name"], "quality": c["quality"], "capabilities": sorted(c["spec"]["capabilities"]), "running": cr.running(c, now),
                             "description": c["description"], **({"clock": _clock(c, now)} if "timekeeper" in c["spec"]["capabilities"] else {}),
                             **({"tended_until": c["runtime"].get("tended_until")} if "upkeep" in c["spec"]["capabilities"] else {}),
                             **_picture(state.picture_of(subject=c["name"]))}
                            for c in state.creations()]
        out["items"] = [{"name": i["name"], "qty": i["qty"], "kind": i["kind"]} for i in state.items()]
        out["coins"] = state.coins()
    return out
