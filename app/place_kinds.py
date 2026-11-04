"""Kinds of invented place (see DESIGN-invented-places.md, "The kind registry").

A place a character mentions becomes real on Pip's first arrival as one of these kinds. The GM proposes the kind; the
engine keeps it only if the characters' own words back it (a shop needs a shop word), and otherwise falls back to the
kind the words suggest, or a `sight`: a destination with a description and nothing to do. The kind decides everything
mechanical: the verbs (only the existing shared `gather` and `browse`, never a new tool), the hours, what the loot table
may hold and how fast it restocks. To add a kind, add one entry here; nothing else needs to know.
"""
import re
from dataclasses import dataclass, field

DEFAULT_SESSION = (15, 60)


@dataclass(frozen=True)
class PlaceKind:
    name: str
    help: str                                   # told to the GM: what this kind is
    words: tuple[str, ...]                      # one must appear in what the characters said (as a word, its start or end)
    verbs: dict = field(default_factory=dict)   # tool -> (default short help, gerund for gather or None)
    loot_kinds: tuple[str, ...] = ()            # item kinds the loot table may hold
    max_tools: int = 0
    capacity: float = 120                       # minutes of good gathering the place holds
    refill: float = 15                          # ...and how many come back per hour
    shop_hours: bool = False                    # bounded opening hours (else: open in daylight)
    session: tuple[int, int] = DEFAULT_SESSION  # how long a gather there may be
    trades: bool = False                        # has booths: buy, sell and pay work here (see market.py)
    stalls: bool = False                        # Pip may set out a stall of its own here, and customers stop while it is there


KINDS: dict[str, PlaceKind] = {k.name: k for k in (
    PlaceKind("wild", "somewhere outdoors to forage: a wood, a shore, a marsh edge",
              ("wood", "forest", "copse", "grove", "orchard", "shore", "beach", "flats", "meadow", "field", "hill",
               "marsh", "fen", "heath", "moor", "dune", "cliff", "bog", "river", "stream", "brook"),
              {"gather": ("forage for what grows here", "foraging")}, ("material", "food", "seed")),
    PlaceKind("yard", "somewhere to dig through what's been left: a scrapyard, a quarry, a tip",
              ("scrap", "heap", "quarry", "tip", "dump", "yard", "wreck", "salvage"),
              {"gather": ("scavenge through what's lying about", "scavenging"),
               "browse": ("look over what's lying about to see what's worth digging for", None)},
              ("material", "tool"), max_tools=1),
    PlaceKind("shop", "somewhere that keeps things to sell: an ironmonger, a chandler, a seed merchant",
              ("shop", "monger", "merchant", "chandler", "smith", "sells", "keeps", "stall", "store", "baker",
               "grocer", "draper"),
              {"browse": ("see what's in stock today", None),
               "gather": ("ask to pick through the drawers, on account", "rummaging")},
              ("tool", "material", "food", "seed"), max_tools=2, capacity=40, refill=2, shop_hours=True, session=(15, 30), trades=True),
    PlaceKind("market", "somewhere with several booths to buy from and sell to: a market square, a bazaar, a quayside market",
              ("market", "bazaar", "quay"),
              {"browse": ("walk the booths and see what's on offer and at what price", None)},
              ("tool", "material", "food", "seed"), max_tools=3, capacity=80, refill=4, shop_hours=True, trades=True, stalls=True),
    PlaceKind("sight", "somewhere just to go and see: a lighthouse, a ruin, a lake with a view", ()),
)}
FALLBACK = "sight"
SHOP_DEFAULT_HOURS = (9, 17)
OPENS, CLOSES = (7, 10), (16, 19)


def _says(kind: PlaceKind, text: str) -> bool:
    tokens = re.findall(r"[a-z]+", str(text or "").lower())
    return any(t.startswith(w) or t.endswith(w) for t in tokens for w in kind.words)


def guess(text: str) -> str:
    """The kind the words suggest: the first whose words appear, else a sight."""
    return next((k.name for k in KINDS.values() if k.words and _says(k, text)), FALLBACK)


def check(proposed, text: str) -> str:
    """A GM-proposed kind, kept only if the words back it (a sight needs none); otherwise what the words suggest."""
    k = KINDS.get(proposed) if isinstance(proposed, str) else None
    if k and (not k.words or _says(k, text)):
        return k.name
    return guess(text)


def _hour(raw, lo: int, hi: int, default: int) -> int:
    try:
        return max(lo, min(hi, int(raw)))
    except (TypeError, ValueError):
        return default


def hours_for(kind: str, opens=None, closes=None) -> tuple[int, int] | None:
    """Opening hours: a shop opens 7-10 and closes 16-19 (so at least six hours); other kinds keep daylight instead."""
    if not KINDS[kind].shop_hours:
        return None
    return (_hour(opens, *OPENS, SHOP_DEFAULT_HOURS[0]), _hour(closes, *CLOSES, SHOP_DEFAULT_HOURS[1]))


def gm_lines() -> str:
    """The kinds, for the GM's design prompt."""
    return "; ".join(f"{k.name} ({k.help})" for k in KINDS.values())
