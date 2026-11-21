"""Talk with characters: the recent lines between the agent and someone, and what the agent said to them waiting for an answer.

A creation that talks does so through its `workings` module (module_library/workings.py: a voice, `ask` and `speak`); the characters
here are the people (neighbors, residents) the engine's conversation code answers for.
"""
import time

from .text import brief
from . import world_pack

CONVERSATION_LINES = 6


def conversation(state, name: str, verbatim_since: float | None = None) -> list[str]:
    """The last lines between the agent and `name`. With `verbatim_since`, `name`'s own earlier lines are shown in brief."""
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
    """The agent acting now says something to them, to be answered. With several agents a character is the world's, so each line
    remembers who said it."""
    line = {"ts": time.time(), "text": text, "by": world_pack.active().agent.key}
    state.update_character(ch["id"], heard=(ch["heard"] + [line])[-5:])


def heard(ch: dict) -> list[dict]:
    """What the agent acting now said to them that is still waiting for an answer."""
    me = world_pack.active().agent.key
    return [h for h in ch["heard"] if h.get("by", me) == me]


def not_mine(ch: dict) -> list[dict]:
    """What other agents said to them, still waiting: not the agent acting now's to answer or to drop."""
    me = world_pack.active().agent.key
    return [h for h in ch["heard"] if h.get("by", me) != me]
