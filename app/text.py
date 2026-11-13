"""Small text helpers shared by the world modules (no app imports, so anything can use them)."""
import re


def span(minutes) -> str:
    """A wait as "45 min", or in whole hours once it is two hours or more ("24 hours")."""
    minutes = int(minutes)
    return f"{minutes} min" if minutes < 120 else f"{round(minutes / 60)} hours"


def clip(text, limit: int) -> str:
    """Collapse whitespace and shorten to `limit` chars, cutting at a sentence end when there is one."""
    text = " ".join(str(text or "").split())
    if len(text) <= limit:
        return text
    cut = text[:limit]
    end = max(cut.rfind(". "), cut.rfind("! "), cut.rfind("? "), cut.rfind("* "))
    return cut[:end + 1] if end > limit // 3 else cut.rsplit(" ", 1)[0] + "..."


def brief(gist, text, limit: int = 200) -> str:
    """A stored one-line summary of something said, or (none stored) its first sentence."""
    return clip(gist, limit) or clip(re.split(r"(?<=[.!?])\s", " ".join(str(text or "").split()), maxsplit=1)[0], limit)


def craft_name(raw) -> str:
    """'Clockmaking (gear train, escapement)' -> 'clockmaking': the core skill, so xp carries across projects. Letters, digits and spaces, as
    the crafting module keys a craft in its store (module_library/crafting.py's craft_name, which this mirrors for the move into it)."""
    text = " ".join(str(raw or "").lower().split())
    for sep in ("(", ",", ";", "/", " - ", ":"):
        text = text.split(sep)[0]
    words = "".join(c if c.isalnum() and c.isascii() else " " for c in text).split()[:3]
    while words and words[-1] in ("and", "or", "of", "with", "the", "for"):
        words.pop()
    return " ".join(words)[:30] or "tinkering"


def coins_text(n: int) -> str:
    return f"{n} coin{'s' if n != 1 else ''}"
