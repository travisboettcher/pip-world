"""Places the agent can be. The home, the library and the places a world starts with are the world pack's (places.json), and so is
every kind of place (docs/DESIGN-engine-audit.md, B3).

`go_to` uses the same real-time session as work (kind `walk`): The agent is walking until it arrives, then wakes there.
Each place gets a description written once by the GM the first time the agent arrives, and kept. A character lives at the place their
record names (`place`): somewhere in the world (a villager at the village, a resident at the place someone told the agent of), or a
home of their own the engine makes for them, worded and of the kind the world says (places.json `dwellings`: "Marigold's home", of
kind `neighbor` in Pip's world). Whoever is at a place greets the agent and talks with it in person there (see neighbors.py and
talk.py). See DESIGN-library.md and DESIGN-neighbor.md.
"""
import time
from dataclasses import dataclass, field

from . import companions
from . import invented_places as invented
from . import world_pack
from . import place_kinds as kinds
from . import sleep as sleepmod
from .text import clip

def _data() -> dict:
    return world_pack.active().data("places")


def home(agent=None) -> dict:
    """The agent's home, as places.json's `home` says one is (key, description, called, aliases, about, offers): the acting agent's own
    (world.json `agents`: docs/DESIGN-multi-agent.md) or else the world's."""
    agent = agent or world_pack.active().agent
    return agent.home_place or _data().get("home", {})


def home_key(agent=None) -> str:
    """The key of the agent's home (the pack's places.json `home`: "workshop" in Pip's world)."""
    return home(agent).get("key", "home")


def __getattr__(name):            # the old constant name, from the active world
    if name == "HOME":
        return home_key()
    raise AttributeError(name)


WALKS = {"near": "a short walk", "far": "a long walk"}
DWELLING_KIND = "dwelling"            # a home the engine makes for someone, when the world doesn't say what kind of place it is
DWELLING_CALLED = "{name}'s home"


def _dwellings(settings=None) -> dict:
    pack = world_pack.load(settings) if settings is not None else world_pack.active()
    return pack.data("places").get("dwellings") or {}


def dwelling_called(name: str, settings=None) -> str:
    """What a home of their own is called, for someone the world brings without one."""
    return str(_dwellings(settings).get("called") or DWELLING_CALLED).replace("{name}", name)


def home_of(ch: dict) -> str:
    """Where a character lives ('' for a made thing that talks)."""
    return ch["place"]


def _dwelling_of(state, key: str) -> dict | None:
    """The character whose own home `key` is: a place the engine made for them, not one of the world's or one someone mentioned."""
    if not key or key == home_key() or key in _start_keys() or state.place_row(key):
        return None
    return next((c for c in state.characters() if c["place"] == key), None)


def _start_keys() -> set:
    d = _data()
    return {p["key"] for p in d.get("start", [])} | ({d["library"]["key"]} if d.get("library") else set())


def resident_of(state, place: str) -> dict | None:
    """Who lives at `place` as their own home (a neighbour at hers), if anyone."""
    return _dwelling_of(state, place)


def place_of(state, ch: dict) -> str | None:
    """Where a character can be met in person: somewhere else just now if a live module says so (a stall on market day), else where
    they live while it's in the world. None for a made thing that talks, or for someone whose place the owner removed (they're kept,
    but out of reach)."""
    if not ch["place"]:                                     # a made thing that talks lives nowhere
        return None
    from .modules import whereabouts
    away = (whereabouts(state, ch["name"]) or {}).get("at")
    if away:
        return away
    rec = state.place_row(ch["place"])
    return ch["place"] if not rec or rec["status"] == "real" else None


def company_at(state, place: str | None) -> list[dict]:
    """The characters the agent can talk with in person at `place` (none while it's walking: pass present_at)."""
    return [c for c in state.characters() if place and place_of(state, c) == place]


def present_at(state) -> str | None:
    """Where the agent is in company: its location, or None while it's walking (it has left, and hasn't arrived)."""
    sess = state.session()
    return None if sess and sess["kind"] == "walk" else state.agent()["location"]


def kind_of(state, key: str) -> str:
    """What kind of place a key is, all of them the world's: "home", an invented place's kind, a built-in place's (places.json), or a
    home of someone's own (places.json `dwellings`)."""
    if key == home_key() or any(key == home_key(a.identity) for a in _everyone()):
        return "home"                                            # its own, or another agent's
    row = state.place_row(key)
    if row:
        return row["kind"]
    d = _data()
    built_in = {p["key"]: p.get("kind", "") for p in d.get("start", [])} | ({d["library"]["key"]: library_kind()} if d.get("library") else {})
    if key in built_in:
        return built_in[key]
    return dwelling_kind() if _dwelling_of(state, key) else ""


def library_kind() -> str:
    lib = _data().get("library") or {}
    return lib.get("kind") or _data().get("fallback_kind") or "sight"


def dwelling_kind() -> str:
    return _dwellings().get("kind") or DWELLING_KIND


def scope_of(location: str) -> str:
    """The scope key tools use for a location: 'home', or the place itself (a tool is scoped by a role, docs/DESIGN-engine-audit.md, B4)."""
    return "home" if location == home_key() else location


def label(place: str) -> str:
    """How to say it: 'home', 'the library', "Marigold's home", 'Saltholm' (a proper name takes no article)."""
    return "home" if place == home_key() else place if place[:1].isupper() else f"the {place}"


@dataclass
class Place:
    """A place the agent can be. `verbs` maps a tool name to (short help for 'Here you can', full description of the verb
    here or None to use the tool's own). `offers` are the short words shown in the directory."""
    key: str
    blurb: str
    walk_minutes: float
    offers: tuple[str, ...] = ()
    verbs: dict = field(default_factory=dict)
    hours: tuple[int, int] | None = None   # local open hours (start, end); None = always open
    daylight_only: bool = False
    invented: bool = False   # from the places table (a place a character mentioned); see invented_places.py
    heard: bool = False      # ...and the agent hasn't been yet: no description, no verbs
    mentions: list = field(default_factory=list)
    distance: str = ""
    kind: str = ""           # a starting place's kind of place (places.json: wild, yard...), whose shared verbs it may offer

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
    """Every place the agent can go, as records: home, the library (if mounted), each neighbor's home."""
    walk = settings.walk_minutes if settings else 10.0
    d = _data()
    mine = home()
    out = {home_key(): Place(home_key(), mine.get("description", "your home"), walk, offers=tuple(mine.get("offers", ("sleep",))))}
    lib_place = d.get("library")
    if library and library.available() and lib_place:          # the world's library, when there are books to read
        out[lib_place["key"]] = _built_in({**lib_place, "kind": library_kind()}, walk)
    wild = settings.wild_places if settings and settings.wild_places is not None else [p["key"] for p in d.get("start", [])]
    for p in d.get("start", []):                               # the places the world starts with (WILD_PLACES may leave some out)
        if p["key"] in wild:
            out[p["key"]] = _built_in(p, walk)
    for c in state.characters():                               # a home of their own, for whoever the world gave one
        if c["place"] and c["place"] not in out and not state.place_row(c["place"]):
            out[c["place"]] = Place(c["place"], f"where {c['name']} lives" + (f" ({c['about']})" if c["about"] else ""), walk,
                                    offers=("talk",), kind=dwelling_kind())
    for rec in invented.records(state):
        if rec["walk_minutes"] is not None and rec["key"] not in out:
            out[rec["key"]] = invented_place(rec)
    for a, h in agents_homes(state):                               # where the other agents it has met live (DESIGN-multi-agent.md)
        if h["key"] not in out:
            out[h["key"]] = Place(h["key"], f"where {a.identity.name} lives" + (f": {h['about']}" if h.get("about") else ""), walk, kind="home")
    return out


def _everyone() -> list:
    from . import others
    return others.everyone()


def agents_homes(state) -> list[tuple]:
    """(agent, its home) for each other agent the agent acting now has met: meeting someone, you learn where they live."""
    from . import others
    return [(a, home(a.identity)) for a in others.others() if others.met(state, a)]


def _built_in(p: dict, walk: float) -> Place:
    return Place(p["key"], p["description"], p.get("walk", walk), offers=tuple(p.get("offers", ())), daylight_only=p.get("daylight_only", False),
                 verbs={v: tuple(x) for v, x in (p.get("verbs") or {}).items()}, kind=p.get("kind", ""))


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
    """The record for where the agent is (a bare one for a location the registry no longer lists)."""
    loc = state.agent()["location"]
    return registry(state, settings, library).get(loc) or Place(loc, "", settings.walk_minutes)


def available(state, library) -> dict[str, str]:
    """place -> what it is, for every place the agent can go."""
    return {k: p.blurb for k, p in registry(state, None, library).items()}


def find(state, library, query) -> str | None:
    q = str(query or "").strip().lower().removeprefix("the ").removeprefix("my ")
    if q in home().get("aliases", ("home",)):
        return home_key()
    places = available(state, library)
    names = [(p, p.lower()) for p in places] + [(r["key"], a) for r in invented.records(state) if r["key"] in places
                                                for a in r["aliases"]]
    hit = list(dict.fromkeys([p for p, n in names if n == q] or [p for p, n in names if q and (q in n or n in q)]))
    if not hit:  # "marigold", "marigold's", "visit marigold thistlewick": where someone lives
        named = q.replace("'s", " ").split()
        hit = list(dict.fromkeys([c["place"] for c in state.characters() if c["place"] in places
                                  and any(w in named for w in c["name"].lower().split() if len(w) > 2)]
                                 + [h["key"] for a, h in agents_homes(state) if a.identity.name.lower() in named]))
    return hit[0] if len(hit) == 1 else None


def start_walk(state, settings, place: str, minutes: float | None = None) -> int:
    minutes = settings.walk_minutes if minutes is None else minutes
    if state.agent()["location"] == home_key():
        state.set_meta(left_home_at=str(time.time()))     # a trip starts: what happens on it waits for the diary at home
    state.start_session(0, 0, minutes, time.time() + minutes * 60 / settings.work_speed, kind="walk", target=place)
    state.update_agent(activity="walking", description="walking home" if place == home_key() else f"on the way to {label(place)}")
    return max(1, round(minutes / settings.work_speed))


async def arrive(state, settings, gm, library, rng=None) -> dict | None:
    """Finish a walk: The agent is now at its destination. The first visit to a place gets a lasting description; a place
    The agent has only heard of is designed instead (invented_places.realise), and retried next time if that fails."""
    sess = state.session()
    if not sess or sess["kind"] != "walk":
        return None
    state.end_session()
    place = sess["target"]
    here_record = registry(state, settings, library).get(place)
    first = place != home_key() and state.meta(f"place:{place}") is None  # home is where the agent started
    bare = False
    if here_record and here_record.heard:
        made = await invented.realise(state, gm, place, label(place), rng)
        bare = not made
        if bare and first:
            state.set_meta(**{f"place:{place}": ""})
    elif first:
        desc = None
        if gm:
            host = resident_of(state, place)
            hints = (f"this is where {host['name']} lives. Who they are: {host['persona']}" if host else
                     library.overview() if place == "library" and library else here_record.blurb if here_record else "")
            desc = await gm.describe_place(label(place), hints)
        state.set_meta(**{f"place:{place}": clip(desc, 500) if desc else ""})
    state.update_agent(location=place, activity="idle",
                       description="just got home" if place == home_key() else f"just arrived at {label(place)}")
    state.set_meta(arrived_at=str(time.time()))  # marks this visit (a neighbor greets the agent once per visit)
    data = {"place": place, "label": label(place), "first_time": first,
            "description": invented.BARE.format(label(place)) if bare else state.meta(f"place:{place}") or ""}
    state.log("arrived", **data)
    return data


def directory(state, settings, library, now: float | None = None) -> list[str]:
    """Where the agent can go and what each place is for, from the same records that decide which tools it is offered."""
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
    where = f"home ({home_key()})" if here_key == home_key() else label(here_key)
    here_place = places.get(here_key)
    closed = "" if not here_place or open_now(here_place, settings) else (
        f", closed for now (it opens at {here_place.hours[0]}:00)" if here_place.hours
        else ", closed for now (it's dark; it opens in the morning)")
    lines = [f"You are at: {where}{closed}" + (f" - {desc}" if desc else "")]
    for host in company_at(state, present_at(state)):
        lines.append(f"You're visiting {host['name']}. Talk with them in person using say with to: {host['name']}."
                     if host["place"] == here_key and _dwelling_of(state, here_key) else
                     f"{host['name']} is here" + (f" ({host['about']})" if host["about"] else "")
                     + f"; talk with them in person using say with to: {host['name']}.")
        if companions.heard(host):
            lines.append(f"{host['name']} hasn't answered yet: give them a moment, no need to say it again.")
    if here_place and here_place.verbs and not closed:
        lines.append("Here you can: " + ", ".join(f"{v} ({short})" for v, (short, _) in here_place.verbs.items()) + ".")
    return lines + directory(state, settings, library)
