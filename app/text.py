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


def coins_text(n: int) -> str:
    return f"{n} coin{'s' if n != 1 else ''}"
