"""The world view's data (docs/DESIGN-world-view.md): everything the browser needs to draw the parchment map, in one read-only call.

The map's land is invented in the browser from a world seed (made once, kept in meta) around the engine's own place spots (worldmap.py).
This adds what the drawing needs beyond `/map`: the seed, which places lie by water (so the coast comes close to them), how often Pip has
been to each and since when, the walk in progress with its times, and the hour, season and weather.
"""
import random
import re
import time
from datetime import datetime

from . import happenings
from . import places
from . import weather
from . import worldmap

COASTAL = re.compile(r"\b(sea|seas|shore|shoreline|coast|harbour|harbor|quay|quayside|tide|tides|tidal|marsh|salt|beach|mudflats?|"
                     r"lighthouse|dunes?|cove|bay|pier|jetty|wharf)\b", re.I)


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
        p["coastal"] = p["key"] != places.HOME and bool(COASTAL.search(_words(state, p["key"], rows)))
    sess = state.session()
    if snap["pip"]["walking"] and sess:
        snap["pip"]["walking"].update(started_at=sess["started_at"], ends_at=sess["ends_at"])
    return {**snap, "seed": seed(state), "now": moment(state, settings, now)}


def moment(state, settings, now: float) -> dict:
    """The time of day (minutes past midnight), the season and the weather, as the map and the scenes draw them."""
    w = weather.current(state, now) if settings.weather else None
    local = datetime.fromtimestamp(now)
    return {"ts": now, "minutes": local.hour * 60 + local.minute, "season": happenings.season_of(now, settings.hemisphere),
            "weather": w.condition if w else None}


def _clock(c: dict, now: float) -> dict:
    """A timekeeper's face as minutes past midnight, and whether it is going."""
    from . import creations as cr
    shown = datetime.fromtimestamp(cr.clock_face(c, now))
    return {"minutes": shown.hour * 60 + shown.minute, "running": cr.running(c, now)}


def scene_view(state, settings, library, place: str | None = None, now: float | None = None) -> dict | None:
    """Everything a scene draws from, for one place (where Pip is, by default): the place, who is there, what is for sale, Pip if it is
    there, and the place's own things (at home: the garden, the creations, the belongings). None if there is no such place."""
    from . import creations as cr
    from . import market
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
        if sess["kind"] in ("work", "experiment"):
            pr = state.project(sess["project_id"])
            session.update(project=pr["name"], stage=pr["stages"][sess["stage"]]["name"] if 0 <= sess["stage"] < len(pr["stages"]) else None)
    present = [{"name": c["name"], "kind": c["kind"], "about": c["about"]} for c in places.company_at(state, key)]
    booths = [{"booth": b, "whose": who, "items": [{"name": e[0], "kind": e[1], "price": market.sell_price(state, b, e, now), "left": market.stock_left(state, b, e, now)}
                                                   for e in table]} for b, who, table in market.booths(state, key, now)]
    out = {
        "place": {"key": key, "label": p.label, "kind": kind, "blurb": p.blurb, "description": (rows.get(key) or {}).get("description") or "",
                  "hours": list(p.hours) if p.hours else None, "open": places.open_now(p, settings, now) if not p.heard else False,
                  "heard_only": p.heard, "coastal": bool(COASTAL.search(_words(state, key, rows)))},
        "pip": {"here": pip_here, "where": a["location"], "walking": walking, "activity": a["activity"], "description": a["description"],
                "mood": a["mood"], "energy": round(a["energy"], 2), "hunger": round(a["hunger"], 2), "asleep": a["activity"] == "sleeping",
                "session": session},
        "present": present, "booths": booths,
        "stall": [{"item": r["name"], "qty": r["qty"], "ask": r["ask"]} for r in state.stall_rows(key)],
        "now": moment(state, settings, now),
    }
    if key == places.HOME:
        out["garden"] = state.garden(now)
        out["creations"] = [{"name": c["name"], "quality": c["quality"], "capabilities": sorted(c["spec"]["capabilities"]), "running": cr.running(c, now),
                             "description": c["description"], **({"clock": _clock(c, now)} if "timekeeper" in c["spec"]["capabilities"] else {}),
                             **({"tended_until": c["runtime"].get("tended_until")} if "upkeep" in c["spec"]["capabilities"] else {})}
                            for c in state.creations()]
        out["items"] = [{"name": i["name"], "qty": i["qty"], "kind": i["kind"]} for i in state.items()]
        out["coins"] = state.coins()
    return out
