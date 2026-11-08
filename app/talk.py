"""The conversation scene (docs/DESIGN-conversation.md, part 2).

When someone Pip is with in person (a neighbor at home, a resident at their place) has spoken this visit, the talk runs as its own short scene instead of
through Pip's world turn: Pip's turns get a small prompt (who it is with, why it came, what it has with it, the date, and the talk so far) and only
`say` and `feel`; the other side answers at once; it goes on until either says goodbye, Pip falls silent, or SCENE_TURNS of Pip's lines. Then Pip's
world turn picks up with the whole talk in view.
"""
from . import conversation as conv
from . import places
from .llm.base import ToolSpec
from .state import State
from .text import clip

SCENE_TURNS = 6
TRANSCRIPT = 12
TODOS_SHOWN = 3
CARRIED_SHOWN = 8

SAY = ToolSpec("say", "Say your next line to the one you are with: one to three sentences. Set `goodbye` when this line ends the talk.",
               {"type": "object", "properties": {"text": {"type": "string"},
                                                 "goodbye": {"type": "boolean", "description": "true when this line ends the talk"}},
                "required": ["text"]})


def partner(state) -> dict | None:
    """Who Pip is with in person, if anyone: the neighbor whose home it is in, or a resident of the place it is at."""
    here = places.present_at(state)
    if not here:
        return None
    return next((ch for ch in state.characters() if ch["kind"] in places.IN_PERSON and places.place_of(state, ch) == here), None)


def waiting(state) -> dict | None:
    """The one Pip should talk with now: they have spoken this visit, and this visit's talk has not been had yet."""
    ch = partner(state)
    visit = state.meta("arrived_at")
    if not ch or not visit or state.meta("talk_done") == visit:
        return None
    spoke = any(e["kind"] == "companion" and e["data"].get("name") == ch["name"] and e["ts"] >= float(visit) for e in state.events(50))
    return ch if spoke else None


def specs(tools) -> list[ToolSpec]:
    return [SAY] + ([tools["feel"][0]] if "feel" in tools else [])


def system(persona: str, ch: dict) -> str:
    return (f"{persona}\n\nRight now you are face to face with {ch['name']}, in the middle of a conversation. Talk as yourself. "
            "Answer only by calling a tool.")


def prompt(state, ch: dict, clock: str, now: float) -> str:
    """Pip's turn in a talk: who it is with, why it came, what it has with it, and everything said this visit."""
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
         f"You have with you: {', '.join(carried) if carried else 'nothing much'}; {state.coins()} coins.",
         f"Talking with {ch['name']} (this visit, oldest first):", *[f"  {l}" for l in said],
         "Your turn: answer what was just said, with say. Don't open with thanks or say back what you were told; ask something, or tell "
         "something of your own. When the talk has run its course, say goodbye (say with goodbye true). You may also feel something."])
