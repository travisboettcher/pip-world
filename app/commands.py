"""Slash commands: information straight from the engine, not a reply from Pip.

A message to Pip over a channel that starts with `/word` is answered here from state: no LLM call, nothing in Pip's
inbox, no wake. They mirror `pipchat` (status, items, projects...). Everything is read-only.
"""
import re
from datetime import datetime
import time

from . import emotions as emo
from . import projects as proj
from . import sleep as sleepmod
from . import stakes
from .state import SECTIONS
from .text import span
from . import world_pack
from . import stats as stats_mod

COMMAND = re.compile(r"^/([a-z]+)(?:\s+(.*))?$", re.I | re.S)
OPEN_SECTIONS = ("todo", "wishlist", "ambitions")
NAMES = ("help", "status", "items", "projects", "creations", "notes", "emotions", "usage")
HELP = {"help": "this list", "status": "what {name} is doing and how {they} {are}", "items": "what {name} owns",
        "projects": "projects in progress", "creations": "what {name} has made",
        "notes": "open to-dos, wishes and ambitions (or /notes diary|learned|todo|wishlist|ambitions)",
        "emotions": "{possessive} emotion state", "usage": "today's token use against the budget"}


def answer(state, settings, text: str, now: float | None = None) -> str | None:
    """The reply to a slash command, or None when `text` isn't one."""
    m = COMMAND.match(str(text or "").strip())
    if not m:
        return None
    name, arg = m.group(1).lower(), (m.group(2) or "").strip()
    handler = _HANDLERS.get(name)
    if not handler:
        return f"I don't know /{name}. Try /help."
    return handler(state, settings, arg, now or time.time())


def _help(state, settings, arg, now):
    a = world_pack.active().agent
    words = {"name": a.name, "possessive": a.possessive, "they": a.they, "are": "are" if a.pronoun == "they" else "is"}
    return f"Commands (answered by the engine, not by {a.name}):\n" + "\n".join(f"/{n}: {HELP[n].format(**words)}" for n in NAMES)


def _status(state, settings, arg, now):
    a = state.agent()
    doing = a["activity"] + (f": {a['description']}" if a["description"] else "")
    lines = [f"{world_pack.active().agent.name} is {doing}",
             f"Mood {a['mood']}; " + ", ".join(f"{d.get('label', n)} {round(a[n] * 100)}%" for n, d in stats_mod.declared(settings).items() if n in a)
             + f"; at the {a['location']}."]
    c = stakes.condition(state)
    if c:
        lines.append(f"Knocked out ({c['label']} ran out) until {datetime.fromtimestamp(c['until']).strftime('%-I:%M %p')}."
                     if c["outcome"] == "knocked_out" else f"Too weak to do much ({c['label']} ran out) until it recovers.")
    lines.append(f"Day {sleepmod.day_number(state, now)}" + (f", {sleepmod.period(settings, now)}" if settings.sleep else "") + ".")
    from . import modules
    lines += modules.status_lines(state)                      # what live modules show the agent (its garden, say)
    return "Status\n" + "\n".join(lines)


def _items(state, settings, arg, now):
    items = state.items()
    if not items:
        return f"Items\n{world_pack.active().agent.name} has nothing."
    return "Items\n" + "\n".join(f"{i['name']} x{i['qty']} ({i['kind']})" for i in items)


def _projects(state, settings, arg, now):
    active = [p for p in proj.published(state)["projects"] if p["status"] == "active"]     # what the crafting module publishes
    if not active:
        return "Projects\nNo projects right now."
    lines = []
    for p in active:
        i = p["current_stage"]
        nxt = p["stages"][i]["name"] if i is not None else "all the planned steps are done"
        lines.append(f"{p['name']}: {p['percent']}%, next: {nxt}")
    return "Projects\n" + "\n".join(lines)


def _creations(state, settings, arg, now):
    made = state.creations()
    if not made:
        return "Creations\nNothing made yet."
    return "Creations\n" + "\n".join(f"{c['name']} ({c['quality']}): {c['description']}" for c in made)


def _notes(state, settings, arg, now):
    wanted = arg.lower()
    if wanted and wanted not in SECTIONS:
        return f"No section {wanted!r}. Options: {', '.join(SECTIONS)}."
    out = []
    for sec in ([wanted] if wanted else OPEN_SECTIONS):
        rows = state.memories(sec, status="open", limit=10)
        out.append(f"{sec.capitalize()}:\n" + ("\n".join(f"#{r['id']} {r['text']}" for r in rows) if rows else "(none)"))
    return "Notes\n" + "\n".join(out)


def _emotions(state, settings, arg, now):
    snap = emo.snapshot(state, now)
    tail = f"; it feels like {snap['blend']}" if snap["blend"] else ""
    return ("Emotions\n" + ", ".join(f"{e['name']} {e['value']}" for e in snap["emotions"])
            + f"\nOverall: {snap['valence_word']}, {snap['arousal_word']}{tail}.")


def _usage(state, settings, arg, now):
    u = state.usage_today()
    pct = round(100 * u["total_tokens"] / u["budget"]) if u["budget"] else 0
    return f"Usage\n{u['total_tokens']:,} of {u['budget']:,} tokens today ({pct}%). Calls: {u['calls']}."


_HANDLERS = {"help": _help, "status": _status, "items": _items, "projects": _projects,
             "creations": _creations, "notes": _notes, "emotions": _emotions, "usage": _usage}
