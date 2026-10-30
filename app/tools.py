"""Tool registry. Tools are declared once in a provider-neutral schema; enable by name via TOOLS."""
import difflib
import re
import time
from dataclasses import dataclass, field
from typing import Awaitable, Callable

import httpx

from .config import Settings
from .llm.base import ToolSpec
from .state import RESOLVABLE, SECTIONS, State, clamp
from .world import FOOD_DEFAULT


@dataclass
class ToolContext:
    state: State
    settings: Settings
    visitor_ids: list[int] = field(default_factory=list)  # inbox items being answered this tick


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


@tool("say", "Speak out loud to a visitor. This is the only way a visitor can hear you.",
      _obj({"text": {"type": "string"}}, ["text"]))
async def say(ctx: ToolContext, args: dict) -> ToolResult:
    text = str(args["text"])[:1000]
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
    ctx.state.update_agent(**fields)
    return ToolResult(f"now {activity}")


@tool("eat", "Eat. With no `item` you have a plain meal (lowers hunger). Name a food item you own (e.g. "
      "something you harvested) to eat that instead - it is used up and usually fills you more.",
      _obj({"item": {"type": "string", "description": "optional: a food item from your belongings"}}, []))
async def eat(ctx: ToolContext, args: dict) -> ToolResult:
    a = ctx.state.agent()
    if not args.get("item"):
        ctx.state.update_agent(hunger=clamp(a["hunger"] - 0.4), activity="eating", description="")
        return ToolResult("ate a meal")
    item, err = ctx.state.find_item(args["item"], kind="food")
    if not item:
        return ToolResult(f"error: {err}", followup=True)
    ctx.state.take_item(item["id"])
    value = float(item["attrs"].get("food_value", FOOD_DEFAULT))
    ctx.state.update_agent(hunger=clamp(a["hunger"] - value), activity="eating", description=f"eating {item['name']}")
    return ToolResult(f"ate {item['name']}")


@tool("rest", "Rest to recover energy until you choose another activity.", _obj({}, []))
async def rest(ctx: ToolContext, args: dict) -> ToolResult:
    ctx.state.update_agent(activity="resting", description="")
    return ToolResult("resting")


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


@tool("use_item", "Use something you own for a purpose. Materials (like brass) are used up; tools are kept.",
      _obj({"item": {"type": "string"}, "purpose": {"type": "string"},
            "quantity": {"type": "integer", "description": "materials only, default 1"}}, ["item", "purpose"]))
async def use_item(ctx: ToolContext, args: dict) -> ToolResult:
    item, err = ctx.state.find_item(args["item"])
    if not item:
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


def enabled_tools(settings: Settings) -> dict[str, tuple[ToolSpec, Handler]]:
    out = {}
    for name in settings.tools:
        if name not in REGISTRY:
            raise ValueError(f"unknown tool {name!r}; options: {sorted(REGISTRY)}")
        if name == "web_search" and not settings.tavily_api_key:
            continue  # silently unavailable without a key
        out[name] = REGISTRY[name]
    return out
