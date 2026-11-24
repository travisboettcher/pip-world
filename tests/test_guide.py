"""The world manual (the guide) is engine-owned and built from what is enabled; the character is a separate, optional file (DESIGN-extract.md)."""
from pathlib import Path

import pytest

from app import guide as G
from app import modules as M
from app import world_pack as W
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
# What the guide said once and says differently now, on purpose: set_activity was how the agent "did" things before projects, walks and
# gathering were tools of their own; it only says what the agent is doing now (2026-11-16). Pip's neighbours are agents now, who visit
# too (0.67.0, 2026-11-23): the page about them says so.
RETIRED = ["Otherwise pick an activity you find interesting and commit to it with set_activity: a short `activity` label (1-3 words) plus a "
           "one-sentence `description`. Let your to-do list, wishlist and ambitions guide you. Change activity when you've made real progress "
           "or lose interest; don't just restate it.",
           "You have a neighbor who lives nearby. You can walk over to visit them at home (go_to) and talk in person with say (to: their "
           "name); they don't come visiting you. Otherwise you write letters (write_letter), which take hours to arrive each way, and they "
           "sometimes send a small parcel. Letters from them arrive in your inbox. You can tuck something you own or made into a letter as a gift."]
SPLIT = "If a visitor left a message, answer them with the say tool (it is the only way they can hear you), in character."
SPLIT_GUIDE_HALF = "If a visitor left a message, answer them with the say tool (it is the only way they can hear you)."
SPLIT_CHARACTER_HALF = "Answer visitors in character."

ALL = Settings.from_env().tools + [t["name"] for man, _ in M.world_modules(Settings()).values() for t in man.get("tools", [])]   # every tool the world has:
#                                                     the engine's (the default list) and its shipped modules' (offered as they're live)
EVERYTHING = Settings(tools=ALL, neighbor=True, sleep=True, emotions="on", night_pass="apply", reflect_hour=3)


def render(settings=EVERYTHING, tools=None, library=True):
    return G.render(settings.tools if tools is None else tools, settings, library)


def find_deployment_persona() -> Path | None:
    return next((p / "persona.md" for p in HERE.parents if (p / "persona.md").is_file() and p.name != "brain"), None)


# --- nothing of the old manual is lost, and none of the character is in it -------------------------------------------------
def test_every_chunk_of_the_old_persona_that_is_manual_is_in_the_guide_in_order():
    rest = norm(OLD)
    for piece in CHARACTER + RETIRED + [SPLIT]:
        assert piece in rest, piece
        rest = rest.replace(piece, "\x00")
    chunks = [c.strip() for c in rest.split("\x00") if c.strip() not in ("", "-")]      # a bullet's dash alone isn't a chunk
    guide = norm(render())
    at = -1
    for chunk in chunks:
        i = guide.find(chunk)
        assert i > at, chunk[:80]                      # present, and after the chunk before it
        at = i
    assert SPLIT_GUIDE_HALF in guide


def test_the_guide_carries_no_character_and_no_manners():
    guide = norm(render())
    for piece in CHARACTER + RETIRED + [SPLIT]:
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
    assert len(ALL) > 25 and {"start_project", "work_on", "plant", "read"} <= set(ALL) and {"say", "write_letter", "browse", "settle", "sleep", "web_search"} <= set(ALL)


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
    (dict(tools=[t for t in ALL if t != "write_letter"]), "Your neighbours live nearby, each at home."),
    (dict(neighbor=False), "Your neighbours live nearby, each at home."),
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
    (dict(tools=[t for t in ALL if t != "set_activity"]), "set_activity only says what you're doing"),
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


def test_every_page_says_when_it_applies_and_the_engine_names_none():
    for pack in (W.DEFAULT, W.DEFAULT.parent / "ashfall"):
        pages = G.pages(W.load(Settings(world_pack=str(pack))))
        assert len(pages) == len(list((pack / "guide").glob("*.md"))) and all(p.order < G.LAST and p.text for p in pages)
        assert [p.order for p in pages] == sorted(p.order for p in pages)
    src = (Path(G.__file__)).read_text()
    for name in ("projects", "market", "neighbor", "library.md", "start_project", "write_letter"):     # what each page needs is its own
        assert f'"{name}"' not in src, name


def test_a_packs_own_page_is_told_when_its_front_matter_says(tmp_path):
    from tests.test_world_pack import pack_dir
    d = pack_dir(tmp_path)
    (d / "guide" / "radio.md").write_text("---\norder: 5\nwhen: tool say and setting emotions=on\n---\nThe radio crackles at dusk.\n")
    (d / "guide" / "geiger.md").write_text("---\norder: 7\nwhen: stakes\nbullet: yes\n---\n- Mind the clicks.")
    (d / "guide" / "loose.md").write_text("No front matter: always, last.")
    s = Settings(world_pack=str(d), emotions="on", stats={"health": {"at_zero": "knocked_out"}})
    assert G.render(["say"], s, False) == "The radio crackles at dusk.\n\nNo front matter: always, last.\n\nYou act on your own.\n\nGuidelines:\n- Mind the clicks."
    assert G.render([], Settings(world_pack=str(d), emotions="off"), False) == "No front matter: always, last.\n\nYou act on your own."   # by name


@pytest.mark.parametrize("front,why", [
    ("order: soon", "`order` is a number"),
    ("bullet: maybe", "`bullet` is yes or no"),
    ("colour: red", "its front matter is lines of order, when and bullet, not 'colour: red'"),
    ("when: tool say or setting x", "not 'tool say or setting x'"),
    ("when: setting no_such_setting", "not 'setting no_such_setting'"),
    ("when: tool Say", "not 'tool Say'"),
    ("when: library books", "not 'library books'"),
    ("when: setting reminders=on extra", "not 'setting reminders=on extra'"),
])
def test_a_page_that_cant_be_read_stops_the_pack(tmp_path, front, why):
    from tests.test_world_pack import pack_dir
    d = pack_dir(tmp_path)
    (d / "guide" / "bad.md").write_text(f"---\n{front}\n---\nText.")
    with pytest.raises(W.PackError) as e:
        W.load(Settings(world_pack=str(d)))
    assert "guide/bad.md: " in str(e.value) and why in str(e.value)


def test_each_condition(tmp_path):
    page = lambda when: G.parse("p", f"---\nwhen: {when}\n---\nx")          # noqa: E731
    s = Settings(reflect_hour=3, reminders="on", night_pass="off", sleep=True)
    assert G.applies(page("tool a|b"), {"b"}, s, False) and not G.applies(page("tool a|b"), {"c"}, s, False)
    assert G.applies(page("setting reminders=on"), set(), s, False) and not G.applies(page("setting reminders=off"), set(), s, False)
    assert G.applies(page("setting sleep"), set(), s, False) and not G.applies(page("setting night_pass"), set(), s, False)
    assert not G.applies(page("setting world_pack"), set(), Settings(world_pack=""), False) and G.applies(page("setting world_pack"), set(), Settings(world_pack="x"), False)
    assert G.applies(page("library"), set(), s, True) and not G.applies(page("library"), set(), s, False)
    assert G.applies(page("reflection"), set(), s, False) and not G.applies(page("reflection"), set(), Settings(reflect_hour=24), False)
    assert G.applies(page("always and tool a"), {"a"}, s, False) and not G.applies(page("always and tool a"), set(), s, False)
    assert G.parse("p", "---\norder: 3\n---\n\nBody.\n") == G.Page("p", "Body.", 3.0, G.ALWAYS, False)
    assert G.parse("p", "---\nwhen: library and setting world_pack=a:b\n---\n  - indented  \n").when == (("library", ""), ("setting", "world_pack=a:b"))
    assert G.parse("p", "---\nbullet: yes\n---\n  - indented  \n").text == "  - indented  "        # only blank lines go
    assert G.parse("p", "X marks it.\nX") == G.Page("p", "X marks it.\nX") and G.parse("p", "---\norder: 1\n---\nX it.X").text == "X it.X"
    assert G.parse("p", "\n  plain  \n\n").text == "  plain  " and G.pages(type("P", (), {"dir": tmp_path})()) == ()


# --- how the agent puts it together -----------------------------------------------------------------------------------------
def test_the_system_prompt_is_the_persona_then_the_guide_and_the_persona_is_re_read(tmp_path):
    persona = tmp_path / "persona.md"
    s, st, gm, agent = make(tmp_path)
    s.persona_path = str(persona)
    assert agent._system_prompt().startswith(W.load(s).persona() + "\n\n")              # no persona file: the pack's
    persona.write_text("You are Pip, who likes bees.")
    prompt = agent._system_prompt()
    assert prompt.startswith("You are Pip, who likes bees.\n\n") and "You act on your own: nobody has to prompt you." in prompt
    persona.write_text("You are Pip, who likes wasps.")
    assert agent._system_prompt().startswith("You are Pip, who likes wasps.")
    persona.write_text("  \n")
    assert agent._system_prompt().startswith(W.load(s).persona() + "\n\n")              # an empty file counts as none


def test_the_guide_follows_the_agents_own_tools_and_library(tmp_path):
    s, st, gm, agent = make(tmp_path)
    agent.tools = T.enabled_tools(Settings(tools=["say", "set_activity"]))
    prompt = agent._system_prompt()
    assert "answer them with the say tool" in prompt and "set_activity only says what you're doing" in prompt and "garden" not in prompt
    assert "a library full of real books" not in prompt                                # no library mounted in this test


def test_a_mounted_library_is_described_to_the_agent_and_a_missing_one_is_not(tmp_path):
    from tests.test_scoping import FakeLibrary
    s, st, gm, agent = make(tmp_path)
    agent.tools = {"browse": T.REGISTRY["browse"], "go_to": T.REGISTRY["go_to"]}    # offered as if a library existed
    agent.library = None
    assert "a library full of real books" not in agent._system_prompt()
    agent.library = FakeLibrary()
    assert "a library full of real books" in agent._system_prompt()


def test_the_guidelines_say_only_what_is_in_your_belongings_is_yours():
    text = norm(render())
    assert "not yours until it is in your belongings" in text and "check your belongings before you cross off" in text
    assert "not yours until it is in your belongings" not in norm(render(Settings(tools=ALL, neighbor=False)))
