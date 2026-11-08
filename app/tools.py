"""Tool registry. Tools are declared once in a provider-neutral schema; enable by name via TOOLS."""
import difflib
from datetime import datetime
import random
import re
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from . import art
from . import companions as comp
from . import expectations as exp
from . import conversation as conv
from . import gathering
from . import happenings
from . import invented_places as invented
from . import market
from . import creations as cr
from . import memory as mem
from . import reminders
from . import library as lib
from . import neighbors as nb
from . import place_kinds as kinds
from . import places
from . import search
from . import weather
from . import wishes
from . import projects as proj
from . import emotions as emo
from . import sleep as sleepmod
from .toolnames import ALIASES, canonical
from .config import Settings
from .llm.base import ToolSpec
from .memory import STOP_WORDS
from .state import RESOLVABLE, SECTIONS, State, clamp
from .text import clip, span
from .world import FOOD_DEFAULT, SEEDS_PER_FOOD, seed_packet_for


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


async def stop_working(ctx: "ToolContext") -> str:
    """Cut work or reading short (when Pip rests instead). Returns a note for the result."""
    sess = ctx.state.session()
    if not sess:
        return ""
    if sess["kind"] == "read":
        r = await lib.finish_reading(ctx.state, ctx.settings, ctx.gm, ctx.library, interrupted=True)
        return f" (you put {r['title']} down early)" if r else ""
    if sess["kind"] == "gather":
        g = await gathering.resolve(ctx.state, ctx.settings, ctx.gm, ctx.rng, interrupted=True)
        return f" (you cut your time at {g['label']} short)" if g else ""
    if sess["kind"] == "experiment":
        e = await proj.resolve_experiment(ctx.state, ctx.settings, ctx.gm, ctx.rng, interrupted=True)
        return f" (you cut the experiment on {e['project']} short)" if e else ""
    w = await proj.resolve_session(ctx.state, ctx.settings, ctx.gm, ctx.rng, interrupted=True)
    return f" (you stopped working on {w['project']} early)" if w else ""


MAX_REST_MINUTES = 240


def busy(ctx: "ToolContext") -> str:
    """Why Pip can't start something new right now, or '' if it can."""
    sess = ctx.state.session()
    if not sess:
        return ""
    left = max(1, round((sess["ends_at"] - time.time()) / 60))
    if sess["kind"] == "walk":
        return f"you're on your way to {places.label(sess['target'])} (about {left} min to go)"
    if sess["kind"] == "read":
        return f"you're reading {sess['target']} (about {left} min left); rest stops early"
    if sess["kind"] == "gather":
        return f"you're out {gathering.verb_for(ctx.state, sess['target'])} at {places.label(sess['target'])} (about {left} min left); rest stops early"
    cur = ctx.state.project(sess["project_id"])
    if sess["kind"] == "experiment":
        return f"you're in the middle of an experiment on {cur['name'] if cur else 'something'} (about {left} min left); rest stops early"
    return f"you're in the middle of working on {cur['name'] if cur else 'something'} (about {left} min left); rest stops early"


@dataclass
class ToolResult:
    text: str
    followup: bool = False  # the model should see this result and respond (e.g. fresh information)
    noop: bool = False      # nothing changed; kept out of the feeds and out of Pip's recent-event list
    images: list = field(default_factory=list)  # [(mime, bytes)] the model looks at in this turn (never stored in events)


Handler = Callable[[ToolContext, dict], Awaitable[ToolResult]]
REGISTRY: dict[str, tuple[ToolSpec, Handler]] = {}


ANYWHERE = "anywhere"
SCOPES: dict[str, tuple[str, ...]] = {}   # tool name -> where it can be used: 'anywhere', 'home', or place keys


def is_here(scope: tuple[str, ...], location: str) -> bool:
    return ANYWHERE in scope or places.scope_of(location) in scope


def listed_here(name: str, place) -> bool:
    """An invented place offers the shared verbs its record lists (gather, browse), wherever it is."""
    return bool(getattr(place, "invented", False)) and name in place.verbs


def out_of_place(ctx, name: str) -> str:
    """Why `name` can't be used where Pip is, or '' if it can."""
    scope = SCOPES.get(name, (ANYWHERE,))
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
    if args.get("to"):
        ch = ctx.state.find_character(args["to"])
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
    if not args.get("item"):
        ctx.state.update_agent(hunger=clamp(a["hunger"] - 0.4),
                               **({} if working else {"activity": "eating", "description": ""}))
        return ToolResult("ate a meal")
    item, err = ctx.state.find_item(args["item"], kind="food")
    if not item:
        return ToolResult(f"error: {err}", followup=True)
    ctx.state.take_item(item["id"])
    value = float(item["attrs"].get("food_value", FOOD_DEFAULT))
    ctx.state.update_agent(hunger=clamp(a["hunger"] - value),
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
    full = (1 - ctx.state.agent()["energy"]) / ctx.settings.recover_per_hour * 60  # minutes until fully rested
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
      "made respond in their own way - use, look at, play or read them, whatever fits.",
      _obj({"item": {"type": "string"}, "purpose": {"type": "string"},
            "quantity": {"type": "integer", "description": "materials only, default 1"}}, ["item", "purpose"]))
async def use_item(ctx: ToolContext, args: dict) -> ToolResult:
    item, err = ctx.state.find_item(args["item"])
    if not item:
        made, _ = ctx.state.find_creation(args["item"])
        if made:
            return ToolResult(await cr.use(ctx.state, ctx.gm, made, str(args.get("purpose") or "")[:200]),
                              followup=True)
        return ToolResult(f"error: {err}", followup=True)
    if item["kind"] == "seed":
        return ToolResult("error: seeds are planted with the plant tool", followup=True)
    if item["kind"] == "food":
        packet = seed_packet_for(item["name"]) if "seed" in str(args.get("purpose") or "").lower() else None
        if not packet:
            return ToolResult("error: food is eaten with the eat tool", followup=True)
        ctx.state.take_item(item["id"], 1)  # a crop's fruit holds seeds: one is used up, a couple of packets saved
        ctx.state.add_item(packet["name"], SEEDS_PER_FOOD, "seed", packet["description"], packet["attrs"])
        return ToolResult(f"scooped {SEEDS_PER_FOOD} {packet['name']} out of one of your {item['name']} and set them aside")
    if item["kind"] == "tool":
        return ToolResult(f"used your {item['name']} (you keep it)")
    qty = max(1, int(args.get("quantity") or 1))
    if qty > item["qty"]:
        return ToolResult(f"error: you only have {item['qty']} {item['name']}", followup=True)
    ctx.state.take_item(item["id"], qty)
    left = item["qty"] - qty
    return ToolResult(f"used {qty} {item['name']} ({left} left)" if left else f"used up your last {item['name']}")


def _plot_arg(args: dict):
    try:
        return int(args["plot"]) if args.get("plot") not in (None, "") else None
    except (TypeError, ValueError):
        return "bad"


@tool("plant", "Plant a seed from your belongings in a garden plot. It grows over real time and you'll "
      "be told when it's ready to harvest.",
      _obj({"seed": {"type": "string"}, "plot": {"type": "integer", "description": "optional; default first empty plot"}},
           ["seed"]), where="home")
async def plant(ctx: ToolContext, args: dict) -> ToolResult:
    item, err = ctx.state.find_item(args["seed"], kind="seed")
    if not item:
        crop = str(args["seed"]).strip().lower().removesuffix(" seeds").removesuffix(" seed")
        food = ctx.state.find_item(crop, kind="food")[0] if seed_packet_for(crop) else None
        hint = f"; you could scoop seeds out of your {food['name']} with use_item (say what for)" if food else ""
        return ToolResult(f"error: {err}{hint}", followup=True)
    plots = ctx.state.garden()
    plot = _plot_arg(args)
    if plot == "bad" or (plot is not None and not 1 <= plot <= len(plots)):
        return ToolResult(f"error: plots are numbered 1-{len(plots)}", followup=True)
    if plot is None:
        free = [p["plot"] for p in plots if p["state"] == "empty"]
        if not free:
            return ToolResult("error: every plot is in use; harvest one first", followup=True)
        plot = free[0]
    elif plots[plot - 1]["state"] != "empty":
        return ToolResult(f"error: plot {plot} is already growing {plots[plot - 1]['crop']}", followup=True)
    at = item["attrs"]
    ctx.state.take_item(item["id"])
    grow = float(at["grow_minutes"]) * weather.grow_factor(ctx.state, ctx.settings, time.time())  # rain helps, snow hinders
    ctx.state.plant(plot, item["name"], at["crop"], grow, int(at["yield"]), float(at["food_value"]))
    mins = max(1, round(grow / ctx.settings.garden_speed))
    return ToolResult(f"planted {item['name']} in plot {plot}; {at['crop']} will be ready in about {span(mins)}")


@tool("harvest", "Harvest a ripe crop from the garden. Gives you food to eat.",
      _obj({"plot": {"type": "integer", "description": "optional; default the first ripe plot"}}, []), where="home")
async def harvest(ctx: ToolContext, args: dict) -> ToolResult:
    plots = ctx.state.garden()
    plot = _plot_arg(args)
    if plot == "bad" or (plot is not None and not 1 <= plot <= len(plots)):
        return ToolResult(f"error: plots are numbered 1-{len(plots)}", followup=True)
    ripe = [p for p in plots if p["state"] == "ready" and plot in (None, p["plot"])]
    if not ripe:
        growing = [p for p in plots if p["state"] == "growing"]
        hint = f"; next ready in about {span(min(p['ready_in_min'] for p in growing))}" if growing else "; nothing is planted"
        return ToolResult(f"nothing ripe to harvest{hint}")
    p = ripe[0]
    ctx.state.clear_plot(p["plot"])
    ctx.state.add_item(p["crop"], p["yield"], "food", f"fresh {p['crop']} from your garden", {"food_value": p["food_value"]})
    return ToolResult(f"harvested {p['yield']} {p['crop']} from plot {p['plot']}")


@tool("web_search", "Search the web for something you are curious about.",
      _obj({"query": {"type": "string"}}, ["query"]))
async def web_search(ctx: ToolContext, args: dict) -> ToolResult:
    found = await search.run(ctx.settings, str(args["query"]))
    if found is None:
        return ToolResult("error: web search isn't set up", followup=True)
    return ToolResult(found or "nothing came back for that search", followup=True)


# --- projects ---------------------------------------------------------------------
def describe_stage(project: dict, i: int) -> str:
    st = project["stages"][i]
    mats = ", ".join(f"{q} {n}" for n, q in st["materials"].items())
    return (f"stage {i + 1}/{len(project['stages'])} '{st['name']}' (about {st['minutes']} min of work"
            + (f"; uses {mats}" if mats and not st["started"] else "") + ")")


STEP_SCHEMA = {"type": "array", "description": "your steps, in order", "items": {"type": "object", "properties": {
    "name": {"type": "string"}, "minutes": {"type": "integer", "description": "your guess, 15-240"},
    "materials": {"type": "object", "additionalProperties": {"type": "integer"},
                  "description": "things you expect this step to use up, e.g. {\"brass wire\": 2}"}},
    "required": ["name"]}}


@tool("start_project",
      "Start making something - anything you'd like to exist. The plan is yours: give the steps you think it "
      "takes (you can start with just the first few; you'll learn more as you go). The world checks your plan "
      "and tells you what you can't know yet. Then work_on it. Some things you make will work or act on their "
      "own; many are simply themselves, and that's just as good.",
      _obj({"name": {"type": "string", "description": "short name"},
            "goal": {"type": "string", "description": "what it should be, look like or do, one sentence"},
            "steps": STEP_SCHEMA}, ["name", "steps"]))
async def start_project(ctx: ToolContext, args: dict) -> ToolResult:
    name = str(args["name"]).strip()[:60]
    goal = str(args.get("goal") or "").strip()[:300]
    if not name:
        return ToolResult("error: a project needs a name", followup=True)
    steps = proj.sanitize_stages(args.get("steps"), proj.MAX_STAGES)
    if not steps:
        return ToolResult("error: sketch at least the first step or two of how you'd do it. If you don't know how "
                          "to begin, look it up (web_search, the library) or ask a visitor, then start", followup=True)
    active = ctx.state.projects("active")
    if any(p["name"].lower() == name.lower() for p in active):
        return ToolResult(f"you're already working on {name!r}; use work_on", followup=True)
    if len(active) >= ctx.state.project_limit():
        return ToolResult(f"you already have {len(active)} projects going ({', '.join(p['name'] for p in active)}); "
                          "finish or abandon_project one first", followup=True)
    belongings = [f"{i['name']} x{i['qty']} ({i['kind']})" for i in ctx.state.items()]
    review = await ctx.gm.review_start(name, goal, steps, belongings, proj.feel(ctx.state)) if ctx.gm else None
    plan = proj.build_plan(steps, review)
    p = ctx.state.add_project(name, goal, plan["craft"], plan["difficulty"], proj.new_stages(plan), plan["tools"])
    ctx.state.update_project(p["id"], questions=plan["questions"], hidden=plan["hidden"])
    listing = "; ".join(f"{i + 1}. {s['name']} (~{s['minutes']} min"
                        + (", needs " + ", ".join(f"{q} {n}" for n, q in s["materials"].items()) if s["materials"] else "")
                        + ")" for i, s in enumerate(plan["stages"]))
    tools = f" Helpful tools: {', '.join(plan['tools'])}." if plan["tools"] else ""
    concern = f" A thought on your plan: {clip((review or {}).get('concerns'), 200)}" if (review or {}).get("concerns") else ""
    unknown = (" What you don't know yet: " + "; ".join(plan["questions"])
               + ". Work out what you can, then experiment or look things up, and revise_plan as you learn."
               if plan["questions"] else "")
    return ToolResult(f"started project #{p['id']} {p['name']} ({plan['craft']}, difficulty {plan['difficulty']}/5). "
                      f"Your plan: {listing}.{tools}{concern}{unknown}", followup=True)


@tool("work_on",
      "Spend a block of focused time (15-120 minutes) on one of your projects. You'll find out how it went when "
      "the time is up - you don't need to do anything meanwhile (or set_activity). Resting stops early.",
      _obj({"project": {"type": "string", "description": "name or #id"},
            "minutes": {"type": "integer", "description": "15-120, default 60"},
            "approach": {"type": "string", "description": "how you'll go about it this time - the world judges what "
                                                          "you actually try, so a thoughtful approach counts"},
            "expect": {"type": "string", "enum": ["well", "slowly", "badly"],
                       "description": "optional: how you expect this session to go; you'll see how close you were"}},
           ["project"]), where="home")
async def work_on(ctx: ToolContext, args: dict) -> ToolResult:
    st = ctx.state
    p, err = st.find_project(args["project"])
    if not p:
        return ToolResult(f"error: {err}", followup=True)
    sess = st.session()
    if sess and sess["kind"] == "work" and sess["project_id"] == p["id"]:
        left = max(1, round((sess["ends_at"] - time.time()) / 60))
        return ToolResult(f"you're already working on {p['name']}; about {left} min to go")
    if why := busy(ctx):
        return ToolResult(why, followup=True)
    i = proj.current_stage(p)
    if i is None:
        if p["questions"]:
            return ToolResult(f"you've done everything you know to do on {p['name']}. Still open: "
                              + "; ".join(p["questions"]) + ". Try an experiment, or learn more and revise_plan.",
                              followup=True)
        return ToolResult(f"{p['name']} is already finished", followup=True)
    stage = p["stages"][i]
    used_up = ""
    if not stage["started"]:
        take, missing = proj.missing_materials(st, stage)
        if missing:
            return ToolResult(f"can't start {describe_stage(p, i)} yet: it needs {', '.join(missing)}", followup=True)
        built_in = proj.mentioned_materials(st, stage)
        for item, qty in take:
            if item["kind"] == "material":
                st.take_item(item["id"], qty)
        for item in built_in:
            st.take_item(item["id"])
        stage["started"] = True
        st.update_project(p["id"], stages=p["stages"])
        if built_in:
            used_up = f" You used up your {', '.join(i['name'] for i in built_in)} on it."
    minutes = proj.clamp_int(args.get("minutes"), *proj.SESSION_MINUTES, 60)
    approach = str(args.get("approach") or "").strip()[:240]
    expect = str(args.get("expect") or "").strip().lower()
    st.start_session(p["id"], i, minutes, time.time() + minutes * 60 / ctx.settings.work_speed, target=approach,
                     expect=expect if expect in exp.SESSION_EXPECT else "")
    st.update_agent(activity="working", description=f"{p['name']}: {stage['name']}")
    real = max(1, round(minutes / ctx.settings.work_speed))
    return ToolResult(f"you settle in to work on {p['name']}, {describe_stage(p, i)}, for {minutes} min. "
                      f"You'll hear how it went in about {real} min.{used_up}")


@tool("experiment",
      "Try something to find out how it works: test an idea about one of your projects (a hypothesis) for 20-90 "
      "minutes. What you learn is decided by the world, not you; a good guess teaches more. It can open up new "
      "steps, answer what you didn't know, or surprise you. You'll hear how it went when the time is up.",
      _obj({"project": {"type": "string", "description": "name or #id"},
            "hypothesis": {"type": "string", "description": "what you think might be true or work, and how you'll test it"},
            "minutes": {"type": "integer", "description": "20-90, default 45"},
            "expect": {"type": "string", "enum": ["works", "partly", "fails"],
                       "description": "optional: how you expect it to turn out; you'll see how close you were"}},
           ["project", "hypothesis"]), where="home")
async def experiment(ctx: ToolContext, args: dict) -> ToolResult:
    st = ctx.state
    p, err = st.find_project(args["project"])
    if not p:
        return ToolResult(f"error: {err}", followup=True)
    hypothesis = str(args.get("hypothesis") or "").strip()[:240]
    if len(hypothesis) < 8:
        return ToolResult("error: say what you think might be true or work, and how you'll test it", followup=True)
    if why := busy(ctx):
        return ToolResult(why, followup=True)
    minutes = proj.clamp_int(args.get("minutes"), *proj.EXPERIMENT_MINUTES, 45)
    expect = str(args.get("expect") or "").strip().lower()
    st.start_session(p["id"], -1, minutes, time.time() + minutes * 60 / ctx.settings.work_speed, kind="experiment",
                     target=hypothesis, expect=expect if expect in exp.EXPERIMENT_EXPECT else "")
    st.update_agent(activity="working", description=f"experiment on {p['name']}: {hypothesis[:80]}")
    real = max(1, round(minutes / ctx.settings.work_speed))
    return ToolResult(f"you set up an experiment on {p['name']} ({hypothesis}) for {minutes} min. "
                      f"You'll see what happens in about {real} min.")


@tool("revise_plan",
      "Change a project's plan: add steps (they come after the ones you have), or drop steps you haven't begun. "
      "It's your plan, so this is up to you. If you learned something elsewhere (a search, a book, a visitor) that "
      "might settle something you didn't know, say what in `because` - the world decides whether it does, and only "
      "after you've worked or experimented again since the last time.",
      _obj({"project": {"type": "string", "description": "name or #id"}, "steps": STEP_SCHEMA,
            "drop": {"type": "array", "items": {"type": "string"}, "description": "names of steps to drop"},
            "because": {"type": "string", "description": "what you learned, and from where"}}, ["project"]))
async def revise_plan(ctx: ToolContext, args: dict) -> ToolResult:
    p, err = ctx.state.find_project(args["project"])
    if not p:
        return ToolResult(f"error: {err}", followup=True)
    steps = proj.sanitize_stages(args.get("steps"), proj.MAX_STAGES_REVISED)
    drop = args.get("drop") if isinstance(args.get("drop"), list) else []
    because = str(args.get("because") or "").strip()[:400]
    if not (steps or drop or because):
        return ToolResult("error: give steps to add, steps to drop, or what you learned", followup=True)
    changes, msg = await proj.revise(ctx.state, ctx.gm, p, steps, drop, because)
    bits = []
    if changes["added"]:
        bits.append("added: " + ", ".join(changes["added"]))
    if changes["dropped"]:
        bits.append("dropped: " + ", ".join(changes["dropped"]))
    if changes["finding"]:
        bits.append(f"you now know: {changes['finding']}")
    if changes["answered"]:
        bits.append(f"settled: {changes['answered']}")
    return ToolResult(" ".join(x for x in (msg, "; ".join(bits) or "the plan stays as it is") if x), followup=True)


@tool("abandon_project", "Give up on one of your projects (materials already used are gone).",
      _obj({"project": {"type": "string"}, "reason": {"type": "string"}}, ["project"]))
async def abandon_project(ctx: ToolContext, args: dict) -> ToolResult:
    p, err = ctx.state.find_project(args["project"])
    if not p:
        return ToolResult(f"error: {err}", followup=True)
    sess = ctx.state.session()
    if sess and sess["kind"] in ("work", "experiment") and sess["project_id"] == p["id"]:
        ctx.state.end_session()
        ctx.state.update_agent(activity="idle", description="")
    ctx.state.update_project(p["id"], status="abandoned", outcome=str(args.get("reason") or "")[:300],
                             finished_at=time.time())
    return ToolResult(f"abandoned {p['name']}")


@tool("tend", "Tend something you made that needs regular care to keep going (however that thing is tended).",
      _obj({"creation": {"type": "string"}}, ["creation"]), where="home")
async def tend(ctx: ToolContext, args: dict) -> ToolResult:
    c, err = ctx.state.find_creation(args["creation"])
    if not c:
        return ToolResult(f"error: {err}", followup=True)
    r = cr.tend(ctx.state, c)
    return ToolResult(r, followup=r.startswith("error"))


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
    if st.letters_since(nb.PIP, time.time() - nb.DAY) >= ctx.settings.letters_per_day:
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
            enclosed = f"{made['name']}, something Pip made: {made['description']}"
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


@tool("browse", "Look through what is on offer where you are. At the library: look for books - give a query (a subject, "
      "title or author), or leave it out to wander the shelves and see what's there.",
      _obj({"query": {"type": "string", "description": "optional"}}, []), where=("library", "junkyard", "neighbor"))
async def browse(ctx: ToolContext, args: dict) -> ToolResult:
    here = ctx.state.agent()["location"]
    theirs = [b for b in market.booths(ctx.state, here, time.time()) if b[1]]
    if places.scope_of(here) == "neighbor":                      # at a neighbor's: what they have for sale, if anything
        if not theirs:
            ch = places.neighbor_at(ctx.state, here)
            away = market.away_at(ctx.state, ch, time.time()) if ch else None
            return ToolResult(f"{ch['name']} is at a stall in {places.label(away)} today, with their wares" if away
                              else f"there's nothing for sale at {places.label(here)}", followup=True)
        return ToolResult(market.wares_line(ctx.state, theirs[0][0], theirs[0][1], theirs[0][2], time.time())
                          + f" You have {ctx.state.coins()} coins. buy what you want, or sell them some of yours.", followup=True)
    table = market.stock_table(ctx.state, here) or gathering.loot_for(ctx.state, here)
    rec = ctx.state.place_row(here) if table and here not in gathering.LOOT else None
    if rec and kinds.KINDS[rec["kind"]].trades:
        return ToolResult("\n".join([shop_stock(ctx, here, table, rec)] + [market.wares_line(ctx.state, k, f"{who}, at a stall here today,", t, time.time())
                                                                            for k, who, t in theirs]), followup=True)
    if table:  # a look around somewhere you can gather: what's worth digging for (nothing is taken)
        seen = gathering.glimpse(ctx.rng, here, table=table)
        return ToolResult(f"Looking over {places.label(here)}, you can make out: " + ", ".join(seen)
                          + ". gather to dig for what you need.", followup=True)
    q = str(args.get("query") or "").strip()
    if q:
        books, where = ctx.library.search(q), f"Looking for {q!r}, you find"
    else:
        shelf, books = ctx.library.wander(ctx.rng)
        where = f"Wandering along {shelf}, you see"
    if not books:
        return ToolResult(f"nothing on the shelves matches {q!r}", followup=True)
    return ToolResult(f"{where}:\n" + "\n".join(f"- {lib.line(b, ctx.state)}" for b in books), followup=True)


def shop_stock(ctx, here: str, table: list, rec: dict) -> str:
    """At a shop, browse shows what's in today with its price (fewer things as the stock runs down) and what's on account."""
    level = gathering.stock(ctx.state, here)
    n = round(gathering.GLIMPSE * min(1.0, level / gathering.full_yield_at(ctx.state, here)))
    now = time.time()
    seen = [e for e in table if e[0] in gathering.glimpse(ctx.rng, here, n, table) and market.stock_left(ctx.state, here, e, now)]
    lines = [f"In stock at {places.label(here)} today: "
             + ", ".join(f"{e[0]} ({market.sell_price(ctx.state, here, e, now)} coins)" for e in seen)
             + f". You have {ctx.state.coins()} coins. buy what you need; "
             + ("sell what you have, or set out a stall with an ask." if kinds.KINDS[rec["kind"]].stalls else "gather to pick through the drawers on account.") if seen else
             f"The shelves at {places.label(here)} are bare today; they restock slowly, so come back in a day or so."]
    lines += market.stall_lines(ctx.state, here, now)
    if rec["on_account"]:
        owed = market.owed(ctx.state, here, now)
        lines.append("On account here: " + ", ".join(f"{q} {name}" for name, q in rec["on_account"].items())
                     + f" ({owed} coins at today's prices; pay settles it).")
    return "\n".join(lines)


def _qty(args: dict) -> int | None:
    try:
        q = int(args.get("quantity", 1))
    except (TypeError, ValueError):
        return None
    return q if q >= 1 else None


_TRADE_ITEM = {"item": {"type": "string"}, "quantity": {"type": "integer", "description": "optional; default 1"}}


@tool("buy", "Buy something from a booth here with your coins. Prices change a little every day and as things are bought.",
      _obj(_TRADE_ITEM, ["item"]), where=("market", "neighbor"))
async def buy(ctx: ToolContext, args: dict) -> ToolResult:
    qty = _qty(args)
    if qty is None:
        return ToolResult("error: quantity must be a whole number, at least 1", followup=True)
    ok, text = market.buy(ctx.state, ctx.state.agent()["location"], str(args.get("item") or ""), qty, time.time())
    return ToolResult(text if ok else f"error: {text}", followup=True)


@tool("sell", "Sell something you have to a booth here: it pays less than it charges, and only has so many coins a day. At a market you can instead set out "
      "a stall: give `ask` (coins each) and customers stop while you are here, paying your price; an ask of 0 takes it back off the stall. "
      "A creation of yours can be sold too (it is theirs after that), and copies of a drawing or writing can be set out on a stall (`item` is its title).",
      _obj({**_TRADE_ITEM, "ask": {"type": "integer", "description": "optional, at a market: your price in coins each, to set out a stall (0: take it back)"}}, ["item"]),
      where=("market", "neighbor"))
async def sell(ctx: ToolContext, args: dict) -> ToolResult:
    here = ctx.state.agent()["location"]
    if args.get("ask") is not None:
        ask = args["ask"]
        if isinstance(ask, bool) or not isinstance(ask, int):
            return ToolResult("error: an ask is a whole number of coins", followup=True)
        if ask == 0:
            ok, text = market.take_back(ctx.state, here, str(args.get("item") or ""))
        else:
            have, _ = ctx.state.find_item(str(args.get("item") or ""))
            qty = _qty(args) if "quantity" in args else (have["qty"] if have else 1)
            if qty is None:
                return ToolResult("error: quantity must be a whole number, at least 1", followup=True)
            ok, text = market.list_on_stall(ctx.state, here, str(args.get("item") or ""), qty, ask, time.time())
        return ToolResult(text if ok else f"error: {text}", followup=True)
    qty = _qty(args)
    if qty is None:
        return ToolResult("error: quantity must be a whole number, at least 1", followup=True)
    ok, text = market.sell(ctx.state, here, str(args.get("item") or ""), qty, time.time())
    return ToolResult(text if ok else f"error: {text}", followup=True)


@tool("pay", "Pay what you owe a booth here for things you took on account.", _obj({}, []), where=("market",))
async def pay(ctx: ToolContext, args: dict) -> ToolResult:
    ok, text = market.pay(ctx.state, ctx.state.agent()["location"], time.time())
    return ToolResult(text if ok else f"error: {text}", followup=True)


@tool("read", "At the library: settle in and read a book (by #id or title) for a while. You'll take in what you "
      "read when the time is up, and next time you pick up where you left off.",
      _obj({"book": {"type": "string"}, "minutes": {"type": "integer", "description": "15-90, default 45"}},
           ["book"]), where="library")
async def read(ctx: ToolContext, args: dict) -> ToolResult:
    if why := busy(ctx):
        return ToolResult(why, followup=True)
    b, err = ctx.library.find(args["book"])
    if not b:
        return ToolResult(f"error: {err}", followup=True)
    if not b["format"]:
        return ToolResult(f"{b['title']} is bound in a way you can't open ({', '.join(b['formats'])})", followup=True)
    mark = ctx.state.bookmark(b["id"])
    if mark and mark["finished"]:
        return ToolResult(f"you've already finished {b['title']}", followup=True)
    if mark and mark["unreadable"]:
        return ToolResult(f"{b['title']} is almost all pictures; there's nothing more to read", followup=True)
    minutes = proj.clamp_int(args.get("minutes"), *lib.READ_MINUTES, 45)
    return ToolResult(lib.start_reading(ctx.state, ctx.settings, b, minutes))


def enabled_tools(settings: Settings) -> dict[str, tuple[ToolSpec, Handler]]:
    out = {}
    for name in settings.tools:
        name = canonical(name)  # an old name in TOOLS (browse_library) means its new one
        if name in out:
            continue
        if name not in REGISTRY:
            raise ValueError(f"unknown tool {name!r}; options: {sorted(REGISTRY)}")
        if name == "web_search" and not search.ready(settings):
            continue  # silently unavailable without a key
        if name == "sleep" and not settings.sleep:
            continue
        if name in ("settle", "feel") and settings.emotions == "off":
            continue
        if name == "send_postcard" and (settings.outreach == "off" or not settings.outreach_channels):
            continue  # no way out configured
        if name in ("browse", "read") and not lib.open_library(settings):
            continue  # no library mounted
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


@tool("resume_project", "Pick a project that is on hold back up.",
      _obj({"project": {"type": "string", "description": "name or #id"}}, ["project"]))
async def resume_project(ctx: ToolContext, args: dict) -> ToolResult:
    p, err = ctx.state.find_project(args["project"], status="paused")
    if not p:
        return ToolResult(f"error: {err}", followup=True)
    if len(ctx.state.projects("active")) >= ctx.state.project_limit():
        return ToolResult("you already have as many projects going as you can; finish or abandon_project one first",
                          followup=True)
    ctx.state.update_project(p["id"], status="active")
    return ToolResult(f"{p['name']} is active again", followup=True)


@tool("gather", "Spend a while gathering what this place offers (15-60 minutes). What you find is down to luck and how "
      "picked-over the place is; you'll see it when the time is up. Resting stops early.",
      _obj({"minutes": {"type": "integer", "description": "15-60, default 30"}}, []), where=("woods", "junkyard"))
async def gather(ctx: ToolContext, args: dict) -> ToolResult:
    if why := busy(ctx):
        return ToolResult(why, followup=True)
    place = ctx.state.agent()["location"]
    if not gathering.loot_for(ctx.state, place):
        return ToolResult("there's nothing to gather here", followup=True)
    lo, hi = gathering.session_for(ctx.state, place)
    minutes = proj.clamp_int(args.get("minutes"), lo, hi, min(30, hi))
    verb = gathering.verb_for(ctx.state, place)
    ctx.state.start_session(0, 0, minutes, time.time() + minutes * 60 / ctx.settings.work_speed, kind="gather", target=place)
    ctx.state.update_agent(activity="gathering", description=f"{verb} at {places.label(place)}")
    real = max(1, round(minutes / ctx.settings.work_speed))
    note = (" The ground looks well picked over."
            if gathering.stock(ctx.state, place) < gathering.full_yield_at(ctx.state, place) else "")
    return ToolResult(f"you set about {verb} at {places.label(place)} for {minutes} min.{note} "
                      f"You'll see what you found in about {real} min.")


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
        finds = [f for f in ctx.state.finds_at(key) if words & content_words(f["item"])]
        stocked = [e[0] for e in market.stock_table(ctx.state, key) or gathering.loot_for(ctx.state, key) or ()] if p.invented else []
        knows = bool(words & (content_words(p.blurb) | content_words(" ".join(h for h, _ in p.verbs.values()))
                              | content_words(" ".join(m["there"] for m in p.mentions)) | content_words(" ".join(stocked))))
        if not (finds or knows):
            continue
        if p.heard:
            lines.append(f"- {places.label(key)}: {p.blurb} (you haven't been)")
            continue
        line = f"- {places.label(key)}: {p.blurb.split(':')[0]}"
        if finds:
            f = finds[0]
            line += f"; you've found {f['item']} there {f['times']} time{'s' if f['times'] != 1 else ''}" \
                    f" (last {mem.ago(f['last_ts'])})"
        elif gathering.loot_for(ctx.state, key):
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


@tool("draw", "Draw a picture, by writing it as SVG on a 400 x 300 canvas (viewBox 0 0 400 300; the canvas is blank, paint a background "
      "if you want one). You may use rect, circle, ellipse, line, polyline, polygon, path, text, g, and linear/radial gradients. "
      "No scripts, images, links or styles; keep it under about 8 KB. It's kept in your gallery where visitors can see it, and you can "
      "send one with a postcard. When it's done you SEE how it came out; if it isn't what you meant, draw it again with `replaces` set to its "
      "number (up to 3 times). If something isn't allowed you'll be told what to change.",
      _obj({"title": {"type": "string", "description": "a short title"},
            "svg": {"type": "string", "description": "the whole <svg>...</svg> element"},
            "caption": {"type": "string", "description": "optional: a line about it"},
            "replaces": {"type": "integer", "description": "optional: the number of your drawing this one redoes"}}, ["title", "svg"]))
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
    try:
        svg = art.sanitize_svg(args.get("svg"))
        art.render_png(svg, 200)  # if it can't be drawn, say so now rather than when someone looks
    except art.SvgRejected as e:
        return ToolResult(f"your drawing wasn't accepted: {e}. Fix it and try again.", followup=True)
    except Exception:
        return ToolResult("your drawing couldn't be rendered: check that every shape and path is complete, then try again.", followup=True)
    caption = clip(args.get("caption"), 200)
    if old:
        n = ctx.state.revise_work(old["id"], svg, title, caption or None)
        ctx.state.log("revised_work", id=old["id"], title=title, revision=n)
        wid = old["id"]
        text = f"you redo #{wid}: {title} (version {n + 1})."
    else:
        wid = ctx.state.add_work("drawing", title, svg, caption, ctx.state.agent()["location"])
        ctx.state.log("made_work", id=wid, what="drawing", title=title, caption=caption)
        text = f"you finish a drawing, #{wid}: {title}. It's in your gallery; you can send it with a postcard."
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
