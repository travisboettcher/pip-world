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
from functools import lru_cache
import time

from . import place_kinds as kinds
from .state import _singular, name_key
from .text import clip
from .world import normalize_attrs
from . import world_pack

DAY = 86400
FORGET_AFTER = 30 * DAY        # a heard-of place nobody mentions again and Pip never visits is forgotten
MENTIONS_KEPT = 6
THERE_CHARS = 240             # what a character said is there: the sentence naming it, and up to two after it that carry facts
BANDS = {"near": (12, 20), "far": (20, 35)}   # walking minutes; "very far" is heard-of but too far to walk
VERY_FAR = "very far"
DISTANCES = ("near", "far", VERY_FAR)
ACTIVE = ("heard", "real")
ARTICLES = {"the", "a", "an"}
CONNECTORS = {"in", "at", "of", "by", "near", "on", "over", "past", "beyond", "from", "and"}
def _place_words() -> dict:
    """The world's place-name words (the pack's places.json `words`): what marks a trade, what names are taken, what a place may be."""
    return world_pack.active().data("places").get("words", {})


def trade_words() -> set:
    return set(_place_words().get("trade", ()))


def reserved() -> set:
    """Names a new place can't take: the built-in places' and the home's."""
    return set(_place_words().get("reserved", ()))


ADJECTIVES = {"old", "new", "little", "big", "great", "high", "low", "north", "south", "east", "west", "upper",
              "lower", "next", "far", "near", "first", "second", "third"}


def _words(name: str) -> list[str]:
    """A name's words, without possessives, punctuation or leading articles."""
    s = re.sub(r"['’]s\b", "", str(name or ""))
    words = re.findall(r"[A-Za-z0-9][A-Za-z0-9'-]*", s)
    while words and words[0].lower() in ARTICLES:
        words = words[1:]
    return words


def _proper(words: list[str]) -> list[str]:
    """The proper-noun part: capitalised words that aren't trade words, articles, connectors or plain adjectives."""
    skip = trade_words() | ARTICLES | CONNECTORS
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
    if c in reserved():
        return True
    names = [ch["name"] for ch in state.characters()] + [p["name"] for p in state.people()] + state.senders() + [speaker]
    taken = {world_pack.active().agent.name.lower()} | {w for n in names for w in _said(n) if len(w) > 2}
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


# --- facts a speaker states: how far, and when it is open --------------------------------------------------------
# "an hour west", "twenty minutes' walk" and "open 9am - 5pm" are kept as numbers, not just near/far and the shop default. The
# engine still owns the minutes: a stated walk is clamped to WALK_CAP, and one beyond a day trip is too far to walk at all.
NUMBERS = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
           "ten": 10, "eleven": 11, "twelve": 12, "fifteen": 15, "twenty": 20, "thirty": 30, "forty": 40, "forty-five": 45,
           "fifty": 50, "sixty": 60}
STATED_WALK_MAX = 120   # minutes: a longer stated trip is "too far to walk"
FOLLOWING = 2           # sentences after the one naming a place that may carry its facts
TRAVEL = re.compile(r"\b(?:walk|walking|stroll|journey|trip|ride|on foot|away|from (?:here|you|your)|north|south|east|west)\b", re.I)
DURATION = re.compile(r"\b(half an hour|(?:an?|one)\s+hours?['’]?s?\s+and\s+a\s+half|(\d+|[a-z-]+)\s+(hours?|minutes?|mins?)\b)", re.I)
HOUR = r"(\d{1,2}|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve)(?::(\d{2}))?\s*(a\.?m\.?|p\.?m\.?)?"
HOUR_WORDS = {w: n for w, n in NUMBERS.items() if 1 <= n <= 12 and w not in ("a", "an")}
OPEN_RANGE = re.compile(HOUR + r"\s*(?:-|–|—|to|till|until)\s*" + HOUR, re.I)
OPEN_AT = re.compile(r"open\w*\s+(?:at|from)?\s*" + HOUR + r".{0,25}?clos\w*\s+(?:at|by)?\s*" + HOUR, re.I)
OPEN_WORD = re.compile(r"\b(?:open|opens|opening|hours)\b", re.I)


def _sentences(text: str) -> list[str]:
    return [t.strip() for t in re.split(r"(?<=[.!?])\s+|\n", text) if t.strip()]


def stated_minutes(text: str) -> int | None:
    """How long a walk the words say it is ("an hour west", "twenty minutes' walk from here"), or None. The duration and a word
    about travel have to be in the same sentence, so "open for an hour" is not a distance."""
    for sentence in _sentences(text):
        if not TRAVEL.search(sentence):
            continue
        m = DURATION.search(sentence)
        if not m:
            continue
        whole = m.group(1).lower()
        if whole == "half an hour":
            return 30
        if "and a half" in whole:
            return 90
        n = int(m.group(2)) if m.group(2).isdigit() else NUMBERS.get(m.group(2).lower())
        if n:
            return n * (60 if m.group(3).lower().startswith("hour") else 1)
    return None


def _hour(num: str, marker: str | None, after: int | None = None) -> int | None:
    n = int(num) if num.isdigit() else HOUR_WORDS.get(num.lower())
    if n is None or not 0 <= n <= 24:
        return None
    marker = (marker or "")[:1].lower()
    if marker == "p":
        return n % 12 + 12
    if marker == "a":
        return n % 12
    if after is not None and n <= after and n < 12:   # "9 to 5": the 5 is the afternoon
        return n + 12
    return n


def stated_hours(text: str) -> tuple[int, int] | None:
    """(opens, closes) as 24-hour clock hours from "open 9am - 5pm", "open from nine to five" or "opens at 8 and closes at 6"."""
    for sentence in _sentences(text):
        if not OPEN_WORD.search(sentence):
            continue
        for pattern in (OPEN_AT, OPEN_RANGE):
            m = pattern.search(sentence)
            if not m:
                continue
            o = _hour(m.group(1), m.group(3))
            c = _hour(m.group(4), m.group(6), after=o)
            if o is not None and c is not None and 0 <= o < c <= 24:
                return o, c
    return None


def _stated_walk(minutes: int) -> tuple[str, float | None]:
    if minutes > STATED_WALK_MAX:
        return VERY_FAR, None
    walk = max(1, min(WALK_CAP, minutes))
    return ("near" if walk <= BANDS["near"][1] else "far"), float(walk)


def _facts(kind: str, there: str) -> dict:
    """The place-row fields a mention's stated walk and hours set (hours only for a kind that keeps them)."""
    out = {}
    minutes = stated_minutes(there)
    if minutes is not None:
        out["distance"], out["walk_minutes"] = _stated_walk(minutes)
    hours = stated_hours(there)
    if hours and kinds.KINDS[kind].shop_hours:
        out["hours"], out["daylight_only"] = list(kinds.hours_for(kind, *hours)), 0
    return out


def accept(state, speaker: str, text: str, raw, now: float | None = None, rng: random.Random | None = None) -> dict | None:
    """A character's `mentions_place` ({place, there, distance, items?}) checked against their own words. A known place
    gains the mention (add_to); a new one is recorded as heard-of if the caps allow. Returns the record, or None."""
    now = now or time.time()
    name = _name(raw)
    c = core(name) if name else ""
    if not c or clip(speaker, 40).lower() == world_pack.active().agent.name.lower() or not set(c.split()) <= _said(text) or _reserved(state, c, speaker):
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
    fields = {"distance": distance, "walk_minutes": walk, "hours": list(hours) if hours else None, "daylight_only": int(not hours),
              **_facts(kind, mention["there"])}
    rec = state.add_place(key, c, aliases=[alias] if alias != key.lower() else [], kind=kind, mentions=[mention],
                          created_at=now, heard_at=now, **fields)
    state.log("heard_of_place", place=key, by=mention["by"], there=mention["there"], distance=fields["distance"])
    return rec


def add_to(state, place, speaker: str, text: str, raw, now: float | None = None,
           rng: random.Random | None = None) -> dict | None:
    """A later mention of a known place: kept as evidence (the newest few), with any new spelling as an alias. At a
    real place, something new it names grows the place (owner decision 3, capped per place): a thing to find there,
    or else a line of description. A heard-of place just keeps the mention, so the design will honour it."""
    now = now or time.time()
    rec = place if isinstance(place, dict) else find_record(state, place, now)
    if not rec or not isinstance(raw, dict):
        return None
    mention = _mention(speaker, raw, now)
    fields = {"mentions": (rec["mentions"] + [mention])[-MENTIONS_KEPT:], "heard_at": now,
              **(_facts(rec["kind"], mention["there"]) if rec["status"] != "real" else {}),   # a real place has been designed: its numbers stay
              **_grow(state, rec, mention, rng or random.Random())}
    name = _name(raw)
    alias = _alias(name) if name else ""
    if alias and alias != rec["key"].lower() and alias not in rec["aliases"]:
        fields["aliases"] = rec["aliases"] + [alias]
    state.update_place(rec["key"], **fields)
    if "description" in fields:
        state.set_meta(**{f"place:{rec['key']}": fields["description"]})
    return state.place_row(rec["key"])


GROWTH_MAX = 3   # things a real place can gain from later mentions
GROWN_VERB = ["look around for what can be had here", "looking around"]


def _grow(state, rec: dict, mention: dict, rng: random.Random) -> dict:
    room = GROWTH_MAX - rec["grown"]
    if rec["status"] != "real" or room <= 0:
        return {}
    known = known_items(state)
    rules = rec["kind"] if kinds.KINDS[rec["kind"]].loot_kinds else "wild"  # a sight grows like somewhere wild
    new = [p for p in promised({"mentions": [mention]}, known) if not any(_covers(e[0], p["name"]) for e in rec["loot"])]
    loot = build_loot([], rules, known, new[:room], rng, existing=rec["loot"])
    if len(loot) > len(rec["loot"]):
        verbs = rec["verbs"] if "gather" in rec["verbs"] else {**rec["verbs"], "gather": GROWN_VERB}
        return {"loot": loot, "verbs": verbs, "grown": rec["grown"] + len(loot) - len(rec["loot"])}
    line = f" {mention['by']} says: {mention['there'].rstrip('.')}."
    if mention["there"] and mention["there"].lower() not in rec["description"].lower() \
            and len(rec["description"] + line) <= 500:
        return {"description": rec["description"] + line, "grown": rec["grown"] + 1}
    return {}


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


def _sentence_span(text: str, start: int, end: int) -> tuple[int, int]:
    lo = max(text.rfind(c, 0, start) for c in ".!?:\n") + 1
    hi = min([i for i in (text.find(c, end) for c in ".!?\n") if i >= 0] or [len(text) - 1]) + 1
    return lo, hi


def _sentence(text: str, start: int, end: int) -> str:
    lo, hi = _sentence_span(text, start, end)
    return text[lo:hi].strip()


def _context(text: str, start: int, end: int) -> str:
    """The sentence naming a place, plus those of the next FOLLOWING sentences that state how far it is or when it is open."""
    lo, pos = _sentence_span(text, start, end)
    parts = [text[lo:pos].strip()]
    for _ in range(FOLLOWING):
        while pos < len(text) and text[pos].isspace():
            pos += 1
        if pos >= len(text):
            break
        stops = [i for i in (text.find(c, pos) for c in ".!?\n") if i >= 0]
        nxt = text[pos:min(stops) + 1 if stops else len(text)].strip()
        pos = min(stops) + 1 if stops else len(text)
        if nxt and (stated_minutes(nxt) is not None or stated_hours(nxt) is not None):
            parts.append(nxt)
    return " ".join(parts)


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
            return said, _context(text, m.start(), m.end())
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
def _chat() -> list:
    return _chat_for(id(world_pack.active()))


@lru_cache(maxsize=8)
def _chat_for(_pack) -> list:
    """The patterns that find a place in a chat message, built from the world's words for what a place may be."""
    features = "|".join(_place_words().get("features", ())) or "place"
    place = (r"(?P<place>[A-Z][\w'’-]+(?:\s+(?:of\s+|on\s+)?[A-Z][\w'’-]+){0,3}"
             rf"|(?i:the)\s+(?:[a-z]+\s+){{0,2}}(?:{features})\b)")
    return [re.compile(p) for p in (
        r"(?i:\b(?:go|walk|head|wander|stroll|pop)(?:\s+over|\s+down|\s+up)?\s+to|\bvisit|\bgo\s+and\s+see)\s+" + place,
        r"(?i:\b(?:there(?:'s|’s|\s+is|\s+are)|try|ask|find)\s+(?:an?|the|some)\s+[^.!?]{1,40}?\s+"
        r"(?:in|at|near|past|beyond|by)\s+)" + place,
        rf"(?i:\b(?:place|{features}|shop|wood)\s+(?:called|named)\s+)" + place,
    )]


def chat_mentions(text: str) -> list[dict]:
    """Places a chat message points Pip to, as `mentions_place`-shaped dicts (the sentence is what's there)."""
    text = str(text or "")
    out, seen = [], set()
    for pat in _chat():
        for m in pat.finditer(text):
            name = m.group("place")
            if core(name) in seen:
                continue
            seen.add(core(name))
            sentence = _context(text, m.start(), m.end())
            out.append({"place": name, "there": sentence, "distance": guess_distance(sentence)})
    return out


def from_chat(state, sender: str, text: str, now: float | None = None) -> list[dict]:
    """A visitor's message: each place it points to is a mention, checked like a character's."""
    return [r for r in (accept(state, sender, text, raw, now) for raw in chat_mentions(text)) if r]


# --- real on arrival: the design, the loot table and the promise check -------------------------------------
TIERS = {"common": ((15, 30), (1, 3)), "uncommon": ((6, 12), (1, 2)), "rare": ((2, 5), (1, 1))}
LOOT_MAX = 10
DESIGNS_PER_DAY = 1
BARE = "you find {}, but can't get your bearings today"


def known_items(state) -> dict[str, tuple[str, str]]:
    """name_key -> (name, kind) for things that already exist (the loot tables, Pip's belongings, other places'
    tables), so an invented place's 'brass wire' is the junkyard's brass wire and stacks with it."""
    from . import finds  # finds reads place rows; keep the import one-way at load time
    out = {}
    tables = list(finds.loot().values()) + [r["loot"] for r in state.place_rows()]
    for name, kind in [(e[0], e[1]) for t in tables for e in t] + [(i["name"], i["kind"]) for i in state.items()]:
        out.setdefault(name_key(name), (name, kind))
    return out


def _plain(text: str) -> str:
    return f" {name_key(' '.join(re.findall(r'[a-z0-9]+', str(text).lower())))} "


def _covers(a: str, b: str) -> bool:
    """Is one name the other with words added ('thin brass wire' / 'brass wire')?"""
    x, y = _plain(a), _plain(b)
    return x in y or y in x


def promised(rec: dict, known: dict) -> list[dict]:
    """What the characters said is there: the items they named, and known things their words mention."""
    there = " ".join(m["there"] for m in rec["mentions"])
    names = [i for m in rec["mentions"] for i in m.get("items", [])]
    names += [n for n, _ in known.values() if _plain(n) in _plain(there)]
    out = []
    for n in names:
        hit = next((v for v in known.values() if _covers(v[0], n)), None)
        name, kind = hit if hit else (n, "material")
        if not any(_covers(name, o["name"]) for o in out):
            out.append({"name": name, "kind": kind, "tier": "uncommon", "description": ""})
    return out


def build_loot(entries, kind: str, known: dict, promises: list[dict], rng: random.Random,
               existing: list | None = None) -> list[list]:
    """GM-proposed entries made into a gathering table: the place kind decides which item kinds may be there and how
    many tools; the tier decides weight and quantity; names reuse what already exists. Every promised thing is in it.
    `existing` is a table to add to (a place growing)."""
    k = kinds.KINDS[kind]
    out = [list(e) for e in existing or []]
    tools = sum(e[1] == "tool" for e in out)

    def add(e, cap: int) -> None:
        nonlocal tools
        if not isinstance(e, dict) or len(out) >= cap:
            return
        name = clip(e.get("name"), 40).strip(" .").lower()
        if not name or any(name_key(o[0]) == name_key(name) for o in out):
            return
        name, item_kind = known.get(name_key(name), (name, e.get("kind")))
        if item_kind not in k.loot_kinds or (item_kind == "tool" and tools >= k.max_tools):
            return
        tier = "rare" if item_kind == "tool" else e.get("tier") if e.get("tier") in TIERS else "common"
        weights, qty = TIERS[tier]
        tools += item_kind == "tool"
        out.append([name, item_kind, rng.randint(*weights), list(qty), clip(e.get("description"), 100) or name,
                    normalize_attrs(name, item_kind, {})])

    for e in list(entries)[:LOOT_MAX * 2] if isinstance(entries, list) else []:
        add(e, LOOT_MAX)
    for p in promises:
        if not any(_covers(o[0], p["name"]) for o in out):
            add(p, len(out) + 1)
    return out


STAPLE_COUNT = 8   # how many kinds of thing a trading place keeps when its design named none


def staples(kind: str, rng: random.Random) -> list[list]:
    """The standard stock of a shop or market whose design came back with nothing to sell: a spread of what Pip can find elsewhere in the world,
    so a trading place is never bare. The kind's tool limit holds."""
    from . import finds
    k = kinds.KINDS[kind]
    pool = [e for table in finds.loot().values() for e in table if e[1] in k.loot_kinds]
    out, tools = [], 0
    for e in rng.sample(pool, len(pool)):
        if e[1] == "tool" and tools >= k.max_tools:
            continue
        tools += e[1] == "tool"
        out.append([e[0], e[1], e[2], list(e[3]), e[4], dict(e[5])])
        if len(out) >= STAPLE_COUNT:
            break
    return out


def backfill_stock(state, rng: random.Random | None = None) -> list[str]:
    """A trading place that became real with nothing to sell is given the standard stock (and the verbs a stocked place has). Returns the places fixed."""
    rng = rng or random.Random()
    fixed = []
    for rec in state.place_rows():
        k = kinds.KINDS.get(rec["kind"])
        if rec["status"] == "real" and k and k.trades and not rec["loot"]:
            loot = staples(rec["kind"], rng)
            state.update_place(rec["key"], loot=loot, verbs={v: [short, gerund] for v, (short, gerund) in k.verbs.items()})
            state.log("stocked", place=rec["key"], items=[e[0] for e in loot])
            fixed.append(rec["key"])
    return fixed


def design(state, rec: dict, raw, rng: random.Random | None = None, now: float | None = None, trusted: bool = False) -> dict | None:
    """Keep a GM design for a heard-of place, checked and clamped: the record becomes real. An unusable design keeps
    it heard-of (bare), and the next arrival tries again."""
    description = clip(raw.get("description"), 500) if isinstance(raw, dict) else ""
    if not description:
        return None
    now, rng = now or time.time(), rng or random.Random()
    kind = raw["kind"] if trusted and raw.get("kind") in kinds.KINDS else \
        kinds.check(raw.get("kind"), " ".join([rec["key"]] + [m["there"] for m in rec["mentions"]]))   # an approved module's kind stands
    k = kinds.KINDS[kind]
    known = known_items(state)
    loot = build_loot(raw.get("loot"), kind, known, promised(rec, known), rng) if k.loot_kinds else []
    if not loot and k.trades:
        loot = staples(kind, rng)                      # a shop or market is never bare
    verbs = {v: [clip(raw.get(f"{v}_help"), 80) or short, (clip(raw.get("gerund"), 40) or gerund) if gerund else None]
             for v, (short, gerund) in k.verbs.items()} if loot else {}
    hours = kinds.hours_for(kind, raw.get("opens"), raw.get("closes"))
    blurb = clip(raw.get("blurb"), 120) or clip(re.split(r"(?<=[.!?])\s", description)[0], 120)
    state.update_place(rec["key"], status="real", kind=kind, hours=list(hours) if hours else None,
                       daylight_only=int(not hours), verbs=verbs, loot=loot, description=description, blurb=blurb,
                       real_at=now)
    state.set_meta(**{f"place:{rec['key']}": description})
    settle(state, rec["key"], raw.get("resident"))
    return state.place_row(rec["key"])


def settle(state, key: str, raw) -> dict | None:
    """Someone the design says lives or works at the place becomes a resident: a character met only there (owner
    decision 5). Checked like a new neighbor: a name and a persona, clipped; never Pip or a name already taken."""
    if not isinstance(raw, dict) or not isinstance(raw.get("name"), str) or not isinstance(raw.get("persona"), str):
        return None
    name, persona = clip(raw["name"].strip(" ."), 40), clip(raw["persona"], 800)
    if not name or not persona or name.lower() in {world_pack.active().agent.name.lower()} | {c["name"].lower() for c in state.characters()}:
        return None
    ch = state.add_character(name, "resident", None, persona, 0, 0, about=clip(raw.get("about"), 160), place=key)
    state.log("resident", name=name, place=key, about=ch["about"])
    return ch


async def realise(state, gm, key: str, label: str, rng: random.Random | None = None,
                  now: float | None = None) -> dict | None:
    """Pip has arrived somewhere it has only heard of: one GM call designs it (at most one a day)."""
    now = now or time.time()
    rec = state.place_row(key)
    from . import module_places
    written = module_places.design(state, key) if rec and rec["status"] == "heard" else None
    if written:                                          # a place a module describes (DESIGN-modules.md, step 6): no GM needed
        return design(state, rec, written, rng, now, trusted=True)
    if not gm or not rec or rec["status"] != "heard":
        return None
    if sum((r["real_at"] or 0) > now - DAY for r in state.place_rows()) >= DESIGNS_PER_DAY:
        return None
    said = [f"{m['by']} says: {m['there']}" if m["there"] else f"{m['by']} mentioned it" for m in rec["mentions"]]
    raw = await gm.design_place(label, said, sorted({n for n, _ in known_items(state).values()}))
    return design(state, rec, raw, rng, now)


# --- seams for the characters' prompts (neighbor letters, in-person talk, a new neighbor) -----------------------
MENTION_PROPERTY = {"type": "object", "properties": {
    "place": {"type": "string", "description": "the destination as you said it: the town, wood or shop to walk to"},
    "there": {"type": "string", "description": "what you say is there or is for, under 120 characters"},
    "distance": {"type": "string", "enum": list(DISTANCES)},
    "items": {"type": "array", "items": {"type": "string"}},
}, "required": ["place"]}
PLACES_SHOWN = 8
WALK_WORDS = {"near": "a short walk", "far": "a long walk", VERY_FAR: "too far to walk"}


def known_names(state, settings=None, library=None) -> list[str]:
    """Every place that exists for Pip (built-in, a neighbor's home, invented, very far ones too), as it's said."""
    from . import places  # places builds on this module
    built = [places.label(k) for k in places.registry(state, settings, library) if k != places.HOME]
    return list(dict.fromkeys(built + [places.label(r["key"]) for r in records(state)]))


def mention_instruction(state, settings=None, library=None) -> str:
    """The sentence a character's prompt carries, so the GM reuses known names (half the dedupe) and reports new ones."""
    return (f"Only if your words point {world_pack.active().agent.name} to a place {world_pack.active().agent.they} could go that isn't one of these: "
            f"{', '.join(known_names(state, settings, library))}, give `mentions_place` (`place`: the destination as "
            "you said it; `there`: what you say is there, under 120 characters; `distance`: near, far or very far, "
            "as you'd put it; `items`: things you say can be had there). Not your own home, not landscape you just "
            "pass through.")


def _line_for(state, rec: dict, name: str) -> str:
    from . import places
    told = next((m for m in rec["mentions"] if m["by"] == name), None)
    notes = [f"you told {world_pack.active().agent.name}: {told['there']}"] if told and told["there"] else []
    if rec["status"] == "real":
        found = [f["item"] for f in state.finds_at(rec["key"])[:2]]
        notes.append(f"{world_pack.active().agent.name} has been" + (f" and found {', '.join(found)} there" if found else ""))
    return f"{places.label(rec['key'])}, {WALK_WORDS[rec['distance']]}" + (f" ({'; '.join(notes)})" if notes else "")


def places_line(state, name: str, settings=None, library=None) -> str:
    """'Places in Pip's world: ...' for a character's prompt: what they told Pip about first, then the built-in places
    and neighbors' homes (not their own), then places others mentioned; up to 8."""
    from . import places
    recs = records(state)
    mine = [r for r in recs if any(m["by"] == name for m in r["mentions"])]
    d = world_pack.active().data("places")
    tags = {p["key"]: p["tag"] for p in [d.get("library", {}), *d.get("start", [])] if p.get("tag")}
    built = [places.label(k) + (f" ({tags[k]})" if k in tags else "")
             for k, p in places.registry(state, settings, library).items()
             if k != places.HOME and not p.invented and k != f"{name}{places.HOME_SUFFIX}"]
    parts = ([_line_for(state, r, name) for r in mine] + built
             + [_line_for(state, r, name) for r in recs if r not in mine])[:PLACES_SHOWN]
    return f"Places in {world_pack.active().agent.possessive} world: " + "; ".join(parts) if parts else ""


# --- owner control (GET/PATCH/DELETE /places, pipchat places) ------------------------------------------------------
WALK_CAP = 50   # minutes: a round trip plus a session fits in daylight
PATCHABLE = ("walk_minutes", "hours", "description", "loot")


def remove(state, key: str) -> dict | None:
    """The owner takes a place out of the world: kept for history, never offered, not re-made by the same name."""
    rec = state.place_row(key)
    if not rec or rec["status"] not in ACTIVE:
        return None
    state.update_place(rec["key"], status="removed")
    return state.place_row(rec["key"])


def _walk(raw) -> float | None:
    if raw is None:
        return None
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        raise ValueError("walk_minutes must be a number of minutes (or null: too far to walk)")
    return max(1, min(WALK_CAP, round(raw)))


def patch(state, key: str, changes: dict, rng: random.Random | None = None) -> dict | None:
    """The owner's edits, through the same rules as everything else: walk 1-50 min (null: too far to walk), shop
    hours within the kind's bounds, a description clipped like the GM's, loot built like a design's."""
    rec = state.place_row(key)
    if not rec or rec["status"] not in ACTIVE:
        return None
    unknown = set(changes) - set(PATCHABLE)
    if unknown:
        raise ValueError(f"can't change {', '.join(sorted(unknown))} (only {', '.join(PATCHABLE)})")
    fields = {}
    if "walk_minutes" in changes:
        walk = _walk(changes["walk_minutes"])
        fields.update(walk_minutes=walk, distance=VERY_FAR if walk is None else "near" if walk <= BANDS["near"][1] else "far")
    if "hours" in changes:
        h = changes["hours"]
        if not kinds.KINDS[rec["kind"]].shop_hours or not isinstance(h, list) or len(h) != 2:
            raise ValueError("hours are [opens, closes], and only a shop keeps hours")
        fields["hours"] = list(kinds.hours_for(rec["kind"], *h))
    if "description" in changes:
        fields["description"] = clip(changes["description"], 500)
        if not fields["description"]:
            raise ValueError("a description can't be empty")
    if "loot" in changes:
        if rec["status"] != "real" or not isinstance(changes["loot"], list):
            raise ValueError(f"loot is a list of {{name, kind, tier, description}}, for a place {world_pack.active().agent.name} has been to")
        fields["loot"] = build_loot(changes["loot"], rec["kind"], known_items(state), [], rng or random.Random())
    state.update_place(rec["key"], **fields)
    if "description" in fields:
        state.set_meta(**{f"place:{rec['key']}": fields["description"]})
    return state.place_row(rec["key"])
