"""Places Pip can be. `workshop` is home (the garden and project work happen there); the library and each
neighbor's home are a walk away.

`go_to` uses the same real-time session as work (kind `walk`): Pip is walking until it arrives, then wakes there.
Each place gets a description written once by the GM the first time Pip arrives, and kept. A neighbor's home is
the place called "<Name>'s home"; while Pip is there, the neighbor greets it and talks with it in person (see
neighbors.py), as does a resident at an invented place. See DESIGN-library.md and DESIGN-neighbor.md.
"""
import time
from dataclasses import dataclass, field

from . import invented_places as invented
from . import place_kinds as kinds
from . import sleep as sleepmod
from .text import clip

FORAGE_HELP = ("Forage in the woods for 15-60 minutes: sticks, bark, resin, feathers, berries, nuts, and now and then "
               "seeds. What you find is down to luck and how picked-over the place is. You'll see what you found when "
               "the time is up; resting stops early.")
SCAVENGE_HELP = ("Scavenge through the junkyard's heaps for 15-60 minutes: scrap metal, wire, springs, gears, odd parts, "
                 "and now and then a tool. What you find is down to luck and how picked-over the heaps are. You'll see "
                 "what you found when the time is up; resting stops early.")
HOME = "workshop"
WALKS = {"near": "a short walk", "far": "a long walk"}
HOME_SUFFIX = "'s home"


def home_of(neighbor: dict) -> str:
    return f"{neighbor['name']}{HOME_SUFFIX}"


def neighbor_at(state, place: str) -> dict | None:
    """The neighbor whose home `place` is, if any."""
    return next((c for c in state.characters("neighbor") if home_of(c) == place), None)


IN_PERSON = ("neighbor", "resident")


def place_of(state, ch: dict) -> str | None:
    """Where a character can be met in person: a neighbor at home, a resident at their place while it's in the world.
    None for a companion, or for a resident whose place the owner removed (they're kept, but out of reach)."""
    if ch["kind"] == "neighbor":
        from .market import away_at          # on their market day a neighbor with wares keeps a stall there, not at home
        return away_at(state, ch, time.time()) or home_of(ch)
    rec = state.place_row(ch["place"]) if ch["kind"] == "resident" else None
    return rec["key"] if rec and rec["status"] == "real" else None


def company_at(state, place: str | None) -> list[dict]:
    """The characters Pip can talk with in person at `place` (none while it's walking: pass present_at)."""
    return [c for c in state.characters() if place and place_of(state, c) == place]


def present_at(state) -> str | None:
    """Where Pip is in company: its location, or None while it's walking (it has left, and hasn't arrived)."""
    sess = state.session()
    return None if sess and sess["kind"] == "walk" else state.agent()["location"]


def scope_of(location: str) -> str:
    """The scope key tools use for a location: 'home', 'neighbor' (any neighbor's home), or the place itself."""
    return "home" if location == HOME else "neighbor" if location.endswith(HOME_SUFFIX) else location


def label(place: str) -> str:
    """How to say it: 'home', 'the library', "Marigold's home", 'Saltholm' (a proper name takes no article)."""
    return "home" if place == HOME else place if place.endswith(HOME_SUFFIX) or place[:1].isupper() else f"the {place}"


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
    invented: bool = False   # from the places table (a place a character mentioned); see invented_places.py
    heard: bool = False      # ...and Pip hasn't been yet: no description, no verbs
    mentions: list = field(default_factory=list)
    distance: str = ""

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
    for rec in invented.records(state):
        if rec["walk_minutes"] is not None and rec["key"] not in out:
            out[rec["key"]] = invented_place(rec)
    return out


def said_about(mentions: list, n: int = 2) -> str:
    """What the characters said about a place: "Briar says: an ironmonger; Morgan says: a harbour"."""
    said = [f"{m['by']} says: {m['there']}" for m in mentions if m["there"]][-n:]
    return "; ".join(said) or (f"{mentions[-1]['by']} mentioned it" if mentions else "")


def _verb_help(rec: dict, verb: str, short: str) -> str | None:
    """The full description of a verb at an invented place (None: the tool's own)."""
    if verb != "gather":
        return None
    lo, hi = kinds.KINDS[rec["kind"]].session
    shop = kinds.KINDS[rec["kind"]].shop_hours
    return (f"{short[:1].upper()}{short[1:]} at {label(rec['key'])} for {lo}-{hi} minutes. What you find is down to luck"
            + (" and what's in stock (it restocks slowly); it goes on account, to settle up later."
               if shop else " and how picked-over the place is.")
            + " You'll see what you found when the time is up; resting stops early.")


TRADE_VERBS = {"buy": "buy something from a booth here", "sell": "sell something you have to a booth here",
               "pay": "pay what you owe on account here"}


def invented_place(rec: dict) -> Place:
    """A places-table row as a Place: a heard-of one has no verbs yet; a real one has its kind's."""
    heard_of = rec["status"] != "real"
    verbs = {v: (short, _verb_help(rec, v, short)) for v, (short, _) in rec["verbs"].items()}
    if not heard_of and kinds.KINDS[rec["kind"]].trades:
        verbs.update({v: (short, None) for v, short in TRADE_VERBS.items()})
        if kinds.KINDS[rec["kind"]].stalls:
            verbs["sell"] = ("sell something you have to a booth here, or set out a stall of your own (sell with an ask)", None)
    since = [m for m in rec["mentions"] if m["ts"] > (rec["real_at"] or 0)]
    blurb = said_about(rec["mentions"]) if heard_of else rec["blurb"] + (f" ({said_about(since, 1)})" if since else "")
    return Place(rec["key"], blurb, rec["walk_minutes"] or 0,
                 offers=tuple(verbs), verbs=verbs, hours=tuple(rec["hours"]) if rec["hours"] else None,
                 daylight_only=bool(rec["daylight_only"]), invented=True, heard=heard_of, mentions=rec["mentions"],
                 distance=rec["distance"])


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
    names = [(p, p.lower()) for p in places] + [(r["key"], a) for r in invented.records(state) if r["key"] in places
                                                for a in r["aliases"]]
    hit = list(dict.fromkeys([p for p, n in names if n == q] or [p for p, n in names if q and (q in n or n in q)]))
    if not hit:  # "marigold", "marigold's", "visit marigold thistlewick"
        hit = [home_of(c) for c in state.characters("neighbor")
               if any(w in q.replace("'s", " ").split() for w in c["name"].lower().split() if len(w) > 2)]
    return hit[0] if len(hit) == 1 else None


def start_walk(state, settings, place: str, minutes: float | None = None) -> int:
    minutes = settings.walk_minutes if minutes is None else minutes
    state.start_session(0, 0, minutes, time.time() + minutes * 60 / settings.work_speed, kind="walk", target=place)
    state.update_agent(activity="walking", description="walking home" if place == HOME else f"on the way to {label(place)}")
    return max(1, round(minutes / settings.work_speed))


async def arrive(state, settings, gm, library, rng=None) -> dict | None:
    """Finish a walk: Pip is now at its destination. The first visit to a place gets a lasting description; a place
    Pip has only heard of is designed instead (invented_places.realise), and retried next time if that fails."""
    sess = state.session()
    if not sess or sess["kind"] != "walk":
        return None
    state.end_session()
    place = sess["target"]
    here_record = registry(state, settings, library).get(place)
    first = place != HOME and state.meta(f"place:{place}") is None  # home is where Pip started
    bare = False
    if here_record and here_record.heard:
        made = await invented.realise(state, gm, place, label(place), rng)
        bare = not made
        if bare and first:
            state.set_meta(**{f"place:{place}": ""})
    elif first:
        desc = None
        if gm:
            host = neighbor_at(state, place)
            hints = (f"this is where {host['name']} lives. Who they are: {host['persona']}" if host else
                     library.overview() if place == "library" and library else here_record.blurb if here_record else "")
            desc = await gm.describe_place(label(place), hints)
        state.set_meta(**{f"place:{place}": clip(desc, 500) if desc else ""})
    state.update_agent(location=place, activity="idle",
                       description="just got home" if place == HOME else f"just arrived at {label(place)}")
    state.set_meta(arrived_at=str(time.time()))  # marks this visit (a neighbor greets Pip once per visit)
    data = {"place": place, "label": label(place), "first_time": first,
            "description": invented.BARE.format(label(place)) if bare else state.meta(f"place:{place}") or ""}
    state.log("arrived", **data)
    return data


def directory(state, settings, library, now: float | None = None) -> list[str]:
    """Where Pip can go and what each place is for, from the same records that decide which tools it is offered."""
    loc = state.agent()["location"]
    lines, heard_of = [], []
    for key, p in registry(state, settings, library).items():
        if key == loc:
            continue
        closed = "" if open_now(p, settings, now) else ", closed now"
        if p.heard:
            heard_of.append(f"- {key}, about {max(1, round(p.walk_minutes))} min, {WALKS[p.distance]}{closed} - {p.blurb}")
            continue
        what = f" [{', '.join(p.offers)}]" if p.offers else ""
        lines.append(f"- {key}, {max(1, round(p.walk_minutes))} min{closed} - {p.blurb}{what}")
    too_far = [f"- {r['key']} - {said_about(r['mentions'])}" for r in invented.records(state, now)
               if r["walk_minutes"] is None and r["key"] != loc]
    return ((["Places you can go (go_to):"] + lines if lines else [])
            + (["Places you've heard of but not been to (go_to works):"] + heard_of if heard_of else [])
            + (["Places you've heard of that are too far to walk to:"] + too_far if too_far else []))


def perception(state, settings, library) -> list[str]:
    here_key = state.agent()["location"]
    places = registry(state, settings, library)
    if len(places) < 2:
        return []
    desc = state.meta(f"place:{here_key}")
    where = f"home ({HOME})" if here_key == HOME else label(here_key)
    here_place = places.get(here_key)
    closed = "" if not here_place or open_now(here_place, settings) else (
        f", closed for now (it opens at {here_place.hours[0]}:00)" if here_place.hours
        else ", closed for now (it's dark; it opens in the morning)")
    lines = [f"You are at: {where}{closed}" + (f" - {desc}" if desc else "")]
    for host in company_at(state, present_at(state)):
        lines.append(f"You're visiting {host['name']}. Talk with them in person using say with to: {host['name']}."
                     if host["kind"] == "neighbor" else
                     f"{host['name']} is here" + (f" ({host['about']})" if host["about"] else "")
                     + f"; talk with them in person using say with to: {host['name']}.")
        if host["heard"]:
            lines.append(f"{host['name']} hasn't answered yet: give them a moment, no need to say it again.")
    if here_place and here_place.verbs and not closed:
        lines.append("Here you can: " + ", ".join(f"{v} ({short})" for v, (short, _) in here_place.verbs.items()) + ".")
    return lines + directory(state, settings, library)
