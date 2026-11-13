"""What the engine still knows of crafting (docs/DESIGN-world-packs.md, 5f): the agent's abilities (the world's: its pack's content.json
`crafting`), how practice becomes a level, and the qualities a made thing can have. Projects themselves are the shipped `crafting` module's
(module_library/crafting.py), which publishes them as `projects` (and its crafts as `skills`) for the dashboard and the night pass.
"""
import math

from . import world_pack

QUALITIES = ("rough", "sound", "fine", "masterwork")


def abilities() -> tuple:
    """What a stage of work exercises (the pack's content.json `crafting`)."""
    return tuple(world_pack.active().data("content").get("crafting", {}).get("abilities", ()))


def default_abilities() -> list:
    return list(world_pack.active().data("content").get("crafting", {}).get("default_abilities", ()))


def __getattr__(name):            # the old constant names, from the active world
    if name == "ABILITIES":
        return abilities()
    if name == "DEFAULT_ABILITIES":
        return default_abilities()
    raise AttributeError(name)


def level(xp: float) -> int:
    return min(5, int(math.sqrt(max(0.0, xp) / 60)))


def published(state) -> dict:
    """What live modules publish of the agent's projects and crafts (the crafting module's): {projects, skills}."""
    from .modules import published as said
    ps, sk = said(state, "projects"), said(state, "skills")
    return {"projects": ps if isinstance(ps, list) else [], "skills": sk if isinstance(sk, dict) else {}}
