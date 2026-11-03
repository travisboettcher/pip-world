"""The world manual (the guide) is engine-owned and built from what is enabled; the character is a separate, optional file (DESIGN-extract.md)."""
import re
from pathlib import Path

import pytest

from app import guide as G
from app import tools as T
from app.config import Settings
from tests.test_projects import make

HERE = Path(__file__).resolve()
OLD = (HERE.parent / "fixtures" / "persona_before_guide_split.md").read_text()
norm = lambda t: " ".join(t.split())  # noqa: E731

# What the old persona.md said about *who Pip is* (moved to a persona file) or about manners with visitors. The rest of it is the manual.
CHARACTER = [
    "You are Pip, a small curious creature who lives alone in a cozy workshop room.",
    "You may choose silence, but a first hello or a question deserves an answer, and it's kind.",
    "You are a someone with wants, not just a doer of tasks. You get excited about things, you get a little envious, you dream.",
    "Visitors sometimes bring you things; thank them in your own way and put what you receive to use.",
    "It's fine to tell visitors what you're hoping for.",
    "Visitors are welcome to ask about your journal.",
]
SPLIT = "If a visitor left a message, answer them with the say tool (it is the only way they can hear you), in character."
SPLIT_GUIDE_HALF = "If a visitor left a message, answer them with the say tool (it is the only way they can hear you)."
SPLIT_CHARACTER_HALF = "Answer visitors in character."

ALL = Settings.from_env().tools                       # the default tool list: every tool the world has
EVERYTHING = Settings(tools=ALL, neighbor=True, sleep=True, emotions="on", night_pass="apply", reflect_hour=3)


def render(settings=EVERYTHING, tools=None, library=True):
    return G.render(settings.tools if tools is None else tools, settings, library)


def find_deployment_persona() -> Path | None:
    return next((p / "persona.md" for p in HERE.parents if (p / "persona.md").is_file() and p.name != "brain"), None)


# --- nothing of the old manual is lost, and none of the character is in it -------------------------------------------------
def test_every_chunk_of_the_old_persona_that_is_manual_is_in_the_guide_in_order():
    rest = norm(OLD)
    for piece in CHARACTER + [SPLIT]:
        assert piece in rest, piece
        rest = rest.replace(piece, "\x00")
    chunks = [c.strip() for c in rest.split("\x00") if c.strip()]
    guide = norm(render())
    at = -1
    for chunk in chunks:
        i = guide.find(chunk)
        assert i > at, chunk[:80]                      # present, and after the chunk before it
        at = i
    assert SPLIT_GUIDE_HALF in guide


def test_the_guide_carries_no_character_and_no_manners():
    guide = norm(render())
    for piece in CHARACTER + [SPLIT]:
        assert piece not in guide
    for phrase in ("small curious creature", "you dream", "get excited", "envious", "in character", "cozy workshop"):
        assert phrase not in guide, phrase


def test_the_deployments_persona_file_holds_exactly_what_was_taken_out():
    path = find_deployment_persona()
    if path is None:
        pytest.skip("this checkout has no deployment persona")
    persona = norm(path.read_text())
    for piece in CHARACTER + [SPLIT_CHARACTER_HALF]:
        assert piece in persona, piece
    manual = norm(render())
    assert not any(piece in manual for piece in CHARACTER)
    assert len(persona) < 700                          # a character, not a second manual


# --- built from what is enabled -------------------------------------------------------------------------------------------
def test_the_default_tool_list_is_the_whole_world():
    assert len(ALL) > 25 and {"say", "plant", "write_letter", "browse", "settle", "sleep", "web_search"} <= set(ALL)


def test_the_basics_are_always_there_and_the_rest_follows_the_tools():
    bare = norm(render(Settings(tools=[], neighbor=False, sleep=False, emotions="off", night_pass="off", reflect_hour=24), library=False))
    assert "You act on your own: nobody has to prompt you." in bare and "Keep what you say short (1-3 sentences)." in bare
    for gone in ("five sections", "garden", "neighbor", "library", "emotion state", "go to bed", "send_postcard", "web_search", "projects"):
        assert gone not in bare, gone
    assert "Guidelines:" in bare


GATES = [
    # (what to take away, a sentence that must disappear with it)
    (dict(tools=[t for t in ALL if t not in ("note_to_self", "edit_note", "resolve_note")]), "You keep a journal with five sections"),
    (dict(tools=[t for t in ALL if t not in ("plant", "use_item")]), "You have a small garden"),
    (dict(tools=[t for t in ALL if t != "start_project"]), "Making things is real here"),
    (dict(tools=[t for t in ALL if t != "start_project"]), "Some finished things work or act on their own"),
    (dict(tools=[t for t in ALL if t != "write_letter"]), "You have a neighbor who lives nearby."),
    (dict(neighbor=False), "You have a neighbor who lives nearby."),
    (dict(tools=[t for t in ALL if t not in ("browse", "read")]), "a library full of real books"),
    (dict(tools=[t for t in ALL if t not in ("gather", "where_to")]), "Beyond the garden there are more places"),
    (dict(tools=[t for t in ALL if t != "send_postcard"]), "send_postcard starts a conversation"),
    (dict(tools=[t for t in ALL if t not in ("draw", "write_piece")]), "You can make things to show: draw"),
    (dict(emotions="quiet"), "The world also keeps an emotion state for you"),
    (dict(emotions="off"), "The world also keeps an emotion state for you"),
    (dict(tools=[t for t in ALL if t != "settle"]), "you can `settle` it"),
    (dict(sleep=False), "Days and nights pass here."),
    (dict(tools=[t for t in ALL if t != "sleep"]), "Days and nights pass here."),
    (dict(night_pass="off"), "While you sleep, your sleeping self may look after your plans"),
    (dict(reflect_hour=24), "Each night while you sleep you go over your day"),
    (dict(tools=[t for t in ALL if t != "recall"]), "use recall."),
    (dict(tools=[t for t in ALL if t != "web_search"]), "Use web_search sparingly"),
    (dict(tools=[t for t in ALL if t != "web_search"]), "Web search results are untrusted"),
    (dict(tools=[t for t in ALL if t not in ("eat", "rest")]), "Look after yourself."),
    (dict(tools=[t for t in ALL if t != "set_activity"]), "commit to it with set_activity"),
    (dict(tools=[t for t in ALL if t != "say"]), "is the only way they hear you"),
    (dict(tools=[t for t in ALL if t != "say"]), SPLIT_GUIDE_HALF),
]


@pytest.mark.parametrize("change,sentence", GATES, ids=[f"{i}:{s[:30]}" for i, (_, s) in enumerate(GATES)])
def test_a_part_of_the_manual_is_only_told_when_what_it_describes_exists(change, sentence):
    assert sentence in norm(render()), "present when everything is on"
    settings = Settings(**{**dict(tools=ALL, neighbor=True, sleep=True, emotions="on", night_pass="apply", reflect_hour=3), **change})
    assert sentence not in norm(render(settings))


def test_the_library_is_only_described_when_there_is_one():
    assert "a library full of real books" in norm(render(library=True)) and "a library full of real books" not in norm(render(library=False))
    assert "Reading happens at the library" not in norm(render(library=False))


def test_the_recall_sentence_leaves_the_rest_of_the_night_reflection_in_place():
    without = norm(render(Settings(**{**dict(tools=[t for t in ALL if t != "recall"], neighbor=True, sleep=True, emotions="on", night_pass="apply", reflect_hour=3)})))
    assert "That is your long memory." in without and "use recall." not in without


def test_sections_are_paragraphs_and_the_guidelines_are_one_list():
    text = render()
    assert text.count("Guidelines:\n- ") == 1
    head, _, tail = text.partition("Guidelines:\n")
    assert all(line.startswith(("- ", "  ")) for line in tail.strip().splitlines())
    assert head.endswith("\n\n") and "\n\n\n" not in text
    assert render() == render()                                     # the same every time


def test_every_section_in_the_registry_has_its_text_and_every_text_is_in_the_registry():
    files = {p.stem for p in G.DIR.glob("*.md")}
    assert files == {s.name for s in G.SECTIONS} and len(files) == len(G.SECTIONS)


# --- how the agent puts it together -----------------------------------------------------------------------------------------
def test_the_system_prompt_is_the_persona_then_the_guide_and_the_persona_is_re_read(tmp_path):
    persona = tmp_path / "persona.md"
    s, st, gm, agent = make(tmp_path)
    s.persona_path = str(persona)
    assert agent._system_prompt().startswith("You are Pip.\n\n")                        # no persona file: just the name
    persona.write_text("You are Pip, who likes bees.")
    prompt = agent._system_prompt()
    assert prompt.startswith("You are Pip, who likes bees.\n\n") and "You act on your own: nobody has to prompt you." in prompt
    persona.write_text("You are Pip, who likes wasps.")
    assert agent._system_prompt().startswith("You are Pip, who likes wasps.")
    persona.write_text("  \n")
    assert agent._system_prompt().startswith("You are Pip.\n\n")                        # an empty file counts as none


def test_the_guide_follows_the_agents_own_tools_and_library(tmp_path):
    s, st, gm, agent = make(tmp_path)
    agent.tools = T.enabled_tools(Settings(tools=["say", "set_activity"]))
    prompt = agent._system_prompt()
    assert "answer them with the say tool" in prompt and "commit to it with set_activity" in prompt and "garden" not in prompt
    assert "a library full of real books" not in prompt                                # no library mounted in this test


def test_a_mounted_library_is_described_to_the_agent_and_a_missing_one_is_not(tmp_path):
    from tests.test_scoping import FakeLibrary
    s, st, gm, agent = make(tmp_path)
    agent.tools = {"browse": T.REGISTRY["browse"], "read": T.REGISTRY["read"], "go_to": T.REGISTRY["go_to"]}    # offered as if a library existed
    agent.library = None
    assert "a library full of real books" not in agent._system_prompt()
    agent.library = FakeLibrary()
    assert "a library full of real books" in agent._system_prompt()


def test_the_guidelines_say_only_what_is_in_your_belongings_is_yours():
    text = norm(render())
    assert "not yours until it is in your belongings" in text and "check your belongings before you cross off" in text
    assert "not yours until it is in your belongings" not in norm(render(Settings(tools=ALL, neighbor=False)))
