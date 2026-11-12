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


DOES = {"add_plot": lambda state: state.add_plot(), "add_project_slot": lambda state: state.add_project_slot()}   # what an effect can do


def _applier(does: str, note: str) -> Callable:
    def apply(state) -> str | None:
        n = DOES[does](state)
        return None if n is None else note.format(n=n)
    return apply


def registry() -> dict[str, WorldEffect]:
    """The world's effects (its pack's content.json `world_effects`): what each is, the words that mark it, and what it does."""
    raw = world_pack.active().data("content").get("world_effects", {})
    return {name: WorldEffect(name, e["help"], tuple(e.get("words", ())), _applier(e["does"], e["note"]), e.get("min_difficulty", 2))
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


def apply(state, spec: dict) -> str | None:
    """Carry out a finished project's world effect, once. If the world has no room, the capability is dropped so the
    creation doesn't claim a change that didn't happen."""
    effect = spec["capabilities"].get("world", {}).get("effect")
    if not effect:
        return None
    note = registry()[effect].apply(state) if effect in registry() else None
    if note is None:
        spec["capabilities"].pop("world", None)
    return note
