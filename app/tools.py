"""Tool registry. Tools are declared once in a provider-neutral schema; enable by name via TOOLS."""
from dataclasses import dataclass
from typing import Awaitable, Callable

import httpx

from .config import Settings
from .llm.base import ToolSpec
from .state import State, clamp


@dataclass
class ToolContext:
    state: State
    settings: Settings


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


def _obj(props: dict, required: list[str]) -> dict:
    return {"type": "object", "properties": props, "required": required}


@tool("set_activity", "Choose what you are doing right now (e.g. painting, reading, tinkering).",
      _obj({"activity": {"type": "string"}, "mood": {"type": "string"}}, ["activity"]))
async def set_activity(ctx: ToolContext, args: dict) -> ToolResult:
    activity = str(args["activity"])[:40].strip().lower() or "idle"
    fields = {"activity": activity}
    if args.get("mood"):
        fields["mood"] = str(args["mood"])[:40]
    ctx.state.update_agent(**fields)
    return ToolResult(f"now {activity}")


@tool("eat", "Eat a meal. Lowers hunger.", _obj({}, []))
async def eat(ctx: ToolContext, args: dict) -> ToolResult:
    a = ctx.state.agent()
    ctx.state.update_agent(hunger=clamp(a["hunger"] - 0.4), activity="eating")
    return ToolResult("ate a meal")


@tool("rest", "Rest to recover energy until you choose another activity.", _obj({}, []))
async def rest(ctx: ToolContext, args: dict) -> ToolResult:
    ctx.state.update_agent(activity="resting")
    return ToolResult("resting")


@tool("note_to_self", "Save a short note you want to remember in future ticks.",
      _obj({"text": {"type": "string"}}, ["text"]))
async def note_to_self(ctx: ToolContext, args: dict) -> ToolResult:
    ctx.state.add_memory(str(args["text"])[:500])
    return ToolResult("noted")


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
