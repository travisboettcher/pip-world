"""Happenings: small events from the world (docs/DESIGN-happenings.md).

The engine decides everything mechanical: whether anything happens (a percentage roll per slot of awake time), the category, tone, severity, the
effects and their caps, and the emotion lens. The model is asked once for the words. Every effect is applied by code from a fixed menu, and the
engine appends what really changed to the text, so the prose can be vivid and still be only prose.
"""
import hashlib
import random
import re
import secrets
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from . import emotions as emo
from . import creations as cr
from . import gathering, market
from . import sleep as sleepmod
from .state import name_key
from .text import clip, span

SEVERITIES = ("minor", "medium", "major")
LENS_AMOUNT = {"minor": 4, "medium": 9, "major": 16}
NEUTRAL_AMOUNT = 2
JOLT_SHARE = 0.3                  # the part of a happening that is a startle (surprise); the rest is meaning, which Pip reads
SLOT_WINDOW = 30 * 60             # a slot is rolled within this long of its start, or skipped
COOLDOWN_HOURS = 12               # a category does not repeat within this
TONE_WEIGHTS = {"good": 35, "bad": 25, "neutral": 40}
PITY = 0.3                        # after two bad ones in a row bad is this much as likely
CROSSOVER = 0.2                   # how often the lens is the unusual one for the tone
LENS_USUAL = {"bad": ("sadness", "fear", "anger", "disgust"), "good": ("joy", "trust", "anticipation"), "neutral": ("surprise", "anticipation")}
LENS_CROSS = {"bad": ("joy", "anticipation", "trust"), "good": ("sadness", "fear"), "neutral": emo.NAMES}
RESOLVE_AFTER_TICKS = 2           # a happening is shown, then Pip gets one more tick to read it
RESOLVE_AFTER_MINUTES = 45        # or this long awake after it was first shown
LOW_HUNGER, LOW_ENERGY = 0.8, 0.25
ENERGY_FLOOR, HUNGER_CEILING = 0.1, 0.95
FRESH_HOURS = 3                   # a resolved happening stays in Pip's prompt this long

SHIFT = {"minor": 0.05, "medium": 0.15, "major": 0.30}                 # share of a crop's time left
ENERGY = {"minor": 0.05, "medium": 0.12, "major": 0.25}
PRICE_UNITS = {"minor": 1, "medium": 3, "major": 6}                    # one unit is 4% of a booth's price (market.PRICE_STEP)
COIN_CAPS = {"minor": (3, 0.10), "medium": (10, 0.20), "major": (25, 0.35)}   # (coins, share of the purse) a loss may take
FOUND_COINS = {"minor": (1, 3), "medium": (3, 10), "major": (8, 25)}
FOUND_ITEMS = {"minor": (1, 1), "medium": (2, 4), "major": (4, 6)}
YIELD_BAD = {"minor": 1, "medium": 2, "major": 3}
YIELD_GOOD = {"minor": 1, "medium": 2, "major": 3}
SEASONS = ("winter", "spring", "summer", "autumn")
SEASON_OF_MONTH = ("winter", "winter", "spring", "spring", "spring", "summer", "summer", "summer", "autumn", "autumn", "autumn", "winter")   # January first
# What a season makes likelier (a missing entry is 1): which categories come up, and the tone of a category (see DESIGN-happenings.md, "Seasons").
SEASON_CATEGORY = {
    "winter": {"garden": 0.5, "creature": 1.2, "pantry": 1.3, "body": 1.3, "mishap": 1.2, "atmosphere": 1.4, "found": 0.8},
    "spring": {"garden": 1.5, "creature": 1.3, "found": 1.2, "kindness": 1.1, "atmosphere": 1.1},
    "summer": {"garden": 1.2, "pantry": 1.5, "creature": 1.1, "market": 1.2, "body": 0.9},
    "autumn": {"found": 1.4, "creature": 1.2, "memory": 1.5, "market": 1.2, "atmosphere": 1.2, "garden": 0.9},
}
SEASON_TONE = {
    "winter": {("body", "bad"): 1.5, ("garden", "bad"): 1.3, ("body", "good"): 0.8},
    "spring": {("garden", "good"): 1.4, ("body", "good"): 1.3},
    "summer": {("pantry", "bad"): 1.4, ("garden", "good"): 1.1},
    "autumn": {("memory", "bad"): 1.4, ("found", "good"): 1.2},
}
NIGHT_STALE_HOURS = 2             # a night is rolled within this long of waking, or not at
MENDING_QTY = (1, 3)                                                    # units of a material a major mishap asks for
OLD_NOTE_DAYS = 2                                                       # a note this old can come back to mind
MIN_DIARY = 7
LOSS_SHARE = {"medium": (0.10, 0.25, 10), "major": (0.25, 0.50, 25)}   # (low, high, most units) of a stack

DENY = re.compile(r"\b(die|dies|died|dead|death|dying|kill|kills|killed|blood|bleed|bleeding|corpse|suicide|hospital)\b", re.I)
BIG_WORDS = re.compile(r"\b(catastroph\w*|disaster\w*|devastat\w*|destroyed|ruined everything|apocalyp\w*)\b", re.I)
MAX_TEXT = 420
MIN_TEXT = 20
TITLE_MAX = 60


# --- slots and the roll ------------------------------------------------------------------------------------
def slot_starts(settings, day: date) -> list[tuple[str, float]]:
    """The slots of the awake day that begins at `day`'s wake hour: (key, start timestamp), `happenings_slot_hours` apart."""
    wake, bed = settings.wake_hour, settings.bedtime_hour
    length = (bed - wake) % 24 or 24
    midnight = datetime(day.year, day.month, day.day)
    out, k = [], 0
    while k * settings.happenings_slot_hours < length:
        start = midnight + timedelta(hours=wake + k * settings.happenings_slot_hours)
        out.append((f"{day.isoformat()}#{k}", start.timestamp()))
        k += 1
    return out


def current_slot(settings, now: float) -> tuple[str, float]:
    """The latest slot that has started, of today's or yesterday's awake day (yesterday's first slot has always started)."""
    today = datetime.fromtimestamp(now).date()
    started = [s for d in (today - timedelta(days=1), today) for s in slot_starts(settings, d) if s[1] <= now]
    return max(started, key=lambda s: s[1])


def salt(state) -> str:
    """A secret per install, so the dice are reproducible here and not guessable from outside."""
    value = state.meta("happenings_salt")
    if not value:
        value = secrets.token_hex(8)
        state.set_meta(happenings_salt=value)
    return value


def roll_slot(state, settings, slot: str, now: float) -> bool:
    """Roll a slot once (the roll is recorded, so a restart cannot roll it again); True when it is a hit."""
    done = state.happening_roll(slot)
    if done:
        return bool(done["hit"])
    roll = random.Random(f"{salt(state)}:{slot}").random()
    hit = roll < settings.happenings_chance
    state.add_happening_roll(slot, now, roll, hit)
    return hit


# --- the dice -------------------------------------------------------------------------------------------------
def pick_severity(rng: random.Random, weights) -> str:
    return rng.choices(SEVERITIES, weights=weights)[0]


def season_of(now: float, hemisphere: str = "north") -> str:
    """The meteorological season of a timestamp (December to February is winter in the north; the south is half a year along)."""
    month = datetime.fromtimestamp(now).month - 1
    return SEASON_OF_MONTH[(month + (6 if hemisphere == "south" else 0)) % 12]


def category_weight(season: str | None, category: str) -> float:
    return SEASON_CATEGORY.get(season, {}).get(category, 1)


def tone_factor(season: str | None, category: str, tone: str) -> float:
    return SEASON_TONE.get(season, {}).get((category, tone), 1)


def pick_tone(rng: random.Random, allowed, recent, factors: dict | None = None) -> str | None:
    """Good, bad or neutral from the base weights (times the season's factors), bad much less likely after two bad ones in a row."""
    tones = [t for t in TONE_WEIGHTS if t in allowed]
    if not tones:
        return None
    factors = factors or {}
    weights = [TONE_WEIGHTS[t] * factors.get(t, 1) * (PITY if t == "bad" and list(recent[:2]) == ["bad", "bad"] else 1) for t in tones]
    return rng.choices(tones, weights=weights)[0]


def pick_lens(rng: random.Random, tone: str) -> str:
    """The emotion the event is written through: usually the one that fits the tone, sometimes the unexpected one."""
    return rng.choice(LENS_CROSS[tone] if rng.random() < CROSSOVER else LENS_USUAL[tone])


def lens_amount(tone: str, severity: str) -> int:
    return NEUTRAL_AMOUNT if tone == "neutral" else LENS_AMOUNT[severity]


def split_amount(amount: int) -> tuple[int, int]:
    """(jolt, meaning): the startle that lands at once and the meaning that waits for Pip's reading."""
    jolt = round(amount * JOLT_SHARE)
    return jolt, amount - jolt


# --- amounts (pure, so they can be tested exactly) --------------------------------------------------------------
def coin_loss(purse: int, severity: str) -> int:
    cap, share = COIN_CAPS[severity]
    return min(cap, int(purse * share))


def food_loss(stack: int, severity: str, u: float) -> int:
    """Units of a stack lost: a minor loss is 1; medium and major take a share (u in 0-1 picks where in the range) up to a cap; one always stays."""
    if stack < 2:
        return 0
    if severity == "minor":
        return 1
    low, high, most = LOSS_SHARE[severity]
    return max(1, min(most, round(stack * (low + (high - low) * u))))      # a share of at most half, so one always stays


# --- the world as the dice see it ---------------------------------------------------------------------------------
def world(state, settings, now: float) -> dict:
    """The facts the categories and the author may use."""
    from . import places  # places imports sleep, and this module is imported by the loop: keep the import local
    agent = state.agent()
    plots = [g for g in state.garden(now) if g["state"] == "growing"]
    foods = sorted((i for i in state.items() if i["kind"] == "food"), key=lambda i: -i["qty"])
    booths = [r for r in state.place_rows() if r["status"] == "real" and "buy" in places.invented_place(r).verbs]
    creations = state.creations()
    diary = state.memories("diary", limit=500)
    return {"now": now, "coins": state.coins(), "hunger": agent["hunger"], "energy": agent["energy"],
            "season": season_of(now, settings.hemisphere) if settings.happenings_seasons else None,
            "low": agent["hunger"] >= LOW_HUNGER or agent["energy"] <= LOW_ENERGY,
            "plots": plots, "foods": foods, "booths": booths, "period": sleepmod.period(settings, now),
            "neighbors": [c["name"] for c in state.characters("neighbor")],
            "creations": [c["name"] for c in creations],
            "stoppable": [{"id": c["id"], "name": c["name"]} for c in creations if "upkeep" in c["spec"]["capabilities"] and cr.running(c, now)],
            "tools": [i["name"] for i in state.items() if i["kind"] == "tool"],
            "old_notes": [m for m in diary if m["ts"] < now - OLD_NOTE_DAYS * 86400], "diary_count": len(diary)}


@dataclass
class Plan:
    effects: list = field(default_factory=list)   # structured, applied by apply_effects
    names: list = field(default_factory=list)     # names the text may use
    facts: dict = field(default_factory=dict)     # extra facts for the author (a memory that surfaces)


def _one_of(rng: random.Random, seq):
    return seq[rng.randrange(len(seq))]


def _plan_garden(w, tone, severity, rng):
    plot = _one_of(rng, w["plots"])
    crop = plot["crop"]
    if tone == "neutral":
        return Plan([], [crop])
    sign = 1 if tone == "good" else -1
    if tone == "bad" and severity == "major" and rng.random() < 0.5:
        return Plan([{"kind": "crop_ruin", "plot": plot["plot"], "crop": crop}], [crop])
    if rng.random() < 0.5:
        left = max(0.0, plot["ready_at"] - w["now"])
        shift = round(left / 60 * SHIFT[severity])
        if shift < 1:
            return None
        return Plan([{"kind": "crop_time", "plot": plot["plot"], "crop": crop, "factor": 1 - sign * SHIFT[severity], "minutes": sign * shift}], [crop])
    delta = YIELD_GOOD[severity] if tone == "good" else min(YIELD_BAD[severity], plot["yield"] - 1)
    if delta < 1:
        return None
    return Plan([{"kind": "crop_yield", "plot": plot["plot"], "crop": crop, "delta": sign * delta}], [crop])


def _find_pool(kinds) -> list:
    return [e for e in gathering.WOODS if e[1] in kinds]


def _found_item(rng, severity, kinds):
    entry = rng.choices(_find_pool(kinds), weights=[e[2] for e in _find_pool(kinds)])[0]
    lo, hi = FOUND_ITEMS[severity]
    return {"kind": "item", "name": entry[0], "qty": rng.randint(lo, hi), "item_kind": entry[1], "description": entry[4], "attrs": entry[5]}


def _pest_loss(w, severity, rng, smallest):
    stacks = [i for i in w["foods"] if i["qty"] >= smallest]
    if w["low"] or not stacks:
        return None
    stack = stacks[0]
    return Plan([{"kind": "food_loss", "name": stack["name"], "qty": food_loss(stack["qty"], severity, rng.random())}], [stack["name"]])


def _plan_creature(w, tone, severity, rng):
    if tone == "neutral":
        return Plan()
    if tone == "good":
        item = _found_item(rng, severity, ("seed", "material"))
        return Plan([item], [item["name"]])
    return _pest_loss(w, severity, rng, 5)


def _plan_pantry(w, tone, severity, rng):
    if tone == "neutral":
        return Plan()
    return _pest_loss(w, severity, rng, 20)


def _plan_found(w, tone, severity, rng):
    if tone == "neutral":
        return Plan()
    if tone == "bad":
        loss = coin_loss(w["coins"], severity)
        return Plan([{"kind": "coins", "delta": -loss}]) if loss >= 1 else None
    if rng.random() < 0.5:
        item = _found_item(rng, severity, ("food", "seed", "material"))
        return Plan([item], [item["name"]])
    lo, hi = FOUND_COINS[severity]
    return Plan([{"kind": "coins", "delta": rng.randint(lo, hi)}])


def _plan_body(w, tone, severity, rng):
    if tone == "neutral":
        return Plan()
    sign = 1 if tone == "good" else -1
    if tone == "bad" and w["low"]:
        return None
    stat = _one_of(rng, ("energy", "hunger"))
    return Plan([{"kind": stat, "delta": sign * ENERGY[severity] * (1 if stat == "energy" else -1)}])


def _plan_market(w, tone, severity, rng):
    booth = _one_of(rng, w["booths"])
    held = [i["name"] for i in w["foods"]]
    table = [e[0] for e in (booth["loot"] or [])]
    pool = held or table
    if not pool:
        return None
    item = _one_of(rng, pool)
    if tone == "neutral":
        return Plan([], [booth["key"], item])
    units = PRICE_UNITS[severity] * (1 if tone == "good" else -1)
    return Plan([{"kind": "price", "place": booth["key"], "item": item, "units": units}], [booth["key"], item])


def _mending_part(rng):
    pool = [e for e in gathering.JUNKYARD if e[1] == "material"]
    entry = rng.choices(pool, weights=[e[2] for e in pool])[0]
    return {"name": entry[0], "qty": rng.randint(*MENDING_QTY)}


def _plan_mishap(w, tone, severity, rng):
    if tone == "neutral":
        return Plan([], w["tools"][:1])
    if severity == "minor":
        return None if w["low"] else Plan([{"kind": "energy", "delta": -ENERGY["minor"]}], w["tools"][:1])
    if not w["stoppable"]:
        return None
    c = _one_of(rng, w["stoppable"])
    part = _mending_part(rng) if severity == "major" else None
    return Plan([{"kind": "creation_stop", "id": c["id"], "name": c["name"], "part": part}], [c["name"]] + ([part["name"]] if part else []))


def _plan_neighbor(w, tone, severity, rng):
    name = _one_of(rng, w["neighbors"])
    return Plan([] if tone == "neutral" else [{"kind": "news", "name": name, "tone": tone}], [name])


def _proper_nouns(text: str) -> list[str]:
    return sorted(set(re.findall(r"\b[A-Z][a-z]+\b", text)))      # Pip's own words: any capitalised word may be a name, sentence-first or not


def _plan_memory(w, tone, severity, rng):
    note = _one_of(rng, w["old_notes"])
    text = clip(note["text"], 200)
    return Plan([], _proper_nouns(text), {"memory": text})


def _plan_kindness(w, tone, severity, rng):
    name = _one_of(rng, w["neighbors"])
    if rng.random() < 0.5:
        item = {**_found_item(rng, severity, ("food", "seed", "material")), "gift": True}
        return Plan([item], [item["name"], name])
    lo, hi = FOUND_COINS[severity]
    return Plan([{"kind": "coins", "delta": rng.randint(lo, hi), "gift": True}], [name])


def _plan_atmosphere(w, tone, severity, rng):
    return Plan()


@dataclass(frozen=True)
class Category:
    name: str
    tones: tuple
    needs: object      # (world) -> bool
    plan: object       # (world, tone, severity, rng) -> Plan | None
    night: bool = True # can it happen while Pip sleeps (and be found on waking)?


CATEGORIES = {c.name: c for c in (
    Category("garden", ("good", "bad", "neutral"), lambda w: bool(w["plots"]), _plan_garden),
    Category("creature", ("good", "bad", "neutral"), lambda w: True, _plan_creature),
    Category("pantry", ("bad", "neutral"), lambda w: True, _plan_pantry),
    Category("found", ("good", "bad", "neutral"), lambda w: True, _plan_found),
    Category("body", ("good", "bad", "neutral"), lambda w: True, _plan_body),
    Category("market", ("good", "bad", "neutral"), lambda w: bool(w["booths"]), _plan_market, night=False),
    Category("mishap", ("bad", "neutral"), lambda w: bool(w["stoppable"] or w["tools"]), _plan_mishap),
    Category("neighbor", ("good", "bad", "neutral"), lambda w: bool(w["neighbors"]), _plan_neighbor, night=False),
    Category("memory", ("good", "bad", "neutral"), lambda w: w["diary_count"] >= MIN_DIARY and bool(w["old_notes"]), _plan_memory),
    Category("kindness", ("good",), lambda w: bool(w["neighbors"]), _plan_kindness),
    Category("atmosphere", ("neutral",), lambda w: True, _plan_atmosphere),
)}


def build(state, settings, w: dict, now: float, rng: random.Random, night: bool = False) -> dict | None:
    """Choose a happening for the world as it is: category, tone, severity, effects and lens. None when nothing is possible."""
    recent = state.happenings(2 * len(CATEGORIES) + 10)       # more than the categories there are, so every one in its cooldown is seen
    cooling = {h["category"] for h in recent if now - h["ts"] < COOLDOWN_HOURS * 3600 and h["status"] != "skipped"}
    last_tones = [h["tone"] for h in recent]
    options = [c for c in CATEGORIES.values() if c.name not in cooling and c.needs(w) and (c.night or not night)]
    season = w.get("season")
    while options:
        cat = rng.choices(options, weights=[category_weight(season, c.name) for c in options])[0]
        tone = pick_tone(rng, cat.tones, last_tones, {t: tone_factor(season, cat.name, t) for t in cat.tones})
        severity = "minor" if tone == "neutral" else pick_severity(rng, settings.happenings_severity)
        plan = cat.plan(w, tone, severity, rng)
        if plan is not None:
            return {"category": cat.name, "tone": tone, "severity": severity, "lens": pick_lens(rng, tone),
                    "effects": plan.effects, "names": plan.names, "facts": plan.facts, "line": effects_line(plan.effects)}
        options.remove(cat)
    return None


# --- effects: described, then applied ---------------------------------------------------------------------------
def _percent(delta: float) -> int:
    return round(abs(delta) * 100)


def _count(qty: int, name: str) -> str:
    """'1 stick', '3 sticks': a name is kept as the world spells it, but one of it is one."""
    from .state import _singular
    if qty != 1:
        return f"{qty} {name}"
    words = name.split()
    return f"1 {' '.join(words[:-1] + [_singular(words[-1])])}"


def describe(e: dict) -> str:
    kind = e["kind"]
    if kind == "coins":
        return f"You {('are given' if e.get('gift') else 'find') if e['delta'] > 0 else 'lose'} {market.coins_text(abs(e['delta']))}."
    if kind == "item":
        return f"You {'are given' if e.get('gift') else 'find'} {_count(e['qty'], e['name'])}."
    if kind == "creation_stop":
        mend = f"{e['part']['qty']} {e['part']['name']} to mend, then " if e.get("part") else ""
        return f"Your {e['name']} stops; it needs {mend}tending."
    if kind == "news":
        return f"You hear news of {e['name']}."
    if kind == "food_loss":
        return f"You lose {_count(e['qty'], e['name'])}."
    if kind == "crop_time":
        return f"Plot {e['plot']}'s {e['crop']} will be ready about {span(abs(e['minutes']))} {'sooner' if e['minutes'] > 0 else 'later'}."
    if kind == "crop_yield":
        return f"Plot {e['plot']}'s {e['crop']} will give {abs(e['delta'])} {'more' if e['delta'] > 0 else 'less'}."
    if kind == "crop_ruin":
        return f"Plot {e['plot']}'s {e['crop']} is lost."
    if kind in ("energy", "hunger"):
        return f"Your {kind} {'rises' if e['delta'] > 0 else 'falls'} by {_percent(e['delta'])}%."
    if kind == "price":
        pct = round(abs((1 + market.PRICE_STEP) ** e["units"] - 1 if e["units"] > 0 else 1 - (1 - market.PRICE_STEP) ** -e["units"]) * 100)
        return f"{e['item'].capitalize()} fetches about {pct}% {'more' if e['units'] > 0 else 'less'} at {e['place']} for now."
    raise ValueError(f"unknown effect {kind!r}")


def effects_line(effects: list) -> str:
    """What really changed, in the engine's words: appended to the story and the only part that is true."""
    return "(" + " ".join(describe(e) for e in effects) + ")" if effects else ""


def apply_effects(state, effects: list, now: float, title: str = "") -> None:
    for e in effects:
        kind = e["kind"]
        if kind == "coins":
            state.add_coins("pip", max(e["delta"], -state.coins()))
        elif kind == "item":
            state.add_item(e["name"], e["qty"], e["item_kind"], e["description"], e["attrs"])
        elif kind == "food_loss":
            have, _ = state.find_item(e["name"], kind="food")
            if have and have["qty"] > 1:
                state.take_item(have["id"], min(e["qty"], have["qty"] - 1))
        elif kind == "crop_time":
            state.scale_plot_time(e["plot"], e["factor"], now)
        elif kind == "crop_yield":
            state.add_plot_yield(e["plot"], e["delta"])
        elif kind == "crop_ruin":
            state.clear_plot(e["plot"])
        elif kind == "energy":
            state.update_agent(energy=max(ENERGY_FLOOR, min(1.0, state.agent()["energy"] + e["delta"])))
        elif kind == "hunger":
            state.update_agent(hunger=max(0.0, min(HUNGER_CEILING, state.agent()["hunger"] + e["delta"])))
        elif kind == "price":
            market.nudge(state, e["place"], e["item"], e["units"], now)
        elif kind == "creation_stop":
            c = next((c for c in state.creations() if c["id"] == e["id"]), None)
            if c and "upkeep" in c["spec"]["capabilities"]:
                rt = dict(c["runtime"])
                rt["halted_at"] = now
                if e.get("part"):
                    rt["needs_part"] = e["part"]
                state.set_runtime(c["id"], rt)
        elif kind == "news":
            from . import neighbors
            ch = next((c for c in state.characters("neighbor") if c["name"] == e["name"]), None)
            if ch and title:
                state.update_character(ch["id"], life=(ch["life"] + [clip(title, 200)])[-neighbors.LIFE_KEPT:])


# --- the words ----------------------------------------------------------------------------------------------------
LENS_CLAUSE = {"joy": "You can't help smiling.", "sadness": "It leaves you a little low.", "anger": "It rankles.", "fear": "It unsettles you.",
               "trust": "It feels like the world is on your side.", "disgust": "You'd rather not look too closely.",
               "surprise": "You didn't see that coming.", "anticipation": "You wonder what comes next."}
TEMPLATES = {
    ("garden", "good"): ("A kind spell", "The light is kind to the garden this morning."),
    ("garden", "bad"): ("A bad turn", "Something is off in the garden: a chill, a pest, a wind."),
    ("garden", "neutral"): ("The garden shifts", "The air in the garden changes, and then settles again."),
    ("creature", "good"): ("A small visitor", "A small creature comes by and leaves something behind."),
    ("creature", "bad"): ("Nibbling", "Something has been at the pantry in the night."),
    ("creature", "neutral"): ("Watched", "A small creature watches you from the fence, then wanders off."),
    ("pantry", "bad"): ("Turned", "Some of what you stored has turned."),
    ("pantry", "neutral"): ("The shelves", "You look over the shelves and find everything as it was."),
    ("found", "good"): ("A small find", "You come across something small and useful."),
    ("found", "bad"): ("A hole in a pocket", "You find a hole in your pocket where something should be."),
    ("found", "neutral"): ("An odd thing", "You notice an odd little thing and turn it over."),
    ("body", "good"): ("Rested", "You wake with a lightness you hadn't expected."),
    ("body", "bad"): ("A rough day", "Your body is slow and heavy today."),
    ("body", "neutral"): ("A yawn", "A great yawn takes you by surprise."),
    ("market", "good"): ("Good word", "You hear that things are selling well."),
    ("market", "bad"): ("Bad word", "You hear the shelves are full and buyers are few."),
    ("market", "neutral"): ("Market talk", "You hear some idle talk about the market."),
    ("mishap", "bad"): ("Something slips", "Something in the workshop slips, jars or gives way."),
    ("mishap", "neutral"): ("A squeak", "Something in the workshop squeaks, and nothing is wrong."),
    ("neighbor", "good"): ("Good news", "Word comes from a neighbor that things are going well."),
    ("neighbor", "bad"): ("A small worry", "Word comes from a neighbor of a small worry."),
    ("neighbor", "neutral"): ("Neighbourly talk", "You hear a little idle talk about a neighbor."),
    ("memory", "good"): ("A fond thought", "An old thought of your own comes back to you."),
    ("memory", "bad"): ("A wistful thought", "An old thought of your own comes back, and lingers."),
    ("memory", "neutral"): ("A thought returns", "An old thought of your own comes back and puzzles you."),
    ("kindness", "good"): ("Left for you", "Someone has left something for you and gone."),
    ("atmosphere", "neutral"): ("In the air", "You notice a sound, a light, a smell, and then it is gone."),
}


def template(c: dict) -> tuple[str, str]:
    title, text = TEMPLATES[(c["category"], c["tone"])]
    memory = (c.get("facts") or {}).get("memory")
    if memory:                                                  # the thought itself, not just that there was one
        text = f"An old thought of your own comes back to you: \"{memory}\""
    return title, f"{text} {LENS_CLAUSE[c['lens']]}"


def trim(text: str) -> str:
    """A text a little over the limit is cut at the last sentence that fits, rather than thrown away."""
    if len(text) <= MAX_TEXT:
        return text
    cut = text[:MAX_TEXT]
    end = max(cut.rfind(mark) for mark in ".!?")
    return cut[:end + 1].rstrip() if end + 1 >= MIN_TEXT else text


def valid_text(text: str, line: str, names, severity: str, tone: str) -> tuple[bool, str]:
    """The checks a model-written text must pass; (ok, reason)."""
    text = " ".join(str(text or "").split())
    if not MIN_TEXT <= len(text) <= MAX_TEXT:
        return False, "length"
    if DENY.search(text):
        return False, "a word that is not allowed"
    if (severity == "minor" or tone == "neutral") and BIG_WORDS.search(text):
        return False, "bigger than the event"
    allowed = {name_key(word) for n in names for word in str(n).split()} | {"pip"}
    for m in re.finditer(r"(?<![.!?]\s)(?<!^)\b[A-Z][a-z]+\b", text):
        if name_key(m.group(0)) not in allowed and m.group(0) != "You":
            return False, f"a name that was not offered: {m.group(0)}"
    digits = set(re.findall(r"\d+", text))
    if digits - set(re.findall(r"\d+", line)):
        return False, "a number the effects do not have"
    return True, ""


async def author(gm, c: dict, facts: dict, recent: list[str], log=None) -> tuple[str, str, str]:
    """(title, text, who wrote it): the model's if it passes the checks (one retry), else the template for the category. `log(reason, attempt)`
    hears why a try was turned down."""
    if gm:
        for attempt in (1, 2):
            out = await gm.write_happening(c["category"], c["tone"], c["severity"], c["lens"], c["line"], facts, recent)
            text = trim(" ".join(str((out or {}).get("text") or "").split()))
            title = clip((out or {}).get("title"), TITLE_MAX).strip(" .")
            names = c["names"] + facts.get("names", []) + ([facts["memory"]] if facts.get("memory") else [])
            ok, why = valid_text(text, c["line"] + " " + facts.get("memory", ""), names, c["severity"], c["tone"])
            if ok and title:
                return title, text, "gm"
            if log:
                log(why if not ok else "no title", attempt)
    title, text = template(c)
    return title, text, "template"


# --- making one --------------------------------------------------------------------------------------------------
def _today_start(now: float) -> float:
    return datetime.fromtimestamp(now).replace(hour=0, minute=0, second=0, microsecond=0).timestamp()


async def create(state, settings, gm, w: dict, now: float, slot: str, rng: random.Random, night: bool = False) -> dict | None:
    """One happening for this slot: chosen, written, applied (unless HAPPENINGS=log) and logged. None when nothing fits."""
    c = build(state, settings, w, now, rng, night)
    if not c:
        return None
    recent = [h["title"] for h in state.happenings(5)]
    facts = {"period": w["period"], "names": list(w["neighbors"]) + list(w["creations"]) + [p["crop"] for p in w["plots"]], **c["facts"],
             **({"season": w["season"]} if w.get("season") else {}), **({"night": True} if night else {})}
    title, text, who = await author(gm, c, facts, recent,
                                    lambda why, n: state.log("happening_rejected", category=c["category"], reason=why, attempt=n))
    amount = lens_amount(c["tone"], c["severity"])
    jolt, meaning = split_amount(amount)
    logged = settings.happenings == "log"
    row = state.add_happening(ts=now, slot=slot, category=c["category"], tone=c["tone"], severity=c["severity"], lens=c["lens"],
                              seed=f"{salt(state)}:{slot}", context={"period": w["period"], "names": c["names"], **c["facts"], **({"night": True} if night else {})}, effects=c["effects"],
                              effects_line=c["line"], meaning={"emotion": c["lens"], "amount": meaning, "jolt": jolt, "shown_at": None},
                              text=text, title=title, author=who, status="logged" if logged else "applied")
    if not logged:
        apply_effects(state, c["effects"], now, title)
    state.log("happening", id=row["id"], category=c["category"], tone=c["tone"], severity=c["severity"], lens=c["lens"], title=title,
              text=text, effects=c["line"], jolt=0 if logged else jolt, status=row["status"])
    return row


# --- Pip's reading -----------------------------------------------------------------------------------------------
def unresolved(state) -> list[dict]:
    return [h for h in state.happenings(10) if h["status"] == "applied"]


def resolve(state, h: dict, emotion: str | None) -> dict:
    """Land a happening's meaning on one emotion (the lens by default, or what Pip says; None: nothing)."""
    read_as = emotion or "nothing"
    moves = {emotion: h["meaning"]["amount"]} if emotion else {}
    state.update_happening(h["id"], read_as=read_as, status="resolved")
    state.log("happening_felt", id=h["id"], title=h["title"], lens=h["lens"], read_as=read_as, differs=read_as != h["lens"], moves=moves)
    return state.happening(h["id"])


def feel(state, settings, emotion: str, about=None, now: float | None = None) -> tuple[bool, str]:
    """Pip says how it takes something that just happened (one of the eight emotions, or 'nothing'). Records a report when nothing is waiting."""
    now = now or time.time()
    emotion = str(emotion or "").strip().lower()
    if emotion != "nothing" and emotion not in emo.NAMES:
        return False, f"you can feel one of: {', '.join(emo.NAMES)}, or nothing"
    waiting = unresolved(state)
    if about is not None:
        try:
            waiting = [h for h in waiting if h["id"] == int(about)]
        except (TypeError, ValueError):
            return False, "about is the number of what happened"
    if not waiting:
        state.log("felt", emotion=emotion, levels={k: round(v) for k, v in emo.levels(state, now).items()})
        return True, f"you note that you feel {emotion}" if emotion != "nothing" else "you note that you feel nothing in particular"
    h = waiting[0]
    resolve(state, h, None if emotion == "nothing" else emotion)
    if emotion == "nothing":
        return True, f"you let {h['title'].lower()} pass"
    return True, f"you take {h['title'].lower()} as {emotion}" + ("" if emotion == h["lens"] else f" (it was written as {h['lens']})")


def perception(state, tools, now: float) -> list[str]:
    """What Pip is told about a happening that is fresh or waiting to be read, and counts each showing."""
    lines = []
    for h in state.happenings(5):
        if h["status"] not in ("applied", "resolved"):
            continue
        waiting = h["status"] == "applied"
        if not waiting and now - h["ts"] > FRESH_HOURS * 3600:
            continue
        lines.append(f"Something happened: {h['title']}. {h['text']} {h['effects_line']}".rstrip())
        if waiting:
            if "feel" in tools:
                lines.append("How it lands is up to you; feel says how you take it.")
            meaning = h["meaning"]
            state.update_happening(h["id"], ticks_seen=h["ticks_seen"] + 1,
                                   meaning={**meaning, "shown_at": meaning.get("shown_at") or now})
    return lines


def resolve_due(state, now: float) -> bool:
    """Land the meaning of happenings Pip has been shown and has not read: one more tick later, or 45 minutes awake after the first showing."""
    if sleepmod.asleep(state):
        return False
    changed = False
    for h in unresolved(state):
        shown = h["meaning"].get("shown_at")
        if h["ticks_seen"] >= RESOLVE_AFTER_TICKS or (shown and now - shown >= RESOLVE_AFTER_MINUTES * 60):
            resolve(state, h, h["lens"])
            changed = True
    return changed


# --- the monitor's step ------------------------------------------------------------------------------------------
async def _night(state, settings, gm, now: float) -> bool:
    """When Pip has woken, roll once for each slot it slept through; a hit is something that happened in the night, found on waking."""
    woke = next((e for e in state.events(200) if e["kind"] == "woke"), None)
    if not woke or sleepmod.asleep(state) or state.meta("happenings_night") == str(woke["id"]):
        return False
    state.set_meta(happenings_night=woke["id"])                                      # one go per sleep, whatever comes of it
    slots = int(woke["data"]["hours"] // settings.happenings_slot_hours)
    if slots < 1 or now - woke["ts"] > NIGHT_STALE_HOURS * 3600:
        return False
    if unresolved(state) or sum(1 for h in state.happenings(20) if h["ts"] >= _today_start(now)) >= settings.happenings_max_per_day:
        return False
    key = f"night:{woke['id']}"
    hits = [k for k in range(slots) if roll_slot(state, settings, f"{key}#{k}", now)]        # every slot is rolled and recorded
    if not hits:
        return False
    slot = f"{key}#{hits[0]}"
    rng = random.Random(hashlib.sha256(f"{salt(state)}:{slot}:build".encode()).hexdigest())
    return await create(state, settings, gm, world(state, settings, now), now, slot, rng, night=True) is not None


async def step(state, settings, gm, now: float | None = None) -> bool:
    """Resolve what is due and, at the start of a slot, roll for a new happening. True when something happened that Pip should hear about."""
    if settings.happenings == "off":
        return False
    now = now or time.time()
    resolve_due(state, now)
    if await _night(state, settings, gm, now):
        return True
    slot = current_slot(settings, now)
    if now - slot[1] > SLOT_WINDOW or state.happening_roll(slot[0]):
        return False
    busy = sleepmod.asleep(state) or (state.session() or {}).get("kind") == "walk" or unresolved(state)
    if busy or sum(1 for h in state.happenings(20) if h["ts"] >= _today_start(now)) >= settings.happenings_max_per_day:
        return False
    if not roll_slot(state, settings, slot[0], now):
        return False
    rng = random.Random(hashlib.sha256(f"{salt(state)}:{slot[0]}:build".encode()).hexdigest())
    return await create(state, settings, gm, world(state, settings, now), now, slot[0], rng) is not None


def replay(state, settings, h: dict) -> dict:
    """Roll a happening's slot again from its stored seed, to check the dice: the recorded roll, whether it still matches, and what the chance says now."""
    roll = random.Random(h["seed"]).random()
    recorded = state.happening_roll(h["slot"])
    return {"id": h["id"], "slot": h["slot"], "seed": h["seed"], "roll": roll, "recorded_roll": recorded["roll"] if recorded else None,
            "matches": bool(recorded) and recorded["roll"] == roll, "chance": settings.happenings_chance, "would_hit": roll < settings.happenings_chance,
            "decided": {k: h[k] for k in ("category", "tone", "severity", "lens")}}


def public_row(h: dict) -> dict:
    """A happening as the public view shows it: what it was and what the engine changed, never the dice."""
    return {k: h[k] for k in ("id", "ts", "category", "tone", "severity", "lens", "read_as", "title", "text", "effects_line", "status")}
