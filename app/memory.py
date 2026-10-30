"""Long-term memory: nightly reflection (consolidation) and recall (retrieval). See DESIGN-memory.md.

Pip reflects in its own voice (its persona is the system prompt): once a day it turns everything since the last
reflection into a day summary, a few insights with importance, notes on the people involved, and a fresh
self-portrait. Those go into every prompt at a fixed size. Everything worth remembering is also indexed for the
`recall` tool (SQLite FTS5, BM25 ranking).
"""
import time
from datetime import datetime

from .text import clip

RECALL_EVENT_KINDS = ("inbox", "say", "gift", "work", "creation_made", "companion")
MAX_INSIGHTS = 5
SELF_PORTRAIT_CHARS = 900
REFLECT_MAX_TOKENS = 2048
RETRY_AFTER = 3600
STOP_WORDS = set("""a an and are as at be but by did do does for from had has have how i if in into is it its me my
of on or so that the their them then there these they this to was we were what when where which who why will with
you your about did any can could would should just""".split())


def recall_text(kind: str, d: dict) -> str | None:
    """The searchable text for an event, or None if it isn't worth remembering on its own."""
    if kind == "inbox":
        return None if d.get("gift") else f"{d.get('sender') or 'A visitor'} said to you: {d['text']}"
    if kind == "say":
        return f"You said to {d['to_name']}: {d['text']}" if d.get("to_name") else f"You said: {d['text']}"
    if kind == "gift":
        return f"{d['sender']} gave you {d['qty']} x {d['item']}"
    if kind == "work":
        return None if d.get("interrupted") else f"Working on {d['project']} ({d['stage']}), {d['result']}: {d['text']}"
    if kind == "creation_made":
        return f"You finished making {d['name']}: {d['description']}"
    if kind == "companion":
        return f"{d['name']} said: {d['text']}"
    return None


def ago(ts: float, now: float | None = None) -> str:
    secs = max(0.0, (now or time.time()) - ts)
    if secs < 90:
        return "just now"
    if secs < 3600:
        return f"{round(secs / 60)} minutes ago"
    if secs < 86400:
        h = round(secs / 3600)
        return "an hour ago" if h == 1 else f"{h} hours ago"
    days = round(secs / 86400)
    return "yesterday" if days == 1 else f"{days} days ago" if days < 14 else datetime.fromtimestamp(ts).strftime("on %b %d")


# --- reflection ---------------------------------------------------------------
def material(state, since: float, until: float, max_chars: int) -> tuple[list[str], set[str]]:
    """One line per notable event in (since, until], newest kept when over budget; plus who appeared."""
    lines, people = [], set()
    for e in state.events_since(since, limit=5000):
        if e["ts"] > until:
            break
        d, k = e["data"], e["kind"]
        text = recall_text(k, d)
        if k in ("inbox", "gift") and d.get("sender"):
            people.add(d["sender"])
        if k == "companion":
            people.add(d["name"])
        if k == "tool" and not str(d.get("result", "")).startswith(("error", "not ")):
            a = d["args"]
            if d["tool"] == "note_to_self":
                text = f"You wrote ({a.get('section')}): {a.get('text')}"
            elif d["tool"] == "resolve_note":
                text = f"You crossed off a note: {a.get('outcome') or d['result']}"
            elif d["tool"] == "start_project":
                text = f"You started a project: {a.get('name')}" + (f" ({a['goal']})" if a.get("goal") else "")
        elif k == "creation" and d.get("what") in ("stopped", "used"):
            text = d["text"]
        if text:
            lines.append(f"[{datetime.fromtimestamp(e['ts']).strftime('%a %H:%M')}] {clip(text, 300)}")
    total, keep = 0, []
    for line in reversed(lines):
        total += len(line) + 1
        if total > max_chars:
            break
        keep.append(line)
    return list(reversed(keep)), people


def due(state, settings, now: float) -> bool:
    local = datetime.fromtimestamp(now)
    if local.hour < settings.reflect_hour or state.meta("last_reflection_day") == local.date().isoformat():
        return False
    failed = float(state.meta("reflection_failed_at") or 0)
    return now - failed >= RETRY_AFTER


async def reflect(state, settings, gm, persona: str, now: float | None = None) -> dict | None:
    """Reflect on everything since the last reflection. Returns the logged event data, or None."""
    now = now or time.time()
    since = float(state.meta("last_reflection_ts") or 0)
    lines, appeared = material(state, since, now, settings.reflect_max_chars)
    done = {"last_reflection_ts": str(now), "last_reflection_day": datetime.fromtimestamp(now).date().isoformat()}
    if not lines:
        state.set_meta(**done)  # a quiet day: nothing to go over
        return None
    known = {p["name"]: p for p in state.people()}
    names = sorted(appeared | set(known))
    portrait = state.meta("self_portrait")
    task = (
        "You are asleep, going over what has happened since you last slept, the way a mind does at night. "
        "This is private: nobody else will read it.\n\n"
        + (f"How you described yourself last time:\n{portrait}\n\n" if portrait else
           "You haven't described yourself before.\n\n")
        + ("What you thought of people so far:\n" + "\n".join(f"- {n}: {p['notes']}" for n, p in known.items()) + "\n\n"
           if known else "")
        + "What happened (oldest first):\n" + "\n".join(lines) + "\n\n"
        "Report, all in your own first-person voice:\n"
        "- `summary`: 2-4 sentences: this stretch of time as you'll remember it - what mattered and how it felt, "
        "not a list.\n"
        f"- `insights`: up to {MAX_INSIGHTS} things you've come to understand or believe - about yourself, your work, "
        "the world or others - each with `importance` 1-10 (10 = will shape you for a long time). Only real ones; "
        "none is fine. Don't repeat what you already believed unless it changed.\n"
        "- `people`: for each person who mattered here, `name` and `notes` (1-3 sentences: who they are to you "
        f"now). Only these names: {', '.join(names) if names else '(nobody came by)'}.\n"
        "- `self`: describe yourself afresh in under 120 words - who you are, what you care about, what you're "
        "working toward - keeping what's still true from last time."
    )
    insight = {"type": "object", "properties": {"text": {"type": "string"}, "importance": {"type": "integer"}},
               "required": ["text"]}
    person = {"type": "object", "properties": {"name": {"type": "string"}, "notes": {"type": "string"}},
              "required": ["name", "notes"]}
    system = persona + "\n\nRight now you are asleep and reflecting. Answer only by calling the `report` tool."
    out = await gm.ask(task, {
        "summary": {"type": "string"}, "insights": {"type": "array", "items": insight},
        "people": {"type": "array", "items": person}, "self": {"type": "string"},
    }, ["summary", "self"], "reflect", system=system, max_tokens=REFLECT_MAX_TOKENS) if gm else None
    if not out or not clip(out.get("summary"), 10):
        state.set_meta(reflection_failed_at=str(now))
        state.log("reflection_error", since=since)
        return None
    summary = clip(out["summary"], 700)
    state.add_reflection("day", summary, 5, since, now)
    insights = []
    for i in (out.get("insights") or [])[:MAX_INSIGHTS]:
        text = clip(i.get("text"), 240) if isinstance(i, dict) else ""
        if text:
            try:
                imp = max(1, min(10, int(i.get("importance") or 5)))
            except (TypeError, ValueError):
                imp = 5
            state.add_reflection("insight", text, imp, since, now)
            insights.append({"text": text, "importance": imp})
    updated = []
    allowed = {n.lower(): n for n in names}
    for p in out.get("people") or []:
        name = allowed.get(str(p.get("name", "")).strip().lower()) if isinstance(p, dict) else None
        notes = clip(p.get("notes"), 400) if name else ""
        if notes:
            state.upsert_person(name, notes, now)
            updated.append(name)
    if clip(out.get("self"), 20):
        state.set_meta(self_portrait=clip(out["self"], SELF_PORTRAIT_CHARS))
    state.set_meta(**done, reflection_failed_at="0")
    data = {"summary": summary, "insights": insights, "people": updated, "lines": len(lines)}
    state.log("reflection", **data)
    return data


# --- prompt section -------------------------------------------------------------
def perception(state, now: float | None = None) -> list[str]:
    """The always-present memory section (fixed size however long Pip lives)."""
    lines = []
    portrait = state.meta("self_portrait")
    if portrait:
        lines += ["Who you are (in your own words, from your last night's reflection):", portrait]
    people = state.people()[:5]
    if people:
        lines.append("People you know:")
        lines += [f"- {p['name']} (last seen {ago(p['last_seen'], now)}): {p['notes']}" for p in people]
    days = state.reflections("day", limit=3)
    if days:
        lines.append("Recent days, as you remember them:")
        lines += [f"- {ago(d['period_end'], now)}: {d['text']}" for d in days]
    beliefs = state.reflections("insight", limit=5, by_importance=True)
    if beliefs:
        lines.append("Things you've come to believe:")
        lines += [f"- {b['text']}" for b in beliefs]
    return lines


def format_recall(hits: list[dict], now: float | None = None) -> str:
    labels = {"day": "a day you remember", "insight": "something you came to believe", "person": "what you think of them"}
    out = []
    for h in hits:
        src = h["source"]
        label = labels.get(src) or (src.split(":", 1)[1] if src.startswith("note:") else "")
        out.append(f"- {ago(h['ts'], now)}" + (f" ({label})" if label else "") + f": {clip(h['text'], 260)}")
    return "\n".join(out)
