"""People: the engine's machinery for anyone a module brings into the world (docs/DESIGN-engine-audit.md, C1).

Correspondence: letters go between the agent and whoever a module brought as writing (`writes`: a neighbour, anyone a world
says). Letters take hours each way. They answer what the agent sends, write first when their module asks (`letter`), may tuck in a
small parcel (capped per day), and have a little life of their own that moves on between letters; what live modules note about them
(`notes`: a trade's wares, say) is theirs to bring up. Letters for the agent arrive in the inbox with the writer as sender, so
perception, diary moments, recall and reflection treat them like any other visit. See DESIGN-neighbor.md.

Anyone the world brings (a module's `character`, of any role: a neighbour, a villager) or who settles at a place a character told
the agent about (a resident, DESIGN-invented-places.md) is met in person where they are: whoever is there greets the agent, a few at a
time (GREETERS), and answers what it says to them (docs/DESIGN-engine-audit.md, C1).
"""
import math
import random
import time

from . import invented_places as invented
from . import places
from . import conversation as conv
from .companions import conversation as talk_lines
from .memory import ago
from .text import brief, clip
from . import world as world_content
from . import world_pack

JITTER = (0.7, 1.3)
LIFE_KEPT = 5
CORRESPONDENCE_SHOWN = 6
LETTERS_CHECKED = 6        # a neighbor's own recent letters a new one must not repeat
REPEAT_LOOKBACK = 8        # a neighbor's own last lines a new one must not repeat
TOLD_KEPT = 30
TOLD_PER_CALL = 3
UPCOMING_KEPT = 3
OVERDUE_GRACE = 3 * 86400  # a plan never brought up this long after it was due has quietly happened
MAX_ATTEMPTS = 3
RETRY_AFTER = 3600
DAY = 86400
GREETERS = 2               # how many of those at a place greet the agent when it arrives; the rest answer when spoken to


def _delay(settings, rng: random.Random) -> float:
    return settings.letter_delay_minutes * 60 * rng.uniform(*JITTER)


def correspondence(state, name: str) -> list[str]:
    out = []
    for lt in state.letters(between=name, limit=CORRESPONDENCE_SHOWN):
        if lt["delivered_at"] is None and lt["sender"] == name:
            continue  # their own letter still on the way isn't part of what's been said yet
        if lt["sender"] == world_pack.active().agent.name:
            out.append(f"{world_pack.active().agent.name}: {lt['text']}" + (f" [enclosed: {lt['enclosed']}]" if lt["enclosed"] else ""))
        else:  # their own words in brief: a model copies vivid phrasing it can see (DESIGN-neighbor-memory.md)
            out.append(f"{name} (in brief): {brief(lt['gist'], lt['text'])}")
    return out


def _told(ch: dict, out: dict) -> dict:
    """Things about themselves the neighbor just told the agent for the first time, added to what the agent already knows."""
    raw = out.get("told")
    new = [t for t in (clip(x, 80) for x in (raw if isinstance(raw, list) else [])) if t][:TOLD_PER_CALL]
    return {"told": (ch["told"] + new)[-TOLD_KEPT:]} if new else {}


def _news(life: list[str], out: dict) -> dict:
    """Their life moves on: a `life_update` joins it only when the model itself says it's news."""
    if clip(out.get("life_update"), 5) and out.get("life_update_new") is True:
        return {"life": (life + [clip(out["life_update"], 200)])[-LIFE_KEPT:]}
    return {}


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
    if not name or raw.get("kind") not in world_content.kinds():                      # any kind of thing the world has
        return None
    try:
        qty = max(1, min(3, int(raw.get("qty") or 1)))
    except (TypeError, ValueError):
        qty = 1
    return {"name": name, "kind": raw["kind"], "qty": qty, "description": clip(raw.get("description"), 160)}


NOT_YET = 1e18             # a neighbour writes first only when a module asks (modules.py, `letter`): never, until then


def arrive(state, settings, new: dict, now: float | None = None, rng: random.Random | None = None) -> dict:
    """Someone a module brought into the world (modules.py, `character`): their record, living where it says (or in a home of their own),
    and their first letter on its way, soon, if they wrote one."""
    now = now or time.time()
    rng = rng or random.Random()
    ch = state.add_character(new["name"], new["kind"], None, clip(new["persona"], 800), settings.neighbor_writes_every_hours * 60, NOT_YET,
                             about=clip(new["about"], 160), place=new.get("home", ""), writes=new.get("writes", False))
    if new.get("letter"):
        lt = state.add_letter(new["name"], world_pack.active().agent.name, clip(new["letter"], 1200), now + _delay(settings, rng) / 4)
        invented.accept(state, new["name"], lt["text"], new.get("mentions_place"), now)
    state.log("character", name=new["name"], role=new["kind"], about=ch["about"], place=ch["place"])
    return ch


async def recall_told(state, gm, tries: dict) -> None:
    """One-time backfill: someone the agent writes to who knows nothing of what they've told the agent has it recalled from everything said
    so far. Done for good once it succeeds; after two failures it waits for the next start (`tries` lives that long)."""
    for ch in state.correspondents() if gm else []:
        done = f"told_recalled:{ch['id']}"
        if ch["told"] or state.meta(done) or tries.get(ch["id"], 0) >= 2:
            continue
        said = [f"{world_pack.active().agent.name if lt['sender'] == world_pack.active().agent.name else ch['name']}: {lt['text']}"
                for lt in state.letters(between=ch["name"], limit=50)
                if lt["delivered_at"] is not None or lt["sender"] == world_pack.active().agent.name] + talk_lines(state, ch["name"])
        if not said:
            continue  # nothing yet (someone just brought in): their first letter is recalled once it arrives
        got = await gm.recall_told(ch["name"], ch["persona"], said, role=ch["kind"])
        if got is None:
            tries[ch["id"]] = tries.get(ch["id"], 0) + 1
            continue
        state.update_character(ch["id"], told=[t for t in (clip(x, 80) for x in got) if t][:TOLD_KEPT])
        state.set_meta(**{done: "1"})


def _deliver_to_agent(state, lt: dict, now: float) -> None:
    text = f"A letter from {lt['sender']}: {lt['text']}"
    p = lt["parcel"]
    if p:
        item = state.add_item(p["name"], p["qty"], p["kind"], p["description"] or f"from {lt['sender']}")
        text += f" (Enclosed: {p['qty']} x {item['name']} ({item['kind']}).)"
        state.log("gift", sender=lt["sender"], item=item["name"], qty=p["qty"], item_kind=item["kind"], letter=lt["id"])
    inbox_id = state.add_inbox(text, lt["sender"], gift=True)  # text names the sender itself
    state.log("inbox", id=inbox_id, text=text, sender=lt["sender"], letter=True, gift=bool(p))
    state.update_letter(lt["id"], delivered_at=now)


def notes_line(state, ch: dict) -> str:
    """What live modules note about someone, for them to bring up when they write (a trade's wares, and what it has to offer)."""
    from .modules import notes_on
    return " ".join(f"{ch['name']} {n}" for n in notes_on(state, ch["name"]))


async def _write(state, settings, gm, rng, ch: dict, now: float, answering: dict | None, library=None) -> bool:
    """Someone writes the agent a letter (an answer, or out of the blue). Returns False if the GM failed."""
    parcel_ok = state.letters_since_parcel(now - DAY) < settings.parcels_per_day
    home = places.home_of(ch)
    ask = dict(told=ch["told"], agenda=agenda(ch, now), role=ch["kind"], **_places(state, settings, library, ch),
               **({"home": places.label(home)} if home else {}), **({"notes": n} if (n := notes_line(state, ch)) else {}))
    args = (ch["name"], ch["persona"], ch["life"], correspondence(state, ch["name"]), answering["text"] if answering else None,
            answering["enclosed"] if answering else "", parcel_ok)
    out = await gm.letter(*args, **ask) if gm else None
    earlier = [lt["text"] for lt in state.letters(between=ch["name"], limit=LETTERS_CHECKED) if lt["sender"] == ch["name"]]
    if out and conv.repeats(out.get("text") or "", earlier):     # the same sentence as an earlier letter: one more try
        out = await gm.letter(*args, again=True, **ask) or out
    text = clip(out.get("text"), 1200) if out else ""
    if not text:
        return False
    invented.accept(state, ch["name"], text, out.get("mentions_place"), now)
    parcel = clean_parcel(out.get("parcel")) if parcel_ok else None
    state.add_letter(ch["name"], world_pack.active().agent.name, text, now + _delay(settings, rng), parcel=parcel,
                     reply_to=answering["id"] if answering else None, gist=clip(out.get("gist"), 200))
    fields = {"next_chatter_at": NOT_YET, **_told(ch, out),
              **_happened(ch, now)}
    fields.update(_news(fields.get("life", ch["life"]), out))
    pending, plan = fields.get("upcoming", ch["upcoming"]), clean_upcoming(out.get("upcoming"), now)
    if plan and len(pending) < UPCOMING_KEPT:
        fields["upcoming"] = pending + [plan]
    state.update_character(ch["id"], **fields)
    return True


def _places(state, settings, library, ch: dict) -> dict:
    """What a character's prompt is told about the places in Pip's world, and how to point the agent to a new one."""
    return {"places": invented.places_line(state, ch["name"], settings, library),
            "mention": invented.mention_instruction(state, settings, library)}


async def step(state, settings, gm, rng: random.Random, now: float | None = None, library=None) -> bool:
    """Deliver due letters, let those the agent writes to answer or write first. Returns True if the agent should wake."""
    now = now or time.time()
    wake = False
    for ch in state.correspondents():
        if moved := _happened(ch, now, OVERDUE_GRACE):
            state.update_character(ch["id"], **moved)
    writers = {c["name"]: c for c in state.correspondents()}
    for lt in state.letters(undelivered=True, limit=200):
        if lt["deliver_at"] > now:
            continue
        if lt["recipient"] == world_pack.active().agent.name:
            _deliver_to_agent(state, lt, now)
            wake = True
            continue
        ch = writers.get(lt["recipient"])
        ok = bool(ch) and await _write(state, settings, gm, rng, ch, now, lt, library)
        if ok or lt["attempts"] + 1 >= MAX_ATTEMPTS or not ch:
            state.update_letter(lt["id"], delivered_at=now, attempts=lt["attempts"] + 1)
            state.log("letter_read", id=lt["id"], by=lt["recipient"], answered=ok)
        else:
            state.update_letter(lt["id"], attempts=lt["attempts"] + 1, deliver_at=now + RETRY_AFTER)
    wake = await _visits(state, settings, gm, now, library) or wake
    from . import looks
    await looks.ensure(state, settings, gm, now)
    await looks.ensure_scenes(state, settings, gm, library, now)
    for ch in state.correspondents():
        in_flight = state.letters(between=ch["name"], undelivered=True, limit=5)
        if not in_flight and now >= ch["next_chatter_at"]:
            if not await _write(state, settings, gm, rng, ch, now, None, library):
                state.update_character(ch["id"], next_chatter_at=now + RETRY_AFTER)
    return wake


async def reply(state, settings, gm, ch: dict, now: float, library=None, closing: bool = False) -> dict | None:
    """One line from someone the agent is with in person: a greeting if this visit has had none, else an answer to what the agent has said (`ch["heard"]`), which it
    consumes. Logged as a `companion` event; returns what the model said (with `goodbye` when `closing` asks for it), or None."""
    where = places.place_of(state, ch)
    visit = state.meta("arrived_at") or ""
    answering = bool(ch["heard"])
    recent = [t for t in ch["replies"] if now - t < 3600]
    a = state.agent()
    situation = f"{world_pack.active().agent.name} seems {a['mood']}."
    if where != places.home_of(ch):                       # somewhere else just now, as a module says (a stall on market day)
        from .modules import whereabouts
        doing = (whereabouts(state, ch["name"]) or {}).get("doing")
        situation += f" {ch['name']} is {doing}." if doing else f" {ch['name']} is at {places.label(where)}."
    at = "" if where == places.home_of(ch) and places.resident_of(state, where) else places.label(where)    # in a home of their own: no place to name
    talk = correspondence(state, ch["name"]) + talk_lines(state, ch["name"], verbatim_since=float(visit or 0))
    talk = talk[-CORRESPONDENCE_SHOWN * 2:]
    can_give = _can_give(state, settings, now)
    ask = dict(told=ch["told"], agenda=agenda(ch, now), at=at, can_give=can_give, role=ch["kind"], **_places(state, settings, library, ch),
               **({"closing": True} if closing else {}))
    heard = [h["text"] for h in ch["heard"]] if answering else []
    out = await gm.speak_in_person(ch["name"], ch["persona"], ch["life"], talk, heard, situation, **ask) if gm else None
    mine = [e["data"]["text"] for e in state.events(200) if e["kind"] == "companion" and e["data"].get("name") == ch["name"]][:REPEAT_LOOKBACK]
    if out and conv.repeats(out["text"], mine):                 # one more try at saying something new
        out = await gm.speak_in_person(ch["name"], ch["persona"], ch["life"], talk, heard, situation, again=True, **ask) or out
    state.set_meta(**{f"greeted:{ch['id']}": visit})
    fields = {**({"heard": [], "replies": recent + [now]} if answering else {}),
              **({**_told(ch, out), **_happened(ch, now)} if out else {})}
    if out and at:                              # met out in the world, their life moves on in talk
        fields.update(_news(fields.get("life", ch["life"]), out))
    if fields:
        state.update_character(ch["id"], **fields)
    if not out:
        return None
    invented.accept(state, ch["name"], out["text"], out.get("mentions_place"), now)
    gist = clip(out.get("gist"), 200)
    handed = _hand_over(state, ch["name"], out.get("give")) if can_give else ""
    state.log("companion", name=ch["name"], text=out["text"] + handed, reply=True, visit=True, **({"gist": gist} if gist else {}),
              **({"goodbye": True} if closing and out.get("goodbye") is True else {}))
    return out


async def _visits(state, settings, gm, now: float, library=None) -> bool:
    """In person: whoever the agent finds where it is greets it once per visit, a few at most (GREETERS), and answers what it says
    (capped per hour)."""
    here = places.present_at(state)
    visit = state.meta("arrived_at") or ""
    wake, greeted = False, sum(1 for c in places.company_at(state, here) if visit and state.meta(f"greeted:{c['id']}") == visit)
    for ch in state.characters():
        if not ch["place"]:
            continue                                            # a thing that talks lives nowhere: it talks through its workings
        where = places.place_of(state, ch)
        if not where or here != where:
            if ch["heard"]:
                state.update_character(ch["id"], heard=[])  # The agent left before they could answer
            continue
        visit = state.meta("arrived_at") or ""
        if visit and state.meta("talk_scene") == visit:
            continue                                            # a talk scene is answering for them (talk.py)
        greeting = state.meta(f"greeted:{ch['id']}") != visit and greeted < GREETERS
        recent = [t for t in ch["replies"] if now - t < 3600]
        answering = bool(ch["heard"]) and len(recent) < settings.companion_replies_per_hour
        if not greeting and not answering:
            continue
        greeted += state.meta(f"greeted:{ch['id']}") != visit
        if not answering and ch["heard"]:
            ch = {**ch, "heard": []}                            # over the hour's limit: a greeting only
        if await reply(state, settings, gm, ch, now, library):
            wake = True
    return wake


def _can_give(state, settings, now: float) -> bool:
    """Whether they may hand the agent something today: letters' parcels and hand-overs share the daily cap."""
    in_person = sum(1 for e in state.events_since(now - DAY) if e["kind"] == "gift" and e["data"].get("in_person"))
    return state.letters_since_parcel(now - DAY) + in_person < settings.parcels_per_day


def _hand_over(state, name: str, raw) -> str:
    """Put what they handed over into the agent's belongings. Returns a note for the line ('' if nothing was given)."""
    p = clean_parcel(raw)
    if not p:
        return ""
    item = state.add_item(p["name"], p["qty"], p["kind"], p["description"] or f"from {name}")
    state.log("gift", sender=name, item=item["name"], qty=p["qty"], item_kind=item["kind"], in_person=True)
    return f" ({name} hands you {p['qty']} x {item['name']}.)"


def send(state, settings, rng: random.Random, to: dict, text: str, enclosed: str) -> dict:
    lt = state.add_letter(world_pack.active().agent.name, to["name"], clip(text, 1200), time.time() + _delay(settings, rng), enclosed=enclosed)
    state.log("letter_sent", id=lt["id"], to=to["name"], text=lt["text"], enclosed=enclosed)
    return lt


def perception(state, now: float | None = None) -> list[str]:
    now = now or time.time()
    writers = state.correspondents()
    if not writers:
        return []
    lines = ["People you write to (write_letter; go_to where they live to visit):"]
    for c in writers:
        visited = state.last_arrived(places.home_of(c))
        from .modules import notes_on
        sells = "; ".join(notes_on(state, c["name"]))
        lines.append(f"- {c['name']}" + (f" (at {places.label(places.home_of(c))})" if places.home_of(c) else "") + f": {c['about']}"
                     + (f" ({sells})" if sells else "") + (f" (you last visited {ago(visited, now)})" if visited else ""))
    for lt in state.letters(undelivered=True, limit=20):
        if lt["sender"] == world_pack.active().agent.name:
            lines.append(f"- your letter to {lt['recipient']} (sent {ago(lt['ts'], now)}) is on its way")
    return lines
