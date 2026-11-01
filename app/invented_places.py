"""Places that characters mention become real (see DESIGN-invented-places.md).

When a character (a neighbor's letter or talk, a companion, a visitor in chat) points Pip at a place that doesn't exist
yet, the engine records it as **heard-of**: a name, who said it and what they said is there, and a walk time the engine
fixes once. Pip's directory lists it, so `go_to` just works. It becomes **real** lazily, on Pip's first arrival: one GM
call proposes its kind, description and what can be found there, and the engine validates and keeps it.

The engine owns everything mechanical: which names count (the name must be in the speaker's own words, not a known
place, a neighbor or a reserved word), the caps, the minutes, the kind's verbs and hours, and the loot numbers.
"""
import random
import re
import time

from . import place_kinds as kinds
from .state import _singular
from .text import clip

DAY = 86400
FORGET_AFTER = 30 * DAY        # a heard-of place nobody mentions again and Pip never visits is forgotten
MENTIONS_KEPT = 6
THERE_CHARS = 120
BANDS = {"near": (12, 20), "far": (20, 35)}   # walking minutes; "very far" is heard-of but too far to walk
VERY_FAR = "very far"
DISTANCES = ("near", "far", VERY_FAR)
ACTIVE = ("heard", "real")
ARTICLES = {"the", "a", "an"}
CONNECTORS = {"in", "at", "of", "by", "near", "on", "over", "past", "beyond", "from", "and"}
TRADE = {"ironmonger", "ironmongery", "shop", "store", "market", "stall", "smithy", "village", "town", "harbour",
         "harbor", "quay", "inn", "mill", "bakery", "baker", "chandler", "chandlery", "merchant", "forge", "wharf",
         "dock", "port", "hamlet", "city", "square", "fair", "emporium", "workshop"}
ADJECTIVES = {"old", "new", "little", "big", "great", "high", "low", "north", "south", "east", "west", "upper",
              "lower", "next", "far", "near", "first", "second", "third"}
RESERVED = {"home", "house", "workshop", "library", "wood", "woods", "junkyard", "market", "garden"}
PIP = "pip"


def _words(name: str) -> list[str]:
    """A name's words, without possessives, punctuation or leading articles."""
    s = re.sub(r"['’]s\b", "", str(name or ""))
    words = re.findall(r"[A-Za-z0-9][A-Za-z0-9'-]*", s)
    while words and words[0].lower() in ARTICLES:
        words = words[1:]
    return words


def _proper(words: list[str]) -> list[str]:
    """The proper-noun part: capitalised words that aren't trade words, articles, connectors or plain adjectives."""
    skip = TRADE | ARTICLES | CONNECTORS
    if not any(w[0].isupper() and w.lower() not in skip | ADJECTIVES for w in words):
        return []
    return [w for w in words if w[0].isupper() and w.lower() not in skip]


def core(name: str) -> str:
    """What makes two spellings the same place: 'the ironmonger in Saltholm' = 'Saltholm'; 'the old mill' stays."""
    words = _words(name)
    return " ".join(_singular(w.lower()) for w in (_proper(words) or words))


def key_for(name: str) -> str:
    """How a new place is called: its proper-noun form ('Saltholm'), or the plain name without an article."""
    words = _words(name)
    return " ".join(_proper(words)) or " ".join(w.lower() for w in words)


def _said(text: str) -> set[str]:
    return {_singular(w) for w in re.findall(r"[a-z0-9]+", re.sub(r"['’]s\b", "", str(text or "").lower()))}


def _reserved(state, c: str, speaker: str = "") -> bool:
    if c in RESERVED:
        return True
    names = [ch["name"] for ch in state.characters()] + [speaker]
    taken = {PIP} | {w for n in names for w in _said(n) if len(w) > 2}
    return bool(taken & set(c.split()))


def _stale(rec: dict, now: float) -> bool:
    return rec["status"] == "heard" and rec["heard_at"] < now - FORGET_AFTER


def records(state, now: float | None = None) -> list[dict]:
    """The places Pip knows of (heard-of and real); a heard-of one nobody has mentioned for 30 days is forgotten."""
    now = now or time.time()
    return [r for r in state.place_rows() if r["status"] in ACTIVE and not _stale(r, now)]


def find_record(state, name, now: float | None = None) -> dict | None:
    """A known invented place by any of its spellings."""
    c = core(name)
    if not c:
        return None
    return next((r for r in records(state, now) if c == r["core"] or c in {core(a) for a in r["aliases"]}), None)


def _mention(speaker: str, raw: dict, now: float) -> dict:
    items = raw.get("items") if isinstance(raw.get("items"), list) else []
    return {"by": clip(speaker, 40), "there": clip(raw.get("there"), THERE_CHARS),
            "items": [clip(i, 40) for i in items if isinstance(i, str) and i.strip()][:3], "ts": now}


def _name(raw) -> str | None:
    if not isinstance(raw, dict) or not isinstance(raw.get("place"), str):
        return None
    name = " ".join(raw["place"].split()).strip(" .,;:!?\"'")
    return name if 2 <= len(name) <= 40 and len(name.split()) <= 5 else None


def _alias(name: str) -> str:
    return " ".join(_words(name)).lower()


def _forget_stale(state, now: float) -> None:
    for r in state.place_rows():
        if _stale(r, now):
            state.update_place(r["key"], status="forgotten")


def accept(state, speaker: str, text: str, raw, now: float | None = None, rng: random.Random | None = None) -> dict | None:
    """A character's `mentions_place` ({place, there, distance, items?}) checked against their own words. A known place
    gains the mention (add_to); a new one is recorded as heard-of if the caps allow. Returns the record, or None."""
    now = now or time.time()
    name = _name(raw)
    c = core(name) if name else ""
    if not c or clip(speaker, 40).lower() == PIP or not set(c.split()) <= _said(text) or _reserved(state, c, speaker):
        return None
    known = find_record(state, name, now)
    if known:
        return add_to(state, known, speaker, text, raw, now)
    _forget_stale(state, now)
    rows = state.place_rows()
    if (sum(r["created_at"] > now - DAY for r in rows) >= state.s.invented_places_per_day
            or sum(r["status"] in ACTIVE for r in rows) >= state.s.invented_places_max):
        return None
    if any(r["core"] == c for r in rows):
        return None  # removed by the owner (or forgotten): not brought back under the same name
    distance = raw.get("distance") if raw.get("distance") in DISTANCES else "far"
    band = BANDS.get(distance)
    walk = round((rng or random.Random()).uniform(*band)) if band else None
    mention = _mention(speaker, raw, now)
    kind = kinds.guess(f"{name} {mention['there']}")
    hours = kinds.hours_for(kind)
    key = key_for(name)
    alias = _alias(name)
    rec = state.add_place(key, c, aliases=[alias] if alias != key.lower() else [], kind=kind, distance=distance,
                          walk_minutes=walk, hours=list(hours) if hours else None, daylight_only=int(not hours),
                          mentions=[mention], created_at=now, heard_at=now)
    state.log("heard_of_place", place=key, by=mention["by"], there=mention["there"], distance=distance)
    return rec


def add_to(state, place, speaker: str, text: str, raw, now: float | None = None) -> dict | None:
    """A later mention of a known place: kept as evidence (the newest few), with any new spelling as an alias."""
    now = now or time.time()
    rec = place if isinstance(place, dict) else find_record(state, place, now)
    if not rec or not isinstance(raw, dict):
        return None
    fields = {"mentions": (rec["mentions"] + [_mention(speaker, raw, now)])[-MENTIONS_KEPT:], "heard_at": now}
    name = _name(raw)
    alias = _alias(name) if name else ""
    if alias and alias != rec["key"].lower() and alias not in rec["aliases"]:
        fields["aliases"] = rec["aliases"] + [alias]
    state.update_place(rec["key"], **fields)
    return state.place_row(rec["key"])


# --- the backstop: a name a character said, found again when Pip tries to go there ----------------
VERY_FAR_CUES = ("days away", "day's walk", "days' walk", "days of walking", "across the sea", "over the sea",
                 "far away", "a long way off", "too far", "over the mountains")
NEAR_CUES = ("nearby", "near here", "close by", "just down", "next door", "round the corner", "around the corner",
             "short walk", "not far", "a step away", "down the lane", "up the lane")
BACKSTOP_EVENTS = 20       # the characters' recent words searched
BACKSTOP_SCAN = 300        # events read to find them


def guess_distance(text: str) -> str:
    """A character's sense of how far, from their words (the engine still owns the minutes)."""
    t = str(text or "").lower()
    if any(c in t for c in VERY_FAR_CUES):
        return VERY_FAR
    return "near" if any(c in t for c in NEAR_CUES) else "far"


def _voices(state, limit: int, scan: int) -> list[tuple[str, str]]:
    """(speaker, words) for the latest things others said to Pip: companions and neighbors in person, delivered
    letters, and visitors in chat. Never Pip's own words, and never engine-written gift notes."""
    out = []
    for e in state.events(scan):
        d = e["data"]
        if e["kind"] == "companion":
            out.append((d.get("name") or "", d.get("text") or ""))
        elif e["kind"] == "inbox" and (d.get("letter") or not d.get("gift")):
            out.append((d.get("sender") or "A visitor", d.get("text") or ""))
        if len(out) >= limit:
            break
    return out


def _sentence(text: str, start: int, end: int) -> str:
    lo = max(text.rfind(c, 0, start) for c in ".!?:\n") + 1
    hi = min([i for i in (text.find(c, end) for c in ".!?\n") if i >= 0] or [len(text) - 1]) + 1
    return text[lo:hi].strip()


def _sentence_start(text: str, at: int) -> bool:
    before = text[:at].rstrip()
    return not before or before[-1] in ".!?:\n\"“"


def _spot(name: str, text: str, proper: bool) -> tuple[str, str] | None:
    """Where `name` (or its core) is said in `text`: (the name as said, the sentence it's in)."""
    for words in (_words(name), core(name).split()):
        if not words:
            continue
        pattern = r"\b" + r"\W+".join(re.escape(w) for w in words) + r"(?:['’]?s)?\b"
        for m in re.finditer(pattern, text, re.I):
            said = m.group(0)
            if proper and (not said[0].isupper() or _sentence_start(text, m.start())):
                continue
            return said, _sentence(text, m.start(), m.end())
    return None


def recall_mention(state, name: str, now: float | None = None, limit: int = BACKSTOP_EVENTS,
                   scan: int = BACKSTOP_SCAN, proper: bool = False) -> dict | None:
    """Pip asked for a place nobody recorded: if a character recently said it, record it now (the sentence it came
    from is what they said is there). A name only Pip has used stays unknown."""
    if not core(name):
        return None
    for speaker, text in _voices(state, limit, scan):
        hit = _spot(name, text, proper)
        if hit:
            said, sentence = hit
            raw = {"place": said, "there": sentence, "distance": guess_distance(sentence)}
            return accept(state, speaker, text, raw, now)
    return None


def named_in(recs: list[dict], text: str) -> list[dict]:
    """The places among `recs` whose name is in `text`."""
    said = _said(text)
    return [r for r in recs if set(r["core"].split()) <= said]


# --- the one-time backfill ---------------------------------------------------------------------------------
BACKFILL_SCAN = 5000
NOT_PLACES = {"monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday", "january", "february",
              "march", "april", "may", "june", "july", "august", "september", "october", "november", "december", "i"}


def backfill(state, now: float | None = None) -> list[dict]:
    """Once, on the first start with invented places: a proper name in one of Pip's open to-dos that a character said
    (as a name: capitalised, mid-sentence) becomes heard-of, so a place mentioned before this existed isn't a dead end."""
    if state.meta("invented_places_backfill"):
        return []
    state.set_meta(invented_places_backfill="1")
    found = []
    for m in state.memories("todo", status="open", limit=200):
        for name in re.findall(r"[A-Z][a-z'’-]+(?:\s+[A-Z][a-z'’-]+)*", m["text"]):
            if name.lower() in NOT_PLACES:
                continue
            rec = recall_mention(state, name, now, limit=BACKFILL_SCAN, scan=BACKFILL_SCAN, proper=True)
            if rec and rec not in found:
                found.append(rec)
    return found


# --- visitors in chat (owner decision 6) -----------------------------------------------------------------------
# A visitor's chat message gets no GM call of its own, so it is read with a few patterns instead: a pointing phrase
# ("go to", "visit", "there's a ... in", "a lake called") followed by a name - a capitalised one, or "the" plus a few
# words ending in a landscape or settlement word. Everything found still goes through `accept` (the caps, reserved
# names, neighbors). What the patterns miss, the go_to backstop still catches, since it searches chat messages too.
FEATURES = (r"valley|lake|mill|woods?|hills?|beach|shore|harbou?r|market|village|town|bay|cove|island|pond|marsh|fen|"
            r"meadow|orchard|quarry|bridge|lighthouse|tower|ruins?|farm|inn|forest|river|square|fair|cliffs?|moor|"
            r"heath|glen|dale|common|green|wharf|quay")
PLACE = (r"(?P<place>[A-Z][\w'’-]+(?:\s+(?:of\s+|on\s+)?[A-Z][\w'’-]+){0,3}"
         rf"|(?i:the)\s+(?:[a-z]+\s+){{0,2}}(?:{FEATURES})\b)")
CHAT = [re.compile(p) for p in (
    r"(?i:\b(?:go|walk|head|wander|stroll|pop)(?:\s+over|\s+down|\s+up)?\s+to|\bvisit|\bgo\s+and\s+see)\s+" + PLACE,
    r"(?i:\b(?:there(?:'s|’s|\s+is|\s+are)|try|ask|find)\s+(?:an?|the|some)\s+[^.!?]{1,40}?\s+"
    r"(?:in|at|near|past|beyond|by)\s+)" + PLACE,
    rf"(?i:\b(?:place|{FEATURES}|shop|wood)\s+(?:called|named)\s+)" + PLACE,
)]


def chat_mentions(text: str) -> list[dict]:
    """Places a chat message points Pip to, as `mentions_place`-shaped dicts (the sentence is what's there)."""
    text = str(text or "")
    out, seen = [], set()
    for pat in CHAT:
        for m in pat.finditer(text):
            name = m.group("place")
            if core(name) in seen:
                continue
            seen.add(core(name))
            sentence = _sentence(text, m.start(), m.end())
            out.append({"place": name, "there": sentence, "distance": guess_distance(sentence)})
    return out


def from_chat(state, sender: str, text: str, now: float | None = None) -> list[dict]:
    """A visitor's message: each place it points to is a mention, checked like a character's."""
    return [r for r in (accept(state, sender, text, raw, now) for raw in chat_mentions(text)) if r]
