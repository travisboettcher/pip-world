"""The conversation scene (docs/DESIGN-conversation.md, part 2).

Between two agents (docs/DESIGN-multi-agent.md, "Talk between agents"), the scene is the listener's turn's: each speaks in turn from the same
small prompt, its own (its persona, its notes on the other, the talk so far), and each line is heard at once.

When someone the agent is with in person (whoever is where it is: someone at home, a villager at the village) has spoken this visit, the talk runs as its own short scene instead of
through Pip's world turn: The agent's turns get a small prompt (who it is with, why it came, what it has with it, the date, and the talk so far) and only
`say` and `feel`; the other side answers at once; it goes on until either says goodbye, the agent falls silent, or SCENE_TURNS of the agent's lines. Then the agent's
world turn picks up with the whole talk in view.
"""
import time

from . import conversation as conv
from . import places
from .llm.base import ToolSpec
from .state import State
from .text import clip

SCENE_TURNS = 6
AGENT_LINES = 8               # a talk between two agents: lines in all, both sides
AGENT_QUIET_MINUTES = 30      # after one, their words to each other are heard but don't wake the other
LOCK_WAIT = 30.0              # seconds to wait for the other to finish a turn of its own
TRANSCRIPT = 12
TODOS_SHOWN = 3
CARRIED_SHOWN = 8

SAY = ToolSpec("say", "Say your next line to the one you are with: one to three sentences. Set `goodbye` when this line ends the talk.",
               {"type": "object", "properties": {"text": {"type": "string"},
                                                 "goodbye": {"type": "boolean", "description": "true when this line ends the talk"}},
                "required": ["text"]})


def partner(state) -> dict | None:
    """Who the agent is with in person, if anyone: the first of whoever is where it is (company_at)."""
    return next(iter(places.company_at(state, places.present_at(state))), None)


def waiting(state) -> dict | None:
    """The one the agent should talk with now: they have spoken this visit, and this visit's talk has not been had yet."""
    ch = partner(state)
    visit = state.meta("arrived_at")
    if not ch or not visit or state.meta("talk_done") == visit:
        return None
    spoke = any(e["kind"] == "companion" and e["data"].get("name") == ch["name"] and e["ts"] >= float(visit) for e in state.events(50))
    return ch if spoke else None


def lately(state, other, now: float | None = None) -> bool:
    """Whether the agent acting now and another agent talked lately (as a scene): for a while, their words don't wake each other."""
    return (now or time.time()) - float(state.meta(f"talked:{other.identity.key}") or 0) < AGENT_QUIET_MINUTES * 60


def agent_waiting(state, inbox: list[dict]):
    """The agent to talk with now, as a scene: one who spoke to the agent acting now (its inbox), is here, and hasn't talked with it
    lately; or None."""
    from . import others
    here = {a.identity.name: a for a in others.here(places.present_at(state))}
    return next((here[m["sender"]] for m in inbox if m.get("source") == "agent" and m.get("sender") in here
                 and not lately(state, here[m["sender"]])), None)


def specs(tools) -> list[ToolSpec]:
    return [SAY] + ([tools["feel"][0]] if "feel" in tools else [])


def system(persona: str, ch: dict) -> str:
    return (f"{persona}\n\nRight now you are face to face with {ch['name']}, in the middle of a conversation. Talk as yourself. "
            "Answer only by calling a tool.")


def prompt(state, ch: dict, clock: str, now: float, on_mind: list[str] = ()) -> str:
    """The agent's turn in a talk: who it is with, why it came, what it has with it, and everything said this visit."""
    people = {p["name"]: p["notes"] for p in state.people()}
    about = people.get(ch["name"]) or ch.get("about") or ""
    todos = [m["text"] for m in reversed(state.memories("todo", status="open", limit=40)) if State.related(ch["name"], m["text"])][:TODOS_SHOWN]
    carried = [f"{i['name']} x{i['qty']}" for i in state.items()][:CARRIED_SHOWN]
    said = conv.visit_lines(state, ch["name"], float(state.meta("arrived_at") or 0))[-TRANSCRIPT:]
    a = state.agent()
    return "\n".join(
        [clock, f"You are at {places.label(state.agent()['location'])}, talking with {ch['name']}.",
         *( [f"What you think of {ch['name']}: {about}"] if about else []),
         *( ["What you meant to do about them:"] + [f"- {clip(t, 160)}" for t in todos] if todos else []),
         f"You were {a['activity']}" + (f" ({a['description']})" if a["description"] else "") + f", feeling {a['mood']}.",
         f"You have with you: {', '.join(carried) if carried else 'nothing much'}; {state.coins()} coins.", *on_mind,
         f"Talking with {ch['name']} (this visit, oldest first):", *[f"  {l}" for l in said],
         "Your turn: answer what was just said, with say. Don't open with thanks or say back what you were told; ask something, or tell "
         "something of your own. When the talk has run its course, say goodbye (say with goodbye true). You may also feel something."])
