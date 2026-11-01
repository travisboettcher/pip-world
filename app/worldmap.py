"""Pip's map (see DESIGN-map.md).

Travel time to a place is a property of the destination, so the world is a star around home and the honest map is radial: a place sits
as many units from home as it takes minutes to walk there. Each place gets a spot once, when it first exists, and keeps it forever (a
`map_places` row), so the map only grows. Where Pip is drawn comes from its location, or from how far along a walk it is.
"""
import hashlib
import math
import time

from . import places

CANDIDATES = 24      # angles tried for a new place
MIN_RADIUS = 4.0     # nothing sits on top of home, however short its walk


def start_index(key: str) -> int:
    """Which of the candidate angles a name tries first (a hash, so the layout is reproducible)."""
    return int(hashlib.sha256(key.lower().encode()).hexdigest(), 16) % CANDIDATES


def candidate(i: int, radius: float) -> tuple[float, float]:
    a = 2 * math.pi * i / CANDIDATES
    return round(radius * math.cos(a), 2), round(radius * math.sin(a), 2)


def place_new(taken: list[tuple[float, float]], key: str, minutes: float) -> tuple[float, float]:
    """Where a new place goes: its walking minutes out from home, at the angle with the most room to its nearest neighbour."""
    radius = max(MIN_RADIUS, float(minutes or 0))
    start = start_index(key)
    best, best_room = None, -1.0
    for step in range(CANDIDATES):
        p = candidate((start + step) % CANDIDATES, radius)
        room = min((math.hypot(p[0] - t[0], p[1] - t[1]) for t in taken), default=math.inf)
        if room > best_room + 1e-9:
            best, best_room = p, room
    return best


def sync(state, settings, library) -> dict[str, tuple[float, float]]:
    """Give every place in the registry a spot if it has none. Returns the spots of the places that exist now."""
    spots = state.map_positions()
    out = {}
    for key, place in places.registry(state, settings, library).items():
        if key not in spots:
            spots[key] = (0.0, 0.0) if key == places.HOME else place_new(list(spots.values()), key, place.walk_minutes)
            state.set_map_position(key, *spots[key])
        out[key] = spots[key]
    return out


def _kind(place, rows: dict) -> str:
    if place.key == places.HOME:
        return "home"
    if place.invented:
        return rows[place.key]["kind"]            # every invented place in the registry comes from this table
    return "neighbor" if place.scope == "neighbor" else "library" if place.key == "library" else "wild"


def _walk(state, spots: dict, now: float) -> tuple[tuple[float, float], dict | None]:
    """Where Pip is drawn when it is not standing in a place: along the walk it is on."""
    origin = state.agent()["location"]
    start = spots.get(origin, (0.0, 0.0))
    sess = state.session()
    if not sess or sess["kind"] != "walk":
        return start, None
    span = sess["ends_at"] - sess["started_at"]
    progress = 1.0 if span <= 0 else max(0.0, min(1.0, (now - sess["started_at"]) / span))
    end = spots.get(sess["target"], start)
    point = (round(start[0] + (end[0] - start[0]) * progress, 2), round(start[1] + (end[1] - start[1]) * progress, 2))
    return point, {"from": origin, "to": sess["target"], "progress": round(progress, 2)}


def snapshot(state, settings, library, now: float | None = None) -> dict:
    now = now or time.time()
    spots = sync(state, settings, library)
    rows = {r["key"]: r for r in state.place_rows()}
    shown = []
    for key, place in places.registry(state, settings, library).items():
        x, y = spots[key]
        shown.append({"key": key, "label": place.label, "kind": _kind(place, rows), "x": x, "y": y,
                      "visited": state.last_arrived(key) is not None, "heard_only": bool(place.heard),
                      "distance_minutes": place.walk_minutes})
    point, walking = _walk(state, spots, now)
    at = None if walking else state.agent()["location"]
    return {"home": places.HOME, "places": shown, "pip": {"x": point[0], "y": point[1], "at": at, "walking": walking}}
