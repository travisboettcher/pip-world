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
    w = weather.current(state, now) if settings.weather else None
    local = datetime.fromtimestamp(now)
    return {**snap, "seed": seed(state),
            "now": {"ts": now, "minutes": local.hour * 60 + local.minute, "season": happenings.season_of(now, settings.hemisphere),
                    "weather": w.condition if w else None}}
