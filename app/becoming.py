"""A character who becomes an agent (docs/DESIGN-multi-agent.md, "A character becomes an agent").

A world.json agent may name the character it was (`was`). The first time it starts in a world that has that character, it takes over
what the character carried: their life so far and what they told others (as things it knows), every exchange the other agents had with
them (letters and words in person, from its own side, when they happened), and letters still in the post (now between agents). Everyone
who dealt with the character has met the agent, and the character steps aside. A world that never had the character starts the agent
as written. Once only: the agent's file remembers it (`became`).
"""
import time

from . import others


def step(agents, now: float | None = None) -> None:
    """At a start: every agent that was a character and hasn't taken over from them yet does now."""
    now = now or time.time()
    for a in agents:
        name = a.identity.was
        if not name or a.state.meta("became"):
            continue
        a.state.set_meta(became=name)
        ch = next((c for c in a.state.characters() if c["name"] == name), None)
        if ch:
            _take_over(a, ch, [b for b in agents if b is not a], now)


def _take_over(a, ch: dict, rest, now: float) -> None:
    name, st = ch["name"], a.state
    for line in ch["life"]:
        st.add_memory(line, "learned")
    for line in ch["told"]:
        st.add_memory(f"Something you have told others: {line}", "learned")
    dealt = []
    for b in rest:
        with a.acting():                                                 # remembered as hers: she is who "you" is
            carried = _history(a, b, name, now)
        if carried:
            dealt.append(b.identity.name)
            for x, y in ((a, b), (b, a)):
                with x.acting():
                    others.meet(x.state, y)
    st.remove_character(ch["id"])
    with a.acting():
        st.log("became", was=name, about=ch["about"], **{"from": dealt})


def _history(a, b, name: str, now: float) -> bool:
    """What `b` and the character said to each other, now `a`'s: told from `a`'s side, at the time it happened; letters still on their
    way, now in the world's post. Whether there was any."""
    seen = False
    them = b.identity.name
    for lt in b.state.letters(between=name, limit=10_000):
        seen = True
        mine = lt["sender"] == name
        if lt["delivered_at"] is None:                                  # still on its way: between the agents now
            sender, recipient = (a, b) if mine else (b, a)
            b.state.db.execute("INSERT INTO agent_post (sender, recipient, text, enclosed, sent_at, deliver_at) VALUES (?, ?, ?, '', ?, ?)",
                               (sender.identity.key, recipient.identity.key, lt["text"], lt["ts"], lt["deliver_at"]))
            b.state.update_letter(lt["id"], delivered_at=now)
        elif mine:
            a.state.remember(lt["ts"], "letter_sent", to=them, text=lt["text"])
        else:
            a.state.remember(lt["ts"], "inbox", text=lt["text"], sender=them, source="letter")
    b.state.db.commit()
    for e in reversed(b.state.events_of(("companion", "say"), limit=100_000)):
        d = e["data"]
        if e["kind"] == "companion" and d.get("name") == name:
            a.state.remember(e["ts"], "say", text=d["text"], to=[], to_name=them)
        elif e["kind"] == "say" and d.get("to_name") == name:
            a.state.remember(e["ts"], "inbox", text=d["text"], sender=them, source="agent")
        else:
            continue
        seen = True
    return seen
