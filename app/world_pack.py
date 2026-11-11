"""World packs (docs/DESIGN-world-packs.md): everything that makes a world *that* world, in one directory the engine loads.

A pack holds `world.json` (its name, and who the agent is: a name, a pronoun, what kind of being), `persona.md` (who the agent is, in its
own words), `narrator.md` (the narrator's voice and the world in a paragraph), `bible.md` (what the builder may add) and `guide/*.md`
(what the agent is told about how its world works). `WORLD_PACK` chooses it; by default it is Pip's world, `worlds/pip`. A pack may leave
any of the prose out. The engine's own fixed instructions to the narrator (`NARRATOR_RULES`) follow the pack's paragraph.
"""
import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

API = 1
DEFAULT = Path(__file__).resolve().parent.parent / "worlds" / "pip"
PRONOUNS = ("it", "she", "he", "they")
NARRATOR_RULES = """Keep the world consistent: things behave the way such things plausibly would, and nothing becomes more powerful
than it is. You never decide what Pip does and you never change a result you are given. Answer only by calling
the `report` tool."""


class PackError(ValueError):
    pass


@dataclass(frozen=True)
class Agent:
    name: str
    pronoun: str = "they"
    kind: str = ""


@dataclass(frozen=True)
class Pack:
    dir: Path
    name: str
    agent: Agent

    def _text(self, rel: str) -> str:
        f = self.dir / rel
        return f.read_text().strip() if f.is_file() else ""

    def persona(self) -> str:
        """Who the agent is (by default, just its name)."""
        return self._text("persona.md") or f"You are {self.agent.name}."

    def narrator(self) -> str:
        return self._text("narrator.md")

    def narrator_system(self) -> str:
        """The narrator's system prompt: the pack's paragraph, then the engine's fixed instructions."""
        return "\n".join(filter(None, [self.narrator(), NARRATOR_RULES]))

    def bible(self) -> str:
        return self._text("bible.md")

    def guide(self, page: str) -> str:
        """One page of the agent's guide ('' if the pack has none by that name)."""
        f = self.dir / "guide" / f"{page}.md"
        return f.read_text().strip("\n") if f.is_file() else ""


def load(settings) -> Pack:
    """The world pack the settings choose (WORLD_PACK), or Pip's world."""
    d = Path(settings.world_pack) if settings.world_pack else DEFAULT
    f = d / "world.json"
    return _load(str(d), f.stat().st_mtime if f.is_file() else 0.0)


@lru_cache(maxsize=8)
def _load(path: str, changed: float = 0.0) -> Pack:
    """The pack at `path` (read again when its world.json changes)."""
    d = Path(path)
    f = d / "world.json"
    if not f.is_file():
        raise PackError(f"world pack {d}: no world.json")
    w = json.loads(f.read_text())
    bad = lambda why: PackError(f"world pack {d}: {why}")  # noqa: E731
    if w.get("api") != API:
        raise bad(f"this engine reads world packs of api {API}")
    a = w.get("agent") or {}
    if not isinstance(a, dict) or not str(a.get("name") or "").strip():
        raise bad("world.json needs an agent with a name")
    pronoun = a.get("pronoun", "they")
    if pronoun not in PRONOUNS:
        raise bad(f"the agent's pronoun is one of {', '.join(PRONOUNS)}")
    return Pack(d, str(w.get("name") or d.name), Agent(str(a["name"]).strip(), pronoun, str(a.get("kind") or "")))
