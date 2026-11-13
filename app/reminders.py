"""What comes to mind: memory step 3 (docs/DESIGN-reminders.md).

Every memory keeps the context it was written in (where Pip was, with whom, doing what, feeling how: State._context_now) and the times it
was used. Its activation is ACT-R's base level over those uses, so a memory fades with time and comes back with use; below a line set by
its importance it is `faded`: it no longer comes to mind by itself, though `recall` still finds it (and that revives it).

Each world turn a cue is built from the situation (who is here or writing, the place, the project, the newest words), memories compete
for two slots on relevance + importance + activation + shared context, and the winners are shown with their frame ("3 days ago, at
Oriel's, while you were visiting, feeling content: ..."). Winners and runners-up are logged (`reminded`), so what was on Pip's mind is a
fact. Being shown is not a use; Pip taking a reminder up (its next turn shares words with it) is. No LLM calls.
"""
import math
import re
import time
from dataclasses import dataclass, field
from datetime import datetime

from . import places
from .memory import STOP_WORDS, ago
from .text import clip

DECAY = 0.5                 # ACT-R's d: activation = ln(sum of (hours since each use) ^ -d)
MIN_HOURS = 0.05            # a use this instant counts as three minutes old (no infinite activation)
FADE_DAYS = 14              # a never-used memory of importance 5 fades after about this long; importance scales it (x0.5 to x2)
REMIND_MIN = 1.0            # the least total score worth bringing to mind
REL_FULL = 4.0              # a BM25 match this strong is fully relevant (live: a common name ~0.2, a rare word ~4-5)
FTS_CANDIDATES = 30
CONTEXT_CANDIDATES = 10
YOUNG_HOURS = 6             # younger memories are still in view
CONTEXT_BONUS = 0.5         # each of: a shared person; the same place or project
RUNNERS_UP = 3
TAKEN_UP_WORDS = 3          # content words a turn must share with a reminder to count as taking it up
FADE_CHECK_SECONDS = 3600
CUE_HOURS = 6               # happenings and gifts this recent are part of the cue
MAX_CUE_CHARS = 1500
VAGUE = set("""about again along back come comes coming came get gets got going gone good great just know like look looks made make
much need new now one really said say says see still sure sit thing things think time today want well went way will yes""".split())  # say nothing about what
LABELS = {"day": "a day you remember", "insight": "something you came to believe", "person": "what you think of them",
          "portrait": "how you described yourself", "change": "something you noticed changing in yourself", "turning": "a day that mattered"}


def activation(uses: list[float], now: float) -> float:
    total = sum(max((now - t) / 3600, MIN_HOURS) ** -DECAY for t in uses)
    return math.log(total) if total > 0 else -math.inf


def fade_line(importance: int) -> float:
    """The activation a memory used once, `FADE_DAYS` (scaled by importance) ago, has: below it, a memory has faded."""
    return math.log((FADE_DAYS * 24 * max(0.5, min(2.0, importance / 5))) ** -DECAY)


def words(text: str) -> list[str]:
    return [w for w in re.findall(r"[a-z0-9]+", str(text).lower()) if len(w) > 2 and w not in STOP_WORDS and w not in VAGUE and w != "pip"]


@dataclass
class Cue:
    people: list[str] = field(default_factory=list)
    place: str | None = None
    project: str | None = None
    words: str = ""

    def context(self) -> list[str]:
        return self.people + [x for x in (self.place, self.project) if x]


def cue(state, inbox: list[dict], now: float, partner: dict | None = None) -> Cue:
    """The situation, as a cue: who is here or writing, where Pip is (away from home), its project, and the newest words."""
    people = [m["sender"] for m in inbox if not m.get("gift") and m.get("sender")]
    text = [m["text"] for m in inbox]
    if partner:
        people.append(partner["name"])
        visit = float(state.meta("arrived_at") or 0)
        said = [e["data"]["text"] for e in state.events(30) if e["kind"] == "companion" and e["data"].get("name") == partner["name"]
                and e["ts"] >= visit]
        text += said[:1]
    place = places.present_at(state)
    place = None if place == places.HOME else place
    project = None
    sess = state.session()
    if sess and sess["kind"] == "module":                       # a module's session: what it's about (a project) and what is being done
        project = sess["about"] or None
        text.append(sess["expect"])
    for e in state.events_since(now - CUE_HOURS * 3600):
        if e["kind"] == "happening":
            text.append(e["data"]["title"])
        elif e["kind"] == "gift":
            text.append(e["data"]["item"])
    return Cue(list(dict.fromkeys(people)), place, project, " ".join(text)[-MAX_CUE_CHARS:])


def in_view(state) -> set[tuple[str, str]]:
    """What the prompt already shows this turn, so it doesn't also come to mind."""
    from . import loop
    keys = {(f"event:{e['kind']}", str(e["id"])) for e in state.events(loop.EVENT_CONTEXT * 2)}
    keys |= {("note:diary", str(m["id"])) for m in state.memories("diary", limit=loop.DIARY_SHOWN)}
    keys |= {("note:learned", str(m["id"])) for m in state.memories("learned", limit=loop.LEARNED_SHOWN)}
    for section in ("todo", "wishlist", "ambitions"):
        keys |= {(f"note:{section}", str(m["id"])) for m in state.memories(section, status="open", limit=loop.LIST_SHOWN)}
    shown = (state.reflections("portrait", limit=1) + state.reflections("day", limit=3)
             + state.reflections("insight", limit=5, by_importance=True, grounded=True) + state.reflections("insight", limit=2, grounded=False)
             + state.reflections("change", limit=2, grounded=True) + state.reflections("turning", limit=2, grounded=True))
    keys |= {(r["kind"], str(r["id"])) for r in shown}
    keys |= {("person", p["name"]) for p in state.people()[:5]}
    return keys


def choose(state, settings, c: Cue, now: float, slots: int, exclude: set) -> tuple[list[dict], list[dict]]:
    """The memories that come to mind (at most `slots`, one per source) and the next few that nearly did."""
    found = {(r["source"], str(r["ref"])): r for r in state.recall_scored(words(c.words), FTS_CANDIDATES)}
    for r in state.memories_about(c.people, c.place, c.project, CONTEXT_CANDIDATES):
        found.setdefault((r["source"], str(r["ref"])), {**r, "score": 0.0})
    cooldown = settings.remind_cooldown_hours * 3600
    scored = []
    for key, r in found.items():
        ctx = state.memory_context(*key)
        if not ctx or ctx["faded"] or key in exclude or ctx["ts"] > now - YOUNG_HOURS * 3600:
            continue
        mine = set(ctx["people"]) | {x for x in (ctx["place"], ctx["project"]) if x}
        if now - ctx["shown_at"] < cooldown and not (set(c.context()) - set(ctx["shown_with"])) & mine:
            continue
        rel = min(1.0, max(0.0, -r["score"]) / REL_FULL)
        bonus = CONTEXT_BONUS * bool(set(c.people) & set(ctx["people"])) \
            + CONTEXT_BONUS * bool((c.place and ctx["place"] == c.place) or (c.project and ctx["project"] == c.project))
        if rel <= 0 and bonus <= 0:
            continue
        act = 1 / (1 + math.exp(-activation(ctx["uses"], now)))
        total = rel + ctx["importance"] / 10 + act + bonus
        scored.append({"source": key[0], "ref": key[1], "text": r["text"], "score": round(total, 3), "ctx": ctx})
    scored.sort(key=lambda m: -m["score"])
    winners, used = [], set()
    for m in scored:
        if len(winners) < slots and m["score"] >= REMIND_MIN and m["source"] not in used:
            winners.append(m)
            used.add(m["source"])
    rest = [m for m in scored if m not in winners][:RUNNERS_UP]
    return winners, rest


def when(ts: float, now: float) -> str:
    if now - ts < 2 * 86400 or now - ts >= 7 * 86400:
        return ago(ts, now)
    return "on " + datetime.fromtimestamp(ts).strftime("%A")


def frame(source: str, text: str, ctx: dict | None, now: float) -> str:
    """A memory with when, where, doing what and how Pip was, each part only if known."""
    ts = ctx["ts"] if ctx else now
    parts = []
    if ctx and ctx["place"] and ctx["place"] != places.HOME:
        parts.append(f"at {places.label(ctx['place'])}")
    if ctx and ctx["activity"] and ctx["activity"] != "idle":
        parts.append(f"while you were {ctx['activity']}")
    if ctx and (ctx["feeling"] or ctx["mood"]):
        parts.append(f"feeling {ctx['feeling'] or ctx['mood']}")
    label = LABELS.get(source) or (source.split(":", 1)[1] if source.startswith("note:") else "")
    return (f"- {when(ts, now)}" + "".join(f", {p}" for p in parts) + (f" ({label})" if label else "")
            + f": {clip(text, 260)}")


def recall_lines(state, hits: list[dict], because: dict, now: float) -> str:
    """`recall`'s answer: each memory framed; a faded one marked as half forgotten. Finding them is a use."""
    out = []
    for h in hits:
        ctx = state.memory_context(h["source"], h["ref"])
        line = frame(h["source"], h["text"], ctx, now) + (" (you had half forgotten this)" if ctx and ctx["faded"] else "")
        if because.get((h["source"], str(h["ref"]))):
            line += "\n    because: " + "; ".join(clip(t, 140) for t in because[(h["source"], str(h["ref"]))])
        out.append(line)
    state.use_memories([(h["source"], h["ref"]) for h in hits], now)
    return "\n".join(out)


def taken_up(state, now: float) -> list[tuple[str, str]]:
    """Reminders Pip took up: its turns since they were shown share at least TAKEN_UP_WORDS content words with them. Those are uses."""
    last = state.meta("reminded_event")
    if not last or state.meta("reminded_checked") == last:
        return []
    after = [e for e in state.events(200, after_id=int(last)) if e["kind"] in ("tool", "tick")]
    if not any(e["kind"] == "tool" for e in after):
        return []                                                       # Pip hasn't acted since: look again next turn
    state.set_meta(reminded_checked=last)
    said = set(words(" ".join(str(e["data"].get("args", "")) + " " + str(e["data"].get("text", "")) for e in after)))
    shown = next((e["data"] for e in state.events(1, before_id=int(last) + 1) if e["kind"] == "reminded"), {})
    keys = [(w["source"], w["ref"]) for w in shown.get("shown", [])
            if len(set(words(state.recall_text_of(w["source"], w["ref"]) or "")) & said) >= TAKEN_UP_WORDS]
    state.use_memories(keys, now)
    return keys


def fade(state, now: float) -> list[tuple[str, str]]:
    """Mark memories whose activation fell below their line as faded, at most once an hour; logged once each."""
    if now - float(state.meta("faded_checked_at") or 0) < FADE_CHECK_SECONDS:
        return []
    state.set_meta(faded_checked_at=str(now))
    gone = [(c["source"], c["ref"]) for c in state.memory_contexts(faded=False)
            if activation(c["uses"], now) < fade_line(c["importance"])]
    if gone:
        state.set_faded(gone)
        state.log("faded", count=len(gone), memories=[f"{s}#{r}" for s, r in gone[:20]])
    return gone


def step(state, settings, c: Cue, now: float, slots: int) -> list[str]:
    """One turn's reminding: count what was taken up, let what is unused fade, choose, log, and the lines to show (if any)."""
    if settings.reminders == "off" or slots <= 0:
        return []
    taken_up(state, now)
    fade(state, now)
    winners, rest = choose(state, settings, c, now, slots, in_view(state))
    if not winners and not rest:
        return []
    brief = lambda m: {"source": m["source"], "ref": m["ref"], "score": m["score"], "text": clip(m["text"], 120)}
    eid = state.log("reminded", shown=[brief(m) for m in winners], nearly=[brief(m) for m in rest], cue=c.context())
    if not winners:
        return []
    state.set_meta(reminded_event=str(eid))
    state.mark_shown([(m["source"], m["ref"]) for m in winners], now, c.context())
    if settings.reminders != "on":
        return []
    return ["This brings to mind:"] + [frame(m["source"], m["text"], m["ctx"], now) for m in winners]
