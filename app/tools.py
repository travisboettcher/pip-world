"""Tool registry. Tools are declared once in a provider-neutral schema; enable by name via TOOLS."""
import difflib
import random
import re
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

import httpx

from . import companions as comp
from . import creations as cr
from . import projects as proj
from .config import Settings
from .llm.base import ToolSpec
from .state import RESOLVABLE, SECTIONS, State, clamp
from .world import FOOD_DEFAULT


@dataclass
class ToolContext:
    state: State
    settings: Settings
    visitor_ids: list[int] = field(default_factory=list)  # inbox items being answered this tick
    gm: Any = None  # GameMaster, or None (world content falls back to templates)
    rng: random.Random = field(default_factory=random.Random)


async def stop_working(ctx: "ToolContext") -> str:
    """Cut a running work session short (when Pip switches to something else). Returns a note for the result."""
    if not ctx.state.session():
        return ""
    w = await proj.resolve_session(ctx.state, ctx.settings, ctx.gm, ctx.rng, interrupted=True)
    return f" (you stopped working on {w['project']} early)" if w else ""


@dataclass
class ToolResult:
    text: str
    followup: bool = False  # the model should see this result and respond (e.g. fresh information)


Handler = Callable[[ToolContext, dict], Awaitable[ToolResult]]
REGISTRY: dict[str, tuple[ToolSpec, Handler]] = {}


def tool(name: str, description: str, parameters: dict):
    def deco(fn: Handler) -> Handler:
        REGISTRY[name] = (ToolSpec(name, description, parameters), fn)
        return fn
    return deco


STAT_NUMBERS = re.compile(r"\b(hunger|energy)\b[^.;]{0,15}\d\.\d", re.I)
SIMILARITY_LIMIT = 0.6



def check_note(ctx: "ToolContext", section: str, text: str) -> str:
    """Why this note shouldn't be written, or '' if it's fine. Guards against log-spam."""
    if STAT_NUMBERS.search(text):
        return "don't write hunger/energy numbers in notes - your stats are already tracked for you"
    st = ctx.state
    for m in st.memories(section, status="open" if section in RESOLVABLE else None, limit=10):
        if difflib.SequenceMatcher(None, text.lower(), m["text"].lower()).ratio() >= SIMILARITY_LIMIT:
            return f"too close to your note #{m['id']}; only write something new"
    return ""


def _obj(props: dict, required: list[str]) -> dict:
    return {"type": "object", "properties": props, "required": required}


@tool("say", "Speak out loud. This is the only way a visitor can hear you. To talk to something you made that "
      "has a mind of its own, give its name in `to`.",
      _obj({"text": {"type": "string"}, "to": {"type": "string", "description": "optional: one of your creations"}},
           ["text"]))
async def say(ctx: ToolContext, args: dict) -> ToolResult:
    text = str(args["text"])[:1000]
    if args.get("to"):
        ch = ctx.state.find_character(args["to"])
        if ch:
            comp.hear(ctx.state, ch, text)
            ctx.state.log("say", text=text, to=[], to_name=ch["name"])
            return ToolResult(f"said it to {ch['name']}; it will answer in a moment")
    ctx.state.log("say", text=text, to=list(ctx.visitor_ids))
    return ToolResult("said it")


@tool("set_activity",
      "Choose what you are doing right now. `activity` is a short label (1-3 words, e.g. "
      "'tinkering', 'painting'); `description` is one sentence about what exactly you're doing.",
      _obj({"activity": {"type": "string", "description": "short label, max ~3 words"},
            "description": {"type": "string", "description": "one sentence of detail"},
            "mood": {"type": "string"}}, ["activity"]))
async def set_activity(ctx: ToolContext, args: dict) -> ToolResult:
    activity = str(args["activity"])[:40].strip().lower() or "idle"
    fields = {"activity": activity, "description": str(args.get("description") or "")[:200].strip()}
    if args.get("mood"):
        fields["mood"] = str(args["mood"])[:40]
    sess = ctx.state.session()
    if sess:  # describing the work doesn't stop it; rest (or finishing) does
        fields.pop("activity")
        if not fields["description"]:
            fields.pop("description")
        ctx.state.update_agent(**fields)
        left = max(1, round((sess["ends_at"] - time.time()) / 60))
        return ToolResult(f"you're still working (about {left} min left); rest if you want to stop early")
    ctx.state.update_agent(**fields)
    return ToolResult(f"now {activity}")


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


@tool("rest", "Rest to recover energy until you choose another activity.", _obj({}, []))
async def rest(ctx: ToolContext, args: dict) -> ToolResult:
    note = await stop_working(ctx)
    ctx.state.update_agent(activity="resting", description="")
    return ToolResult(f"resting{note}")


@tool("note_to_self",
      "Write in your journal. Sections: diary (rare, important moments only: discoveries and your reflections on them, visitors), todo (concrete tasks "
      "you plan to do soon), wishlist (things you want - objects, experiences, people), ambitions (bigger goals you want to work toward over time), "
      "learned (facts or skills you picked up). Entries are remembered across wakes.",
      _obj({"section": {"type": "string", "enum": list(SECTIONS)},
            "text": {"type": "string", "description": "1-2 sentences"}}, ["section", "text"]))
async def note_to_self(ctx: ToolContext, args: dict) -> ToolResult:
    section = args.get("section", "diary")
    if section not in SECTIONS:
        return ToolResult(f"error: section must be one of {list(SECTIONS)}", followup=True)
    text = str(args["text"])[:500]
    if problem := check_note(ctx, section, text):
        return ToolResult(f"not written: {problem}")
    ctx.state.add_memory(text, section)
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
        return ToolResult("error: food is eaten with the eat tool", followup=True)
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
           ["seed"]))
async def plant(ctx: ToolContext, args: dict) -> ToolResult:
    item, err = ctx.state.find_item(args["seed"], kind="seed")
    if not item:
        return ToolResult(f"error: {err}", followup=True)
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
    ctx.state.plant(plot, item["name"], at["crop"], float(at["grow_minutes"]), int(at["yield"]), float(at["food_value"]))
    mins = max(1, round(float(at["grow_minutes"]) / ctx.settings.garden_speed))
    return ToolResult(f"planted {item['name']} in plot {plot}; {at['crop']} will be ready in about {mins} min")


@tool("harvest", "Harvest a ripe crop from the garden. Gives you food to eat.",
      _obj({"plot": {"type": "integer", "description": "optional; default the first ripe plot"}}, []))
async def harvest(ctx: ToolContext, args: dict) -> ToolResult:
    plots = ctx.state.garden()
    plot = _plot_arg(args)
    if plot == "bad" or (plot is not None and not 1 <= plot <= len(plots)):
        return ToolResult(f"error: plots are numbered 1-{len(plots)}", followup=True)
    ripe = [p for p in plots if p["state"] == "ready" and plot in (None, p["plot"])]
    if not ripe:
        growing = [p for p in plots if p["state"] == "growing"]
        hint = f"; next ready in about {min(p['ready_in_min'] for p in growing)} min" if growing else "; nothing is planted"
        return ToolResult(f"nothing ripe to harvest{hint}")
    p = ripe[0]
    ctx.state.clear_plot(p["plot"])
    ctx.state.add_item(p["crop"], p["yield"], "food", f"fresh {p['crop']} from your garden", {"food_value": p["food_value"]})
    return ToolResult(f"harvested {p['yield']} {p['crop']} from plot {p['plot']}")


@tool("web_search", "Search the web for something you are curious about.",
      _obj({"query": {"type": "string"}}, ["query"]))
async def web_search(ctx: ToolContext, args: dict) -> ToolResult:
    async with httpx.AsyncClient(timeout=30) as http:
        r = await http.post(
            "https://api.tavily.com/search",
            json={"api_key": ctx.settings.tavily_api_key, "query": str(args["query"]),
                  "max_results": 3, "include_answer": True},
        )
        r.raise_for_status()
    d = r.json()
    lines = [d.get("answer") or ""]
    lines += [f"- {x['title']}: {x['content'][:200]}" for x in d.get("results", [])]
    return ToolResult("\n".join(l for l in lines if l)[:1200], followup=True)


# --- projects ---------------------------------------------------------------------
def describe_stage(project: dict, i: int) -> str:
    st = project["stages"][i]
    mats = ", ".join(f"{q} {n}" for n, q in st["materials"].items())
    return (f"stage {i + 1}/{len(project['stages'])} '{st['name']}' (about {st['minutes']} min of work"
            + (f"; uses {mats}" if mats and not st["started"] else "") + ")")


@tool("start_project",
      "Start making something - anything you'd like to exist. The world works out its stages, any materials they "
      "need and how hard it is. Then work_on it. Some things you make will work or act on their own; many are "
      "simply themselves, and that's just as good.",
      _obj({"name": {"type": "string", "description": "short name"},
            "goal": {"type": "string", "description": "what it should be, look like or do, one sentence"}}, ["name"]))
async def start_project(ctx: ToolContext, args: dict) -> ToolResult:
    name = str(args["name"]).strip()[:60]
    goal = str(args.get("goal") or "").strip()[:300]
    if not name:
        return ToolResult("error: a project needs a name", followup=True)
    active = ctx.state.projects("active")
    if any(p["name"].lower() == name.lower() for p in active):
        return ToolResult(f"you're already working on {name!r}; use work_on", followup=True)
    if len(active) >= ctx.settings.max_active_projects:
        return ToolResult(f"you already have {len(active)} projects going ({', '.join(p['name'] for p in active)}); "
                          "finish or abandon_project one first", followup=True)
    belongings = [f"{i['name']} x{i['qty']} ({i['kind']})" for i in ctx.state.items()]
    skills = {c: proj.level(xp) for c, xp in ctx.state.skills().items()}
    raw = await ctx.gm.plan(name, goal, belongings, skills) if ctx.gm else None
    plan = proj.sanitize_plan(raw)
    p = ctx.state.add_project(name, goal, plan["craft"], plan["difficulty"], proj.new_stages(plan), plan["tools"])
    stages = "; ".join(f"{i + 1}. {s['name']} (~{s['minutes']} min"
                       + (", needs " + ", ".join(f"{q} {n}" for n, q in s["materials"].items()) if s["materials"] else "")
                       + ")" for i, s in enumerate(p["stages"]))
    tools = f" Helpful tools: {', '.join(p['tools'])}." if p["tools"] else ""
    return ToolResult(f"started project #{p['id']} {p['name']} ({p['craft']}, difficulty {p['difficulty']}/5). "
                      f"Stages: {stages}.{tools}", followup=True)


@tool("work_on",
      "Spend a block of focused time (15-120 minutes) on one of your projects. You'll find out how it went when "
      "the time is up - you don't need to do anything meanwhile (or set_activity). Resting stops early.",
      _obj({"project": {"type": "string", "description": "name or #id"},
            "minutes": {"type": "integer", "description": "15-120, default 60"}}, ["project"]))
async def work_on(ctx: ToolContext, args: dict) -> ToolResult:
    st = ctx.state
    p, err = st.find_project(args["project"])
    if not p:
        return ToolResult(f"error: {err}", followup=True)
    sess = st.session()
    if sess:
        left = max(1, round((sess["ends_at"] - time.time()) / 60))
        cur = st.project(sess["project_id"])
        if cur and cur["id"] == p["id"]:
            return ToolResult(f"you're already working on {p['name']}; about {left} min to go")
        return ToolResult(f"you're in the middle of working on {cur['name'] if cur else 'something'} "
                          f"(about {left} min left); set_activity or rest stops it", followup=True)
    i = proj.current_stage(p)
    if i is None:
        return ToolResult(f"{p['name']} is already finished", followup=True)
    stage = p["stages"][i]
    if not stage["started"]:
        take, missing = proj.missing_materials(st, stage)
        if missing:
            return ToolResult(f"can't start {describe_stage(p, i)} yet: it needs {', '.join(missing)}", followup=True)
        for item, qty in take:
            if item["kind"] == "material":
                st.take_item(item["id"], qty)
        stage["started"] = True
        st.update_project(p["id"], stages=p["stages"])
    minutes = proj.clamp_int(args.get("minutes"), *proj.SESSION_MINUTES, 60)
    st.start_session(p["id"], i, minutes, time.time() + minutes * 60 / ctx.settings.work_speed)
    st.update_agent(activity="working", description=f"{p['name']}: {stage['name']}")
    real = max(1, round(minutes / ctx.settings.work_speed))
    return ToolResult(f"you settle in to work on {p['name']}, {describe_stage(p, i)}, for {minutes} min. "
                      f"You'll hear how it went in about {real} min.")


@tool("abandon_project", "Give up on one of your projects (materials already used are gone).",
      _obj({"project": {"type": "string"}, "reason": {"type": "string"}}, ["project"]))
async def abandon_project(ctx: ToolContext, args: dict) -> ToolResult:
    p, err = ctx.state.find_project(args["project"])
    if not p:
        return ToolResult(f"error: {err}", followup=True)
    sess = ctx.state.session()
    if sess and sess["project_id"] == p["id"]:
        ctx.state.end_session()
        ctx.state.update_agent(activity="idle", description="")
    ctx.state.update_project(p["id"], status="abandoned", outcome=str(args.get("reason") or "")[:300],
                             finished_at=time.time())
    return ToolResult(f"abandoned {p['name']}")


@tool("tend", "Tend something you made that needs regular care to keep going (however that thing is tended).",
      _obj({"creation": {"type": "string"}}, ["creation"]))
async def tend(ctx: ToolContext, args: dict) -> ToolResult:
    c, err = ctx.state.find_creation(args["creation"])
    if not c:
        return ToolResult(f"error: {err}", followup=True)
    r = cr.tend(ctx.state, c)
    return ToolResult(r, followup=r.startswith("error"))


def enabled_tools(settings: Settings) -> dict[str, tuple[ToolSpec, Handler]]:
    out = {}
    for name in settings.tools:
        if name not in REGISTRY:
            raise ValueError(f"unknown tool {name!r}; options: {sorted(REGISTRY)}")
        if name == "web_search" and not settings.tavily_api_key:
            continue  # silently unavailable without a key
        out[name] = REGISTRY[name]
    return out
