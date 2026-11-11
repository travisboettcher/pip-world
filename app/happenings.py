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
from datetime import datetime

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
TONES = ("good", "bad", "neutral")
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
MENDING_QTY = (1, 3)                                                    # units of a material a major mishap asks for
OLD_NOTE_DAYS = 2                                                       # a note this old can come back to mind
MIN_DIARY = 7
LOSS_SHARE = {"medium": (0.10, 0.25, 10), "major": (0.25, 0.50, 25)}   # (low, high, most units) of a stack

DENY = re.compile(r"\b(die|dies|died|dead|death|dying|kill|kills|killed|blood|bleed|bleeding|corpse|suicide|hospital)\b", re.I)
BIG_WORDS = re.compile(r"\b(catastroph\w*|disaster\w*|devastat\w*|destroyed|ruined everything|apocalyp\w*)\b", re.I)
MAX_TEXT = 420
MIN_TEXT = 20
TITLE_MAX = 60


# --- the dice the engine still owns: a secret per install, the season, the lens, the amounts ----------------------------
def salt(state) -> str:
    """A secret per install, so the dice are reproducible here and not guessable from outside."""
    value = state.meta("happenings_salt")
    if not value:
        value = secrets.token_hex(8)
        state.set_meta(happenings_salt=value)
    return value


def season_of(now: float, hemisphere: str = "north") -> str:
    """The meteorological season of a timestamp (December to February is winter in the north; the south is half a year along)."""
    month = datetime.fromtimestamp(now).month - 1
    return SEASON_OF_MONTH[(month + (6 if hemisphere == "south" else 0)) % 12]


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
            "places": [places.label(r["key"]) for r in state.place_rows() if r["status"] == "real"],
            "old_notes": [m for m in diary if m["ts"] < now - OLD_NOTE_DAYS * 86400], "diary_count": len(diary)}


@dataclass
class Plan:
    effects: list = field(default_factory=list)   # structured, applied by apply_effects
    names: list = field(default_factory=list)     # names the text may use
    facts: dict = field(default_factory=dict)     # extra facts for the author (a memory that surfaces)


def _one_of(rng: random.Random, seq):
    return seq[rng.randrange(len(seq))]


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


def _mending_part(rng):
    pool = [e for e in gathering.JUNKYARD if e[1] == "material"]
    entry = rng.choices(pool, weights=[e[2] for e in pool])[0]
    return {"name": entry[0], "qty": rng.randint(*MENDING_QTY)}


def _proper_nouns(text: str) -> list[str]:
    return sorted(set(re.findall(r"\b[A-Z][a-z]+\b", text)))      # Pip's own words: any capitalised word may be a name, sentence-first or not


def _plan_memory(w, tone, severity, rng):
    note = _one_of(rng, w["old_notes"])
    text = clip(note["text"], 200)
    return Plan([], _proper_nouns(text), {"memory": text})


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
FALLBACK = {"good": ("A small good turn", "Something small goes your way."), "bad": ("A small bad turn", "Something small goes against you."),
            "neutral": ("A moment", "Something small happens, and passes.")}


def template(c: dict) -> tuple[str, str]:
    title, text = c.get("fallback") or FALLBACK[c["tone"]]
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


async def record(state, settings, gm, c: dict, w: dict, now: float, slot: str, night: bool = False, by: str = "") -> dict:
    """A decided happening (category, tone, severity, lens, effects): written, stored, applied (unless HAPPENINGS=log) and logged."""
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
              text=text, effects=c["line"], jolt=0 if logged else jolt, status=row["status"], **({"by": by} if by else {}))
    return row


async def from_modules(state, settings, gm, now: float | None = None) -> bool:
    """Write and record the happenings live modules proposed. True when one happened (Pip should hear of it)."""
    now, made = now or time.time(), False
    for m in state.modules("live"):
        if m.get("happen"):
            state.update_module(m["id"], happen=[])
            made |= await from_module(state, settings, gm, m["name"], m["happen"][0], now) is not None
    return made


# --- happenings a module proposes (modules.py, `happen`) --------------------------------------------------------
# A module decides that something happens and what kind of thing changes; the engine sets every amount by the severity, checks every
# target is real and that the tone fits (a good turn only gives, a bad one only takes, a neutral one changes nothing), and keeps the
# day's limits. The words are written and checked as for any happening, and Pip takes it the same way.
INTENTS = ("coins", "item", "food_loss", "crop", "energy", "hunger", "price", "stop", "news", "memory")
INTENTS_MAX, ABOUT_MAX, CATEGORY = 2, 300, re.compile(r"^[a-z][a-z -]{1,23}$")
GAINS, LOSSES = {"coins", "item", "crop", "energy", "hunger", "price", "news"}, {"coins", "food_loss", "crop", "energy", "hunger", "price", "stop", "news"}


def world_names(w: dict) -> set:
    """Every name a happening may mention: neighbors, creations, crops, belongings, tools, places."""
    return {n.lower() for n in [*w["neighbors"], *w["creations"], *(p["crop"] for p in w["plots"]), *(f["name"] for f in w["foods"]), *w["tools"],
                                *(b["key"] for b in w["booths"]), *w.get("places", [])]}


def _intent(w, tone, severity, i: dict, rng) -> Plan:
    """One effect a module asked for, made real by the engine; raises ValueError saying why it can't be."""
    kind = i.get("kind")
    if kind not in INTENTS:
        raise ValueError(f"an effect's kind is one of {', '.join(INTENTS)}")
    if kind == "memory":
        if w["diary_count"] < MIN_DIARY or not w["old_notes"]:
            raise ValueError("Pip has no old thought to come back to it")
        return _plan_memory(w, tone, severity, rng)
    if tone == "neutral":
        raise ValueError("a neutral happening changes nothing (only a memory may come back)")
    if kind not in (GAINS if tone == "good" else LOSSES):
        raise ValueError(f"a {tone} turn can't bring {kind.replace('_', ' ')}")
    sign = 1 if tone == "good" else -1
    if kind == "coins":
        if tone == "bad":
            loss = coin_loss(w["coins"], severity)
            if loss < 1:
                raise ValueError("Pip has no coins to lose")
            return Plan([{"kind": "coins", "delta": -loss}])
        lo, hi = FOUND_COINS[severity]
        return Plan([{"kind": "coins", "delta": rng.randint(lo, hi), **({"gift": True} if i.get("gift") else {})}])
    if kind == "item":
        pool = {e[0]: e for e in gathering.WOODS + gathering.JUNKYARD}
        name = str(i.get("name") or "").strip().lower()
        if name and name not in pool:
            raise ValueError(f"nothing called {name} is found in this world; leave the name out, or use one of: {', '.join(sorted(pool))}")
        item = _found_item(rng, severity, ("food", "seed", "material")) if not name else \
            {"kind": "item", "name": name, "qty": rng.randint(*FOUND_ITEMS[severity]), "item_kind": pool[name][1], "description": pool[name][4], "attrs": pool[name][5]}
        return Plan([{**item, **({"gift": True} if i.get("gift") else {})}], [item["name"]])
    if kind == "food_loss":
        plan = _pest_loss(w, severity, rng, 5)
        if plan is None:
            raise ValueError("there is nothing to lose from the pantry (or Pip is too low for it)")
        return plan
    if kind in ("energy", "hunger"):
        if tone == "bad" and w["low"]:
            raise ValueError("Pip is too low already")
        return Plan([{"kind": kind, "delta": sign * ENERGY[severity] * (1 if kind == "energy" else -1)}])
    if kind == "crop":
        plot = next((p for p in w["plots"] if p["plot"] == i.get("plot")), None)
        if not plot:
            raise ValueError("`plot` is the number of a plot with something growing")
        how = i.get("how", "time")
        if how == "ruin":
            if tone != "bad" or severity != "major":
                raise ValueError("only a major bad turn ruins a crop")
            return Plan([{"kind": "crop_ruin", "plot": plot["plot"], "crop": plot["crop"]}], [plot["crop"]])
        if how == "time":
            shift = round(max(0.0, plot["ready_at"] - w["now"]) / 60 * SHIFT[severity])
            if shift < 1:
                raise ValueError("that crop is as good as ripe")
            return Plan([{"kind": "crop_time", "plot": plot["plot"], "crop": plot["crop"], "factor": 1 - sign * SHIFT[severity], "minutes": sign * shift}],
                        [plot["crop"]])
        if how != "yield":
            raise ValueError("`how` is time, yield or ruin")
        delta = YIELD_GOOD[severity] if tone == "good" else min(YIELD_BAD[severity], plot["yield"] - 1)
        if delta < 1:
            raise ValueError("that crop can't give any less")
        return Plan([{"kind": "crop_yield", "plot": plot["plot"], "crop": plot["crop"], "delta": sign * delta}], [plot["crop"]])
    if kind == "price":
        booth = next((b for b in w["booths"] if b["key"] == i.get("place")), None)
        if not booth:
            raise ValueError("`place` is the key of a place that sells")
        pool = [f["name"] for f in w["foods"]] + [e[0] for e in booth["loot"] or []]
        item = str(i.get("item") or "").strip().lower() or (pool[rng.randrange(len(pool))] if pool else "")
        if not item or item not in {p.lower() for p in pool}:
            raise ValueError(f"`item` is something sold at {booth['key']} or that Pip has")
        return Plan([{"kind": "price", "place": booth["key"], "item": item, "units": sign * PRICE_UNITS[severity]}], [booth["key"], item])
    if kind == "stop":
        c = next((c for c in w["stoppable"] if c["name"].lower() == str(i.get("creation") or "").strip().lower()), None)
        if not c or severity == "minor":
            raise ValueError("`creation` is one of Pip's running things that need tending, and a minor turn stops nothing")
        part = _mending_part(rng) if severity == "major" and i.get("mend") else None
        return Plan([{"kind": "creation_stop", "id": c["id"], "name": c["name"], "part": part}], [c["name"]] + ([part["name"]] if part else []))
    name = next((n for n in w["neighbors"] if n.lower() == str(i.get("name") or "").strip().lower()), None)   # news
    if not name:
        raise ValueError("`name` is one of Pip's neighbors")
    return Plan([{"kind": "news", "name": name, "tone": tone}], [name])


def shape(p) -> None:
    """A proposed happening's form (raises ValueError): what can be checked without looking at the world."""
    if not isinstance(p, dict) or not CATEGORY.match(str(p.get("category") or "")) or p.get("tone") not in TONES \
            or p.get("severity", "minor") not in SEVERITIES:
        raise ValueError("`happen` is {category (a word or two), tone (good, bad, neutral), severity (minor, medium, major), effects?, about?, names?}")
    effects, about, names = p.get("effects") or [], p.get("about") or "", p.get("names") or []
    if not isinstance(effects, list) or len(effects) > INTENTS_MAX or not all(isinstance(e, dict) for e in effects):
        raise ValueError(f"`effects` is a list of up to {INTENTS_MAX} {{kind, ...}}")
    if not isinstance(about, str) or len(about) > ABOUT_MAX or not isinstance(names, list) or not all(isinstance(n, str) for n in names):
        raise ValueError(f"`about` is a line of up to {ABOUT_MAX} characters, and `names` a list of names")
    if any(e.get("kind") not in INTENTS for e in effects):
        raise ValueError(f"an effect's kind is one of {', '.join(INTENTS)}")


def decide(state, settings, p: dict, now: float, rng) -> dict:
    """A module's proposed happening, made concrete: {category, tone, severity, lens, effects, names, facts, line}. Raises ValueError."""
    shape(p)
    effects, about, names = p.get("effects") or [], p.get("about") or "", p.get("names") or []
    tone = p["tone"]
    severity = "minor" if tone == "neutral" else p.get("severity", "minor")
    w = world(state, settings, now)
    unknown = [n for n in names if n.lower() not in world_names(w)]
    if unknown:
        raise ValueError(f"no one and nothing called {unknown[0]} is in Pip's world")
    plan = Plan()
    for i in effects:
        one = _intent(w, tone, severity, i, rng)
        plan.effects += one.effects
        plan.names += one.names
        plan.facts.update(one.facts)
    if len({e["kind"] for e in plan.effects}) < len(plan.effects):
        raise ValueError("one effect of each kind")
    return {"category": p["category"], "tone": tone, "severity": severity, "lens": pick_lens(rng, tone), "effects": plan.effects,
            "names": list(dict.fromkeys(plan.names + names)), "facts": {**plan.facts, **({"about": about.strip()} if about.strip() else {})},
            "line": effects_line(plan.effects)}


def room_for(state, settings, now: float) -> str:
    """Why no happening can come now ('' when one can): the same limits the engine's own keep."""
    if settings.happenings == "off":
        return "happenings are off"
    if unresolved(state):
        return "Pip hasn't taken in the last one yet"
    if sum(1 for h in state.happenings(20) if h["ts"] >= _today_start(now)) >= settings.happenings_max_per_day:
        return f"there have been {settings.happenings_max_per_day} today already"
    if sleepmod.asleep(state) or (state.session() or {}).get("kind") == "walk":
        return "Pip is asleep or out walking"
    return ""


async def from_module(state, settings, gm, name: str, p: dict, now: float) -> dict | None:
    """A happening a module proposed, checked again now, written and recorded (None if it no longer fits: logged as dropped)."""
    rng = random.Random(hashlib.sha256(f"{salt(state)}:{name}:{now}".encode()).hexdigest())
    why = room_for(state, settings, now)
    try:
        c = None if why else decide(state, settings, p, now, rng)
    except ValueError as e:
        why = str(e)
    if why:
        state.log("happening_dropped", module=name, category=str(p.get("category"))[:24], reason=why)
        return None
    w = world(state, settings, now)
    if isinstance(p.get("fallback"), dict) and p["fallback"].get("title") and p["fallback"].get("text"):
        c["fallback"] = (clip(p["fallback"]["title"], TITLE_MAX), clip(p["fallback"]["text"], MAX_TEXT))
    return await record(state, settings, gm, c, w, now, f"module:{name}:{int(now)}", bool(p.get("night")), by=name)


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
async def step(state, settings, gm, now: float | None = None) -> bool:
    """Land the meaning of what Pip has been shown and not read. The dice are a module's (module_library/happenings.py); what modules
    propose is written by `from_modules`."""
    if settings.happenings == "off":
        return False
    resolve_due(state, now or time.time())
    return False


def public_row(h: dict) -> dict:
    """A happening as the public view shows it: what it was and what the engine changed, never the dice."""
    return {k: h[k] for k in ("id", "ts", "category", "tone", "severity", "lens", "read_as", "title", "text", "effects_line", "status")}
