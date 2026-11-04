"""Long-term memory: nightly reflection (consolidation) and recall (retrieval). See DESIGN-memory.md.

Pip reflects in its own voice (its persona is the system prompt): once a day it turns everything since the last
reflection into a day summary, a few insights with importance, notes on the people involved, and a fresh
self-portrait. Those go into every prompt at a fixed size. Everything worth remembering is also indexed for the
`recall` tool (SQLite FTS5, BM25 ranking).
"""
import re
import time
from datetime import datetime

from . import capabilities as caps
from . import turning
from .text import clip

RECALL_EVENT_KINDS = ("inbox", "say", "gift", "work", "experiment", "creation_made", "companion", "letter_sent", "reading", "gathered", "outreach", "world_changed", "made_work", "revised_work", "heard_of_place", "happening")
MAX_INSIGHTS = 5
SELF_PORTRAIT_CHARS = 900
REFLECT_MAX_TOKENS = 2048
RETRY_AFTER = 3600
LEGACY_GIFT = re.compile(r"^.{1,40} gave you \d+ x ")  # gifts logged before inbox events were flagged
STOP_WORDS = set("""a an and are as at be but by did do does for from had has have how i if in into is it its me my
of on or so that the their them then there these they this to was we were what when where which who why will with
you your about did any can could would should just""".split())


def recall_text(kind: str, d: dict) -> str | None:
    """The searchable text for an event, or None if it isn't worth remembering on its own."""
    if kind == "inbox" and d.get("letter"):
        return d["text"]  # "A letter from X: ..."
    if kind == "reading":
        return f"You read {d['title']}: {d['summary']}" + "".join(f' "{q}"' for q in d.get("quotes", []))
    if kind == "letter_sent":
        return f"You wrote to {d['to']}: {d['text']}" + (f" (enclosed: {d['enclosed']})" if d.get("enclosed") else "")
    if kind == "inbox":
        if d.get("gift") or LEGACY_GIFT.match(d["text"]):  # a gift has its own `gift` event
            return None
        return f"{d.get('sender') or 'A visitor'} said to you: {d['text']}"
    if kind == "say":
        return f"You said to {d['to_name']}: {d['text']}" if d.get("to_name") else f"You said: {d['text']}"
    if kind == "gift":
        return f"{d['sender']} gave you {d['qty']} x {d['item']}"
    if kind == "work":
        return None if d.get("interrupted") else (
            f"Working on {d['project']} ({d['stage']}), {d['result']}: {d['text']}"
            + (f" You learned: {d['learned']}" if d.get("learned") else "")
            + (f" ({d['expectation']})" if d.get("expectation") else ""))
    if kind == "experiment":
        return None if d.get("interrupted") else (
            f"Experiment on {d['project']} ({d['hypothesis']}): {d['text']}"
            + (f" You learned: {d['finding']}" if d.get("finding") else "")
            + (f" ({d['expectation']})" if d.get("expectation") else ""))
    if kind == "world_changed":
        return d["text"]
    if kind == "happening":
        return f"Something happened: {d['title']}. {d['text']} {d.get('effects', '')}".rstrip()
    if kind == "revised_work":
        return f"You looked at your drawing '{d['title']}' and redrew it"
    if kind == "made_work":
        return (f"You drew '{d['title']}'" + (f": {d['caption']}" if d.get("caption") else "") if d.get("what") == "drawing"
                else f"You wrote '{d['title']}': {d.get('text', '')}")
    if kind == "outreach":
        if not d.get("delivered"):
            return None
        return (f"You sent a postcard to a friend outside: {d['text']}" if d.get("what") == "postcard"
                else f"You answered a friend outside: {d['text']}")
    if kind == "gathered":
        return None if d.get("interrupted") and not d.get("items") else d["text"]
    if kind == "creation_made":
        return f"You finished making {d['name']}: {d['description']}"
    if kind == "companion":
        return f"{d['name']} said: {d['text']}"
    if kind == "heard_of_place":
        return f"{d['by']} told you about {d['place']}" + (f": {d['there']}" if d["there"] else "")
    return None


def event_importance(kind: str, d: dict, firsts=()) -> int:
    """How much an event matters for what survives a long day's reflection (1-10; 0 = not worth keeping).
    Deterministic, no LLM: visitors and finished things weigh most, routine tool use least; a first adds weight."""
    if kind == "tick":
        return 0
    r = d.get("result") or d.get("outcome")
    if kind == "inbox":
        base = 6
    elif kind == "gift":
        base = 5
    elif kind in ("letter_sent", "companion"):
        base = 4 if kind == "letter_sent" else 3
    elif kind == "work":
        base = 7 if d.get("project_done") else 5 if r in ("blowup", "breakthrough") else 4 if r == "setback" else 2
    elif kind == "experiment":
        base = 6 if r == "surprise" else 5 if r == "insight" else 2
    elif kind == "creation_made":
        base = 7
    elif kind == "reading":
        base = 4 if d.get("finished") else 2
    elif kind in ("woke", "alert"):
        base = 3
    elif kind == "world_changed":
        base = 6
    elif kind in ("made_work", "revised_work"):
        base = 5
    elif kind == "happening":
        base = {"minor": 3, "medium": 5, "major": 7}.get(d.get("severity"), 3)
    elif kind == "happening_felt":
        base = 2
    elif kind == "outreach":
        base = 5 if d.get("what") == "postcard" else 3
    elif kind == "reflection":
        base = 2
    elif kind == "say":
        base = 3
    elif kind == "tool":
        base = {"note_to_self": 3 if (d.get("args") or {}).get("section") == "diary" else 2, "resolve_note": 3,
                "start_project": 3, "write_letter": 4, "sleep": 3}.get(d.get("tool"), 1)
    else:
        base = 1
    bonus = max((3 if f.get("tier") == "major" else 1 for f in firsts), default=0)
    return max(1, min(10, base + bonus))


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


def compute_day_stats(state, since: float, until: float) -> dict:
    """Plain counts of what Pip did in a stretch of time - facts to compare days by, not judgments."""
    c = {k: 0 for k, _ in STAT_LABELS}
    for e in state.events_since(since, limit=5000):
        if e["ts"] > until:
            break
        k, d = e["kind"], e["data"]
        if k == "work" and not d.get("interrupted"):
            c["work_sessions"] += 1
            c["minutes_worked"] += d.get("minutes") or 0
            c["with_approach"] += 1 if d.get("approach") else 0
            c["setbacks"] += d.get("result") == "setback"
            c["blowups"] += d.get("result") == "blowup"
            c["breakthroughs"] += d.get("result") == "breakthrough"
            c["projects_finished"] += bool(d.get("project_done"))
            c["predictions"] += bool(d.get("expected"))
            c["surprises"] += bool(d.get("surprise"))
        elif k == "experiment" and not d.get("interrupted"):
            c["experiments"] += 1
            c["predictions"] += bool(d.get("expected"))
            c["surprises"] += bool(d.get("surprise"))
        elif k == "inbox" and not d.get("letter") and not d.get("gift"):
            c["visitor_messages"] += 1
            c["messages_from_outside"] += d.get("source", "web") != "web"
        elif k == "letter_sent":
            c["letters_sent"] += 1
        elif k == "made_work":
            c["pictures_drawn"] += d.get("what") == "drawing"
            c["pieces_written"] += d.get("what") == "writing"
        elif k == "outreach" and d.get("what") == "postcard" and d.get("delivered"):
            c["postcards_sent"] += 1
        elif k == "woke":
            c["hours_slept"] += d.get("hours") or 0
        elif k == "tool_error" or (k == "tool" and str(d.get("result", "")).startswith("error")):
            c["tool_errors"] += 1
        elif k == "tool" and d.get("tool") == "note_to_self" and str(d.get("result", "")).startswith("wrote"):
            c["notes_written"] += 1
    return {k: round(v, 1) if isinstance(v, float) else int(v) for k, v in c.items()}


def format_stats(rows: list[tuple[str, dict]]) -> str:
    return "\n".join(f"- {day}: " + ", ".join(f"{s[k]} {label}" for k, label in STAT_LABELS if s.get(k))
                     for day, s in rows if any(s.values())) 


# --- reflection ---------------------------------------------------------------
def material(state, since: float, until: float, max_chars: int) -> tuple[list[str], set[str], dict[int, str]]:
    """One line per notable event in (since, until], each tagged with its id so reflections can cite it. Over budget
    the most important events are kept (newest breaking ties), shown in time order. Also: who appeared, and
    {event id: text} for what was shown."""
    cands, people = [], set()
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
            firsts = "; ".join(f["label"] for f in d.get("firsts", []))
            body = clip(text, 300) + (f" (first: {firsts})" if firsts else "")
            line = f"[e{e['id']} {datetime.fromtimestamp(e['ts']).strftime('%a %H:%M')}] {body}"
            cands.append((e["importance"] or 1, e["id"], line, clip(text, 300)))
    total, keep = 0, []
    for imp, eid, line, text in sorted(cands, key=lambda c: (c[0], c[1]), reverse=True):
        total += len(line) + 1
        if total > max_chars:
            break
        keep.append((eid, line, text))
    keep.sort()
    return [l for _, l, _ in keep], people, {eid: t for eid, _, t in keep}


def due(state, settings, now: float) -> bool:
    failed = float(state.meta("reflection_failed_at") or 0)
    if now - failed < RETRY_AFTER:
        return False
    if settings.sleep:
        if state.agent()["activity"] == "sleeping":  # Pip reflects as it sleeps: once per sleep
            return state.meta("reflected_sleep") != state.meta("sleep_started")
        # fallback if Pip hasn't slept for a long while: the old fixed hour
        if now - float(state.meta("last_reflection_ts") or 0) < 30 * 3600:
            return False
    local = datetime.fromtimestamp(now)
    return local.hour >= settings.reflect_hour and state.meta("last_reflection_day") != local.date().isoformat()


async def reflect(state, settings, gm, persona: str, now: float | None = None,
                  shown_out: dict | None = None) -> dict | None:
    """Reflect on everything since the last reflection. Returns the logged event data, or None."""
    now = now or time.time()
    since = float(state.meta("last_reflection_ts") or 0)
    lines, appeared, shown = material(state, since, now, settings.reflect_max_chars)
    done = {"last_reflection_ts": str(now), "last_reflection_day": datetime.fromtimestamp(now).date().isoformat()}
    if state.agent()["activity"] == "sleeping":
        done["reflected_sleep"] = state.meta("sleep_started")
    if not lines:
        state.set_meta(**done)  # a quiet day: nothing to go over
        return None
    stats = compute_day_stats(state, since, now)
    today = datetime.fromtimestamp(now).date().isoformat()
    state.save_day_stats(today, stats)
    crafts, ability_of = state.capability_context()
    snapshot = caps.collect([e for e in state.events_since(0, limit=10**6) if e["ts"] <= now], crafts, ability_of)
    before = next((snap for day, snap in state.capability_snapshots(2) if day != today), None)
    state.save_capabilities(today, snapshot)
    can_do = caps.format_snapshot(snapshot, before)
    candidate = turning.detect(state, since, now, stats, today, STAT_LABELS)
    if candidate["flagged"]:
        state.add_turning(candidate["score"], candidate["signals"], since, now)
        for sg in candidate["signals"]:  # evidence Pip can cite even if the budget cut the line from the material
            for ev in sg["events"]:
                shown.setdefault(ev, clip(state.event_text(ev) or sg["text"], 300))
    firsts = state.firsts_between(since, now)
    surprises = [x for x in reversed(state.expectations(limit=20, since=since, surprising=True)) if x["event_id"] in shown]
    portraits = list(reversed(state.reflections("portrait", limit=PORTRAITS_SHOWN)))
    earlier = state.reflections("insight", limit=EARLIER_BELIEFS, by_importance=True)
    earlier_text = {r["id"]: r["text"] for r in earlier}
    known = {p["name"]: p for p in state.people()}
    names = sorted(appeared | set(known))
    task = (
        "You are asleep, going over what has happened since you last slept, the way a mind does at night. "
        "This is private: nobody else will read it.\n\n"
        + (("How you have described yourself before (oldest first):\n"
            + "\n".join(f"[{datetime.fromtimestamp(p['period_end']).strftime('%b %d')}] {p['text']}" for p in portraits)
            + "\n\n") if portraits else "You haven't described yourself before.\n\n")
        + (f"Your recent days in plain counts (not judgments):\n{numbers}\n\n" if (numbers := format_stats(state.day_stats(4))) else "")
        + ("What you thought of people so far:\n" + "\n".join(f"- {n}: {p['notes']}" for n, p in known.items()) + "\n\n"
           if known else "")
        + (("What you have actually been able to do, counted from outcomes (not judgments):\n" + can_do + "\n\n")
           if can_do else "")
        + (("Things that changed more than usual (facts, not verdicts):\n"
            + "\n".join("- " + (f"[e{sg['events'][0]}] " if sg["events"] else "") + sg["text"]
                         for sg in candidate["signals"]) + "\n\n") if candidate["flagged"] else "")
        + (("Things that did not go as you expected (cite their ids):\n"
            + "\n".join(f"- [e{x['event_id']}] {x['subject']}: you expected {x['expected']}; {x['actual']}"
                         if x["kind"] != "step" else f"- [e{x['event_id']}] {x['subject']}: you guessed {x['expected']}; "
                         f"it took {x['actual']}" for x in surprises) + "\n\n") if surprises else "")
        + (("Things that happened for the first time since you last slept:\n"
            + "\n".join(f"- {f['label']}" for f in firsts) + "\n\n") if firsts else "")
        + ("What you already believed (cite as i<number> if a new insight builds on or revises one):\n"
           + "\n".join(f"[i{r['id']}] {r['text']}" for r in earlier) + "\n\n" if earlier else "")
        + "What happened (oldest first; each line starts with its id):\n" + "\n".join(lines) + "\n\n"
        "Report, all in your own first-person voice:\n"
        "- `summary`: 2-4 sentences: this stretch of time as you'll remember it - what mattered and how it felt, "
        "not a list.\n"
        f"- `insights`: up to {MAX_INSIGHTS} things you've come to understand or believe - about yourself, your work, "
        "the world or others - each with `importance` 1-10 (10 = will shape you for a long time) and `because`: "
        "the ids (like e123 or i7) of the lines above it rests on. Only cite what truly shows it; an insight you "
        "can't point to anything for is only a hunch (leave `because` empty). Only real ones; none is fine, and "
        "so is a quiet day. Don't repeat what you already believed unless it changed.\n"
        "- `people`: for each person who mattered here, `name` and `notes` (1-3 sentences: who they are to you "
        f"now). Only these names: {', '.join(names) if names else '(nobody came by)'}.\n"
        "- `wishes`: at most two things you found yourself wishing for since you last slept - something you'd like to do, something you wish you could do "
        "but can't (say what stops you), or something you wish you understood. Each has `kind` (activity, ability or idea) and `text` (one sentence). "
        "None is fine.\n"
        "- `self`: describe yourself afresh in under 120 words - who you are, what you care about, what you're "
        "working toward - keeping what's still true from before. Describe what you can do from the counts above, "
        "not from what you'd like to be true.\n"
        "- `changed`: only if you see yourself differently than in the earlier descriptions - what you do, care "
        "about or believe differently now. Each has `text`, `importance`, and `because` (ids of the lines or "
        "beliefs, as above; the counts above are fair evidence too - name them in `text`). Leave it empty if "
        "you're much the same; most nights you are.\n"
        "- `turning_points`: at most one, and only if this stretch genuinely changed something for you - what "
        "changed, in your words (`text`, `importance`, `because` as above). Most days are not turning points; "
        "leave it empty."
    )
    insight = {"type": "object", "properties": {"text": {"type": "string"}, "importance": {"type": "integer"},
                                                "because": {"type": "array", "items": {"type": "string"}}},
               "required": ["text"]}
    person = {"type": "object", "properties": {"name": {"type": "string"}, "notes": {"type": "string"}},
              "required": ["name", "notes"]}
    system = persona + "\n\nRight now you are asleep and reflecting. Answer only by calling the `report` tool."
    out = await gm.ask(task, {
        "summary": {"type": "string"}, "insights": {"type": "array", "items": insight},
        "people": {"type": "array", "items": person}, "self": {"type": "string"},
        "wishes": {"type": "array", "items": {"type": "object", "properties": {"kind": {"type": "string"}, "text": {"type": "string"}}, "required": ["kind", "text"]}},
        "changed": {"type": "array", "items": insight}, "turning_points": {"type": "array", "items": insight},
    }, ["summary", "self"], "reflect", system=system, max_tokens=REFLECT_MAX_TOKENS) if gm else None
    if not out or not clip(out.get("summary"), 10):
        state.set_meta(reflection_failed_at=str(now))
        state.log("reflection_error", since=since)
        return None
    summary = clip(out["summary"], 700)
    state.add_reflection("day", summary, 5, since, now)
    from . import wishes  # wishes needs the state module, which needs this one
    wishes.add_reflected(state, out.get("wishes"), now)
    insights = await cited_insights(state, settings, gm, out.get("insights"), shown, earlier_text, since, now)
    changes = await cited_insights(state, settings, gm, out.get("changed"), shown, earlier_text, since, now,
                                   kind="change", limit=MAX_CHANGES)
    turns = await cited_insights(state, settings, gm, out.get("turning_points"), shown, earlier_text, since, now,
                                 kind="turning", limit=1)
    updated = []
    allowed = {n.lower(): n for n in names}
    for p in out.get("people") or []:
        name = allowed.get(str(p.get("name", "")).strip().lower()) if isinstance(p, dict) else None
        notes = clip(p.get("notes"), 400) if name else ""
        if notes:
            state.upsert_person(name, notes, now)
            updated.append(name)
    if clip(out.get("self"), 20):
        portrait = clip(out["self"], SELF_PORTRAIT_CHARS)
        state.set_meta(self_portrait=portrait)
        state.add_reflection("portrait", portrait, 5, since, now, support="n/a")  # append-only: every version is kept
    state.set_meta(**done, reflection_failed_at="0")
    data = {"summary": summary, "insights": insights, "changes": changes, "turning": turns, "candidate": candidate if candidate["flagged"] else None,
            "people": updated, "lines": len(lines),
            "stats": stats}
    if shown_out is not None:
        shown_out.update(shown)  # so the night pass can cite the same lines
    state.log("reflection", **data)
    return data


STAT_LABELS = [("work_sessions", "work sessions"), ("minutes_worked", "minutes worked"),
               ("with_approach", "sessions where you described your approach"), ("setbacks", "setbacks"),
               ("blowups", "tries that blew up"), ("breakthroughs", "breakthroughs"), ("experiments", "experiments"),
               ("projects_finished", "projects finished"), ("visitor_messages", "messages from visitors"),
               ("notes_written", "journal entries"), ("letters_sent", "letters sent"), ("hours_slept", "hours slept"),
               ("tool_errors", "tool errors"),
               ("predictions", "predictions made"), ("surprises", "surprises"),
               ("focus_kept", "focus items kept"), ("focus_total", "focus items reviewed"),
               ("postcards_sent", "postcards sent"), ("messages_from_outside", "messages from outside"),
               ("pictures_drawn", "pictures drawn"), ("pieces_written", "pieces written")]
EARLIER_BELIEFS = 8
HUNCHES_SHOWN = 2
PORTRAITS_SHOWN = 3
MAX_CHANGES = 2
CHANGES_SHOWN = 2
TURNING_SHOWN = 2
MAX_CITES = 6
CITE = re.compile(r"^\s*\[?([ei])\s*#?(\d+)\]?\s*$", re.I)


def valid_cites(because, shown: dict, earlier: dict) -> list[tuple[str, int]]:
    """Keep only citations that point at something Pip was actually shown tonight."""
    out = []
    for ref in because if isinstance(because, list) else []:
        m = CITE.match(str(ref))
        if not m:
            continue
        kind, n = ("event" if m.group(1).lower() == "e" else "reflection"), int(m.group(2))
        if (n in shown if kind == "event" else n in earlier) and (kind, n) not in out:
            out.append((kind, n))
    return out[:MAX_CITES]


async def cited_insights(state, settings, gm, raw, shown: dict, earlier: dict, since: float, now: float,
                         kind: str = "insight", limit: int = MAX_INSIGHTS) -> list[dict]:
    """Store a night's insights with the evidence they cite. Uncited ones are hunches; the optional support check
    (one small GM call) demotes claims the cited lines don't show. Nothing is rewritten: history is append-only."""
    items = []
    for i in (raw if isinstance(raw, list) else [])[:limit]:
        text = clip(i.get("text"), 240) if isinstance(i, dict) else ""
        if not text:
            continue
        try:
            imp = max(1, min(10, int(i.get("importance") or 5)))
        except (TypeError, ValueError):
            imp = 5
        cites = valid_cites(i.get("because"), shown, earlier)
        items.append({"text": text, "importance": imp, "cites": cites,
                      "support": "unchecked" if cites else "none", "grounded": bool(cites)})
    if settings.verify_insights and gm and any(it["cites"] for it in items):
        asked = [{"index": n, "claim": it["text"],
                  "evidence": [shown[i] if k == "event" else earlier[i] for k, i in it["cites"]]}
                 for n, it in enumerate(items) if it["cites"]]
        for v in (await gm.verify_insights(asked)) or []:
            n = v.get("index")
            if isinstance(n, int) and 0 <= n < len(items) and items[n]["cites"] and v.get("verdict") in (
                    "supported", "partly", "unsupported"):
                items[n]["support"] = v["verdict"]
                if v["verdict"] == "unsupported":  # the lines it cites don't show it: keep it, but as a hunch
                    items[n].update(grounded=False, importance=min(items[n]["importance"], 3))
    for it in items:
        state.add_reflection(kind, it["text"], it["importance"], since, now, grounded=it["grounded"],
                             support=it["support"], cites=it["cites"])
    return [{"text": it["text"], "importance": it["importance"], "grounded": it["grounded"],
             "support": it["support"], "cited": len(it["cites"])} for it in items]


# --- prompt section -------------------------------------------------------------
def perception(state, now: float | None = None) -> list[str]:
    """The always-present memory section (fixed size however long Pip lives)."""
    lines = []
    portrait = state.meta("self_portrait")
    if portrait:
        lines += ["Who you are (in your own words, from your last night's reflection):", portrait]
    changed = state.reflections("change", limit=CHANGES_SHOWN, grounded=True)
    if changed:
        lines.append("How you've changed:")
        lines += [f"- {c['text']}" for c in changed]
    mattered = state.reflections("turning", limit=TURNING_SHOWN, grounded=True)
    if mattered:
        lines.append("Days that mattered to you:")
        lines += [f"- {ago(t['period_end'], now)}: {t['text']}" for t in mattered]
    people = state.people()[:5]
    if people:
        lines.append("People you know:")
        lines += [f"- {p['name']} (last seen {ago(p['last_seen'], now)}): {p['notes']}" for p in people]
    days = state.reflections("day", limit=3)
    if days:
        lines.append("Recent days, as you remember them:")
        lines += [f"- {ago(d['period_end'], now)}: {d['text']}" for d in days]
    beliefs = state.reflections("insight", limit=5, by_importance=True, grounded=True)
    if beliefs:
        lines.append("Things you've come to believe:")
        lines += [f"- {b['text']}" for b in beliefs]
    hunches = state.reflections("insight", limit=HUNCHES_SHOWN, grounded=False)
    if hunches:
        lines.append("Hunches (nothing you can point to yet):")
        lines += [f"- {h['text']}" for h in hunches]
    return lines


def format_recall(hits: list[dict], now: float | None = None, because: dict | None = None) -> str:
    labels = {"day": "a day you remember", "insight": "something you came to believe", "person": "what you think of them",
              "portrait": "how you described yourself", "change": "something you noticed changing in yourself", "turning": "a day that mattered"}
    out = []
    for h in hits:
        src = h["source"]
        label = labels.get(src) or (src.split(":", 1)[1] if src.startswith("note:") else "")
        line = f"- {ago(h['ts'], now)}" + (f" ({label})" if label else "") + f": {clip(h['text'], 260)}"
        if because and because.get((src, str(h.get("ref")))):
            line += "\n    because: " + "; ".join(clip(t, 140) for t in because[(src, str(h["ref"]))])
        out.append(line)
    return "\n".join(out)
