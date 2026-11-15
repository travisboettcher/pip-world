"""What the engine still knows of crafting (docs/DESIGN-world-packs.md, 5f): the agent's abilities (the world's: its pack's content.json
`crafting`), how practice becomes a level, and the qualities a made thing can have. Projects themselves are the shipped `crafting` module's
(module_library/crafting.py), which publishes them as `projects` (and its crafts as `skills`) for a page, and as `plans` for the night
pass; the engine reads neither.
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
