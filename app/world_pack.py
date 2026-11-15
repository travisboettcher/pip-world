"""World packs (docs/DESIGN-world-packs.md): everything that makes a world *that* world, in one directory the engine loads.

A pack holds `world.json` (its name, and who the agent is: a name, a pronoun, what kind of being), `persona.md` (who the agent is, in its
own words), `narrator.md` (the narrator's voice and the world in a paragraph), `bible.md` (what the builder may add) and `guide/*.md`
(what the agent is told about how its world works). `WORLD_PACK` chooses it; by default it is Pip's world, `worlds/pip`. A pack may leave
any of the prose out. The engine's own fixed instructions to the narrator (`NARRATOR_RULES`) follow the pack's paragraph. How the agent
looks in a scene: `sprite.json` (its own pixel frames, SPRITE_FRAMES of them), else the agent's `look` in world.json (words from the
pack's scene.json `look` lists, the same a character's look is chosen from), else a look drawn from its name and persona. A pack's `web/`
is its page (docs/DESIGN-engine-audit.md, B5).
"""
import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

API = 1
DEFAULT = Path(__file__).resolve().parent.parent / "worlds" / "pip"
PRONOUNS = ("it", "she", "he", "they")
LIBRARY = Path(__file__).resolve().parent / "module_library"     # the engine's own modules (`std:` in a pack's `modules`)
MODULE_NAME = re.compile(r"^[a-z][a-z0-9-]{2,39}$")
NARRATOR_RULES = """Keep the world consistent: things behave the way such things plausibly would, and nothing becomes more powerful
than it is. You never decide what {agent} does and you never change a result you are given. Answer only by calling
the `report` tool."""
FLOOR_RULES = ("Whatever the world: no sexual content; nothing that encourages or describes self-harm; nothing about real people; "
               "and real-world news is never told as this world's own.")   # the engine's floor (app/tone.py): no pack lowers it


class PackError(ValueError):
    pass


SPRITE_FRAMES = 10   # sprite.json's frames, in order: 0-1 standing, 2-5 walking, 6 asleep, 7-8 working (two beats), 9 sitting
FORMS = {"it": ("it", "its", "itself"), "she": ("her", "her", "herself"), "he": ("him", "his", "himself"), "they": ("them", "their", "themself")}


@dataclass(frozen=True)
class Agent:
    """Who the agent is. Engine prompts use the name where a sentence's subject is the agent (so verbs agree in any world), and the
    object, possessive and reflexive forms elsewhere."""
    name: str
    pronoun: str = "they"
    kind: str = ""
    lives: str = ""                # where and how the agent lives, for prompts that need it ("lives alone in a workshop with a garden")
    look: tuple = ()               # world.json's `look`, as (field, word) pairs: how a scene draws the agent without a sprite.json

    @property
    def they(self) -> str:
        """The subject form: only before a verb that agrees with any of them (a past tense, a "can")."""
        return self.pronoun

    @property
    def them(self) -> str:
        return FORMS[self.pronoun][0]

    @property
    def their(self) -> str:
        return FORMS[self.pronoun][1]

    @property
    def themself(self) -> str:
        return FORMS[self.pronoun][2]

    @property
    def possessive(self) -> str:
        """The name's possessive: "the agent's"."""
        return f"{self.name}'s"


@dataclass(frozen=True)
class Pack:
    dir: Path
    name: str
    agent: Agent
    modules: tuple | None = None    # what the world runs: ((where, name, params), ...), `std` the engine's, `pack` its own; None: all the engine ships

    def module(self, name: str) -> tuple[dict, str]:
        """One of the pack's own modules (`modules/<name>.json` and `.py`): (manifest, source)."""
        d = self.dir / "modules"
        return json.loads((d / f"{name}.json").read_text()), (d / f"{name}.py").read_text()

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
        return "\n".join(filter(None, [self.narrator(), NARRATOR_RULES.format(agent=self.agent.name), FLOOR_RULES]))

    def bible(self) -> str:
        return self._text("bible.md")

    def data(self, name: str) -> dict:
        """One of the pack's data files (`<name>.json`: scene, items, places...), or {} if it has none."""
        return _data(str(self.dir / f"{name}.json"))

    def sprite(self) -> dict | None:
        """The agent's own pixel frames (sprite.json, checked when the pack loads): {w, h, palette, frames}, or None."""
        return _sprite(str(self.dir / "sprite.json"))


@lru_cache(maxsize=32)
def _data(path: str) -> dict:
    f = Path(path)
    return json.loads(f.read_text()) if f.is_file() else {}


_active: list = []


def active() -> Pack:
    """The world this engine is running (set when the agent starts: `set_active`); Pip's world until then."""
    return _active[0] if _active else _load(str(DEFAULT), (DEFAULT / "world.json").stat().st_mtime)


def set_active(pack: Pack) -> None:
    _active[:] = [pack]


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
    look = a.get("look", {})
    if not isinstance(look, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in look.items()):
        raise bad("the agent's `look` maps a look's fields to words, like {\"hair\": \"auburn\"}")
    try:
        _sprite(str(d / "sprite.json"))
    except ValueError as e:
        raise bad(f"sprite.json: {e}") from None
    pack = Pack(d, str(w.get("name") or d.name), Agent(str(a["name"]).strip(), pronoun, str(a.get("kind") or ""), str(a.get("lives") or ""),
                                                       tuple(look.items())), _modules(d, w.get("modules"), bad))
    from . import creations, guide
    try:
        guide.pages(pack)                                   # each page says when it applies: checked once, here
        creations.check_catalogue(pack.data("content"))     # what a made thing can notice and do, in the engine's words
    except ValueError as e:
        raise bad(str(e)) from None
    return pack


@lru_cache(maxsize=8)
def _sprite(path: str) -> dict | None:
    """sprite.json: {"palette": {letter: colour}, "frames": [rows, ...]}, every frame a pixel picture of the same size."""
    from . import art
    raw = _data(path)
    if not raw:
        return None
    frames = raw.get("frames")
    if not isinstance(frames, list) or len(frames) != SPRITE_FRAMES:
        raise ValueError(f"`frames` is a list of {SPRITE_FRAMES} pixel pictures: 0-1 standing, 2-5 walking, 6 asleep, 7-8 working, 9 sitting")
    out = []
    for i, rows in enumerate(frames):
        try:
            rows, palette = art.clean_pixels(rows, raw.get("palette"))
        except art.SvgRejected as e:
            raise ValueError(f"frame {i}: {e}") from None
        out.append(rows)
    if len({(len(r), len(r[0])) for r in out}) > 1:
        raise ValueError("every frame is the same size")
    return {"w": len(out[0][0]), "h": len(out[0]), "palette": palette, "frames": out}


def _modules(d: Path, raw, bad) -> tuple | None:
    """world.json's `modules`: each `"std:<name>"` (one the engine ships), `"<pack>:<name>"` (the pack's own, in `modules/`), or
    `{"module": ..., "params": {...}}` to set its params. None when the pack names none: it runs everything the engine ships."""
    if raw is None:
        return None
    if not isinstance(raw, list):
        raise bad("`modules` is a list")
    out = []
    for e in raw:
        spec, params = (e, {}) if isinstance(e, str) else (e.get("module"), e.get("params", {})) if isinstance(e, dict) else (None, None)
        where, _, name = str(spec or "").partition(":")
        if not MODULE_NAME.match(name) or where not in ("std", d.name) or not isinstance(params, dict):
            raise bad(f'each of `modules` is "std:<name>" (the engine\'s), "{d.name}:<name>" (the pack\'s own, in modules/), or '
                      '{"module": ..., "params": {...}}')
        files = (LIBRARY / name, ) if where == "std" else (d / "modules" / name, )
        if not all(f.with_suffix(x).is_file() for f in files for x in (".json", ".py")):
            raise bad(f"no module {spec}: " + ("the engine ships none by that name" if where == "std" else f"modules/{name}.json and .py are needed"))
        out.append(("std" if where == "std" else "pack", name, params))
    if len({n for _, n, _ in out}) < len(out):
        raise bad("each module once in `modules`")
    return tuple(out)
