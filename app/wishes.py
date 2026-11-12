"""Wishes of every kind (docs/DESIGN-wishes.md).

A wish is a note on the wishlist with a `kind`: a thing to have, an activity to do, an ability Pip wishes it had, or an idea it wishes it understood. A wish for a
thing is shown with where it could be had; the nightly reflection may add a couple of wishes of its own; and the wishes that are not things are shared with Pip's friend
without being asked (one a day, through the same channel as its postcards).
"""
import difflib
import json
import re
import time

from . import finds, market
from . import place_kinds as kinds
from . import places
from . import sleep as sleepmod
from .state import State
from .text import clip

KINDS = ("thing", "activity", "ability", "idea")
SHAREABLE = ("activity", "ability", "idea")
MAX_SOURCES = 2                  # places named beside a wish for a thing
REFLECTED_MAX = 2                # wishes one night's reflection may add
WISH_CHARS = 200
SHARE_TEXT_MAX = 230             # a postcard is at most 240 characters
SIMILAR = 0.85
OPEN_CHECKED = 60
RETRY_SECONDS = 3600             # after a postcard that did not go out
SHARED_KEPT = 200


def market_price(state, place: str, name: str, now: float) -> int:
    entry = next(e for e in market.stock_table(state, place) if e[0] == name)
    return market.fair_price(state, place, name, entry[1], entry[5], now)


def sources(state, text: str, now: float) -> list[str]:
    """Where a wished-for thing could be had: shops and markets that sell something like it (with today's price), then places Pip has been that have turned it up."""
    sold, found = [], []
    for rec in state.place_rows():
        if rec["status"] != "real" or not kinds.KINDS[rec["kind"]].trades:
            continue
        entry = next((e for e in market.stock_table(state, rec["key"]) if State.related(e[0], text)), None)
        if entry:
            sold.append(f"{places.label(rec['key'])} sells {entry[0]} ({market.fair_price(state, rec['key'], entry[0], entry[1], entry[5], now)} coins)")
    for key, table in finds.loot().items():
        if state.last_arrived(key) is None:
            continue
        entry = next((e for e in table if State.related(e[0], text)), None)
        if entry:
            found.append(f"{places.label(key)} has turned up {entry[0]}")
    return (sold + found)[:MAX_SOURCES]


MAKING = re.compile(r"\b(make|making|made|build|building|craft|create|mend|repair|design|invent|carve|forge|tinker)\w*", re.I)


def doings(state, settings, library, text: str, tools) -> list[str]:
    """Where a wish to do something (or be able to) could be tried: places Pip knows whose verbs share its words, and a project when it is about making."""
    from .tools import content_words
    want = content_words(text)
    out = []
    for key, p in places.registry(state, settings, library).items():
        if p.heard:
            continue
        for verb, (short, _) in p.verbs.items():
            if verb in tools and want & content_words(short):
                out.append(f"at {places.label(key)}: {short}")
                break
    if "start_project" in tools and MAKING.search(text):
        out.append("start_project could make a start on it")
    return out[:MAX_SOURCES]


def _same(text: str, other: str) -> bool:
    from .tools import overlapping
    return difflib.SequenceMatcher(None, text.lower(), other.lower()).ratio() >= SIMILAR or overlapping(text, other)


def add_reflected(state, raw, now: float) -> list[dict]:
    """The wishes the nightly reflection proposed, made safe: a known kind, a short text, no repeat of an open wish, at most REFLECTED_MAX."""
    added: list[dict] = []
    if not isinstance(raw, list):
        return added
    open_wishes = [m["text"] for m in state.memories("wishlist", status="open", limit=OPEN_CHECKED)]
    for w in raw:
        if len(added) >= REFLECTED_MAX:
            break
        kind = str(w.get("kind") or "").strip().lower() if isinstance(w, dict) else ""
        text = clip(w.get("text"), WISH_CHARS).strip() if isinstance(w, dict) and isinstance(w.get("text"), str) else ""
        if kind not in KINDS or not text or any(_same(text, o) for o in open_wishes):
            continue
        wish_id = state.add_memory(text, "wishlist", kind)
        open_wishes.append(text)
        state.log("wished", id=wish_id, wish=kind, text=text, source="reflection")
        added.append({"id": wish_id, "kind": kind, "text": text})
    return added


def _today(now: float) -> str:
    return time.strftime("%Y-%m-%d", time.localtime(now))


async def share_step(state, settings, outreach, now: float | None = None) -> bool:
    """Tell Pip's friend, unasked, about a wish that is not a thing: one postcard a day at most, and only when postcards may go out. True when one was sent."""
    if settings.wish_share != "on":
        return False
    now = now or time.time()
    if sleepmod.asleep(state) or state.meta("wish_shared_day") == _today(now) or now - float(state.meta("wish_try_at") or 0) < RETRY_SECONDS \
            or not outreach.can_send(now):
        return False
    shared = set(json.loads(state.meta("wish_shared_ids") or "[]"))
    fresh = [m for m in reversed(state.memories("wishlist", status="open", limit=OPEN_CHECKED)) if m["kind"] in SHAREABLE and m["id"] not in shared]
    if not fresh:
        return False
    used, text = [], ""
    for m in fresh:
        line = clip(m["text"], WISH_CHARS if not used else 100).strip()
        joined = f"{text} Also: {line}" if used else f"A wish of mine: {line}"
        if len(joined) > SHARE_TEXT_MAX:
            break
        used.append(m["id"])
        text = joined
    state.set_meta(wish_try_at=now)
    ok, _ = await outreach.send_postcard(text, now)
    if not ok:
        return False
    state.set_meta(wish_shared_day=_today(now), wish_shared_ids=json.dumps(sorted(shared | set(used))[-SHARED_KEPT:]))
    state.log("wish_shared", ids=used, text=text)
    return True
