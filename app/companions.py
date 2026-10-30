"""Companions: creations with a `companion` capability get a character that talks.

Characters are not full agents: one small GM call per line, a tiny context, no tools. A companion chatters every
so often (doesn't wake Pip) and answers when Pip talks to it with say(to=...) (the answer wakes Pip). Replies are
capped per hour so Pip and its bird can't ping-pong the budget away. A stopped creation is silent.
"""
import random
import time

from .creations import running

CONVERSATION_LINES = 6
JITTER = (0.7, 1.3)


def add_for_creation(state, rng: random.Random, c: dict) -> dict | None:
    comp = c["spec"]["capabilities"].get("companion")
    if not comp:
        return None
    first = time.time() + comp["chatter_minutes"] * 60 * rng.uniform(*JITTER)
    return state.add_character(c["name"], "creation", c["id"], comp["persona"], comp["chatter_minutes"], first)


def conversation(state, name: str) -> list[str]:
    lines = []
    for e in reversed(state.events(200)):
        d = e["data"]
        if e["kind"] == "companion" and d["name"] == name:
            lines.append(f"{name}: {d['text']}")
        elif e["kind"] == "say" and d.get("to_name") == name:
            lines.append(f"Pip: {d['text']}")
    return lines[-CONVERSATION_LINES:]


async def step(state, settings, gm, rng: random.Random, now: float | None = None) -> bool:
    """Let every companion that's due say one line. Returns True if Pip should wake (it was answered)."""
    now = now or time.time()
    wake = False
    for ch in state.characters():
        if ch["kind"] != "creation":
            continue
        c = state.creation(ch["creation_id"])
        if not c or c.get("given_to") or not running(c, now):
            continue
        recent = [t for t in ch["replies"] if now - t < 3600]
        answering = bool(ch["heard"]) and len(recent) < settings.companion_replies_per_hour
        if not answering and now < ch["next_chatter_at"]:
            continue
        a = state.agent()
        situation = f"Pip is {a['activity']}" + (f" ({a['description']})" if a["description"] else "") + \
                    f", feeling {a['mood']}."
        about = c["description"] + (f" Quirks: {'; '.join(c['spec']['quirks'])}." if c["spec"]["quirks"] else "")
        heard = [h["text"] for h in ch["heard"]] if answering else []
        text = await gm.speak(ch["name"], ch["persona"], about, situation, conversation(state, ch["name"]), heard) \
            if gm else None
        fields = {"next_chatter_at": now + ch["chatter_minutes"] * 60 * rng.uniform(*JITTER)}
        if answering:
            fields.update(heard=[], replies=recent + [now])
        state.update_character(ch["id"], **fields)
        if text:
            state.log("companion", name=ch["name"], text=text, reply=answering)
            wake = wake or answering
    return wake


def hear(state, ch: dict, text: str) -> None:
    state.update_character(ch["id"], heard=(ch["heard"] + [{"ts": time.time(), "text": text}])[-5:])
