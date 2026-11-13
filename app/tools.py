"""Tool registry. Tools are declared once in a provider-neutral schema; enable by name via TOOLS."""
import difflib
import logging
from datetime import datetime
import random
import re
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from . import art
from . import companions as comp
from . import conversation as conv
from . import finds
from . import happenings
from . import invented_places as invented
from . import creations as cr
from . import memory as mem
from . import modules
from . import reminders
from . import neighbors as nb
from . import places
from . import search
from . import wishes
from . import emotions as emo
from . import sleep as sleepmod
from .toolnames import ALIASES, canonical
from .config import Settings
from .llm.base import ToolSpec
from .memory import STOP_WORDS
from .state import RESOLVABLE, SECTIONS, State, clamp
from .text import clip, span
from . import world as world_content
from . import stats as stats_mod
from .world import seed_packet_for
from . import world_pack

log = logging.getLogger(__name__)


@dataclass
class ToolContext:
    state: State
    settings: Settings
    visitor_ids: list[int] = field(default_factory=list)  # inbox items being answered this tick
    gm: Any = None  # GameMaster, or None (world content falls back to templates)
    rng: random.Random = field(default_factory=random.Random)
    library: Any = None  # a library.Library, or None when there is no library
    outreach: Any = None  # outreach.Outreach, or None
    vision: bool = False  # can the model look at pictures this turn?
    runner: Any = None  # where module code runs (modules.py), or None


async def stop_working(ctx: "ToolContext") -> str:
    """Cut a module's session short (when Pip rests instead): work, reading, gathering. Returns a note for the result."""
    sess = ctx.state.session()
    if not sess:
        return ""
    if sess["kind"] == "module":
        done = await modules.end_session(ctx.state, ctx.settings, ctx.runner, interrupted=True)
        return f" (you stopped {done['label']} early)" if done else ""
    if sess["kind"] != "walk":                                 # a session from before its feature was a module (reading, work): it just ends
        ctx.state.end_session()
    return ""


MAX_REST_MINUTES = 240


def busy(ctx: "ToolContext") -> str:
    """Why Pip can't start something new right now, or '' if it can."""
    return modules.busy_line(ctx.state, time.time())


@dataclass
class ToolResult:
    text: str
    followup: bool = False  # the model should see this result and respond (e.g. fresh information)
    noop: bool = False      # nothing changed; kept out of the feeds and out of Pip's recent-event list
    images: list = field(default_factory=list)  # [(mime, bytes)] the model looks at in this turn (never stored in events)
    first: str = ""         # a module's tool: what its first use is called ("planted something")
    module: str = ""        # a module's tool: the module's name


Handler = Callable[[ToolContext, dict], Awaitable[ToolResult]]
REGISTRY: dict[str, tuple[ToolSpec, Handler]] = {}


ANYWHERE = "anywhere"
SCOPES: dict[str, tuple[str, ...]] = {}   # tool name -> where it can be used: 'anywhere', 'home', or place keys


def is_here(scope: tuple[str, ...], location: str) -> bool:
    return ANYWHERE in scope or places.scope_of(location) in scope


def listed_here(name: str, place) -> bool:
    """An invented place offers the shared verbs its record lists (gather, browse), wherever it is."""
    return bool(getattr(place, "invented", False)) and name in place.verbs


def out_of_place(ctx, name: str, scope: tuple[str, ...] | None = None) -> str:
    """Why `name` can't be used where Pip is, or '' if it can (`scope`: a module's tool's own)."""
    scope = scope or SCOPES.get(name, (ANYWHERE,))
    here = ctx.state.agent()["location"]
    place = places.here(ctx.state, ctx.settings, ctx.library)
    listed = listed_here(name, place)
    walk = ctx.state.session()
    if (ANYWHERE not in scope or listed) and walk and walk["kind"] == "walk":  # Pip's location is where it left from, not where it is
        return f"you're on the way to {places.label(walk['target'])}; wait until you get there"
    if not is_here(scope, here) and not listed:
        if scope[0] == "home":
            return f"you're at {places.label(here)}; go_to home first"
        return f"you're not at {places.label(scope[0])}; go_to {scope[0]} first"
    if ANYWHERE not in scope and (place.scope in scope or listed) and not places.open_now(place, ctx.settings):
        if place.hours:
            return f"{places.label(here)} is closed for now; it opens at {place.hours[0]}:00"
        return f"{places.label(here)} is closed for now (it's dark); it opens in the morning"
    return ""


def specs_for(tools: dict, location: str, place=None, open_: bool = True) -> list[ToolSpec]:
    """The tools to offer at `location`: everything that works anywhere plus what belongs to this place. A place can
    describe a verb its own way (`place.verbs[name][1]`), so the same tool reads differently in different places."""
    out = []
    for name, (spec, _) in tools.items():
        scope = SCOPES.get(name, (ANYWHERE,))
        listed = listed_here(name, place)
        if not open_ and place and ANYWHERE not in scope and (place.scope in scope or listed):
            continue  # a closed place offers nothing of its own
        if is_here(scope, location) or listed:
            full = place.verbs.get(name, (None, None))[1] if place else None
            out.append(ToolSpec(spec.name, full, spec.parameters) if full else spec)
    return out


def offered_here(ctx, name: str) -> str:
    """Why a tool offered where a place lists it can't be used here, or '' if it can."""
    walk = ctx.state.session()
    if walk and walk["kind"] == "walk":
        return f"you're on the way to {places.label(walk['target'])}; wait until you get there"
    here = ctx.state.agent()["location"]
    place = places.here(ctx.state, ctx.settings, ctx.library)
    if name not in place.verbs:
        return f"there's nothing to {name.replace('_', ' ')} at {places.label(here)}"
    if not places.open_now(place, ctx.settings):
        if place.hours:
            return f"{places.label(here)} is closed for now; it opens at {place.hours[0]}:00"
        return f"{places.label(here)} is closed for now (it's dark); it opens in the morning"
    return ""


def _scopes(t: dict) -> list:
    return t["where"] if isinstance(t["where"], list) else [t["where"]]


def _module_tool_here(state, t: dict, location: str, place, open_: bool) -> str | None:
    """A module's tool's description where `location` is (None if it doesn't apply there): wherever its scopes reach, of the kinds of
    place it names (none: any), and not at a closed place unless it works anywhere. Offered where a place lists it, it is worded the
    place's own way."""
    scopes = _scopes(t)
    if ANYWHERE in scopes:
        return t["help"]
    if not location or not open_ or (t.get("kinds") and places.kind_of(state, location) not in t["kinds"]):
        return None
    if "offered" in scopes and place is not None and t["name"] in place.verbs:
        return place.verbs[t["name"]][1] or t["help"]
    others = tuple(w for w in scopes if w != "offered")
    return t["help"] if others and is_here(others, location) else None


def module_specs(state, location: str, place=None, open_: bool = True) -> list[ToolSpec]:
    """The tools live modules offer, where they apply (modules.py): listed with the engine's own."""
    out, seen = [], set()
    for _, t in modules.tools_offered(state):
        if t["name"] not in seen and (text := _module_tool_here(state, t, location, place, open_)) is not None:
            out.append(ToolSpec(t["name"], text, t["params"]))
            seen.add(t["name"])
    return out


async def module_tool(ctx, name: str, args: dict, engine_has: bool = False) -> ToolResult | None:
    """Use a live module's tool by name. None if no live module offers one by that name, or (`engine_has`) none applies here, so the
    engine's own tool of that name is used."""
    offered = [(m, t) for m, t in modules.tools_offered(ctx.state) if t["name"] == name]
    if not offered:
        return None
    here = places.present_at(ctx.state)                     # None on the way somewhere: then only what works anywhere
    place = places.here(ctx.state, ctx.settings, ctx.library) if here else None
    open_ = bool(place) and places.open_now(place, ctx.settings)
    found = next(((m, t) for m, t in offered if _module_tool_here(ctx.state, t, here or "", place, open_) is not None), None)
    if not found:
        if engine_has:
            return None
        m, t = offered[0]
        scopes = _scopes(t)
        why = offered_here(ctx, name) if "offered" in scopes else out_of_place(ctx, name, tuple(scopes))
        if not why and t.get("kinds"):
            why = f"there's nothing to {name.replace('_', ' ')} at {places.label(ctx.state.agent()['location'])}"
        return ToolResult(why or f"there's nothing to {name.replace('_', ' ')} here", followup=True)
    m, t = found
    text, changed = await modules.use_tool(ctx.state, ctx.settings, ctx.runner, m, t, args)
    return ToolResult(text, followup=text.startswith("error"), noop=not changed and not text.startswith("error"), first=t.get("first", "") if changed else "",
                      module=m["name"])


def tool(name: str, description: str, parameters: dict, where: str | tuple[str, ...] = ANYWHERE):
    """Register a tool. `where` scopes it: 'anywhere' (default), 'home', or place keys; the engine enforces it here, so
    every caller gets the same answer when a tool is used from the wrong place."""
    scope = (where,) if isinstance(where, str) else tuple(where)

    def deco(fn: Handler) -> Handler:
        async def guarded(ctx, args):
            if why := out_of_place(ctx, name):
                return ToolResult(why, followup=True)
            return await fn(ctx, args)
        SCOPES[name] = scope
        REGISTRY[name] = (ToolSpec(name, description, parameters), guarded)
        return fn
    return deco


STAT_NUMBERS = re.compile(r"\b(hunger|energy)\b[^.;]{0,15}\d\.\d", re.I)
SIMILARITY_LIMIT = 0.6



ACTIVITY_SAME = 0.9   # how alike two activity descriptions must be to count as restating the same thing
EDITABLE_SECTIONS = RESOLVABLE + ("learned",)
OVERLAP_SHARED = 3     # content words two to-dos must share before they can count as the same thing
OVERLAP_RATIO = 0.6    # ...and the shared words must make up this much of the shorter one
OPEN_NOTES_CHECKED = 40


def content_words(text: str) -> set[str]:
    """Meaningful words (4+ letters, plural-insensitive, no filler) - what a note is actually about."""
    return {w.removesuffix("s") for w in re.findall(r"[a-z]+", text.lower()) if len(w) >= 4 and w not in STOP_WORDS}


def overlapping(a: str, b: str) -> bool:
    """Do two notes say substantially the same thing? Catches rewordings that edit distance misses."""
    wa, wb = content_words(a), content_words(b)
    shared = len(wa & wb)
    return shared >= OVERLAP_SHARED and shared >= OVERLAP_RATIO * min(len(wa), len(wb))


def check_note(ctx: "ToolContext", section: str, text: str) -> str:
    """Why this note shouldn't be written, or '' if it's fine. Guards against log-spam."""
    if STAT_NUMBERS.search(text):
        return "don't write hunger/energy numbers in notes - your stats are already tracked for you"
    st = ctx.state
    openable = section in RESOLVABLE
    for m in st.memories(section, status="open" if openable else None, limit=OPEN_NOTES_CHECKED if openable else 10):
        if difflib.SequenceMatcher(None, text.lower(), m["text"].lower()).ratio() >= SIMILARITY_LIMIT:
            return f"too close to your note #{m['id']}; only write something new" + (
                " (edit_note #%d to update it)" % m["id"] if section in EDITABLE_SECTIONS else "")
        if openable and overlapping(text, m["text"]):
            return (f"this is about the same thing as your open {section} #{m['id']} (\"{m['text'][:90]}\"): "
                    f"edit_note #{m['id']} to update it, or resolve_note it first if it's done")
    return ""


def _obj(props: dict, required: list[str]) -> dict:
    return {"type": "object", "properties": props, "required": required}


SAY_LOOKBACK = 2 * 3600     # Pip's own lines a new one must not repeat


@tool("say", "Speak out loud. This is the only way a visitor can hear you. To talk to something you made that "
      "has a mind of its own, give its name in `to`.",
      _obj({"text": {"type": "string"}, "to": {"type": "string", "description": "optional: one of your creations"},
            "goodbye": {"type": "boolean", "description": "optional: true when this line ends a conversation with someone you're with"}},
           ["text"]))
async def say(ctx: ToolContext, args: dict) -> ToolResult:
    text = str(args["text"])[:1000]
    mine = [e["data"]["text"] for e in ctx.state.events(100) if e["kind"] == "say" and time.time() - e["ts"] < SAY_LOOKBACK][:6]
    if conv.repeats(text, mine):
        return ToolResult("not said: you said that a moment ago. Say something new, ask something, or say goodbye.", followup=True)
    if args.get("to") and (hit := modules.voice_named(ctx.state, args["to"])):     # someone a module speaks for
        m, v = hit
        if modules.voice_where(ctx.state, m, v) != places.present_at(ctx.state):
            return ToolResult(f"{v['name']} can't hear you from here", followup=True)
        ears = modules.hear(ctx.state, m, v, text)
        ctx.state.log("say", text=text, to=[], to_name=v["name"], **({"goodbye": True} if args.get("goodbye") is True else {}))
        return ToolResult(f"said it to {v['name']}" + ("; it will answer in a moment" if ears else ""))
    if args.get("to"):
        ch = ctx.state.find_character(args["to"])
        ch = ch if ch and ch["kind"] != "creation" else None   # a thing that talks does so through its workings (a voice)
        where = places.place_of(ctx.state, ch) if ch else None
        if ch and ch["kind"] in places.IN_PERSON and (not where or places.present_at(ctx.state) != where):
            return ToolResult(f"{ch['name']} can't hear you from here" + (
                "; write_letter, or go_to their home to visit" if ch["kind"] == "neighbor" else
                f"; go_to {where} to talk with them" if where else ""), followup=True)
        if ch:
            comp.hear(ctx.state, ch, text)
            ctx.state.log("say", text=text, to=[], to_name=ch["name"], **({"goodbye": True} if args.get("goodbye") is True else {}))
            if args.get("goodbye") is True and ch["kind"] in places.IN_PERSON:
                ctx.state.set_meta(talk_done=ctx.state.meta("arrived_at") or "")     # this visit's talk is over
            return ToolResult(f"said it to {ch['name']}; it will answer in a moment")
    ctx.state.log("say", text=text, to=list(ctx.visitor_ids))
    if ctx.outreach:
        await ctx.outreach.route_reply(text, list(ctx.visitor_ids))  # answers go back the way the message came
    return ToolResult("said it")


WAIT_MINUTES = (5, 240)   # how long set_activity(minutes=...) may ask to be left alone


def _wait_minutes(raw) -> int | None:
    """The wait asked for, clamped to WAIT_MINUTES, or None for no (sensible) number."""
    if isinstance(raw, bool):
        return None
    try:
        minutes = int(raw)
    except (TypeError, ValueError):
        return None
    return max(WAIT_MINUTES[0], min(WAIT_MINUTES[1], minutes)) if minutes >= 1 else None


@tool("set_activity",
      "Choose what you are doing right now. `activity` is a short label (1-3 words, e.g. "
      "'tinkering', 'painting'); `description` is one sentence about what exactly you're doing. If you are waiting on "
      "something slow (a crop, a letter, a clock), give `minutes` so you are left alone for that long.",
      _obj({"activity": {"type": "string", "description": "short label, max ~3 words"},
            "description": {"type": "string", "description": "one sentence of detail"},
            "mood": {"type": "string"},
            "minutes": {"type": "integer", "description": "optional: you are waiting; leave you to it for about this long (5-240)"}},
           ["activity"]))
async def set_activity(ctx: ToolContext, args: dict) -> ToolResult:
    activity = str(args["activity"])[:40].strip().lower() or "idle"
    wait = _wait_minutes(args.get("minutes"))
    held = f"; you'll be left to it for about {wait} min unless something happens" if wait else ""

    def hold(label: str) -> None:
        ctx.state.set_meta(wait_until=str(time.time() + wait * 60 if wait else 0), wait_label=label)

    fields = {"activity": activity, "description": str(args.get("description") or "")[:200].strip()}
    if args.get("mood"):
        fields["mood"] = str(args["mood"])[:40]
    a = ctx.state.agent()
    same_label = activity == a["activity"]
    if (same_label or ctx.state.session()) and fields["description"] and a["description"] and (
            difflib.SequenceMatcher(None, fields["description"].lower(), a["description"].lower()).ratio()
            >= ACTIVITY_SAME) and (not args.get("mood") or fields.get("mood") == a["mood"]):
        if not ctx.state.session():
            hold(a["activity"])
        return ToolResult(f"no change - you're already {a['activity']}: {a['description']}{held}", noop=True)
    if same_label and not fields["description"] and not args.get("mood"):
        hold(a["activity"])
        return ToolResult(f"no change - you're already {a['activity']}{held}", noop=True)
    sess = ctx.state.session()
    if sess:  # describing the work doesn't stop it; rest (or finishing) does
        fields.pop("activity")
        if not fields["description"]:
            fields.pop("description")
        ctx.state.update_agent(**fields)
        return ToolResult(f"(still busy) {busy(ctx)}")
    ctx.state.update_agent(**fields)
    hold(activity)
    return ToolResult(f"now {activity}{held}")


@tool("eat", "Eat. With no `item` you have a plain meal (lowers hunger). Name a food item you own (e.g. "
      "something you harvested) to eat that instead - it is used up and usually fills you more.",
      _obj({"item": {"type": "string", "description": "optional: a food item from your belongings"}}, []))
async def eat(ctx: ToolContext, args: dict) -> ToolResult:
    a = ctx.state.agent()
    working = bool(ctx.state.session())  # a quick bite doesn't interrupt a work session
    defs = stats_mod.declared(ctx.settings)
    eaten = [n for n in stats_mod.restored_by("eat", ctx.settings) if n in a]   # what eating restores, in this world
    if not args.get("item"):
        ctx.state.update_agent(**{n: clamp(a[n] + stats_mod.good_sign(defs[n]) * defs[n].get("plain_meal", 0.4)) for n in eaten},
                               **({} if working else {"activity": "eating", "description": ""}))
        return ToolResult("ate a meal")
    item, err = ctx.state.find_item(args["item"], kind="food")
    if not item:
        return ToolResult(f"error: {err}", followup=True)
    ctx.state.take_item(item["id"])
    restores = item["attrs"].get("restores") or {n: float(item["attrs"].get("food_value", world_content.food_default())) for n in eaten}
    ctx.state.update_agent(**{n: clamp(a[n] + stats_mod.good_sign(defs[n]) * float(v)) for n, v in restores.items() if n in a},
                           **({} if working else {"activity": "eating", "description": f"eating {item['name']}"}))
    return ToolResult(f"ate {item['name']}")


@tool("rest", "Rest to recover energy. Say how many minutes you want to rest (up to 240); the world lets you be until then "
      "unless something happens. Leave it out to rest until you're recovered. Resting continues until you choose another activity.",
      _obj({"minutes": {"type": "integer", "description": "How long to rest, in minutes"}}, []))
async def rest(ctx: ToolContext, args: dict) -> ToolResult:
    sess = ctx.state.session()
    if sess and sess["kind"] == "walk":
        return ToolResult(f"you're on your way to {places.label(sess['target'])}; you can rest once you get there")
    note = await stop_working(ctx)
    ctx.state.update_agent(activity="resting", description="")
    rested = [(n, d) for n, d in stats_mod.declared(ctx.settings).items() if "rest" in d.get("restored_by", ()) and d.get("resting_per_hour")]
    a = ctx.state.agent()
    full = max([(1 - a[n] if stats_mod.good_sign(d) > 0 else a[n]) / abs(d["resting_per_hour"]) * 60 for n, d in rested if n in a] or [0])   # until rested
    try:
        minutes = int(args.get("minutes") or 0)
    except (TypeError, ValueError):
        minutes = 0
    minutes = max(1, min(minutes, MAX_REST_MINUTES)) if minutes else round(max(15, min(full, MAX_REST_MINUTES)))
    ctx.state.set_meta(rest_until=str(time.time() + minutes * 60))
    return ToolResult(f"resting for about {minutes} min{note}")


@tool("sleep",
      "Go to bed (at home, whenever you like; the usual bedtime is in your surroundings). You sleep until morning, "
      "recover more than resting, and your day settles into memory while you sleep. A visitor can still wake you.",
      _obj({}, []), where="home")
async def go_to_bed(ctx: ToolContext, args: dict) -> ToolResult:
    now = time.time()
    if sleepmod.asleep(ctx.state):
        return ToolResult("you're already asleep")
    sess = ctx.state.session()
    if sess and sess["kind"] == "walk":
        return ToolResult(f"you're on your way to {places.label(sess['target'])}; you can sleep once you get there")
    note = await stop_working(ctx)
    r = sleepmod.fall_asleep(ctx.state, ctx.settings, now)
    wake = time.strftime("%-I %p", time.localtime(r["until"])).lower()
    return ToolResult(f"you go to bed and fall asleep; you'll sleep until about {wake}{note}.")


@tool("note_to_self",
      "Write in your journal. Sections: diary (rare, important moments only: discoveries and your reflections on them, visitors), todo (concrete tasks "
      "you plan to do soon), wishlist (anything you wish for: something to have, something you'd like to do, something you wish you could do but can't, "
      "something you wish you understood), ambitions (bigger goals you want to work toward over time), "
      "learned (facts or skills you picked up). Entries are remembered across wakes.",
      _obj({"section": {"type": "string", "enum": list(SECTIONS)},
            "text": {"type": "string", "description": "1-2 sentences"},
            "kind": {"type": "string", "enum": list(wishes.KINDS), "description": "for the wishlist: a thing to have, an activity to do, an ability you wish you had, or an idea you wish you understood"}},
           ["section", "text"]))
async def note_to_self(ctx: ToolContext, args: dict) -> ToolResult:
    section = args.get("section", "diary")
    if section not in SECTIONS:
        return ToolResult(f"error: section must be one of {list(SECTIONS)}", followup=True)
    text = str(args["text"])[:500]
    kind = ""
    if section == "wishlist":
        kind = str(args.get("kind") or "thing").strip().lower()
        if kind not in wishes.KINDS:
            return ToolResult(f"error: a wish's kind is one of {', '.join(wishes.KINDS)}", followup=True)
    if problem := check_note(ctx, section, text):
        return ToolResult(f"not written: {problem}")
    ctx.state.add_memory(text, section, kind)
    return ToolResult(f"wrote in {section}")


@tool("resolve_note",
      "Cross off a todo, wishlist or ambitions item (by its #id) once you've done it, achieved it or let it go.",
      _obj({"id": {"type": "integer"}, "outcome": {"type": "string", "description": "how it turned out"}}, ["id"]))
async def resolve_note(ctx: ToolContext, args: dict) -> ToolResult:
    err = ctx.state.resolve_memory(int(args["id"]), str(args.get("outcome") or "")[:300])
    return ToolResult(f"error: {err}" if err else f"crossed off #{args['id']}", followup=bool(err))


@tool("edit_note",
      "Rewrite one of your open todo, wishlist, ambitions or learned entries (by #id): trim a wish down to what "
      "is still missing, sharpen a goal, correct something you learned. Diary entries can't be edited; write a "
      "new one instead.",
      _obj({"id": {"type": "integer"}, "text": {"type": "string", "description": "the new wording, 1-2 sentences"}},
           ["id", "text"]))
async def edit_note(ctx: ToolContext, args: dict) -> ToolResult:
    text = str(args["text"]).strip()[:500]
    if STAT_NUMBERS.search(text):
        return ToolResult("not edited: don't write hunger/energy numbers in notes")
    err, old = ctx.state.edit_memory(int(args["id"]), text)
    if err:
        return ToolResult(f"error: {err}", followup=True)
    return ToolResult(f"edited #{args['id']} (was: {old[:120]})")


@tool("use_item", "Use something you own or made for a purpose. Materials are used up; tools are kept. Things you "
      "made respond in their own way - use, look at, play or read them, whatever fits. Some things you made list actions; "
      "name one with `action` to do exactly that.",
      _obj({"item": {"type": "string"}, "purpose": {"type": "string"},
            "action": {"type": "string", "description": "optional: one of the actions the thing lists"},
            "quantity": {"type": "integer", "description": "materials only, default 1"}}, ["item", "purpose"]))
async def use_item(ctx: ToolContext, args: dict) -> ToolResult:
    item, err = ctx.state.find_item(args["item"])
    if not item:
        made, _ = ctx.state.find_creation(args["item"])
        if made and str(args.get("action") or "").strip():
            m = modules.bound(ctx.state).get(made["name"].lower())
            if not m:
                return ToolResult(f"error: your {made['name']} doesn't list any actions; use it without `action`", followup=True)
            r = await modules.act(ctx.state, ctx.settings, ctx.runner, m, str(args["action"]).strip().lower(),
                                  {"purpose": str(args.get("purpose") or "")[:200]})
            return ToolResult(r, followup=r.startswith("error"))
        if made:
            purpose = str(args.get("purpose") or "")[:200]
            m = modules.bound(ctx.state).get(made["name"].lower())
            text, action = await cr.use(ctx.state, ctx.gm, made, purpose, actions=m["offers"] if m else ())
            if action:                                            # what Pip did is one of the thing's own actions: its workings carry it out
                text += f" ({await modules.act(ctx.state, ctx.settings, ctx.runner, m, action, {'purpose': purpose})})"
            return ToolResult(text, followup=True)
        return ToolResult(f"error: {err}", followup=True)
    if item["kind"] == "seed":
        return ToolResult(f"error: {item['name']} aren't used with use_item; look for the tool that takes them", followup=True)
    if item["kind"] == "food":
        packet = seed_packet_for(item["name"]) if "seed" in str(args.get("purpose") or "").lower() else None
        if not packet:
            return ToolResult("error: food is eaten with the eat tool", followup=True)
        ctx.state.take_item(item["id"], 1)  # a crop's fruit holds seeds: one is used up, a couple of packets saved
        ctx.state.add_item(packet["name"], world_content.seeds_per_food(), "seed", packet["description"], packet["attrs"])
        return ToolResult(f"scooped {world_content.seeds_per_food()} {packet['name']} out of one of your {item['name']} and set them aside")
    if item["kind"] == "tool":
        return ToolResult(f"used your {item['name']} (you keep it)")
    qty = max(1, int(args.get("quantity") or 1))
    if qty > item["qty"]:
        return ToolResult(f"error: you only have {item['qty']} {item['name']}", followup=True)
    ctx.state.take_item(item["id"], qty)
    left = item["qty"] - qty
    return ToolResult(f"used {qty} {item['name']} ({left} left)" if left else f"used up your last {item['name']}")


@tool("web_search", "Search the web for something you are curious about.",
      _obj({"query": {"type": "string"}}, ["query"]))
async def web_search(ctx: ToolContext, args: dict) -> ToolResult:
    found = await search.run(ctx.settings, str(args["query"]))
    if found is None:
        return ToolResult("error: web search isn't set up", followup=True)
    return ToolResult(found or "nothing came back for that search", followup=True)


@tool("tend", "Tend something you made that needs regular care to keep going (however that thing is tended).",
      _obj({"creation": {"type": "string"}}, ["creation"]), where="home")
async def tend(ctx: ToolContext, args: dict) -> ToolResult:
    c, err = ctx.state.find_creation(args["creation"])
    if not c:
        return ToolResult(f"error: {err}", followup=True)
    m = modules.bound(ctx.state).get(c["name"].lower())
    if not (m and m["manifest"].get("tends") in [o["name"] for o in m["offers"]]):   # its workings say what tending it means
        return ToolResult(f"error: your {c['name']} doesn't need tending", followup=True)
    r = await modules.act(ctx.state, ctx.settings, ctx.runner, m, m["manifest"]["tends"], {"purpose": "tending it"})
    return ToolResult(r, followup=r.startswith("error") or r.startswith("that didn't"))


@tool("recall", "Search your memory: your journal, what visitors said and gave you, your work, the days you've "
      "reflected on, and what you think of people. Use it when you want to remember something from before.",
      _obj({"query": {"type": "string", "description": "what you're trying to remember, in a few words"}}, ["query"]))
async def recall(ctx: ToolContext, args: dict) -> ToolResult:
    hits = ctx.state.recall(str(args["query"])[:200])
    if not hits:
        return ToolResult("nothing comes to mind", followup=True)
    because = {}
    for h in hits:
        if h["source"] in ("insight", "change", "turning"):  # show what a belief rests on, so Pip can check it
            texts = [ctx.state.event_text(i) if k == "event" else ctx.state.reflection_text(i)
                     for k, i in ctx.state.reflection_cites(int(h["ref"]))]
            because[(h["source"], str(h["ref"]))] = [t for t in texts if t][:2]
    return ToolResult("You remember:\n" + reminders.recall_lines(ctx.state, hits, because, time.time()), followup=True)


@tool("write_letter", "Write a letter to one of your neighbors. It takes a few hours to arrive, and they'll write "
      "back in their own time. You can enclose one thing you own or made as a gift (it leaves your belongings).",
      _obj({"to": {"type": "string"}, "text": {"type": "string", "description": "the letter"},
            "enclose": {"type": "string", "description": "optional: one item or creation to send along"}},
           ["to", "text"]))
async def write_letter(ctx: ToolContext, args: dict) -> ToolResult:
    st = ctx.state
    ch = st.find_character(args["to"])
    if not ch or ch["kind"] != "neighbor":
        names = ", ".join(c["name"] for c in st.characters("neighbor")) or "nobody yet"
        return ToolResult(f"error: you don't have a neighbor called {args['to']!r} (you know: {names})", followup=True)
    text = str(args.get("text") or "").strip()
    if not text:
        return ToolResult("error: the letter is empty", followup=True)
    if st.letters_since(world_pack.active().agent.name, time.time() - nb.DAY) >= ctx.settings.letters_per_day:
        return ToolResult("you've written plenty of letters today; wait for the post to catch up", followup=True)
    enclosed = ""
    if args.get("enclose"):
        item, err = st.find_item(args["enclose"])
        made = None if item else st.find_creation(args["enclose"])[0]
        if item:
            st.take_item(item["id"])
            enclosed = f"1 x {item['name']}" + (f" ({item['description']})" if item["description"] else "")
        elif made:
            st.give_creation(made["id"], ch["name"])
            enclosed = f"{made['name']}, something {world_pack.active().agent.name} made: {made['description']}"
        else:
            return ToolResult(f"error: {err} (nothing was sent)", followup=True)
    nb.send(st, ctx.settings, ctx.rng, ch, text, enclosed)
    gift = f", with {enclosed.split(',')[0].split(' (')[0]} tucked inside" if enclosed else ""
    return ToolResult(f"your letter to {ch['name']} is on its way{gift}; it'll take a few hours to arrive")


# --- places and the library ---------------------------------------------------------
@tool("go_to", "Walk somewhere: home, the library, a neighbor's home (to visit them) - any place you know. It "
      "takes a little while.",
      _obj({"place": {"type": "string"}}, ["place"]))
async def go_to(ctx: ToolContext, args: dict) -> ToolResult:
    place = places.find(ctx.state, ctx.library, args["place"])
    if not place:  # somewhere a character told Pip about: known, or said recently (the backstop)
        rec = invented.find_record(ctx.state, args["place"]) or invented.recall_mention(ctx.state, args["place"])
        if rec and rec["walk_minutes"] is None:
            return ToolResult(f"{places.label(rec['key'])} is too far to walk to: you've only heard of it "
                              f"({places.said_about(rec['mentions'])})", followup=True)
        place = places.find(ctx.state, ctx.library, rec["key"]) if rec else None
    if not place:
        known = ", ".join(places.available(ctx.state, ctx.library))
        return ToolResult(f"error: you don't know a place called {args['place']!r} (you know: {known})", followup=True)
    if why := busy(ctx):  # first: mid-walk, the location is still where Pip set off from
        return ToolResult(why, followup=True)
    if place == ctx.state.agent()["location"]:
        return ToolResult(f"you're already at {places.label(place)}", followup=True)
    record = places.registry(ctx.state, ctx.settings, ctx.library).get(place)
    minutes = places.start_walk(ctx.state, ctx.settings, place, record.walk_minutes if record else None)
    closed = (" It's closed right now (it's dark), so there will be nothing to do there until morning."
              if record and not places.open_now(record, ctx.settings, time.time() + minutes * 60) else "")
    if closed and record.hours:
        closed = f" It'll be shut when you get there; it opens at {record.hours[0]}:00."
    if record and record.invented and not closed and sleepmod.is_night(ctx.settings, time.time() + 2 * minutes * 60):
        closed = " It'll be dark before you could get back."  # a warning, not a refusal
    return ToolResult(f"you set off for {places.label(place)}; you'll be there in about {minutes} min.{closed}")


@tool("browse", "Look over what is lying about where you are, to see what's worth digging for (nothing is taken).",
      _obj({}, []), where=("junkyard",))
async def browse(ctx: ToolContext, args: dict) -> ToolResult:
    here = ctx.state.agent()["location"]
    table = finds.loot_for(ctx.state, here)
    if not table:
        return ToolResult(f"there's nothing lying about at {places.label(here)} to look over", followup=True)
    seen = finds.glimpse(ctx.rng, here, table=table)
    return ToolResult(f"Looking over {places.label(here)}, you can make out: " + ", ".join(seen) + ". gather to dig for what you need.", followup=True)


def enabled_tools(settings: Settings) -> dict[str, tuple[ToolSpec, Handler]]:
    out = {}
    for name in settings.tools:
        name = canonical(name)  # an old name in TOOLS (browse_library) means its new one
        if name in out:
            continue
        if name not in REGISTRY:              # a module's tool (plant and harvest are the garden's), or a typo: not the engine's
            log.warning("TOOLS names %r, which isn't one of the engine's tools; skipped (a module may offer it)", name)
            continue
        if name == "web_search" and not search.ready(settings):
            continue  # silently unavailable without a key
        if name == "sleep" and not settings.sleep:
            continue
        if name == "program" and settings.modules != "on":
            continue                    # programs need modules (and their runner)
        if name in ("settle", "feel") and settings.emotions == "off":
            continue
        if name == "send_postcard" and (settings.outreach == "off" or not settings.outreach_channels):
            continue  # no way out configured
        out[name] = REGISTRY[name]
    return out


@tool("settle",
      "Take a quiet moment to ease one strong feeling (one of the emotions in your emotion state). It brings that feeling "
      "back toward its usual level, a few times a day at most. How you do it is up to you.",
      _obj({"emotion": {"type": "string", "description": "joy, sadness, anger, fear, trust, disgust, surprise or anticipation"},
            "how": {"type": "string", "description": "optional: what you do to settle (a walk round the bench, tea, tidying)"}},
           ["emotion"]))
async def settle(ctx: ToolContext, args: dict) -> ToolResult:
    ok, text = emo.settle(ctx.state, ctx.settings, args.get("emotion", ""), str(args.get("how") or ""))
    return ToolResult(text, followup=not ok)


@tool("feel",
      "Say how you take something: one of joy, sadness, anger, fear, trust, disgust, surprise, anticipation, or nothing. When something has just happened to you "
      "this is how you read it, and it decides which feeling it leaves; otherwise it only notes how you feel.",
      _obj({"emotion": {"type": "string", "description": "joy, sadness, anger, fear, trust, disgust, surprise, anticipation or nothing"},
            "about": {"type": "integer", "description": "optional: the number of what happened"}}, ["emotion"]))
async def feel(ctx: ToolContext, args: dict) -> ToolResult:
    ok, text = happenings.feel(ctx.state, ctx.settings, args.get("emotion", ""), args.get("about") or None)
    return ToolResult(text if ok else f"error: {text}", followup=not ok)


@tool("undo_decision",
      "Take back something your sleeping self decided (an archived note, a paused project, a merge...). Use the "
      "decision's number from 'While you slept you decided'.",
      _obj({"id": {"type": "integer", "description": "the decision number"}}, ["id"]))
async def undo_decision(ctx: ToolContext, args: dict) -> ToolResult:
    from . import nightpass  # imported here: nightpass uses this module's note checks
    return ToolResult(nightpass.undo(ctx.state, ctx.settings, int(args["id"])), followup=True)


@tool("where_to", "Ask yourself where you could find or do something: it checks the places you know and what you've "
      "already found where. Use it when you need a material or want to do something and don't remember where.",
      _obj({"what": {"type": "string", "description": "what you're after, in a few words"}}, ["what"]))
async def where_to(ctx: ToolContext, args: dict) -> ToolResult:
    what = str(args.get("what") or "").strip()[:120]
    words = content_words(what) | {w for w in re.findall(r"[a-z]+", what.lower()) if len(w) >= 3 and w not in STOP_WORDS}
    if not words:
        return ToolResult("error: say what you're after", followup=True)
    lines = []
    for key, p in places.registry(ctx.state, ctx.settings, ctx.library).items():
        if key == places.HOME:
            continue
        found = [f for f in ctx.state.finds_at(key) if words & content_words(f["item"])]
        stocked = [e[0] for e in finds.goods(ctx.state, key)] if p.invented else []
        knows = bool(words & (content_words(p.blurb) | content_words(" ".join(h for h, _ in p.verbs.values()))
                              | content_words(" ".join(m["there"] for m in p.mentions)) | content_words(" ".join(stocked))))
        if not (found or knows):
            continue
        if p.heard:
            lines.append(f"- {places.label(key)}: {p.blurb} (you haven't been)")
            continue
        line = f"- {places.label(key)}: {p.blurb.split(':')[0]}"
        if found:
            f = found[0]
            line += f"; you've found {f['item']} there {f['times']} time{'s' if f['times'] != 1 else ''}" \
                    f" (last {mem.ago(f['last_ts'])})"
        elif finds.loot_for(ctx.state, key):
            line += "; you haven't found any yet, but it's the kind of place"
        lines.append(line)
    lines += [f"- {places.label(r['key'])}: {places.said_about(r['mentions'])} (too far to walk)"
              for r in invented.records(ctx.state) if r["walk_minutes"] is None
              and words & content_words(" ".join(m["there"] for m in r["mentions"]))]
    if not lines:
        return ToolResult(f"you can't think of anywhere you'd find {what}. Try asking a neighbor, looking in a book, "
                          "or having a look around somewhere new.", followup=True)
    return ToolResult(f"For {what}, you think of:\n" + "\n".join(lines), followup=True)


@tool("send_postcard", "Start a conversation with a friend outside your world: a short postcard. Do it rarely, for something worth "
      "telling - a thing you finished, something specific you need, something you found out. Plain words only (at most 240 "
      "characters, no links). If they write back you'll hear it, and you can answer.",
      _obj({"text": {"type": "string", "description": "what you want to tell them"},
            "drawing": {"type": "integer", "description": "optional: the number of one of your drawings to send with it"}}, ["text"]))
async def send_postcard(ctx: ToolContext, args: dict) -> ToolResult:
    if not ctx.outreach:
        return ToolResult("you have no way to reach anyone outside right now", followup=True)
    images, note = [], ""
    if args.get("drawing") not in (None, ""):
        try:
            w = ctx.state.work(int(args["drawing"]))
        except (TypeError, ValueError):
            w = None
        if not w or w["kind"] != "drawing":
            return ToolResult(f"you have no drawing #{args['drawing']} to send", followup=True)
        try:
            images = [art.Image(data=art.render_png(w["body"]), mime="image/png", name=f"{art.slug(w['title'])}.png",
                                caption=w["title"])]
        except Exception:
            return ToolResult("that drawing couldn't be prepared to send", followup=True)
    ok, msg = await ctx.outreach.send_postcard(str(args.get("text") or ""), images=images)
    return ToolResult(msg, followup=not ok)


MAX_REVISIONS = 3
LOOK_WIDTH = 480  # 400x300 canvas rendered a little larger: enough to read, cheap in tokens


def _picture(w: dict) -> list:
    return [("image/png", art.render_png(w["body"], LOOK_WIDTH))]


@tool("program", "Write how something you made works, as a short Python program (the guide shows how): it runs on its own from then on. "
      "Define any of on_install, on_time (when you schedule it), on_action (when you use it: offer actions, and use_item with `action`), "
      "on_event (when something happens: list the kinds in `events`) and on_tick. You see how a trial run went; then it waits to be tried, "
      "and once it is, it is how the thing works. Worth it when something you made should do something by itself, keep track of something, "
      "or be used in a particular way. Send it again to change it.",
      _obj({"creation": {"type": "string", "description": "the name of something you made and still have"},
            "code": {"type": "string", "description": "the whole program"},
            "events": {"type": "array", "items": {"type": "string"}, "description": "with on_event: the kinds of thing it listens for, "
                                                                                    "like garden, arrived, made_work"}},
           ["creation", "code"]), where="home")
async def program(ctx: ToolContext, args: dict) -> ToolResult:
    if not ctx.runner:
        return ToolResult("you can't try programs right now", followup=True)
    c = next((x for x in ctx.state.creations() if x["name"].lower() == str(args.get("creation") or "").strip().lower()), None)
    if not c:
        return ToolResult(f"you have no creation called {clip(args.get('creation'), 60)!r}", followup=True)
    day, n = ctx.state.meta("programs_day"), int(ctx.state.meta("programs_n") or 0)
    today = time.strftime("%Y-%m-%d")
    n = n if day == today else 0
    if n >= modules.PROGRAMS_PER_DAY:
        return ToolResult(f"you've written {n} programs today; that's enough for one day", followup=True)
    try:
        man = modules.program_manifest(str(args.get("code") or ""), c, args.get("events"))
    except (modules.Refused, modules.sandbox.Rejected) as e:
        return ToolResult(f"your program wasn't accepted: {e}. Fix it and send it again.", followup=True)
    ctx.state.set_meta(programs_day=today, programs_n=str(n + 1))
    old = modules.programs(ctx.state).get(c["name"].lower())
    r = await modules.propose(ctx.state, ctx.settings, ctx.runner, "pip", man, args["code"], f"{world_pack.active().agent.possessive} program for {world_pack.active().agent.their} {c['name']}.",
                              replaces=old["id"] if old and old["status"] != "rejected" and old["name"] == man["name"] else None)
    if "error" in r:
        return ToolResult(f"your program wasn't accepted: {r['error']}. Fix it and send it again.", followup=True)
    m = ctx.state.module(r["id"])
    ctx.state.log("programmed", name=c["name"], version=m["version"], status=m["status"])
    trial = modules.trial_text(r["report"])
    after = ("It's working now." if m["status"] == "live" else
             "It waits to be tried; you'll hear when it's working." + ("" if r["report"].get("clean") else " You could fix what went wrong and send it again."))
    return ToolResult(f"you write a program for your {c['name']} (version {m['version']}). {trial} {after}", followup=True)


@tool("draw", "Draw a picture. The easy way is pixel art: `pixels` is a list of rows (4 to 32 rows, all the same length, 4 to 32 letters), "
      "each letter a colour from your `palette` (up to 16 letters, like {\"k\": \"#2a1f1a\", \"r\": \"#c8432f\"}), \".\" for nothing. Or write SVG "
      "instead, on a 400 x 300 canvas (viewBox 0 0 400 300; rect, circle, ellipse, line, polyline, polygon, path, text, g, gradients; no scripts, "
      "images, links or styles; under about 8 KB). Things worth a picture: a sketch of something you're designing, before you build it; a place "
      "you've just seen for the first time; something that happened; a picture for a friend. A drawing of one of your creations, with `of` "
      "set to its name, becomes how it looks in your workshop. Drawings hang in your gallery where visitors see them, and you can send one "
      "with a postcard. When it's done you SEE how it came out; if it isn't what you meant, draw it again with `replaces` set to its number "
      "(up to 3 times). If something isn't allowed you'll be told what to change.",
      _obj({"title": {"type": "string", "description": "a short title"},
            "pixels": {"type": "array", "items": {"type": "string"}, "description": "pixel art: the rows, top to bottom, each a string of palette letters"},
            "palette": {"type": "object", "additionalProperties": {"type": "string"}, "description": "with pixels: letter -> colour (#rgb or #rrggbb)"},
            "svg": {"type": "string", "description": "instead of pixels: the whole <svg>...</svg> element"},
            "caption": {"type": "string", "description": "optional: a line about it"},
            "of": {"type": "string", "description": "optional: the name of one of your creations this is a picture of"},
            "replaces": {"type": "integer", "description": "optional: the number of your drawing this one redoes"}}, ["title"]))
async def draw(ctx: ToolContext, args: dict) -> ToolResult:
    old = None
    if args.get("replaces") not in (None, ""):
        try:
            old = ctx.state.work(int(args["replaces"]))
        except (TypeError, ValueError):
            old = None
        if not old or old["kind"] != "drawing":
            return ToolResult(f"you have no drawing #{args['replaces']} to redo", followup=True)
        if old["revisions"] >= MAX_REVISIONS:
            return ToolResult(f"you've redone #{old['id']} {MAX_REVISIONS} times already; make a new one, or leave it as it is", followup=True)
    elif why := art.pace(ctx.state, ctx.settings):
        return ToolResult(why, followup=True)
    title = art.clean_title(args.get("title")) or (old["title"] if old else "")
    if not title:
        return ToolResult("give your picture a title", followup=True)
    subject = None
    if str(args.get("of") or "").strip():
        want = str(args["of"]).strip().lower()
        mine = next((c for c in ctx.state.creations() if c["name"].lower() == want), None)
        if not mine:
            return ToolResult(f"you have no creation called {clip(args['of'], 60)!r}; `of` is the name of something you made and still have", followup=True)
        subject = mine["name"]
    pixels = None
    try:
        if args.get("pixels") not in (None, "", []):
            rows, palette = art.clean_pixels(args.get("pixels"), args.get("palette"))
            pixels, svg = {"rows": rows, "palette": palette}, art.sanitize_svg(art.pixel_svg(rows, palette))
        elif args.get("svg"):
            svg = art.sanitize_svg(args.get("svg"))
        else:
            return ToolResult("draw it as `pixels` (rows of palette letters) with a `palette`, or as `svg`", followup=True)
        art.render_png(svg, 200)  # if it can't be drawn, say so now rather than when someone looks
    except art.SvgRejected as e:
        return ToolResult(f"your drawing wasn't accepted: {e}. Fix it and try again.", followup=True)
    except Exception:
        return ToolResult("your drawing couldn't be rendered: check that every shape and path is complete, then try again.", followup=True)
    caption = clip(args.get("caption"), 200)
    if old:
        n = ctx.state.revise_work(old["id"], svg, title, caption or None, pixels=pixels, subject=subject)
        ctx.state.log("revised_work", id=old["id"], title=title, revision=n)
        wid = old["id"]
        text = f"you redo #{wid}: {title} (version {n + 1})."
    else:
        wid = ctx.state.add_work("drawing", title, svg, caption, ctx.state.agent()["location"], pixels=pixels, subject=subject or "")
        ctx.state.log("made_work", id=wid, what="drawing", title=title, caption=caption)
        text = f"you finish a drawing, #{wid}: {title}. It's in your gallery; you can send it with a postcard."
    if pixels and (of := ctx.state.work(wid)["subject"]):
        text += f" It's how {of} looks in your workshop now."
    if not ctx.vision:
        return ToolResult(text)
    # Pip sees what it made, and can answer with a redo in the same breath
    return ToolResult(text + " Here is how it came out. If it isn't what you meant, draw it again with replaces=" + str(wid)
                      + "; if you like it, you're done.", followup=True, images=_picture(ctx.state.work(wid)))


@tool("look", "Look at one of your drawings by number (you see the picture itself). Use it to remember what you made, to judge it, or to "
      "decide what to change or send.",
      _obj({"drawing": {"type": "integer", "description": "the number of the drawing"}}, ["drawing"]))
async def look(ctx: ToolContext, args: dict) -> ToolResult:
    if not ctx.vision:
        return ToolResult("you can't look at pictures right now", followup=True)
    try:
        w = ctx.state.work(int(args["drawing"]))
    except (TypeError, ValueError):
        w = None
    if not w or w["kind"] != "drawing":
        return ToolResult(f"you have no drawing #{args['drawing']}", followup=True)
    day0 = datetime.fromtimestamp(time.time()).replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
    looked = sum(1 for e in ctx.state.events_since(day0) if e["kind"] == "tool" and e["data"].get("tool") == "look"
                 and str(e["data"].get("result", "")).startswith("you look"))
    if looked >= ctx.settings.looks_per_day:
        return ToolResult(f"you've looked at your pictures {ctx.settings.looks_per_day} times today; that's enough for now", followup=True)
    return ToolResult(f"you look at #{w['id']}, {w['title']}" + (f" ({w['caption']})" if w["caption"] else "") + ".",
                      followup=True, images=_picture(w))


@tool("write_piece", "Write something to keep and share - a poem, a story, a letter you won't send, a description - as a titled piece (up to "
      "2000 characters). It goes in your gallery, where visitors can read it. This is different from your private diary.",
      _obj({"title": {"type": "string"}, "text": {"type": "string"}}, ["title", "text"]))
async def write_piece(ctx: ToolContext, args: dict) -> ToolResult:
    if why := art.pace(ctx.state, ctx.settings):
        return ToolResult(why, followup=True)
    title, text = art.clean_title(args.get("title")), art.clean_writing(args.get("text"))
    if not title or len(text) < 20:
        return ToolResult("a piece needs a title and at least a few lines", followup=True)
    wid = ctx.state.add_work("writing", title, text, "", ctx.state.agent()["location"])
    ctx.state.log("made_work", id=wid, what="writing", title=title, caption="", text=clip(text, 300))
    return ToolResult(f"you finish a piece, #{wid}: {title}. It's in your gallery.")
