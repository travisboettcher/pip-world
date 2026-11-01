"""Slash commands: information straight from the engine, not a reply from Pip.

A message to Pip over a channel that starts with `/word` is answered here from state: no LLM call, nothing in Pip's
inbox, no wake. They mirror `pipchat` (status, items, garden...). Everything is read-only.
"""
import re
import time

from . import emotions as emo
from . import projects as proj
from . import sleep as sleepmod
from .state import SECTIONS

COMMAND = re.compile(r"^/([a-z]+)(?:\s+(.*))?$", re.I | re.S)
OPEN_SECTIONS = ("todo", "wishlist", "ambitions")
NAMES = ("help", "status", "items", "garden", "projects", "creations", "notes", "emotions", "usage")
HELP = {"help": "this list", "status": "what Pip is doing and how it is", "items": "what Pip owns",
        "garden": "the garden plots", "projects": "projects in progress", "creations": "what Pip has made",
        "notes": "open to-dos, wishes and ambitions (or /notes diary|learned|todo|wishlist|ambitions)",
        "emotions": "Pip's emotion state", "usage": "today's token use against the budget"}


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
    return "Commands (answered by the workshop, not by Pip):\n" + "\n".join(f"/{n}: {HELP[n]}" for n in NAMES)


def _status(state, settings, arg, now):
    a = state.agent()
    doing = a["activity"] + (f": {a['description']}" if a["description"] else "")
    lines = [f"Pip is {doing}",
             f"Mood {a['mood']}; hunger {round(a['hunger'] * 100)}%, energy {round(a['energy'] * 100)}%; at the {a['location']}."]
    lines.append(f"Day {sleepmod.day_number(state, now)}" + (f", {sleepmod.period(settings, now)}" if settings.sleep else "") + ".")
    return "Status\n" + "\n".join(lines)


def _items(state, settings, arg, now):
    items = state.items()
    if not items:
        return "Items\nNothing in the workshop."
    return "Items\n" + "\n".join(f"{i['name']} x{i['qty']} ({i['kind']})" for i in items)


def _garden(state, settings, arg, now):
    lines = []
    for g in state.garden(now):
        if g["state"] == "empty":
            lines.append(f"Plot {g['plot']}: empty")
        elif g["state"] == "ready":
            lines.append(f"Plot {g['plot']}: {g['crop']}, ready to harvest")
        else:
            lines.append(f"Plot {g['plot']}: {g['crop']}, growing (ready in about {g['ready_in_min']} min)")
    return "Garden\n" + "\n".join(lines)


def _projects(state, settings, arg, now):
    active = state.projects("active")
    if not active:
        return "Projects\nNo projects right now."
    lines = []
    for p in active:
        i = proj.current_stage(p)
        nxt = p["stages"][i]["name"] if i is not None else "all the planned steps are done"
        lines.append(f"{p['name']}: {proj.percent(p)}%, next: {nxt}")
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


_HANDLERS = {"help": _help, "status": _status, "items": _items, "garden": _garden, "projects": _projects,
             "creations": _creations, "notes": _notes, "emotions": _emotions, "usage": _usage}
