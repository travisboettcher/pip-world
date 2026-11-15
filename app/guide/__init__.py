"""The guide: how this world works, told to the agent at every wake (see DESIGN-extract.md, "Persona: ship a world manual, not a character").

The pages are the world pack's (`guide/<name>.md`, docs/DESIGN-world-packs.md), and each says when it applies and where it goes, in a
front matter of its own (docs/DESIGN-engine-audit.md, B2), so the agent is never told about something it cannot do and a smaller setup
costs fewer tokens:

    ---
    order: 60
    when: tool start_project
    ---

`when` is one or more conditions joined by "and": `always`; `tool a|b` (any of those tools is enabled); `setting name` (that setting is
on: set, and not "off") or `setting name=value`; `library` (books are mounted); `stakes` (one of the world's stats can run out);
`reflection` (the agent reflects at night). Pages go in `order` (a page without front matter applies always, after the rest), and
`bullet: yes` puts one in the closing "Guidelines" list instead of a paragraph. The engine keeps only the conditions; which page needs
what is the page's. It is a manual in a neutral voice; it never says who the agent is, how it feels or how it should behave towards
people. That is the *persona* (the pack's `persona.md`, or the deployment's `PERSONA_PATH`), put in front of the guide.
"""
import dataclasses
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from .. import stats
from .. import world_pack

FRONT = re.compile(r"\A---\n(.*?)\n---\n?", re.S)
LAST = 10_000                                                  # where a page that doesn't say goes: after the rest
ALWAYS = (("always", ""),)
PREDICATES = {
    "always": lambda s, lib: True,
    "library": lambda s, lib: lib,
    "stakes": lambda s, lib: any(d.get("at_zero") for d in stats.declared(s).values()),   # a stat that can run out
    "reflection": lambda s, lib: s.reflect_hour < 24,
}


@dataclass(frozen=True)
class Page:
    name: str
    text: str
    order: float = LAST
    when: tuple = ALWAYS          # ((kind, argument), ...), all of which must hold
    bullet: bool = False          # a line of the closing "Guidelines" list rather than a paragraph


def _settings() -> set:
    from ..config import Settings
    return {f.name for f in dataclasses.fields(Settings)}


def _condition(c: str) -> tuple[str, str]:
    kind, _, arg = c.strip().partition(" ")
    arg = arg.strip()
    if kind in PREDICATES and not arg:
        return kind, ""
    if kind == "tool" and re.fullmatch(r"[a-z_]+(\|[a-z_]+)*", arg):
        return kind, arg
    if kind == "setting" and arg.partition("=")[0] in _settings() and " " not in arg:
        return kind, arg
    raise ValueError(f"`when` is conditions joined by \"and\": always, tool a|b, setting name (or name=value: one of the engine's "
                     f"settings), library, stakes, reflection; not {c.strip()!r}")


def parse(name: str, raw: str) -> Page:
    """A page and its front matter. Raises ValueError saying what's wrong with it."""
    m = FRONT.match(raw)
    if not m:
        return Page(name, raw.strip("\n"))
    meta = {}
    for line in m.group(1).splitlines():
        key, sep, value = line.partition(":")
        if not sep or key.strip() not in ("order", "when", "bullet"):
            raise ValueError(f"guide/{name}.md: its front matter is lines of order, when and bullet, not {line.strip()!r}")
        meta[key.strip()] = value.strip()
    try:
        order = float(meta.get("order", LAST))
    except ValueError:
        raise ValueError(f"guide/{name}.md: `order` is a number") from None
    if meta.get("bullet", "no") not in ("yes", "no"):
        raise ValueError(f"guide/{name}.md: `bullet` is yes or no")
    try:
        when = tuple(_condition(c) for c in meta["when"].split(" and ")) if "when" in meta else ALWAYS
    except ValueError as e:
        raise ValueError(f"guide/{name}.md: {e}") from None
    return Page(name, raw[m.end():].strip("\n"), order, when, meta.get("bullet") == "yes")


def applies(page: Page, tools: set, settings, library: bool) -> bool:
    def holds(kind, arg):
        if kind == "tool":
            return any(t in tools for t in arg.split("|"))
        if kind == "setting":
            name, eq, want = arg.partition("=")
            value = getattr(settings, name)
            return str(value) == want if eq else bool(value) and value != "off"
        return PREDICATES[kind](settings, library)
    return all(holds(k, a) for k, a in page.when)


def pages(pack) -> tuple:
    """The pack's guide pages, in order (checked: a page that can't be read raises ValueError)."""
    files = sorted((pack.dir / "guide").glob("*.md"))         # none, if the pack has no guide
    return _pages(tuple((str(f), f.stat().st_mtime) for f in files))


@lru_cache(maxsize=8)
def _pages(files: tuple) -> tuple:
    return tuple(sorted((parse(Path(f).stem, Path(f).read_text()) for f, _ in files), key=lambda p: (p.order, p.name)))


def render(tools, settings, library: bool) -> str:
    """The manual for what is enabled: paragraphs, then the Guidelines list."""
    tools, pack = set(tools), world_pack.load(settings)
    paragraphs, bullets = [], []
    for page in pages(pack):
        if page.text and applies(page, tools, settings, library):
            (bullets if page.bullet else paragraphs).append(page.text)
    return "\n\n".join(paragraphs + (["Guidelines:\n" + "\n".join(bullets)] if bullets else []))
