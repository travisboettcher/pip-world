"""Lasting changes Pip can make to its world (see DESIGN-creations.md, "Pip changes its world").

A finished project may carry a `world` capability naming one effect from this registry. The GM proposes it only for work that
plainly made that kind of change; the engine then checks it (the effect exists, the project is hard enough, the project's own
words are about it, the world has room under a hard cap) and applies it once. Anything lasting that is *not* in this registry
still happens as an ordinary creation: a pond Pip digs is a thing in the world with a description, just without a mechanical
effect. To give a new kind of change teeth, add one entry here (a few lines): nothing else needs to know.
"""
from dataclasses import dataclass
from typing import Callable
from . import world_pack


@dataclass(frozen=True)
class WorldEffect:
    name: str
    help: str                                      # told to the GM: what this effect is for
    words: tuple[str, ...]                         # at least one must appear in the project's own words
    apply: Callable[[object], str | None]          # (state) -> the line to record, or None if the world has no room
    min_difficulty: int = 2
    request: tuple[str, str] | None = None         # (module, what): a live module makes the change (`does`: "request:<module>:<what>")


DOES: dict[str, Callable] = {}   # what an effect can do itself (none since 0.42.0: a module does it, "request:<module>:<what>")


def _applier(does: str, note: str) -> Callable:
    def apply(state) -> str | None:
        if does not in DOES:                       # a module's change: made through it (see `apply` below)
            return None
        n = DOES[does](state)
        return None if n is None else note.format(n=n)
    return apply


def _request(does: str) -> tuple[str, str] | None:
    parts = does.split(":")
    return (parts[1], parts[2]) if len(parts) == 3 and parts[0] == "request" else None


def registry() -> dict[str, WorldEffect]:
    """The world's effects (its pack's content.json `world_effects`): what each is, the words that mark it, and what it does."""
    raw = world_pack.active().data("content").get("world_effects", {})
    return {name: WorldEffect(name, e["help"], tuple(e.get("words", ())), _applier(e["does"], e.get("note", "")), e.get("min_difficulty", 2),
                              _request(e["does"]))
            for name, e in raw.items()}


def __getattr__(name):            # the old constant name, from the active world
    if name == "EFFECTS":
        return registry()
    raise AttributeError(name)


def gm_lines() -> str:
    """The sentence the GM design prompt carries: every effect, and when it applies."""
    listing = "; ".join(f"{e.name} ({e.help})" for e in registry().values())
    return (f"world: ONLY if what {world_pack.active().agent.name} finished made a lasting change of one of these kinds to {world_pack.active().agent.their} world - give `effect` as one of: "
            f"{listing}. For anything else never use it (a pond, a painting or a gift is just itself)")


def allowed(effect, project: dict) -> bool:
    e = registry().get(effect)
    if not e or project["difficulty"] < e.min_difficulty:
        return False
    words = " ".join([project["name"], project.get("goal") or ""] + [st["name"] for st in project["stages"]]).lower()
    return any(w in words for w in e.words)


async def apply(state, spec: dict) -> str | None:
    """Carry out a finished project's world effect, once. If the world has no room, the capability is dropped so the
    creation doesn't claim a change that didn't happen. A module's change is asked of the module; its reply is the line."""
    effect = spec["capabilities"].get("world", {}).get("effect")
    if not effect:
        return None
    e = registry().get(effect)
    note = None
    if e and e.request:
        from . import modules
        try:
            note = await modules.ask_module(state, state.s, modules.runner_for(state.s), *e.request, {}, True) or None
        except modules.Refused:
            note = None
    elif e:
        note = e.apply(state)
    if note is None:
        spec["capabilities"].pop("world", None)
    return note
