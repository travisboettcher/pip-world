"""A world's tone (docs/DESIGN-world-packs.md, phase 3): what may happen in it and how big, from the pack's tone.json.

The pack says which words a happening may not use (`deny`), which words are too big for a small turn (`big_words`), how long a happening's
text and title may be (`text`), and the size of each effect by severity (`sizes`). Words are regular expressions matched as whole words.

Under every pack is the engine's floor, which no pack can lower: no sexual content, nothing that encourages or describes self-harm, nothing
about real people, and real-world news never presented as the world's own. The floor is in the narrator's instructions
(`world_pack.FLOOR_RULES`, after every pack's own), in the words every happening is checked against (`FLOOR_WORDS`, added to any pack's),
and in the name check that turns down any name the world did not offer.
"""
import re
from functools import lru_cache

from . import world_pack

FLOOR_WORDS = (r"sex", r"sexual\w*", r"sexy", r"erotic\w*", r"nude", r"porn\w*", r"rap(?:e|ed|es|ing|ist)", r"orgasm\w*",
               r"suicid\w*", r"self[- ]harm\w*", r"kill(?:ing|ed)? (?:yourself|myself|himself|herself|themselves|themself)",
               r"cut(?:ting)? (?:yourself|myself|himself|herself|themselves|themself)")
DEFAULTS = {
    "deny": [], "big_words": [],
    "text": {"min": 20, "max": 420, "title_max": 60},
    "sizes": {
        "lens": {"minor": 4, "medium": 9, "major": 16},                 # how strongly a happening is felt
        "stat": {"minor": 0.05, "medium": 0.12, "major": 0.25},          # a stat's change
        "coin_caps": {"minor": [3, 0.10], "medium": [10, 0.20], "major": [25, 0.35]},   # (coins, share of the purse) a loss may take
        "found_coins": {"minor": [1, 3], "medium": [3, 10], "major": [8, 25]},
        "found_items": {"minor": [1, 1], "medium": [2, 4], "major": [4, 6]},
        "food_loss": {"medium": [0.10, 0.25, 10], "major": [0.25, 0.50, 25]},     # (low, high, most units) of a stack
        "mending_qty": [1, 3],                                           # units of a material a major mishap asks for
    },
}


def tone(pack=None) -> dict:
    """The pack's tone over the engine's defaults (each size table replaced whole, the text limits key by key)."""
    t = (pack or world_pack.active()).data("tone")
    return {"deny": list(t.get("deny", [])), "big_words": list(t.get("big_words", [])),
            "text": {**DEFAULTS["text"], **t.get("text", {})}, "sizes": {**DEFAULTS["sizes"], **t.get("sizes", {})}}


@lru_cache(maxsize=16)
def _words(words: tuple):
    return re.compile(r"\b(?:" + "|".join(words) + r")\b", re.I) if words else None


def deny(pack=None):
    """The words no happening may use: the engine's floor and the pack's own."""
    return _words(FLOOR_WORDS + tuple(tone(pack)["deny"]))


def big_words(pack=None):
    """Words too big for a minor or neutral turn (None if the pack names none)."""
    return _words(tuple(tone(pack)["big_words"]))


def text(name: str) -> int:
    """A text limit: `min`, `max` or `title_max`."""
    return tone()["text"][name]


def size(name: str, severity: str | None = None):
    """An effect's size for a severity (or the whole entry, for one with no severities)."""
    s = tone()["sizes"][name]
    return s if severity is None else s[severity]
