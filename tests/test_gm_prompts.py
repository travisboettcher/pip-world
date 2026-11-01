"""Exact prompts and tool schemas for the neighbor's GM calls (letters, talk in person, recalling what's been told)."""
import pytest

from app.gm import GameMaster
from app.llm.base import LLMResponse, ToolCall, Usage
from app.llm.fake import FakeBackend
from tests.test_projects import make, report


class SchemaBackend(FakeBackend):
    """The fake backend, also keeping the `report` tool's JSON schema of each call."""

    async def complete(self, system, messages, tools, max_tokens):
        self.schemas = getattr(self, "schemas", []) + [tools[0].parameters]
        return await super().complete(system, messages, tools, max_tokens)


def master(tmp_path, *script):
    s, st, _, _ = make(tmp_path)
    backend = SchemaBackend(list(script))
    return GameMaster(backend, st), backend, st


def task(backend, i=0):
    return backend.calls[i]["messages"][0]["content"]


REMEMBERING = {"gist": {"type": "string"}, "told": {"type": "array", "items": {"type": "string"}}}
UPCOMING = {"type": "object", "properties": {"what": {"type": "string"}, "in_days": {"type": "integer"}}}
LETTER_PROPS = {"text": {"type": "string"}, "life_update": {"type": "string"}, "life_update_new": {"type": "boolean"},
                "upcoming": UPCOMING, **REMEMBERING}
PARCEL = {"type": "object", "properties": {"name": {"type": "string"}, "kind": {"type": "string"},
                                           "qty": {"type": "integer"}, "description": {"type": "string"}},
          "required": ["name", "kind"]}

LETTER_BARE = (
    "Write as Briar, Pip's neighbor. Who Briar is: An owl.\n"
    "\n"
    "No letter is waiting; Briar decides to write to Pip anyway.\n"
    "\n"
    "Write Briar's letter: 2-5 sentences in their own voice, answering what Pip said if anything, and sharing "
    "something from their own life. Pip can walk over to visit Briar at home (you can invite it), but Briar "
    "doesn't go out visiting; letters and the occasional small parcel are the rest. Also report:\n"
    '- `gist`: one sentence, third person, of what this letter says (e.g. "Told Pip the tide times for the '
    'week and asked how its walk went")\n'
    "- `told`: 0-3 short phrases for things about Briar or their world that this letter tells Pip for the "
    "first time (not anything Pip already knows); empty if nothing is new\n"
    "Optional:\n"
    "- `life_update`: one sentence, only if something in their life has changed since what's already happening "
    "(it carries into later letters), with `life_update_new`: true if it's really new, false if it restates "
    "something above\n"
    "- `upcoming`: only if something is coming up for Briar in the next two weeks that isn't listed above: "
    "`what` (a few words) and `in_days` (1-14)\n"
)

LETTER_FULL = (
    "Write as Briar, Pip's neighbor. Who Briar is: An owl.\n"
    "What's already happening in Briar's life (not news any more): The roof leaks. Rain came.\n"
    "Coming up for Briar:\n"
    "- market in 2 days\n"
    "- a storm tomorrow\n"
    "Things Pip already knows about Briar (refer back to them if it's natural, but don't introduce them again "
    "as news):\n"
    "- has a lamp\n"
    "- likes tea\n"
    "Your letters with Pip so far (oldest first; Pip's in full, yours in brief):\n"
    "Pip: hi\n"
    "Briar (in brief): said hello\n"
    "\n"
    "Pip's letter just arrived:\n"
    "Dear Briar, hi.\n"
    "Pip enclosed something with it: a cup. React to it honestly.\n"
    "\n"
    "Write Briar's letter: 2-5 sentences in their own voice, answering what Pip said if anything, and sharing "
    "something from their own life. Pip can walk over to visit Briar at home (you can invite it), but Briar "
    "doesn't go out visiting; letters and the occasional small parcel are the rest. Also report:\n"
    '- `gist`: one sentence, third person, of what this letter says (e.g. "Told Pip the tide times for the '
    'week and asked how its walk went")\n'
    "- `told`: 0-3 short phrases for things about Briar or their world that this letter tells Pip for the "
    "first time (not anything Pip already knows); empty if nothing is new\n"
    "Optional:\n"
    "- `life_update`: one sentence, only if something in their life has changed since what's already happening "
    "(it carries into later letters), with `life_update_new`: true if it's really new, false if it restates "
    "something above\n"
    "- `upcoming`: only if something is coming up for Briar in the next two weeks that isn't listed above: "
    "`what` (a few words) and `in_days` (1-14)\n"
    "- `parcel`: only if it's natural, a small thing to send along (`name`, `kind`: material, seed, food or "
    "tool, `qty` 1-3, `description`). Most letters have no parcel.\n"
)

GREETING_BARE = (
    "Voice Briar, Pip's neighbor. Who Briar is: An owl.\n"
    "Right now Pip is visiting Briar at home. It is raining.\n"
    "Pip has just arrived at the door; greet it as Briar would. One to three short sentences, spoken aloud, in "
    "character; a small action in *asterisks* is fine. Briar stays at home and can't do more than they "
    "plausibly could. Report the line as `text`, and:\n"
    '- `gist`: one sentence, third person, of what this line says (e.g. "Told Pip the tide times for the week '
    'and asked how its walk went")\n'
    "- `told`: 0-3 short phrases for things about Briar or their world that this line tells Pip for the first "
    "time (not anything Pip already knows); empty if nothing is new\n"
)

TALK_FULL = (
    "Voice Briar, Pip's neighbor. Who Briar is: An owl.\n"
    "Lately in Briar's life: The roof leaks. Rain came.\n"
    "Coming up for Briar:\n"
    "- market in 2 days\n"
    "Things Pip already knows about Briar (refer back to them if it's natural, but don't introduce them again "
    "as news):\n"
    "- has a lamp\n"
    "What's passed between them recently (letters and talk, oldest first; Pip's words in full, Briar's earlier "
    "ones in brief):\n"
    "Pip: hi\n"
    "Briar: hello\n"
    "Right now Pip is visiting Briar at home. It is raining.\n"
    'Pip just said: "hi" / "how are you"\n'
    "Answer Pip as Briar, face to face. One to three short sentences, spoken aloud, in character; a small "
    "action in *asterisks* is fine. Briar stays at home and can't do more than they plausibly could. Report "
    "the line as `text`, and:\n"
    '- `gist`: one sentence, third person, of what this line says (e.g. "Told Pip the tide times for the week '
    'and asked how its walk went")\n'
    "- `told`: 0-3 short phrases for things about Briar or their world that this line tells Pip for the first "
    "time (not anything Pip already knows); empty if nothing is new\n"
)

RECALL = (
    "Briar is Pip's neighbor. Who Briar is: An owl.\n"
    "Everything Briar and Pip have said to each other so far (letters and talk, oldest first):\n"
    "Pip: hi\n"
    "Briar: I have a lamp\n"
    "\n"
    "List what Briar has told Pip about themselves or their world, as `told`: short phrases (under 12 words), "
    'e.g. "their door rattles in the wind". At most 20, the ones that stand out most; facts and details, not '
    "greetings or feelings, and nothing that only Pip said."
)


@pytest.mark.asyncio
async def test_letter_prompt_with_nothing_yet(tmp_path):
    gm, b, _ = master(tmp_path, report(text="Hello!"))
    assert await gm.neighbor_letter("Briar", "An owl.", [], [], None, "", False) == {"text": "Hello!"}
    assert task(b) == LETTER_BARE
    assert b.schemas == [{"type": "object", "properties": LETTER_PROPS, "required": ["text"]}]


@pytest.mark.asyncio
async def test_letter_prompt_with_everything(tmp_path):
    gm, b, _ = master(tmp_path)
    await gm.neighbor_letter("Briar", "An owl.", ["The roof leaks.", "Rain came."],
                             ["Pip: hi", "Briar (in brief): said hello"], "Dear Briar, hi.", "a cup", True,
                             told=["has a lamp", "likes tea"], agenda=["market in 2 days", "a storm tomorrow"])
    assert task(b) == LETTER_FULL
    assert b.schemas == [{"type": "object", "properties": {**LETTER_PROPS, "parcel": PARCEL}, "required": ["text"]}]


@pytest.mark.asyncio
async def test_a_failed_letter_is_logged_as_neighbor_letter(tmp_path):
    gm, b, st = master(tmp_path)  # the fake answers "..." with no report
    assert await gm.neighbor_letter("Briar", "An owl.", [], [], None, "", False) is None
    (e,) = [e for e in st.events(5) if e["kind"] == "gm_error"]
    assert e["data"]["purpose"] == "neighbor_letter"


@pytest.mark.asyncio
async def test_greeting_prompt_with_nothing_yet(tmp_path):
    gm, b, _ = master(tmp_path, report(text="Come in!", gist="Welcomed Pip.", told=[]))
    out = await gm.speak_in_person("Briar", "An owl.", [], [], [], True, "It is raining.")
    assert out == {"text": "Come in!", "gist": "Welcomed Pip.", "told": []}
    assert task(b) == GREETING_BARE
    assert b.schemas == [{"type": "object", "properties": {"text": {"type": "string"}, **REMEMBERING},
                          "required": ["text"]}]


@pytest.mark.asyncio
async def test_talk_prompt_with_everything(tmp_path):
    gm, b, _ = master(tmp_path)
    await gm.speak_in_person("Briar", "An owl.", ["The roof leaks.", "Rain came."], ["Pip: hi", "Briar: hello"],
                             ["hi", "how are you"], False, "It is raining.", told=["has a lamp"],
                             agenda=["market in 2 days"])
    assert task(b) == TALK_FULL


@pytest.mark.asyncio
async def test_a_spoken_line_is_clipped_to_400_and_a_blank_or_failed_one_is_none(tmp_path):
    long = "word " * 79 + "abcde"  # exactly 400 characters
    gm, b, st = master(tmp_path, report(text=long), report(text=long + "f"), report(text="   "))
    args = ("Briar", "An owl.", [], [], ["hi"], False, "")
    assert (await gm.speak_in_person(*args))["text"] == long.strip()
    assert (await gm.speak_in_person(*args))["text"] == "word " * 78 + "word..."
    assert await gm.speak_in_person(*args) is None
    assert await gm.speak_in_person(*args) is None  # the fake has nothing left: no report
    (e,) = [e for e in st.events(5) if e["kind"] == "gm_error"]
    assert e["data"]["purpose"] == "speak_in_person"


@pytest.mark.asyncio
async def test_recall_prompt_and_only_strings_are_kept(tmp_path):
    gm, b, st = master(tmp_path, report(told=["has a lamp", 3, None, "likes tea"]), report(told="a lamp"))
    assert await gm.recall_told("Briar", "An owl.", ["Pip: hi", "Briar: I have a lamp"]) == ["has a lamp",
                                                                                           "likes tea"]
    assert task(b) == RECALL
    assert b.schemas[0] == {"type": "object", "properties": {"told": {"type": "array", "items": {"type": "string"}}},
                            "required": ["told"]}
    assert await gm.recall_told("Briar", "An owl.", []) is None  # not a list
    assert await gm.recall_told("Briar", "An owl.", []) is None  # no report at all
    (e,) = [e for e in st.events(5) if e["kind"] == "gm_error"]
    assert e["data"]["purpose"] == "recall_told"
