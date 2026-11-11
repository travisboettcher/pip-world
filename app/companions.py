"""Talk with characters: the recent lines between Pip and someone, and what Pip said to them waiting for an answer.

A creation that talks does so through its `workings` module (module_library/workings.py: a voice, `ask` and `speak`); the characters
here are the people (neighbors, residents) the engine's conversation code answers for.
"""
import time

from .text import brief
from . import world_pack

CONVERSATION_LINES = 6


def conversation(state, name: str, verbatim_since: float | None = None) -> list[str]:
    """The last lines between Pip and `name`. With `verbatim_since`, `name`'s own earlier lines are shown in brief."""
    lines = []
    for e in reversed(state.events(200)):
        d = e["data"]
        if e["kind"] == "companion" and d["name"] == name:
            earlier = verbatim_since is not None and e["ts"] < verbatim_since
            lines.append(f"{name} (in brief): {brief(d.get('gist'), d['text'])}" if earlier else f"{name}: {d['text']}")
        elif e["kind"] == "say" and d.get("to_name") == name:
            lines.append(f"{world_pack.active().agent.name}: {d['text']}")
    return lines[-CONVERSATION_LINES:]


def hear(state, ch: dict, text: str) -> None:
    state.update_character(ch["id"], heard=(ch["heard"] + [{"ts": time.time(), "text": text}])[-5:])
