"""The neighbor: a GM-invented character who lives nearby and exchanges slow letters with Pip.

Letters take hours each way. The neighbor answers what Pip sends, writes first now and then, may tuck in a small
parcel (capped per day), and has a little life of their own that moves on between letters. Letters for Pip arrive
in the inbox with the neighbor as sender, so perception, diary moments, recall and reflection treat them like any
other visit. See DESIGN-neighbor.md.
"""
import math
import random
import time

from . import places
from .companions import conversation as talk_lines
from .memory import ago
from .text import brief, clip
from .world import KINDS

PIP = "Pip"
JITTER = (0.7, 1.3)
LIFE_KEPT = 5
CORRESPONDENCE_SHOWN = 6
TOLD_KEPT = 30
TOLD_PER_CALL = 3
UPCOMING_KEPT = 3
OVERDUE_GRACE = 3 * 86400  # a plan never brought up this long after it was due has quietly happened
MAX_ATTEMPTS = 3
RETRY_AFTER = 3600
DAY = 86400
PARCEL_KINDS = tuple(k for k in KINDS if k in ("material", "seed", "food", "tool"))


def _delay(settings, rng: random.Random) -> float:
    return settings.letter_delay_minutes * 60 * rng.uniform(*JITTER)


def correspondence(state, name: str) -> list[str]:
    out = []
    for lt in state.letters(between=name, limit=CORRESPONDENCE_SHOWN):
        if lt["delivered_at"] is None and lt["sender"] == name:
            continue  # their own letter still on the way isn't part of what's been said yet
        if lt["sender"] == PIP:
            out.append(f"Pip: {lt['text']}" + (f" [enclosed: {lt['enclosed']}]" if lt["enclosed"] else ""))
        else:  # their own words in brief: a model copies vivid phrasing it can see (DESIGN-neighbor-memory.md)
            out.append(f"{name} (in brief): {brief(lt['gist'], lt['text'])}")
    return out


def _told(ch: dict, out: dict) -> dict:
    """Things about themselves the neighbor just told Pip for the first time, added to what Pip already knows."""
    raw = out.get("told")
    new = [t for t in (clip(x, 80) for x in (raw if isinstance(raw, list) else [])) if t][:TOLD_PER_CALL]
    return {"told": (ch["told"] + new)[-TOLD_KEPT:]} if new else {}


def clean_upcoming(raw, now: float) -> dict | None:
    """A model-written plan made safe: a few words, due in 1-14 days."""
    what = clip(raw.get("what"), 100).strip(" .") if isinstance(raw, dict) else ""
    try:
        return {"what": what, "due_at": now + max(1, min(14, int(raw["in_days"]))) * DAY} if what else None
    except (KeyError, TypeError, ValueError):
        return None


def _when(due_at: float, now: float) -> str:
    days = math.ceil((due_at - now) / DAY)
    return "today or this week" if due_at <= now else f"in {days} day" + ("s" if days != 1 else "")


def agenda(ch: dict, now: float) -> list[str]:
    """The neighbor's plans as they'd see them: due ones happen now, the rest are coming up."""
    return [f"{_when(u['due_at'], now)}: {u['what']}" for u in ch["upcoming"]]


def _happened(ch: dict, now: float, grace: float = 0) -> dict:
    """Plans that have come due (or, with `grace`, are long overdue) move into the neighbor's life."""
    done = [u for u in ch["upcoming"] if u["due_at"] + grace <= now]
    return {"life": (ch["life"] + [f"Recently: {u['what']}." for u in done])[-LIFE_KEPT:],
            "upcoming": [u for u in ch["upcoming"] if u not in done]} if done else {}


def clean_parcel(raw) -> dict | None:
    """A model-written parcel made safe: a known kind, a short name, 1-3 of it."""
    if not isinstance(raw, dict):
        return None
    name = clip(raw.get("name"), 40).strip(" .")
    if not name or raw.get("kind") not in PARCEL_KINDS:
        return None
    try:
        qty = max(1, min(3, int(raw.get("qty") or 1)))
    except (TypeError, ValueError):
        qty = 1
    return {"name": name, "kind": raw["kind"], "qty": qty, "description": clip(raw.get("description"), 160)}


async def ensure_neighbor(state, settings, gm, rng: random.Random, now: float | None = None) -> dict | None:
    """Invent the neighbor once (their first letter follows shortly). Retries hourly if the GM fails."""
    now = now or time.time()
    existing = state.characters("neighbor")
    if existing or not settings.neighbor or now < float(state.meta("neighbor_retry_at") or 0):
        return existing[0] if existing else None
    world = "Pip lives in its home, a workshop with a small garden"
    made = [c["name"] for c in state.creations()]
    if made:
        world += f"; it has made {', '.join(made[:5])}"
    raw = await gm.invent_neighbor(world) if gm else None
    name = clip(raw.get("name"), 40) if raw else ""
    if not raw or not name or not clip(raw.get("letter"), 10) or name.lower() == PIP.lower():
        state.set_meta(neighbor_retry_at=str(now + RETRY_AFTER))
        return None
    every = settings.neighbor_writes_every_hours * 60
    ch = state.add_character(name, "neighbor", None, clip(raw["persona"], 800), every,
                             now + every * 60 * rng.uniform(*JITTER), about=clip(raw.get("about"), 160))
    state.add_letter(name, PIP, clip(raw["letter"], 1200), now + _delay(settings, rng) / 4)  # the first comes soon
    state.log("neighbor", name=name, about=ch["about"])
    return ch


async def recall_told(state, gm, tries: dict) -> None:
    """One-time backfill: a neighbor who knows nothing of what they've told Pip has it recalled from everything said
    so far. Done for good once it succeeds; after two failures it waits for the next start (`tries` lives that long)."""
    for ch in state.characters("neighbor") if gm else []:
        done = f"told_recalled:{ch['id']}"
        if ch["told"] or state.meta(done) or tries.get(ch["id"], 0) >= 2:
            continue
        said = [f"{PIP if lt['sender'] == PIP else ch['name']}: {lt['text']}"
                for lt in state.letters(between=ch["name"], limit=50)
                if lt["delivered_at"] is not None or lt["sender"] == PIP] + talk_lines(state, ch["name"])
        if not said:
            continue  # nothing yet (a neighbor just invented): their first letter is recalled once it arrives
        got = await gm.recall_told(ch["name"], ch["persona"], said)
        if got is None:
            tries[ch["id"]] = tries.get(ch["id"], 0) + 1
            continue
        state.update_character(ch["id"], told=[t for t in (clip(x, 80) for x in got) if t][:TOLD_KEPT])
        state.set_meta(**{done: "1"})


def _deliver_to_pip(state, lt: dict, now: float) -> None:
    text = f"A letter from {lt['sender']}: {lt['text']}"
    p = lt["parcel"]
    if p:
        item = state.add_item(p["name"], p["qty"], p["kind"], p["description"] or f"from {lt['sender']}")
        text += f" (Enclosed: {p['qty']} x {item['name']} ({item['kind']}).)"
        state.log("gift", sender=lt["sender"], item=item["name"], qty=p["qty"], item_kind=item["kind"], letter=lt["id"])
    inbox_id = state.add_inbox(text, lt["sender"], gift=True)  # text names the sender itself
    state.log("inbox", id=inbox_id, text=text, sender=lt["sender"], letter=True, gift=bool(p))
    state.update_letter(lt["id"], delivered_at=now)


async def _write(state, settings, gm, rng, ch: dict, now: float, answering: dict | None) -> bool:
    """The neighbor writes a letter (an answer, or out of the blue). Returns False if the GM failed."""
    parcel_ok = state.letters_since_parcel(now - DAY) < settings.parcels_per_day
    out = await gm.neighbor_letter(ch["name"], ch["persona"], ch["life"], correspondence(state, ch["name"]),
                                   answering["text"] if answering else None,
                                   answering["enclosed"] if answering else "", parcel_ok, told=ch["told"],
                                   agenda=agenda(ch, now)) if gm else None
    text = clip(out.get("text"), 1200) if out else ""
    if not text:
        return False
    parcel = clean_parcel(out.get("parcel")) if parcel_ok else None
    state.add_letter(ch["name"], PIP, text, now + _delay(settings, rng), parcel=parcel,
                     reply_to=answering["id"] if answering else None, gist=clip(out.get("gist"), 200))
    fields = {"next_chatter_at": now + ch["chatter_minutes"] * 60 * rng.uniform(*JITTER), **_told(ch, out),
              **_happened(ch, now)}
    if clip(out.get("life_update"), 5) and out.get("life_update_new") is True:  # the model's own "is this news?"
        fields["life"] = (fields.get("life", ch["life"]) + [clip(out["life_update"], 200)])[-LIFE_KEPT:]
    pending, plan = fields.get("upcoming", ch["upcoming"]), clean_upcoming(out.get("upcoming"), now)
    if plan and len(pending) < UPCOMING_KEPT:
        fields["upcoming"] = pending + [plan]
    state.update_character(ch["id"], **fields)
    return True


async def step(state, settings, gm, rng: random.Random, now: float | None = None) -> bool:
    """Deliver due letters, let neighbors answer or write first. Returns True if Pip should wake."""
    now = now or time.time()
    wake = False
    for ch in state.characters("neighbor"):
        if moved := _happened(ch, now, OVERDUE_GRACE):
            state.update_character(ch["id"], **moved)
    neighbors = {c["name"]: c for c in state.characters("neighbor")}
    for lt in state.letters(undelivered=True, limit=200):
        if lt["deliver_at"] > now:
            continue
        if lt["recipient"] == PIP:
            _deliver_to_pip(state, lt, now)
            wake = True
            continue
        ch = neighbors.get(lt["recipient"])
        ok = bool(ch) and await _write(state, settings, gm, rng, ch, now, lt)
        if ok or lt["attempts"] + 1 >= MAX_ATTEMPTS or not ch:
            state.update_letter(lt["id"], delivered_at=now, attempts=lt["attempts"] + 1)
            state.log("letter_read", id=lt["id"], by=lt["recipient"], answered=ok)
        else:
            state.update_letter(lt["id"], attempts=lt["attempts"] + 1, deliver_at=now + RETRY_AFTER)
    wake = await _visits(state, settings, gm, now) or wake
    for ch in state.characters("neighbor"):
        in_flight = state.letters(between=ch["name"], undelivered=True, limit=5)
        if not in_flight and now >= ch["next_chatter_at"]:
            if not await _write(state, settings, gm, rng, ch, now, None):
                state.update_character(ch["id"], next_chatter_at=now + RETRY_AFTER)
    return wake


async def _visits(state, settings, gm, now: float) -> bool:
    """In person: a neighbor greets Pip once per visit and answers what Pip says (capped per hour)."""
    here = places.present_at(state)
    wake = False
    for ch in state.characters("neighbor"):
        if here != places.home_of(ch):
            if ch["heard"]:
                state.update_character(ch["id"], heard=[])  # Pip left before they could answer
            continue
        visit = state.meta("arrived_at") or ""
        greeting = state.meta(f"greeted:{ch['id']}") != visit
        recent = [t for t in ch["replies"] if now - t < 3600]
        answering = bool(ch["heard"]) and len(recent) < settings.companion_replies_per_hour
        if not greeting and not answering:
            continue
        a = state.agent()
        situation = f"Pip seems {a['mood']}."
        talk = correspondence(state, ch["name"]) + talk_lines(state, ch["name"], verbatim_since=float(visit or 0))
        talk = talk[-CORRESPONDENCE_SHOWN * 2:]
        out = await gm.speak_in_person(ch["name"], ch["persona"], ch["life"], talk,
                                       [h["text"] for h in ch["heard"]] if answering else [], greeting and not answering,
                                       situation, told=ch["told"], agenda=agenda(ch, now)) if gm else None
        state.set_meta(**{f"greeted:{ch['id']}": visit})
        fields = {**({"heard": [], "replies": recent + [now]} if answering else {}),
                  **({**_told(ch, out), **_happened(ch, now)} if out else {})}
        if fields:
            state.update_character(ch["id"], **fields)
        if out:
            gist = clip(out.get("gist"), 200)
            state.log("companion", name=ch["name"], text=out["text"], reply=True, visit=True,
                      **({"gist": gist} if gist else {}))
            wake = True
    return wake


def send(state, settings, rng: random.Random, to: dict, text: str, enclosed: str) -> dict:
    lt = state.add_letter(PIP, to["name"], clip(text, 1200), time.time() + _delay(settings, rng), enclosed=enclosed)
    state.log("letter_sent", id=lt["id"], to=to["name"], text=lt["text"], enclosed=enclosed)
    return lt


def perception(state, now: float | None = None) -> list[str]:
    now = now or time.time()
    neighbors = state.characters("neighbor")
    if not neighbors:
        return []
    lines = ["Your neighbors (they live nearby: visit them with go_to, or write with write_letter):"]
    for c in neighbors:
        visited = state.last_arrived(places.home_of(c))
        lines.append(f"- {c['name']}: {c['about']}" + (f" (you last visited {ago(visited, now)})" if visited else ""))
    for lt in state.letters(undelivered=True, limit=20):
        if lt["sender"] == PIP:
            lines.append(f"- your letter to {lt['recipient']} (sent {ago(lt['ts'], now)}) is on its way")
    return lines
