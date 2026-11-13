"""Kinds of invented place (see DESIGN-invented-places.md, "The kind registry").

A place a character mentions becomes real on Pip's first arrival as one of these kinds. The GM proposes the kind; the
engine keeps it only if the characters' own words back it (a shop needs a shop word), and otherwise falls back to the
kind the words suggest, or a `sight`: a destination with a description and nothing to do. The kind decides everything
mechanical: the verbs (only the existing shared `gather` and `browse`, never a new tool), the hours, what the loot table
may hold and how fast it restocks. The kinds are the world pack's (places.json `kinds`); to add one, add an entry there.
"""
import re
from dataclasses import dataclass, field
from functools import lru_cache

from . import world_pack

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
    trades: bool = False                        # has booths: the trade module's buy, sell and pay work here
    stalls: bool = False                        # Pip may set out a stall of its own here, and customers stop while it is there


def registry() -> dict[str, PlaceKind]:
    """The kinds of place the active world can grow (its pack's places.json `kinds`)."""
    return _registry(id(world_pack.active()))


@lru_cache(maxsize=8)
def _registry(_pack) -> dict[str, PlaceKind]:
    raw = world_pack.active().data("places").get("kinds", {})
    return {name: PlaceKind(name, k["help"], tuple(k.get("words", ())), {v: tuple(x) for v, x in (k.get("verbs") or {}).items()},
                            tuple(k.get("loot_kinds", ())), k.get("max_tools", 0), k.get("capacity", 120), k.get("refill", 15),
                            k.get("shop_hours", False), tuple(k.get("session", DEFAULT_SESSION)), k.get("trades", False), k.get("stalls", False))
            for name, k in raw.items()}


def _places() -> dict:
    return world_pack.active().data("places")


def fallback() -> str:
    return _places().get("fallback_kind", "sight")


def __getattr__(name):            # the old constant names, from the active world
    if name == "KINDS":
        return registry()
    if name == "FALLBACK":
        return fallback()
    if name == "SHOP_DEFAULT_HOURS":
        return tuple(_places().get("shop_default_hours", (9, 17)))
    if name in ("OPENS", "CLOSES"):
        return tuple(_places().get(name.lower(), (7, 10) if name == "OPENS" else (16, 19)))
    raise AttributeError(name)


def _says(kind: PlaceKind, text: str) -> bool:
    tokens = re.findall(r"[a-z]+", str(text or "").lower())
    return any(t.startswith(w) or t.endswith(w) for t in tokens for w in kind.words)


def guess(text: str) -> str:
    """The kind the words suggest: the first whose words appear, else a sight."""
    return next((k.name for k in registry().values() if k.words and _says(k, text)), fallback())


def check(proposed, text: str) -> str:
    """A GM-proposed kind, kept only if the words back it (a sight needs none); otherwise what the words suggest."""
    k = registry().get(proposed) if isinstance(proposed, str) else None
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
    if not registry()[kind].shop_hours:
        return None
    p = _places()
    opens_, closes_, default = p.get("opens", (7, 10)), p.get("closes", (16, 19)), p.get("shop_default_hours", (9, 17))
    return (_hour(opens, *opens_, default[0]), _hour(closes, *closes_, default[1]))


def gm_lines() -> str:
    """The kinds, for the GM's design prompt."""
    return "; ".join(f"{k.name} ({k.help})" for k in registry().values())
