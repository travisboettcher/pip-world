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
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, replace
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
KEY = re.compile(r"^[a-z][a-z0-9_]{0,23}$")
HOME_KEYS = {"key", "description", "called", "aliases", "about", "offers"}
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
    key: str = ""                  # which agent this is, in a world of several (docs/DESIGN-multi-agent.md): a word, from the name by default
    home: str = ""                 # its own home (json, shaped as places.json's `home`), or "" for the world's
    persona_file: str = ""         # its persona in the pack, or "" for persona.md
    temperament: tuple = ()        # where its feelings rest: (emotion, 0-100) pairs over the engine's baselines (emotions.baseline)
    knows: tuple = ()              # the other agents it already knows when the world starts (neighbours), by key; the rest it meets by chance
    role: str = ""                 # what it does in this world (a word): guide pages may be for a role (`when: role villager`)

    @property
    def home_place(self) -> dict:
        return json.loads(self.home) if self.home else {}

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
    agent: Agent                    # the first of its agents, and the only one in most worlds
    modules: tuple | None = None    # what the world runs: ((where, name, params), ...), `std` the engine's, `pack` its own; None: all the engine ships
    agents: tuple = ()              # everyone who lives in it with a mind of their own (world.json `agents`, or just `agent`)

    def agent_named(self, key: str) -> Agent | None:
        """One of its agents by key ("": the first)."""
        return next((a for a in self.agents if a.key == key), None) if key else self.agent

    def module(self, name: str) -> tuple[dict, str]:
        """One of the pack's own modules (`modules/<name>.json` and `.py`): (manifest, source)."""
        d = self.dir / "modules"
        return json.loads((d / f"{name}.json").read_text()), (d / f"{name}.py").read_text()

    def _text(self, rel: str) -> str:
        f = self.dir / rel
        return f.read_text().strip() if f.is_file() else ""

    def persona(self, agent: Agent | None = None) -> str:
        """Who an agent is (the first by default): its own persona file, else persona.md for the first, else just its name."""
        agent = agent or self.agent
        text = self._text(agent.persona_file) if agent.persona_file else self._text("persona.md") if agent is self.agent else ""
        return text or f"You are {agent.name}."

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
_acting: ContextVar = ContextVar("acting", default=None)      # (Agent, its State): who the code running now is acting for


def default() -> Pack:
    """Pip's world: the pack an engine runs when nothing says otherwise."""
    return _load(str(DEFAULT), (DEFAULT / "world.json").stat().st_mtime)


def active() -> Pack:
    """The world this engine is running (set when the agent starts: `set_active`); Pip's world until then. Its `agent` is the one acting
    now (`acting`), else its first."""
    pack = _active[0] if _active else default()
    who = _acting.get()
    return replace(pack, agent=who[0]) if who and who[0] is not pack.agent else pack


@contextmanager
def acting(agent: Agent, state=None):
    """Run what follows as `agent` (its loop, a tick, a request about it): whatever names the agent names it, and the narrator spends
    from its State. Each asyncio task carries its own (contextvars), so agents' loops don't see each other's."""
    token = _acting.set((agent, state))
    try:
        yield
    finally:
        _acting.reset(token)


def acting_state():
    """The State of the agent acting now, or None (the world's own steps)."""
    who = _acting.get()
    return who[1] if who else None


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
    agents = tuple(_agent(d, a, bad) for a in (w.get("agents") or [w.get("agent")]))
    keys = [a.key for a in agents]
    dup = next((k for k in keys if keys.count(k) > 1), None)
    if dup:
        raise bad(f"two agents can't share the key {dup!r}")
    if any(k not in keys or k == a.key for a in agents for k in a.knows):
        raise bad("an agent's `knows` lists other agents of this world by key")
    try:
        _sprite(str(d / "sprite.json"))
    except ValueError as e:
        raise bad(f"sprite.json: {e}") from None
    pack = Pack(d, str(w.get("name") or d.name), agents[0], _modules(d, w.get("modules"), bad), agents)
    from . import creations, guide
    try:
        guide.pages(pack)                                   # each page says when it applies: checked once, here
        creations.check_catalogue(pack.data("content"))     # what a made thing can notice and do, in the engine's words
    except ValueError as e:
        raise bad(str(e)) from None
    return pack


def _agent(d: Path, a, bad) -> Agent:
    """One agent of world.json (`agent`, or each of `agents`)."""
    if not isinstance(a, dict) or not str(a.get("name") or "").strip():
        raise bad("world.json needs an agent with a name")
    pronoun = a.get("pronoun", "they")
    if pronoun not in PRONOUNS:
        raise bad(f"the agent's pronoun is one of {', '.join(PRONOUNS)}")
    look = a.get("look", {})
    if not isinstance(look, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in look.items()):
        raise bad("the agent's `look` maps a look's fields to words, like {\"hair\": \"auburn\"}")
    name = str(a["name"]).strip()
    key = a.get("key", re.sub(r"[^a-z0-9_]", "", name.lower()))
    if not isinstance(key, str) or not KEY.match(key):
        raise bad("an agent's `key` is a word in lower case")
    home = a.get("home") or {}
    if home and (not isinstance(home, dict) or set(home) - HOME_KEYS or not isinstance(home.get("key"), str)
                 or not isinstance(home.get("description"), str)):
        raise bad("an agent's `home` is {key, description, called?, aliases?, about?, offers?}")
    persona = a.get("persona") or ""
    if persona and not (d / persona).is_file():
        raise bad(f"the agent {key}'s persona {persona} isn't in the pack")
    from .emotions import NAMES
    temper = a.get("temperament", {"baseline": {}})
    rest = temper.get("baseline") if isinstance(temper, dict) and set(temper) <= {"baseline"} else None
    if not isinstance(rest, dict) or any(k not in NAMES or not isinstance(v, int) or isinstance(v, bool) or not 0 <= v <= 100
                                         for k, v in rest.items()):
        raise bad(f"an agent's `temperament` is {{\"baseline\": {{emotion: 0-100}}}}, emotions among {', '.join(NAMES)}")
    role = a.get("role", "")
    if not isinstance(role, str) or (role and not KEY.match(role)):
        raise bad("an agent's `role` is a word in lower case")
    knows = a.get("knows", [])
    if not isinstance(knows, list) or not all(isinstance(k, str) for k in knows):
        raise bad("an agent's `knows` lists other agents of this world by key")
    return Agent(name, pronoun, str(a.get("kind") or ""), str(a.get("lives") or ""), tuple(look.items()), key,
                 json.dumps(home, sort_keys=True) if home else "", persona, tuple(rest.items()), tuple(knows), role)


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
