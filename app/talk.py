"""The conversation scene (docs/DESIGN-conversation.md, part 2).

Between two agents (docs/DESIGN-multi-agent.md, "Talk between agents"), the scene is started by the listener's turn and goes on as a task of
its own: each speaks in turn from the same small prompt, its own (its persona, its notes on the other, the talk so far), each line is
heard at once, and each takes as long as it takes to say, with a pause after it.

When someone the agent is with in person (whoever is where it is: someone at home, a villager at the village) has spoken this visit, the talk runs as its own short scene instead of
through Pip's world turn: The agent's turns get a small prompt (who it is with, why it came, what it has with it, the date, and the talk so far) and only
`say` and `feel`; the other side answers at once; it goes on until either says goodbye, the agent falls silent, or SCENE_TURNS of the agent's lines. Then the agent's
world turn picks up with the whole talk in view.
"""
import asyncio
import time

from . import conversation as conv
from . import places
from .llm.base import ToolSpec
from .state import State
from .text import clip

SCENE_TURNS = 6
SPOKEN_WORDS_PER_SECOND = 2.5 # a talk between two agents takes time, not a number of lines (the owner, 2026-11-21): each line as long
LINE_PAUSE_SECONDS = 20       # as it takes to say, and a pause after it, so how long they stay together is what limits it
STRETCH_MINUTES = 20          # of talk, then each has a world turn (to act on what was said); words left pick the talk up again
AGENT_QUIET_MINUTES = 30      # after one, their words to each other are heard but don't wake the other (the next turn picks the talk up)
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
    """The one the agent should talk with now, if this visit's talk has not been had yet: the one here it spoke to last this visit, or
    else the first one here who has spoken to it."""
    company = {c["name"]: c for c in places.company_at(state, places.present_at(state))}
    visit = state.meta("arrived_at")
    if not company or not visit or state.meta("talk_done") == visit:
        return None
    since = [e for e in state.events(50) if e["ts"] >= float(visit)]
    addressed = next((e["data"]["to_name"] for e in since if e["kind"] == "say" and e["data"].get("to_name") in company), None)
    spoke = {e["data"].get("name") for e in since if e["kind"] == "companion"}
    return company[addressed] if addressed else next((c for c in company.values() if c["name"] in spoke), None)


def line_seconds(text: str) -> float:
    """How long a line of a talk between agents takes: saying it, and the pause before the next."""
    return len(text.split()) / SPOKEN_WORDS_PER_SECOND + LINE_PAUSE_SECONDS


async def wait(seconds: float) -> None:
    """The pause between two lines of a talk, while the agents are free for anything else."""
    await asyncio.sleep(seconds)


def cut_short(speaker_state, listener_state) -> str | None:
    """Why a talk between two agents can't go on to the next line, if it can't: one has left or fallen asleep, or the one to speak
    is exhausted or has spent the day's tokens."""
    from . import sleep as sleepmod, stats
    if places.present_at(speaker_state) != places.present_at(listener_state):
        return "parted"
    if sleepmod.asleep(speaker_state) or sleepmod.asleep(listener_state):
        return "asleep"
    if stats.exhausted(speaker_state):                                    # spent: the talk has worn them out (DESIGN-stamina.md)
        return "too tired"
    return "budget" if speaker_state.budget_exceeded() else None


def lately(state, other, now: float | None = None) -> bool:
    """Whether the agent acting now and another agent talked lately (as a scene): for a while, their words don't wake each other."""
    return (now or time.time()) - float(state.meta(f"talked:{other.identity.key}") or 0) < AGENT_QUIET_MINUTES * 60


def agent_waiting(state, inbox: list[dict]):
    """The agent to talk with now, as a scene: one who spoke to the agent acting now (its inbox) and is here; or None. Lately or not:
    words left after a talk pick it up again, rather than going on a line per world turn."""
    from . import others
    here = {a.identity.name: a for a in others.here(places.present_at(state))}
    return next((here[m["sender"]] for m in inbox if m.get("source") == "agent" and m.get("sender") in here), None)


def specs(tools) -> list[ToolSpec]:
    return [SAY] + [tools[n][0] for n in ("feel", "give") if n in tools]       # give: a deal struck can be kept on the spot


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
