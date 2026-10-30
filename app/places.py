"""Places Pip can be. `workshop` is home (the garden and project work happen there); the library and each
neighbor's home are a walk away.

`go_to` uses the same real-time session as work (kind `walk`): Pip is walking until it arrives, then wakes there.
Each place gets a description written once by the GM the first time Pip arrives, and kept. A neighbor's home is
the place called "<Name>'s home"; while Pip is there, the neighbor greets it and talks with it in person (see
neighbors.py). See DESIGN-library.md and DESIGN-neighbor.md.
"""
import time
from dataclasses import dataclass, field

from . import sleep as sleepmod
from .text import clip

FORAGE_HELP = ("Forage in the woods for 15-60 minutes: sticks, bark, resin, feathers, berries, nuts, and now and then "
               "seeds. What you find is down to luck and how picked-over the place is. You'll see what you found when "
               "the time is up; resting stops early.")
SCAVENGE_HELP = ("Scavenge through the junkyard's heaps for 15-60 minutes: scrap metal, wire, springs, gears, odd parts, "
                 "and now and then a tool. What you find is down to luck and how picked-over the heaps are. You'll see "
                 "what you found when the time is up; resting stops early.")
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


@dataclass
class Place:
    """A place Pip can be. `verbs` maps a tool name to (short help for 'Here you can', full description of the verb
    here or None to use the tool's own). `offers` are the short words shown in the directory."""
    key: str
    blurb: str
    walk_minutes: float
    offers: tuple[str, ...] = ()
    verbs: dict = field(default_factory=dict)
    hours: tuple[int, int] | None = None   # local open hours (start, end); None = always open
    daylight_only: bool = False

    @property
    def label(self) -> str:
        return label(self.key)

    @property
    def scope(self) -> str:
        return scope_of(self.key)


def open_now(place: Place, settings, now: float | None = None) -> bool:
    """Is the place open (hours, and daylight if it needs it)? Closed places can be walked to, but offer no tools."""
    now = now or time.time()
    if place.daylight_only and sleepmod.is_night(settings, now):
        return False
    if place.hours:
        hour = time.localtime(now).tm_hour
        start, end = place.hours
        return start <= hour < end if start < end else hour >= start or hour < end
    return True


def registry(state, settings, library) -> dict[str, Place]:
    """Every place Pip can go, as records: home, the library (if mounted), each neighbor's home."""
    walk = settings.walk_minutes if settings else 10.0
    out = {HOME: Place(HOME, "your home: your workshop and garden", walk, offers=("projects", "garden", "sleep"))}
    if library and library.available():
        out["library"] = Place("library", "a library a short walk away, full of real books you can read", walk,
                               offers=("browse", "read"),
                               verbs={"browse": ("look for books, by subject, title or author, or wander the shelves", None),
                                      "read": ("settle in and read a book for a while", None)})
    wild = settings.wild_places if settings else ["woods", "junkyard"]
    if "woods" in wild:
        out["woods"] = Place("woods", "a patch of woods past the garden: sticks, bark, resin, berries and nuts, birdsong", 8,
                             offers=("gather",), daylight_only=True,
                             verbs={"gather": ("forage for sticks, bark, berries and nuts", FORAGE_HELP)})
    if "junkyard" in wild:
        out["junkyard"] = Place("junkyard", "a scrapyard over the hill: heaps of scrap metal, wire, springs and old machine parts",
                                15, offers=("gather", "browse"), daylight_only=True,
                                verbs={"gather": ("scavenge through the heaps", SCAVENGE_HELP),
                                       "browse": ("look over the heaps to see what's worth digging for", None)})
    for c in state.characters("neighbor"):
        out[home_of(c)] = Place(home_of(c), f"where your neighbor {c['name']} lives" + (f" ({c['about']})" if c["about"] else ""),
                                walk, offers=("talk",))
    return out


def here(state, settings, library) -> Place:
    """The record for where Pip is (a bare one for a location the registry no longer lists)."""
    loc = state.agent()["location"]
    return registry(state, settings, library).get(loc) or Place(loc, "", settings.walk_minutes)


def available(state, library) -> dict[str, str]:
    """place -> what it is, for every place Pip can go."""
    return {k: p.blurb for k, p in registry(state, None, library).items()}


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


def start_walk(state, settings, place: str, minutes: float | None = None) -> int:
    minutes = settings.walk_minutes if minutes is None else minutes
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
    here_record = registry(state, settings, library).get(place)
    first = state.meta(f"place:{place}") is None
    if first:
        desc = None
        if gm and place != HOME:
            host = neighbor_at(state, place)
            hints = (f"this is where {host['name']} lives. Who they are: {host['persona']}" if host else
                     library.overview() if place == "library" and library else here_record.blurb if here_record else "")
            desc = await gm.describe_place(label(place), hints)
        state.set_meta(**{f"place:{place}": clip(desc, 500) if desc else ""})
    state.update_agent(location=place, activity="idle",
                       description="just got home" if place == HOME else f"just arrived at {label(place)}")
    state.set_meta(arrived_at=str(time.time()))  # marks this visit (a neighbor greets Pip once per visit)
    data = {"place": place, "label": label(place), "first_time": first, "description": state.meta(f"place:{place}") or ""}
    state.log("arrived", **data)
    return data


def directory(state, settings, library, now: float | None = None) -> list[str]:
    """Where Pip can go and what each place is for, from the same records that decide which tools it is offered."""
    loc = state.agent()["location"]
    lines = []
    for key, p in registry(state, settings, library).items():
        if key == loc:
            continue
        closed = "" if open_now(p, settings, now) else ", closed now"
        what = f" [{', '.join(p.offers)}]" if p.offers else ""
        lines.append(f"- {key}, {max(1, round(p.walk_minutes))} min{closed} - {p.blurb}{what}")
    return ["Places you can go (go_to):"] + lines if lines else []


def perception(state, settings, library) -> list[str]:
    here_key = state.agent()["location"]
    places = registry(state, settings, library)
    if len(places) < 2:
        return []
    desc = state.meta(f"place:{here_key}")
    where = f"home ({HOME})" if here_key == HOME else label(here_key)
    here_place = places.get(here_key)
    closed = ", closed for now (it's dark; it opens in the morning)" if here_place and not open_now(here_place, settings) else ""
    lines = [f"You are at: {where}{closed}" + (f" - {desc}" if desc else "")]
    host = neighbor_at(state, here_key)
    if host:
        lines.append(f"You're visiting {host['name']}. Talk with them in person using say with to: {host['name']}.")
    if here_place and here_place.verbs and not closed:
        lines.append("Here you can: " + ", ".join(f"{v} ({short})" for v, (short, _) in here_place.verbs.items()) + ".")
    return lines + directory(state, settings, library)
