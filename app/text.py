"""Small text helpers shared by the world modules (no app imports, so anything can use them)."""


def clip(text, limit: int) -> str:
    """Collapse whitespace and shorten to `limit` chars, cutting at a sentence end when there is one."""
    text = " ".join(str(text or "").split())
    if len(text) <= limit:
        return text
    cut = text[:limit]
    end = max(cut.rfind(". "), cut.rfind("! "), cut.rfind("? "), cut.rfind("* "))
    return cut[:end + 1] if end > limit // 3 else cut.rsplit(" ", 1)[0] + "..."


def craft_name(raw) -> str:
    """'Clockmaking (gear train, escapement)' -> 'clockmaking': the core skill, so xp carries across projects."""
    text = " ".join(str(raw or "").lower().split())
    for sep in ("(", ",", ";", "/", " - ", ":"):
        text = text.split(sep)[0]
    words = text.strip(" .").split()[:3]
    while words and words[-1] in ("and", "or", "of", "with", "the", "for", "&"):
        words.pop()
    return " ".join(words)[:30] or "tinkering"
