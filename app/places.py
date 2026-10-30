"""Places Pip can be. `workshop` is home (the garden and project work happen there); the library and each
neighbor's home are a walk away.

`go_to` uses the same real-time session as work (kind `walk`): Pip is walking until it arrives, then wakes there.
Each place gets a description written once by the GM the first time Pip arrives, and kept. A neighbor's home is
the place called "<Name>'s home"; while Pip is there, the neighbor greets it and talks with it in person (see
neighbors.py). See DESIGN-library.md and DESIGN-neighbor.md.
"""
import time

from .text import clip

HOME = "workshop"
HOME_SUFFIX = "'s home"


def home_of(neighbor: dict) -> str:
    return f"{neighbor['name']}{HOME_SUFFIX}"


def neighbor_at(state, place: str) -> dict | None:
    """The neighbor whose home `place` is, if any."""
    return next((c for c in state.characters("neighbor") if home_of(c) == place), None)


def scope_of(location: str) -> str:
    """The scope key tools use for a location: 'home', 'neighbor' (any neighbor's home), or the place itself."""
    return "home" if location == HOME else "neighbor" if location.endswith(HOME_SUFFIX) else location


def label(place: str) -> str:
    """How to say it: 'home', 'the library', "Marigold's home"."""
    return "home" if place == HOME else place if place.endswith(HOME_SUFFIX) else f"the {place}"


def available(state, library) -> dict[str, str]:
    """place -> what it is, for every place Pip can go."""
    out = {HOME: "your home: your workshop and garden"}
    if library and library.available():
        out["library"] = "a library a short walk away, full of real books you can read"
    for c in state.characters("neighbor"):
        out[home_of(c)] = f"where your neighbor {c['name']} lives" + (f" ({c['about']})" if c["about"] else "")
    return out


def find(state, library, query) -> str | None:
    q = str(query or "").strip().lower().removeprefix("the ").removeprefix("my ")
    if q in ("home", "house", "garden", "my workshop"):
        return HOME
    places = available(state, library)
    hit = [p for p in places if p.lower() == q] or [p for p in places if q and (q in p.lower() or p.lower() in q)]
    if not hit:  # "marigold", "marigold's", "visit marigold thistlewick"
        hit = [home_of(c) for c in state.characters("neighbor")
               if any(w in q.replace("'s", " ").split() for w in c["name"].lower().split() if len(w) > 2)]
    return hit[0] if len(hit) == 1 else None


def start_walk(state, settings, place: str) -> int:
    minutes = settings.walk_minutes
    state.start_session(0, 0, minutes, time.time() + minutes * 60 / settings.work_speed, kind="walk", target=place)
    state.update_agent(activity="walking", description="walking home" if place == HOME else f"on the way to {label(place)}")
    return max(1, round(minutes / settings.work_speed))


async def arrive(state, settings, gm, library) -> dict | None:
    """Finish a walk: Pip is now at its destination. The first visit to a place gets a lasting description."""
    sess = state.session()
    if not sess or sess["kind"] != "walk":
        return None
    state.end_session()
    place = sess["target"]
    first = state.meta(f"place:{place}") is None
    if first:
        desc = None
        if gm and place != HOME:
            host = neighbor_at(state, place)
            hints = (f"this is where {host['name']} lives. Who they are: {host['persona']}" if host else
                     library.overview() if place == "library" and library else "")
            desc = await gm.describe_place(label(place), hints)
        state.set_meta(**{f"place:{place}": clip(desc, 500) if desc else ""})
    state.update_agent(location=place, activity="idle",
                       description="just got home" if place == HOME else f"just arrived at {label(place)}")
    state.set_meta(arrived_at=str(time.time()))  # marks this visit (a neighbor greets Pip once per visit)
    data = {"place": place, "label": label(place), "first_time": first, "description": state.meta(f"place:{place}") or ""}
    state.log("arrived", **data)
    return data


def perception(state, library) -> list[str]:
    here = state.agent()["location"]
    places = available(state, library)
    if len(places) < 2:
        return []
    desc = state.meta(f"place:{here}")
    where = f"home ({HOME})" if here == HOME else label(here)
    lines = [f"You are at: {where}" + (f" - {desc}" if desc else "")]
    host = neighbor_at(state, here)
    if host:
        lines.append(f"You're visiting {host['name']}. Talk with them in person using say with to: {host['name']}.")
    lines.append("Places you can go (go_to): " + "; ".join(f"{p} ({what})" for p, what in places.items() if p != here))
    return lines
