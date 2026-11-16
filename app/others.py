"""The other agents in this world (docs/DESIGN-multi-agent.md, release 3): who else lives here with a mind of their own, where they are,
and how agents reach each other. They see each other where they are and meet the first time; `say` to one who is here is heard (it
arrives in their inbox and wakes them); a letter to one they've met goes by the world's post and arrives hours later, with anything
tucked inside. Minds stay private: an agent knows another only by what it sees, hears and reads.
"""
import json
import random
import time

from . import places
from . import world_pack
from .text import clip

_world: list = []          # the World running here (loop.World registers itself)
POST_HOURS = (2, 6)        # how long a letter between agents takes


def use(world) -> None:
    _world[:] = [world]


def everyone() -> list:
    """The world's agents (loop.Agent), first first."""
    return list(_world[0].agents) if _world else []


def others() -> list:
    """Everyone but the agent acting now."""
    me = world_pack.active().agent.key
    return [a for a in everyone() if a.identity.key != me]


def named(name: str):
    """Another agent by name or key, or None."""
    q = str(name or "").strip().lower()
    return next((a for a in others() if q and q in (a.identity.name.lower(), a.identity.key)), None)


def here(place: str | None) -> list:
    """The other agents at `place` (not on their way somewhere)."""
    return [a for a in others() if place and places.present_at(a.state) == place]


def met(state, other) -> bool:
    return state.meta(f"met:{other.identity.key}") is not None


def meet(state, other, now: float | None = None) -> bool:
    """The agent acting now and `other` see each other: the first time, they meet (both remember it). True if they just met."""
    if met(state, other):
        return False
    now, me = now or time.time(), world_pack.active().agent
    state.set_meta(**{f"met:{other.identity.key}": str(now)})
    other.state.set_meta(**{f"met:{me.key}": str(now)})
    where = places.present_at(state)
    state.log("met", name=other.identity.name, about=other.identity.kind, place=where)
    other.state.log("met", name=me.name, about=me.kind, place=where)
    other.request_wake()
    return True


def seen(state, now: float | None = None) -> list[str]:
    """The perception's lines for the other agents here (and they meet, the first time)."""
    out = []
    for a in here(places.present_at(state)):
        first = meet(state, a, now)
        what = a.state.agent()
        doing = f", {what['activity']}" if what["activity"] not in ("idle", "") else ""
        out.append(f"{a.identity.name} is here ({a.identity.kind}{doing})" + (": you haven't met before" if first else "")
                   + f". They hear you if you say(to=\"{a.identity.name}\").")
    return out


def say(state, other, text: str) -> str:
    """Speak to another agent: heard if they are here (their inbox, and it wakes them). The tool's answer."""
    me, where = world_pack.active().agent, places.present_at(state)
    if not where or places.present_at(other.state) != where:
        there = places.present_at(other.state)
        said = "home" if there == places.home_key(other.identity) else places.label(there) if there else ""
        return f"{other.identity.name} can't hear you from here" + ("; write_letter to reach them" if met(state, other) else "") \
            + (f" (they're at {said})" if met(state, other) and said else "")
    meet(state, other)
    other.receive(text, me.name, source="agent")
    state.log("say", text=text, to=[], to_name=other.identity.name)
    return f"said it to {other.identity.name}; {other.identity.they} heard you"


def post(state, other, text: str, enclosed: dict | None, rng: random.Random | None = None, now: float | None = None) -> None:
    """A letter to another agent, by the world's post: it arrives in POST_HOURS (an item tucked inside goes with it)."""
    now, me, rng = now or time.time(), world_pack.active().agent, rng or random.Random()
    state.db.execute("INSERT INTO agent_post (sender, recipient, text, enclosed, sent_at, deliver_at) VALUES (?, ?, ?, ?, ?, ?)",
                     (me.key, other.identity.key, text, json.dumps(enclosed) if enclosed else "", now,
                      now + rng.uniform(*POST_HOURS) * 3600))
    state.db.commit()
    state.log("letter_sent", to=other.identity.name, text=clip(text, 400), enclosed=(enclosed or {}).get("name", ""))


def posted_since(state, since: float) -> int:
    """How many letters the agent acting now has sent other agents since then."""
    me = world_pack.active().agent.key
    return state.db.execute("SELECT COUNT(*) FROM agent_post WHERE sender = ? AND sent_at >= ?", (me, since)).fetchone()[0]


def deliver(now: float | None = None) -> int:
    """The world's post: every letter between agents that is due arrives in its recipient's inbox (and what was tucked inside, in their
    things). How many arrived."""
    now, n = now or time.time(), 0
    agents = {a.identity.key: a for a in everyone()}
    if not agents:
        return 0
    st = next(iter(agents.values())).state
    for row in st.db.execute("SELECT * FROM agent_post WHERE delivered_at IS NULL AND deliver_at <= ? ORDER BY id", (now,)).fetchall():
        to, sender = agents.get(row["recipient"]), agents.get(row["sender"])
        if to is None:
            continue                                                    # not running here now: it waits
        name = sender.identity.name if sender else row["sender"]
        inside = json.loads(row["enclosed"]) if row["enclosed"] else None
        if inside:
            to.state.add_item(inside["name"], inside["qty"], inside["kind"], inside.get("description", ""), inside.get("attrs") or {})
        to.receive(row["text"] + (f"\n(Tucked inside: {inside['qty']} x {inside['name']}.)" if inside else ""), name, source="letter")
        st.db.execute("UPDATE agent_post SET delivered_at = ? WHERE id = ?", (now, row["id"]))
        n += 1
    st.db.commit()
    return n


def read(state) -> list[dict]:
    """The modules' `agents` read: each agent's public facts (no one's mind)."""
    out = []
    for a in everyone():
        me = a.state.agent()
        out.append({"key": a.identity.key, "name": a.identity.name, "where": me["location"], "activity": me["activity"],
                    "asleep": me["activity"] == "sleeping"})
    return out
