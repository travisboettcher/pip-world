"""The night pass: after the nightly reflection, the agent's sleeping self may adjust its own goals (DESIGN-nightpass.md).

A second call, once per sleep, in the agent's voice. It decides a few things from a fixed vocabulary about the agent's own to-dos,
wishes, ambitions and plans, and sets a short focus for tomorrow. The engine validates every decision (known ops,
age floors, a cap, cited evidence), applies it reversibly (archive and pause, never delete) and records it so the agent can
`undo_decision`. Facts in, decisions out: the engine never tells the agent what to want.

Plans are whatever live modules publish as `plans` (modules.plans: the crafting module's projects, a world's repairs or expeditions),
cited as `<module>:<id>`; putting one on hold or taking it back up is asking that module (`pause`, `resume`), and undoing it is asking
the opposite (docs/DESIGN-engine-audit.md, B1).
"""
import difflib
import re
import time
from datetime import datetime

from . import memory as mem
from . import modules
from . import places
from . import tools as tools_mod
from .text import clip

SECTIONS = ("todo", "wishlist", "ambitions")
OPS = ("archive_note", "merge_notes", "resolve_note", "pause_plan", "resume_plan", "adopt")
MIN_AGE = {"todo": 24 * 3600, "wishlist": 3 * 86400, "ambitions": 3 * 86400}
EDIT_COOLDOWN = 24 * 3600
MIN_BETWEEN_PASSES = 6 * 3600
MAX_FOCUS = 3
IDLE_PLAN_DAYS = 3
UNUSED_TOOL_DAYS = 7
UNSEEN_PERSON_DAYS = 7
SHOWN_DECISIONS = 3          # ticks a decision is announced for
DECISION_MAX_AGE_HOURS = 24
REF = re.compile(r"^\s*\[?(?:([ein])\s*#?(\d+)|([a-z][a-z0-9-]*):#?(\d+))\]?\s*$", re.I)


def _ref(raw) -> tuple[str, int | str] | None:
    """A cited id: ("e", 12), ("i", 3), ("n", 4), or a plan ("plan", "crafting:2")."""
    m = REF.match(str(raw))
    if not m:
        return None
    return (m.group(1).lower(), int(m.group(2))) if m.group(1) else ("plan", f"{m.group(3).lower()}:{int(m.group(4))}")


# --- the facts the pass is given --------------------------------------------------------------
def _plans(state) -> dict:
    """Every plan live modules publish, by its ref (`crafting:2`)."""
    return {f"{p['module']}:{p['id']}": p for p in modules.plans(state)}


def _going(plans: dict, module: str) -> int:
    return sum(1 for p in plans.values() if p["module"] == module and p["status"] == "active")


def _no_room(plans: dict, p: dict) -> bool:
    """Taking `p` back up would be more than its module lets go at once."""
    return p["limit"] is not None and _going(plans, p["module"]) >= p["limit"]


def facts(state, settings, now: float, tool_names=()) -> dict:
    """Everything the pass sees, as text blocks, plus the set of ids it may cite and refer to."""
    notes, lines = {}, []
    for section in SECTIONS:
        for m in state.memories(section, status="open", limit=40):
            notes[m["id"]] = m
            edited = f", edited {mem.ago(m['edited_at'], now)}" if m["edited_at"] else ""
            lines.append(f"[n{m['id']}] ({section}, written {mem.ago(m['ts'], now)}{edited}) {clip(m['text'], 170)}")
    plans, plines = {}, []
    everything = _plans(state)
    for status in ("active", "paused"):
        for ref, p in ((r, q) for r, q in everything.items() if q["status"] == status):
            plans[ref] = p
            done = f"{p['progress']}% done, " if p["progress"] is not None else ""
            plines.append(f"[{ref}] {p['name']} ({status}): {done}last worked on {mem.ago(p['last_touched'], now)}")
    quiet = []
    for p in (q for q in everything.values() if q["status"] == "active"):
        days = (now - p["last_touched"]) / 86400
        if days >= IDLE_PLAN_DAYS:
            quiet.append(f"you haven't worked on {p['name']} for {round(days)} days")
    for person in state.people():
        days = (now - person["last_seen"]) / 86400
        if days >= UNSEEN_PERSON_DAYS:
            quiet.append(f"you haven't seen {person['name']} for {round(days)} days")
    with state.lock:
        used = {r["t"]: r["ts"] for r in state.db.execute(
            "SELECT json_extract(data, '$.tool') AS t, MAX(ts) AS ts FROM events WHERE kind = 'tool' GROUP BY t")}
    with state.lock:
        visits = {r["key"].removeprefix("place:"): r["last_ts"] for r in state.db.execute(
            "SELECT key, last_ts FROM facets WHERE key LIKE 'place:%'")}
    for place, ts in visits.items():
        if place != places.home_key() and (now - ts) / 86400 >= UNSEEN_PERSON_DAYS:
            quiet.append(f"you haven't been to {place} for {round((now - ts) / 86400)} days")
    for t in sorted(tool_names):
        if t in used and (now - used[t]) / 86400 >= UNUSED_TOOL_DAYS and t not in ("say", "set_activity"):
            quiet.append(f"you haven't used {t} for {round((now - used[t]) / 86400)} days")
    return {"notes": notes, "note_lines": lines, "plans": plans, "plan_lines": plines, "quiet": quiet[:8]}


def review_focus(state, now: float) -> tuple[list[dict], int]:
    """Close last night's focus items that the log shows were kept. Returns (the rest, for the agent to decide on; kept)."""
    left, kept_n = [], 0
    for f in state.focus("open"):
        kept = False
        if f["ref_kind"] == "note" and f["ref_id"]:
            m = state.memory(f["ref_id"])
            kept = bool(m and m["status"] == "done")
        elif f["ref_kind"].startswith("plan:") and f["ref_id"]:
            p = _plans(state).get(f"{f['ref_kind'][5:]}:{f['ref_id']}")
            kept = bool(p and (p["status"] == "done" or p["last_touched"] > f["decided_at"]))
        if kept:
            state.close_focus(f["id"], "kept", "the log shows it moved")
            kept_n += 1
        else:
            left.append(f)
    return left, kept_n


# --- validation -----------------------------------------------------------------------------
def _cites(because, shown: dict, state, notes: dict, plans: dict) -> list[str]:
    out = []
    for raw in because if isinstance(because, list) else []:
        r = _ref(raw)
        if not r:
            continue
        kind, n = r
        ok = (n in shown if kind == "e" else state.reflection_text(n) is not None if kind == "i"
              else n in notes if kind == "n" else n in plans)
        cite = n if kind == "plan" else f"{kind}{n}"
        if ok and cite not in out:
            out.append(cite)
    return out[:6]


def _old_enough(m: dict, now: float) -> str:
    if now - m["ts"] < MIN_AGE[m["section"]]:
        return f"#{m['id']} is too new to let go of"
    if m["edited_at"] and now - m["edited_at"] < EDIT_COOLDOWN:
        return f"#{m['id']} was edited in the last day"
    return ""


def validate(state, settings, raw_ops, f: dict, shown: dict, now: float) -> tuple[list[dict], list[str]]:
    """(accepted ops, reasons others were rejected). Accepted ops carry everything `apply` needs."""
    ok, rejected, adopted = [], [], 0
    notes, plans = f["notes"], dict(f["plans"])
    for raw in (raw_ops if isinstance(raw_ops, list) else []):
        if len(ok) >= settings.max_night_ops:
            rejected.append("more decisions than allowed in a night")
            break
        if not isinstance(raw, dict) or raw.get("op") not in OPS:
            rejected.append(f"unknown decision {raw.get('op') if isinstance(raw, dict) else raw!r}")
            continue
        op, reason = raw["op"], clip(raw.get("reason"), 200)
        cites = _cites(raw.get("because"), shown, state, notes, plans)
        if not cites:
            rejected.append(f"{op}: nothing cited")
            continue

        def reject(why):
            rejected.append(f"{op}: {why}")

        if op in ("archive_note", "resolve_note"):
            n = raw.get("id")
            m = notes.get(n) if isinstance(n, int) else None
            if not m:
                reject(f"no open note {n!r}")
            elif op == "archive_note" and (why := _old_enough(m, now)):
                reject(why)
            elif op == "resolve_note" and len(str(raw.get("outcome") or "").strip()) < 4:
                reject("no outcome given")
            else:
                outcome = clip(raw.get("outcome"), 200)
                ok.append({"op": op, "target_kind": "note", "target_id": n, "args": {"outcome": outcome} if outcome else {},
                           "reason": reason, "cites": cites,
                           "summary": (f"archived your {m['section']} #{n} ({clip(m['text'], 60)})" if op == "archive_note"
                                       else f"crossed off #{n}: {outcome}")})
        elif op == "merge_notes":
            ids = [i for i in dict.fromkeys(raw.get("ids") if isinstance(raw.get("ids"), list) else []) if isinstance(i, int)]
            ms = [notes.get(i) for i in ids]
            text = clip(raw.get("text"), 400)
            if not (2 <= len(ids) <= 4) or not all(ms) or len({m["section"] for m in ms}) != 1 or not text:
                reject("needs 2-4 open notes from one section and the merged text")
            elif why := next((w for w in (_old_enough(m, now) for m in ms) if w), ""):
                reject(why)
            else:
                ok.append({"op": op, "target_kind": "note", "target_id": ids[0], "args": {"ids": ids, "text": text},
                           "reason": reason, "cites": cites,
                           "summary": f"merged your {ms[0]['section']} " + ", ".join(f"#{i}" for i in ids) + f" into #{ids[0]}"})
        elif op in ("pause_plan", "resume_plan"):
            pausing = op == "pause_plan"
            r = _ref(raw.get("plan"))
            p = plans.get(r[1]) if r and r[0] == "plan" else None
            if not p or p["status"] != ("active" if pausing else "paused"):
                reject(f"no such plan {'going' if pausing else 'on hold'} ({raw.get('plan')!r})")
            elif ("pause" if pausing else "resume") not in p["can"]:
                reject(f"{p['module']} can't {'put its plans on hold' if pausing else 'take its plans back up'}")
            elif not pausing and _no_room(plans, p):
                reject(f"as many going as {p['module']} allows")
            else:
                ok.append({"op": op, "target_kind": f"plan:{p['module']}", "target_id": p["id"], "args": {}, "reason": reason,
                           "cites": cites, "summary": f"put {p['name']} on hold" if pausing else f"took {p['name']} off hold"})
                plans[r[1]] = {**p, "status": "paused" if pausing else "active"}     # what the next decision sees
        elif op == "adopt":
            section, text = raw.get("section"), clip(raw.get("text"), 300)
            if adopted or section not in ("todo", "ambitions") or len(text) < 8:
                reject("one new todo or ambition a night, with real text")
            elif tools_mod.stat_number_in(settings, text):
                reject("no stat numbers in notes")
            elif any(difflib.SequenceMatcher(None, text.lower(), m["text"].lower()).ratio() >= tools_mod.SIMILARITY_LIMIT
                     or tools_mod.overlapping(text, m["text"]) for m in notes.values() if m["section"] == section):
                reject("you already have something like it")
            else:
                adopted += 1
                ok.append({"op": op, "target_kind": "note", "target_id": None, "args": {"section": section, "text": text},
                           "reason": reason, "cites": cites, "summary": f"added to your {section}: {text}"})
    return ok, rejected


# --- applying and undoing -----------------------------------------------------------------------
def apply(state, settings, op: dict, applied: bool = True) -> int:
    """Record one validated decision and (unless `applied` is False, i.e. log mode) carry it out."""
    kind, tid, args = op["op"], op["target_id"], op["args"]
    before: dict = {}
    if applied:
        if kind == "archive_note":
            before = {"status": state.memory(tid)["status"]}
            state.set_memory_status(tid, "archived")
        elif kind == "resolve_note":
            m = state.memory(tid)
            before = {"status": m["status"], "outcome": m["outcome"]}
            state.resolve_memory(tid, args.get("outcome", ""))
        elif kind == "merge_notes":
            first, rest = args["ids"][0], args["ids"][1:]
            before = {"first_text": state.memory(first)["text"], "archived": rest}
            state.edit_memory(first, args["text"])
            for i in rest:
                state.set_memory_status(i, "archived")
        elif kind in ("pause_plan", "resume_plan"):                  # the plan's module's to do, on its next step
            before = {"status": "active" if kind == "pause_plan" else "paused"}
            modules.queue_request(state, op["target_kind"][5:], "pause" if kind == "pause_plan" else "resume", {"plan": tid}, by="night pass")
        elif kind == "adopt":
            new_id = state.add_memory(args["text"], args["section"])
            before = {"memory_id": new_id}
            tid = new_id
    return state.add_decision(kind, op["target_kind"], tid, args, before, op["reason"], op["cites"], op["summary"], applied)


def undo(state, settings, decision_id: int) -> str:
    """Take a night decision back. Returns what happened (or why it couldn't)."""
    d = state.decision(decision_id)
    if not d or not d["applied"]:
        return f"no decision #{decision_id} that was carried out"
    if d["undone"]:
        return f"decision #{decision_id} is already undone"
    op, tid, before = d["op"], d["target_id"], d["before"]
    if op in ("archive_note", "resolve_note"):
        state.set_memory_status(tid, before["status"], before.get("outcome", "") if op == "resolve_note" else None)
    elif op == "merge_notes":
        state.edit_memory(tid, before["first_text"])
        for i in before["archived"]:
            state.set_memory_status(i, "open")
    elif op in ("pause_plan", "resume_plan"):
        module, plans = d["target_kind"][5:], _plans(state)
        p = plans.get(f"{module}:{tid}")
        if not p:
            return f"#{decision_id}'s plan is gone"
        if ("resume" if op == "pause_plan" else "pause") not in p["can"]:
            return f"{module} can't {'take its plans back up' if op == 'pause_plan' else 'put its plans on hold'}"
        if op == "pause_plan" and _no_room(plans, p):
            return "you already have as many going as you can; finish or pause one first"
        modules.queue_request(state, module, "resume" if op == "pause_plan" else "pause", {"plan": tid}, by="night pass")
    elif op == "adopt":
        state.set_memory_status(before["memory_id"], "archived")
    state.mark_decision_undone(decision_id)
    state.log("night_undo", decision=decision_id, summary=d["summary"])
    return f"undone: {d['summary']}"


# --- the call ---------------------------------------------------------------------------------
def _schema() -> dict:
    op = {"type": "object", "properties": {
        "op": {"type": "string", "enum": list(OPS)}, "id": {"type": "integer"},
        "ids": {"type": "array", "items": {"type": "integer"}}, "text": {"type": "string"},
        "outcome": {"type": "string"}, "section": {"type": "string", "enum": ["todo", "ambitions"]}, "plan": {"type": "string"},
        "because": {"type": "array", "items": {"type": "string"}}, "reason": {"type": "string"}}, "required": ["op"]}
    focus = {"type": "object", "properties": {"text": {"type": "string"}, "ref": {"type": "string"}}, "required": ["text"]}
    review = {"type": "object", "properties": {"id": {"type": "integer"}, "status": {"type": "string", "enum": ["carried", "dropped"]},
                                              "reason": {"type": "string"}}, "required": ["id", "status"]}
    return {"decisions": {"type": "array", "items": op}, "focus": {"type": "array", "items": focus},
            "review": {"type": "array", "items": review}}


def _task(state, settings, now, reflection: dict, f: dict, leftover: list[dict], recent: list[dict]) -> str:
    parts = ["You have just gone over your day in your sleep. Now, still asleep, you may look after your own plans."]
    parts.append("What you concluded tonight:\n" + reflection["summary"]
                 + "".join(f"\n[i{r['id']}] ({r['kind']}) {r['text']}" for r in recent))
    if f["note_lines"]:
        parts.append("Your open notes:\n" + "\n".join(f["note_lines"]))
    if f["plan_lines"]:
        parts.append("Your plans:\n" + "\n".join(f["plan_lines"]))
    if leftover:
        parts.append("You meant to focus on these, and nothing in the log shows they moved:\n"
                     + "\n".join(f"[f{x['id']}] {x['text']}" for x in leftover))
    if f["quiet"]:
        parts.append("Things you haven't done in a while (just facts):\n" + "\n".join(f"- {q}" for q in f["quiet"]))
    ex = next(iter(f["plans"]), "")                                    # a plan's id as it is cited, from what is shown
    parts.append(
        "You can decide, using only what is above. Most nights you'll change little or nothing - leave `decisions` empty "
        "unless the evidence is there. Allowed decisions: archive_note (id: an old note you've outgrown or that "
        "something else replaced), merge_notes (ids, text: near-duplicates into one), resolve_note (id, outcome: it is "
        f"already done), pause_plan / resume_plan (plan: its id{f', like {ex}' if ex else ''}), adopt (section todo|ambitions, text: one new "
        f"goal that tonight's evidence points to). Every decision needs `because` (ids like e12, i3, n4{f', {ex}' if ex else ''} from above) and a "
        f"one-line `reason`; at most {settings.max_night_ops}. An unmet wish is not a reason to drop it. Nothing is "
        "deleted, and you can undo any of this later.\n"
        f"`focus`: up to {MAX_FOCUS} things you want to give your attention to tomorrow (`text`, and `ref` like n4"
        f"{f' or {ex}' if ex else ''} if it is about a note or plan). `review`: for each [f#] above, say whether you are carrying it on "
        "(`carried`) or letting it go (`dropped`)."
    )
    return "\n\n".join(parts)


async def run(state, settings, gm, persona: str, reflection: dict, shown: dict, tool_names=(),
              now: float | None = None, since_ts: float = 0.0) -> dict | None:
    """Run the night pass after a successful reflection. Returns the logged event data, or None."""
    if settings.night_pass == "off" or not gm:
        return None
    now = now or time.time()
    if now - float(state.meta("night_pass_ts") or 0) < MIN_BETWEEN_PASSES:
        return None
    apply_it = settings.night_pass == "apply"
    f = facts(state, settings, now, tool_names)
    leftover, kept = review_focus(state, now) if apply_it else ([x for x in state.focus("open")], 0)
    if not (f["notes"] or f["plans"] or leftover):
        return None
    recent = [r for kind in ("insight", "change", "turning") for r in state.reflections(kind, limit=6)
              if r["ts"] >= since_ts]
    system = persona + "\n\nRight now you are asleep and deciding about your own plans. Answer only by calling the `report` tool."
    out = await gm.ask(_task(state, settings, now, reflection, f, leftover, recent), _schema(), [],
                       "night_pass", system=system, max_tokens=1500)
    state.set_meta(night_pass_ts=str(now))
    if out is None:
        state.log("night_pass", mode=settings.night_pass, failed=True)
        return None
    ok, rejected = validate(state, settings, out.get("decisions"), f, shown, now)
    if ok and settings.verify_insights:
        items = [{"index": n, "claim": f"{o['summary']}. Reason: {o['reason']}",
                  "evidence": [_evidence(state, c, shown, f) for c in o["cites"]]} for n, o in enumerate(ok)]
        for v in (await gm.verify_insights(items)) or []:
            n = v.get("index")
            if isinstance(n, int) and 0 <= n < len(ok) and v.get("verdict") == "unsupported":
                ok[n]["unsupported"] = True
        rejected += [f"{o['op']}: the cited evidence doesn't show it" for o in ok if o.get("unsupported")]
        ok = [o for o in ok if not o.get("unsupported")]
    ids = [apply(state, settings, o, apply_it) for o in ok]
    dropped = carried = 0
    new_focus = []
    if apply_it:
        decided = {r.get("id"): r for r in (out.get("review") if isinstance(out.get("review"), list) else [])
                   if isinstance(r, dict)}
        for x in leftover:
            r = decided.get(x["id"], {})
            status = "carried" if r.get("status") == "carried" else "dropped"
            state.close_focus(x["id"], status, clip(r.get("reason") or ("not reviewed" if not r else ""), 200))
            carried += status == "carried"
            dropped += status == "dropped"
        day = datetime.fromtimestamp(now).date().isoformat()
        for item in (out.get("focus") if isinstance(out.get("focus"), list) else [])[:MAX_FOCUS]:
            text = clip(item.get("text") if isinstance(item, dict) else item, 160)
            r = _ref(item.get("ref")) if isinstance(item, dict) else None
            ref_kind = "note" if r and r[0] == "n" else f"plan:{r[1].split(':')[0]}" if r and r[0] == "plan" else ""
            ref_id = (r[1] if r[0] == "n" else int(r[1].split(":")[1])) if ref_kind else None
            if text:
                state.add_focus(day, text, ref_kind, ref_id)
                new_focus.append(text)
        total = kept + carried + dropped
        if total:
            today = day
            have = dict(state.day_stats(30)).get(today, {})
            state.save_day_stats(today, {**have, "focus_kept": kept, "focus_total": total})
    data = {"mode": settings.night_pass, "decisions": [o["summary"] for o in ok], "decision_ids": ids,
            "rejected": rejected, "focus": new_focus, "kept": kept, "carried": carried, "dropped": dropped,
            "applied": len(ids) if apply_it else 0}
    state.log("night_pass", **data)
    return data


def _evidence(state, cite: str, shown: dict, f: dict) -> str:
    kind, n = _ref(cite)
    if kind == "e":
        return shown.get(n, "")
    if kind == "i":
        return state.reflection_text(n) or ""
    if kind == "n":
        return (f["notes"].get(n) or {}).get("text", "")
    p = f["plans"].get(n)
    return f"{p['name']}: {p['about']}" if p else ""


# --- what the agent sees ---------------------------------------------------------------------------
def perception(state, settings) -> list[str]:
    lines = []
    new = state.unseen_decisions(DECISION_MAX_AGE_HOURS, SHOWN_DECISIONS)
    if new:
        state.mark_decisions_shown([d["id"] for d in new])
        lines.append("While you slept you decided (undo_decision takes any of it back):")
        lines += [f"- #{d['id']}: {d['summary']}" + (f" - {d['reason']}" if d["reason"] else "") for d in new]
    focus = state.focus("open", limit=MAX_FOCUS)
    if focus:
        lines.append("Your focus today (you chose it in your sleep):")
        lines += [f"- {x['text']}" for x in focus]
    return lines
