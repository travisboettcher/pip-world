"""Exact prompts and tool schemas for the neighbor's GM calls (letters, talk in person, recalling what's been told)."""
import pytest

from app.gm import GameMaster
from app.invented_places import MENTION_PROPERTY
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
    "something from their own life. Don't reuse a sentence, image or daily ritual from your earlier letters; tell something new. Pip can walk over to visit Briar at home (you can invite it), but Briar "
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
    "Places in Pip's world: the woods (foraging); Saltholm, a long walk\n"
    "Your letters with Pip so far (oldest first; Pip's in full, yours in brief):\n"
    "Pip: hi\n"
    "Briar (in brief): said hello\n"
    "\n"
    "Pip's letter just arrived:\n"
    "Dear Briar, hi.\n"
    "Pip enclosed something with it: a cup. React to it honestly.\n"
    "\n"
    "Write Briar's letter: 2-5 sentences in their own voice, answering what Pip said if anything, and sharing "
    "something from their own life. Don't reuse a sentence, image or daily ritual from your earlier letters; tell something new. Pip can walk over to visit Briar at home (you can invite it), but Briar "
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
    "- Only if your words point Pip somewhere new, give `mentions_place`.\n"
)

GREETING_BARE = (
    "Voice Briar, Pip's neighbor. Who Briar is: An owl.\n"
    "Right now Pip is visiting Briar at home. It is raining.\n"
    "Pip has just arrived at the door; greet it as Briar would. One or two short sentences, spoken aloud, in character. Most lines need no action; if one helps, a few words in "
    "*asterisks*, never a gesture already used in this talk. Talk like a person, not a teacher: you may ask Pip something, tell your own news "
    "or what you think, disagree, or bring the talk to a close when it has run its course; don't keep giving instructions or say again what "
    "has already been said. Briar stays at home and can't do more than they "
    "plausibly could, and hands Pip nothing: nothing changes hands today, so never describe giving, counting out, tipping out "
    "or letting Pip take or help themselves to anything; if Pip asks for something, say it isn't to be had today. Report the line as `text`, and:\n"
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
    "Places in Pip's world: the woods (foraging); Saltholm, a long walk\n"
    "What's passed between them recently (letters and talk, oldest first; Pip's words in full, Briar's earlier "
    "ones in brief):\n"
    "Pip: hi\n"
    "Briar: hello\n"
    "Right now Pip is visiting Briar at home. It is raining.\n"
    'Pip just said: "hi" / "how are you"\n'
    "Answer Pip as Briar, face to face. One or two short sentences, spoken aloud, in character. Most lines need no action; if one helps, a few words in "
    "*asterisks*, never a gesture already used in this talk. Talk like a person, not a teacher: you may ask Pip something, tell your own news "
    "or what you think, disagree, or bring the talk to a close when it has run its course; don't keep giving instructions or say again what "
    "has already been said. Briar stays at home and can't do more than they plausibly could, and hands Pip nothing: nothing changes hands today, so never "
    "describe giving, counting out, tipping out or letting Pip take or help themselves to anything; if Pip asks for something, say it isn't to be "
    "had today. Report the line as `text`, and:\n"
    '- `gist`: one sentence, third person, of what this line says (e.g. "Told Pip the tide times for the week '
    'and asked how its walk went")\n'
    "- `told`: 0-3 short phrases for things about Briar or their world that this line tells Pip for the first "
    "time (not anything Pip already knows); empty if nothing is new\n"
    "- Only if your words point Pip somewhere new, give `mentions_place`.\n"
)

PLACES = "Places in Pip's world: the woods (foraging); Saltholm, a long walk"
MENTION = "Only if your words point Pip somewhere new, give `mentions_place`."
MENTIONS = {"mentions_place": MENTION_PROPERTY}

LIFE_UPDATE = (
    "Optional:\n"
    "- `life_update`: one sentence, only if something in their life has changed since what's already happening "
    "(it carries into later talk), with `life_update_new`: true if it's really new, false if it restates "
    "something above\n"
)

RESIDENT_GREETING = (
    "Voice Mr Teague, who Pip meets at Saltholm. Who Mr Teague is: An ironmonger.\n"
    "Right now Pip is at Saltholm, with Mr Teague. It is raining.\n"
    "Pip has just arrived; greet it as Mr Teague would. One or two short sentences, spoken aloud, in character. Most lines need no action; if one helps, a few words in "
    "*asterisks*, never a gesture already used in this talk. Talk like a person, not a teacher: you may ask Pip something, tell your own news "
    "or what you think, disagree, or bring the talk to a close when it has run its course; don't keep giving instructions or say again what "
    "has already been said. Mr Teague stays at Saltholm and can't do more than they "
    "plausibly could, and hands Pip nothing: nothing changes hands today, so never describe giving, counting out, tipping out "
    "or letting Pip take or help themselves to anything; if Pip asks for something, say it isn't to be had today. Report the line as `text`, and:\n"
    '- `gist`: one sentence, third person, of what this line says (e.g. "Told Pip the tide times for the week '
    'and asked how its walk went")\n'
    "- `told`: 0-3 short phrases for things about Mr Teague or their world that this line tells Pip for the first "
    "time (not anything Pip already knows); empty if nothing is new\n"
    + LIFE_UPDATE
)

RESIDENT_TALK = (
    "Voice Mr Teague, who Pip meets at Saltholm. Who Mr Teague is: An ironmonger.\n"
    "Lately in Mr Teague's life: A new drawer came.\n"
    "Things Pip already knows about Mr Teague (refer back to them if it's natural, but don't introduce them again "
    "as news):\n"
    "- sells wire\n"
    "Places in Pip's world: the woods (foraging); Saltholm, a long walk\n"
    "What's passed between them recently (oldest first; Pip's words in full, Mr Teague's earlier ones in brief):\n"
    "Pip: hi\n"
    "Mr Teague: hello\n"
    "Right now Pip is at Saltholm, with Mr Teague. It is raining.\n"
    'Pip just said: "any wire?"\n'
    "Answer Pip as Mr Teague, face to face. One or two short sentences, spoken aloud, in character. Most lines need no action; if one helps, a few words in "
    "*asterisks*, never a gesture already used in this talk. Talk like a person, not a teacher: you may ask Pip something, tell your own news "
    "or what you think, disagree, or bring the talk to a close when it has run its course; don't keep giving instructions or say again what "
    "has already been said. Mr Teague stays at Saltholm and can't do more than they plausibly could, "
    "and hands Pip nothing: nothing changes hands today, so never describe giving, counting out, tipping out or letting Pip take or help "
    "themselves to anything; if Pip asks for something, say it isn't to be had today. Report the line as `text`, and:\n"
    '- `gist`: one sentence, third person, of what this line says (e.g. "Told Pip the tide times for the week '
    'and asked how its walk went")\n'
    "- `told`: 0-3 short phrases for things about Mr Teague or their world that this line tells Pip for the first "
    "time (not anything Pip already knows); empty if nothing is new\n"
    + LIFE_UPDATE
    + "- Only if your words point Pip somewhere new, give `mentions_place`.\n"
)
LIFE_PROPS = {"life_update": {"type": "string"}, "life_update_new": {"type": "boolean"}}

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
                             told=["has a lamp", "likes tea"], agenda=["market in 2 days", "a storm tomorrow"],
                             places=PLACES, mention=MENTION)
    assert task(b) == LETTER_FULL
    assert b.schemas == [{"type": "object", "properties": {**LETTER_PROPS, "parcel": PARCEL, **MENTIONS},
                          "required": ["text"]}]


@pytest.mark.asyncio
async def test_a_failed_letter_is_logged_as_neighbor_letter(tmp_path):
    gm, b, st = master(tmp_path)  # the fake answers "..." with no report
    assert await gm.neighbor_letter("Briar", "An owl.", [], [], None, "", False) is None
    (e,) = [e for e in st.events(5) if e["kind"] == "gm_error"]
    assert e["data"]["purpose"] == "neighbor_letter"


@pytest.mark.asyncio
async def test_greeting_prompt_with_nothing_yet(tmp_path):
    gm, b, _ = master(tmp_path, report(text="Come in!", gist="Welcomed Pip.", told=[]))
    out = await gm.speak_in_person("Briar", "An owl.", [], [], [], "It is raining.")
    assert out == {"text": "Come in!", "gist": "Welcomed Pip.", "told": []}
    assert task(b) == GREETING_BARE
    assert b.schemas == [{"type": "object", "properties": {"text": {"type": "string"}, **REMEMBERING},
                          "required": ["text"]}]


@pytest.mark.asyncio
async def test_talk_prompt_with_everything(tmp_path):
    gm, b, _ = master(tmp_path)
    await gm.speak_in_person("Briar", "An owl.", ["The roof leaks.", "Rain came."], ["Pip: hi", "Briar: hello"],
                             ["hi", "how are you"], "It is raining.", told=["has a lamp"],
                             agenda=["market in 2 days"], places=PLACES, mention=MENTION)
    assert task(b) == TALK_FULL
    assert b.schemas == [{"type": "object", "properties": {"text": {"type": "string"}, **REMEMBERING, **MENTIONS},
                          "required": ["text"]}]


@pytest.mark.asyncio
async def test_a_resident_greets_pip_where_they_are(tmp_path):
    gm, b, _ = master(tmp_path)
    await gm.speak_in_person("Mr Teague", "An ironmonger.", [], [], [], "It is raining.", at="Saltholm")
    assert task(b) == RESIDENT_GREETING
    assert b.schemas == [{"type": "object", "properties": {"text": {"type": "string"}, **REMEMBERING, **LIFE_PROPS},
                          "required": ["text"]}]


@pytest.mark.asyncio
async def test_a_resident_talks_with_pip_with_everything(tmp_path):
    gm, b, _ = master(tmp_path)
    await gm.speak_in_person("Mr Teague", "An ironmonger.", ["A new drawer came."], ["Pip: hi", "Mr Teague: hello"],
                             ["any wire?"], "It is raining.", told=["sells wire"], places=PLACES, mention=MENTION,
                             at="Saltholm")
    assert task(b) == RESIDENT_TALK
    assert b.schemas == [{"type": "object", "properties": {"text": {"type": "string"}, **REMEMBERING, **LIFE_PROPS,
                                                           **MENTIONS}, "required": ["text"]}]


@pytest.mark.asyncio
async def test_a_spoken_line_is_clipped_to_400_and_a_blank_or_failed_one_is_none(tmp_path):
    long = "word " * 79 + "abcde"  # exactly 400 characters
    gm, b, st = master(tmp_path, report(text=long), report(text=long + "f"), report(text="   "))
    args = ("Briar", "An owl.", [], [], ["hi"], "")
    assert (await gm.speak_in_person(*args))["text"] == long.strip()
    assert (await gm.speak_in_person(*args))["text"] == "word " * 78 + "word..."
    assert await gm.speak_in_person(*args) is None
    assert await gm.speak_in_person(*args) is None  # the fake has nothing left: no report
    (e,) = [e for e in st.events(5) if e["kind"] == "gm_error"]
    assert e["data"]["purpose"] == "speak_in_person"


@pytest.mark.asyncio
async def test_a_structured_ask_is_the_modules_prompt_and_schema(tmp_path):
    gm, b, _ = master(tmp_path)
    schema = {"type": "object", "properties": {"name": {"type": "string", "description": "what they're called", "x": 1}}, "required": ["name"]}
    await gm.structured("Who lives near?", schema)
    await gm.structured("Who lives near?", schema, mentions=True)
    assert task(b, 0) == "Who lives near?" and task(b, 1) == "Who lives near?"
    props = {"name": {"type": "string", "description": "what they're called"}}
    assert b.schemas == [{"type": "object", "properties": props, "required": ["name"]},
                         {"type": "object", "properties": {**props, **MENTIONS}, "required": ["name"]}]


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


# --- designing a place a character told Pip about (invented places) --------------------------------------------
DESIGN_BARE = (
    "Pip has just arrived at Fallow for the first time. Nobody has described it before; this is what others told "
    "Pip about it (the place must agree with all of it):\n"
    "- Briar says: a meadow\n"
    "- Morgan mentioned it\n"
    "\n"
    "Decide what Fallow is. `kind`, one of: {kinds}. Use the kind what was said suggests; a shop only if someone "
    "said there's a shop or a trade there. Give:\n"
    "- `description`: 2-3 sentences of the place as Pip finds it (kept, and shown whenever Pip is here)\n"
    "- `blurb`: one short line for a list of places\n"
    "- `loot`: 4-10 things that can be found or had there, each {{`name`, `kind`: material, food, seed or tool, "
    "`tier`: common, uncommon or rare, `description`}}; include everything the words above say is there. \n"
    "- for a shop: `opens` and `closes` (local hours); `gather_help` (a few words: how Pip picks through the "
    "stock), `browse_help` (a few words: how Pip sees what's in), `gerund` (e.g. 'rummaging in the drawer'). For a "
    "wild place or a yard: `gather_help` and `gerund`. A sight needs none of these.\n"
    "- `resident`: someone who lives or works there and will talk with Pip, if the place has one (a shop "
    "normally has its keeper; a wild place or a sight often has nobody): `name`, `persona` (3-5 sentences, "
    "private: who they are, their days, how they talk) and `about` (one short line of what Pip would know of them "
    "once met). If the words above name someone who is there, it's them; never Pip or whoever told Pip about it."
)
STR = {"type": "string"}
DESIGN_SCHEMA = {"type": "object", "properties": {
    "kind": STR, "description": STR, "blurb": STR,
    "loot": {"type": "array", "items": {"type": "object", "properties": {"name": STR, "kind": STR, "tier": STR,
                                                                         "description": STR}}},
    "opens": {"type": "integer"}, "closes": {"type": "integer"}, "gather_help": STR, "browse_help": STR, "gerund": STR,
    "resident": {"type": "object", "properties": {"name": STR, "persona": STR, "about": STR},
                 "required": ["name", "persona"]},
}, "required": ["kind", "description"]}


async def test_design_place_prompt_and_schema_exactly(tmp_path):
    from app import place_kinds
    gm, backend, st = master(tmp_path, report(kind="wild", description="A meadow."))
    out = await gm.design_place("Fallow", ["Briar says: a meadow", "Morgan mentioned it"], [])
    assert out == {"kind": "wild", "description": "A meadow."}
    assert task(backend) == DESIGN_BARE.format(kinds=place_kinds.gm_lines())
    assert backend.schemas[0] == DESIGN_SCHEMA
    backend.queue(report(kind="wild"))
    assert await gm.design_place("Fallow", [], []) is None
    assert st.events(limit=1)[0]["data"] == {"purpose": "design_place", "error": "no usable report"}


async def test_a_failed_structured_ask_is_logged_as_such(tmp_path):
    gm, backend, st = master(tmp_path, report(age=3))
    assert await gm.structured("Who?", {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]}) is None
    assert st.events(limit=1)[0]["data"] == {"purpose": "module_structured", "error": "no usable report"}


@pytest.mark.asyncio
async def test_a_neighbor_may_hand_pip_something_only_through_give(tmp_path):
    gm, b, _ = master(tmp_path)
    await gm.speak_in_person("Briar", "An owl.", [], [], ["got any seeds?"], "It is raining.", can_give=True)
    t = task(b)
    assert "hands Pip nothing" not in t and "could. Report the line as `text`, and:\n" in t
    assert ("- `give`: only if Briar really hands Pip something small right now "
            "(`name`, `kind`: material, seed, food or tool, `qty` 1-3, `description`). Pip receives exactly this and nothing "
            "else, so never describe handing over, offering a pinch of, letting Pip take or help themselves to, or giving anything you do not "
            "report here\n") in t
    assert "give" in b.schemas[0]["properties"] and b.schemas[0]["properties"]["give"]["type"] == "object"
    await gm.speak_in_person("Briar", "An owl.", [], [], ["got any seeds?"], "It is raining.")
    assert "give" not in b.schemas[1]["properties"] and "`give`" not in task(b, 1)
    assert "hands Pip nothing" in task(b, 1)


# --- using a creation (and the news a radio brings) ----------------------------------------------------------------
USE_PROPS = {"text": {"type": "string"}, "mood": {"type": "string"}, "energy": {"type": "number"}}


@pytest.mark.asyncio
async def test_using_a_creation_asks_which_of_its_own_actions_pip_did(tmp_path):
    gm, b, _ = master(tmp_path, report(text="Tick."), report(text="Tick."))
    await gm.use("- clock", "wind it", "Pip is idle.", [{"name": "tend", "help": "wound: keeps it going about 12 hours"},
                                                        {"name": "set", "help": "set it to the right time"}])
    assert task(b, 0).endswith("- `action`: only if what Pip does is one of these, its name: tend (wound: keeps it going about 12 hours); "
                               "set (set it to the right time). Looking at it, admiring it or talking about it is none of them")
    assert b.schemas[0] == {"type": "object", "properties": {**USE_PROPS, "action": {"type": "string"}}, "required": ["text"]}
    await gm.use("- painting", "admire it", "Pip is idle.")
    assert "`action`" not in task(b, 1) and b.schemas[1] == {"type": "object", "properties": USE_PROPS, "required": ["text"]}
    assert "bulletin" not in task(b, 1) and "`tend`" not in task(b, 1) and "set_clock" not in task(b, 1)


