"""Talk that reads like talk (docs/DESIGN-conversation.md): no saying the same thing twice, the conversation shown in full, and the neighbor told to talk like a person."""
import time

import pytest

from app import conversation as C
from app import neighbors as nb
from app import tools as T
from tests.test_neighbor import FixedRng, neighbor
from tests.test_projects import call, make, report

HOUR = 3600


# --- repeats ---------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("text, earlier, said", [
    ("Keep the packet dry and feel its weight before you tip it.", ["Good. Keep the packet dry and feel its weight before you tip it, Pip."], True),
    ("I'll see you Thursday at half past four.", ["Thank you, Oriel. I'll see you Thursday at half past four."], True),
    ("*Nods slowly.* The step is still cool this morning.", ["*Lays her palm on the tin.* The step is still cool this morning, Pip."], True),
    ("*Nods slowly, palm on the tin.* Good.", ["*Nods slowly, palm on the tin.* Half past four, then."], False),       # a gesture is not a repeat; the words are
    ("thank you", ["Thank you!"], False),                                                                            # a short line may come twice
    ("THE HERON IS BACK ON THE FLATS, PIP.", ["The heron is back on the flats, Pip!"], True),
    ("The heron is back on the flats.", ["The heron flew off the flats."], False),
    ("A brand new thought about the tides tonight.", [], False),
    ("", ["anything at all here to compare with"], False),
    ("The tide came in early and the boats went out late", ["The tide went in early and the boats came out late"], True),            # nearly the same line
])
def test_what_counts_as_saying_the_same_thing_again(text, earlier, said):
    assert C.repeats(text, earlier) is said


# --- transcripts ---------------------------------------------------------------------------------------------------------
def test_a_visit_is_shown_in_full_since_pip_arrived(tmp_path):
    s, st, gm, agent = make(tmp_path)
    st.log("companion", name="Oriel", text="Before you came.")
    since = time.time() + 0.001
    time.sleep(0.01)
    st.log("say", text="Hello, Oriel!", to=[], to_name="Oriel")
    st.log("companion", name="Oriel", text="Pip! Come in.")
    st.log("companion", name="Briar", text="Not Oriel.")
    st.log("say", text="To someone else.", to=[], to_name="Briar")
    assert C.visit_lines(st, "Oriel", since) == ["You: Hello, Oriel!", "Oriel: Pip! Come in."]
    for i in range(12):
        st.log("say", text=f"line {i}", to=[], to_name="Oriel")
    assert C.visit_lines(st, "Oriel", since)[-1] == "You: line 11" and len(C.visit_lines(st, "Oriel", since)) == C.VISIT_LINES


def test_a_chat_with_a_visitor_is_shown_with_pips_answers_and_its_postcards(tmp_path):
    s, st, gm, agent = make(tmp_path)
    now = time.time()
    st.log("outreach", what="postcard", channel="matrix", text="A wish of mine: a stall.", delivered=True)
    st.log("outreach", what="postcard", channel="matrix", text="Never went.", delivered=False)
    st.log("inbox", id=1, text="Lovely idea!", sender="Travis", source="matrix")
    st.log("say", text="Thank you, it's on my mind.", to=[1])
    st.log("inbox", id=2, text="Travis gave you 1 x file.", sender="Travis", gift=True)
    st.log("inbox", id=3, text="A letter.", sender="Travis", letter=True)
    st.log("inbox", id=4, text="Hello from someone else.", sender="Dana", source="web")
    st.log("say", text="Hi Dana.", to=[4])
    st.log("inbox", id=5, text="Is it a good project?", sender="Travis", source="matrix")
    assert C.thread_lines(st, "Travis", now + 1, skip_ids={5}) == [
        "You (a postcard you sent): A wish of mine: a stall.", "Travis: Lovely idea!", "You: Thank you, it's on my mind."]
    assert C.thread_lines(st, "Travis", now + 1)[-1] == "Travis: Is it a good project?"
    assert C.thread_lines(st, "Travis", now + 4 * 86400) == []                                      # three days is the memory of a thread
    assert C.thread_lines(st, "Dana", now + 1) == ["Dana: Hello from someone else.", "You: Hi Dana."]


def test_a_long_chat_shows_its_latest_lines(tmp_path):
    s, st, gm, agent = make(tmp_path)
    for i in range(15):
        st.log("inbox", id=i, text=f"message {i}", sender="Travis", source="matrix")
    lines = C.thread_lines(st, "Travis", time.time() + 1)
    assert len(lines) == C.THREAD_LINES and lines[-1] == "Travis: message 14"


def test_pip_is_shown_the_chat_so_far_beside_a_waiting_message_and_its_postcards_among_events(tmp_path):
    s, st, gm, agent = make(tmp_path)
    st.log("outreach", what="postcard", channel="matrix", text="A wish of mine: a stall.", delivered=True)
    i = agent.receive("I think this is a good project for you!", "Travis", source="matrix", conversation="$t")
    p = agent._perception("event", st.pending_inbox())
    assert "Your conversation with Travis so far (oldest first):\n  You (a postcard you sent): A wish of mine: a stall." in p
    assert "- Travis (via matrix): I think this is a good project for you!" in p
    assert "- you sent a postcard (matrix): A wish of mine: a stall." in p


@pytest.mark.asyncio
async def test_pip_is_shown_the_visit_so_far_at_a_neighbors_home(tmp_path):
    s, st, gm, agent = make(tmp_path, [report(text="A low cottage humming with bees."), report(text="Pip! Come in.")], work_speed=1e6)
    neighbor(st, s)
    await call(agent, "go_to", place="Marigold")
    time.sleep(0.01)
    await agent.finish_work()
    await nb.step(st, s, agent.gm, FixedRng(), time.time())
    p = agent._perception("event", [])
    assert "Talking with Marigold (this visit, oldest first):\n  Marigold: Pip! Come in." in p
    st.update_agent(location="workshop")
    assert "Talking with Marigold" not in agent._perception("event", [])


# --- Pip does not say the same thing twice -------------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_pip_is_stopped_from_repeating_a_line_it_has_just_said(tmp_path):
    s, st, gm, agent = make(tmp_path)
    agent.tools["say"] = T.REGISTRY["say"]
    line = "I'll keep the packet dry and feel its weight before I tip it."
    assert (await call(agent, "say", text=line)).text == "said it"
    r = await call(agent, "say", text="Thank you, Oriel. " + line)
    assert r.text == "not said: you said that a moment ago. Say something new, ask something, or say goodbye." and r.followup
    assert (await call(agent, "say", text="Thank you!")).text == "said it" and (await call(agent, "say", text="Thank you!")).text == "said it"
    st.db.execute("UPDATE events SET ts = ts - ? WHERE kind = 'say'", (3 * HOUR,))
    st.db.commit()
    assert (await call(agent, "say", text=line)).text == "said it"                                   # hours later, it may come again


# --- the neighbor ----------------------------------------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_a_neighbor_who_repeats_herself_is_asked_once_for_something_new(tmp_path):
    s, st, gm, agent = make(tmp_path, [report(text="A low cottage humming with bees."), report(text="Keep the packet dry and feel its weight, Pip."),
                                       report(text="Keep the packet dry and feel its weight, Pip, always."), report(text="How are the carrots coming on?")],
                            work_speed=1e6)
    neighbor(st, s)
    await call(agent, "go_to", place="Marigold")
    time.sleep(0.01)
    await agent.finish_work()
    await nb.step(st, s, agent.gm, FixedRng(), time.time())                                         # the greeting
    await call(agent, "say", text="Shall I bring the packet?", to="marigold")
    await nb.step(st, s, agent.gm, FixedRng(), time.time())
    said = [e["data"]["text"] for e in st.events(10) if e["kind"] == "companion"]
    assert said[0] == "How are the carrots coming on?"
    assert "say something new this time" in gm.calls[3]["messages"][0]["content"] and "say something new" not in gm.calls[2]["messages"][0]["content"]


@pytest.mark.asyncio
async def test_she_is_told_to_talk_like_a_person(tmp_path):
    s, st, gm, agent = make(tmp_path, [report(text="A low cottage."), report(text="Pip! Come in.")], work_speed=1e6)
    neighbor(st, s)
    await call(agent, "go_to", place="Marigold")
    time.sleep(0.01)
    await agent.finish_work()
    await nb.step(st, s, agent.gm, FixedRng(), time.time())
    task = gm.calls[1]["messages"][0]["content"]
    assert "Most lines need no action" in task and "never a gesture already used in this talk" in task
    assert "Talk like a person, not a teacher" in task and "bring the talk to a close" in task


def test_a_creation_with_a_mind_is_told_not_to_repeat_itself():
    import inspect
    from app import gm
    assert "not something already said in the conversation above" in inspect.getsource(gm.GameMaster.speak)


# --- the day and the guide ---------------------------------------------------------------------------------------------------
def test_pip_knows_the_day_and_the_time():
    from app.loop import clock_line
    assert clock_line(time.mktime((2026, 11, 7, 14, 5, 0, 0, 0, -1))) == "It is Saturday 7 November, 2:05 pm."
    assert clock_line(time.mktime((2026, 11, 5, 9, 30, 0, 0, 0, -1))) == "It is Thursday 5 November, 9:30 am."


def test_the_prompt_carries_the_day(tmp_path):
    from app.loop import clock_line
    s, st, gm, agent = make(tmp_path)
    p = agent._perception("timer", [])
    assert p.split("\n")[2].startswith("It is ") and p.split("\n")[2].endswith(("am.", "pm."))


def test_the_guide_says_how_to_hold_a_conversation():
    from app import guide
    from app.config import Settings
    text = guide.render(["say"], Settings(), False)
    assert "In a conversation, answer what was just said" in text and "say goodbye before you walk away" in text
    assert "In a conversation" not in guide.render(["note_to_self"], Settings(), False)


# --- details found by the mutation run --------------------------------------------------------------------------------------
def test_six_words_at_either_end_of_a_long_line_are_a_repeat():
    assert C.repeats("keep the packet dry this time", ["Oh and one more thing before you go, Pip: keep the packet dry this time"])
    assert C.repeats("Oh and one more thing before you go, Pip: keep the packet dry this time", ["keep the packet dry this time"])
    assert C.repeats("the tide came in early", ["The tide came in early!"])                         # five words, the same line
    assert not C.repeats("*nods* the tide came in", ["*smiles* the tide came in"])                   # four words; the gestures do not count


def test_the_edges_of_a_visit_and_a_thread(tmp_path):
    s, st, gm, agent = make(tmp_path)
    eid = st.log("say", text="At the very moment.", to=[], to_name="Oriel")
    st.db.execute("UPDATE events SET ts = 1000 WHERE id = ?", (eid,))
    st.db.commit()
    assert C.visit_lines(st, "Oriel", 1000) == ["You: At the very moment."]                        # said the moment Pip arrived: part of the visit
    now = time.time()
    old = st.log("inbox", id=1, text="Three days ago exactly.", sender="Travis", source="matrix")
    st.db.execute("UPDATE events SET ts = ? WHERE id = ?", (now - 3 * 86400, old))
    st.db.commit()
    assert C.thread_lines(st, "Travis", now) == ["Travis: Three days ago exactly."]
    st.log("inbox", id=2, text="Travis gave you 1 x file.", sender="Travis", gift=True, source="matrix")
    st.log("say", text="Thanks for the file!", to=[2])
    st.log("inbox", id=3, text="A letter from Travis.", sender="Travis", letter=True)
    st.log("say", text="What a letter.", to=[3])
    assert C.thread_lines(st, "Travis", now) == ["Travis: Three days ago exactly."]                # answers to gifts and letters are not the chat
    st.log("inbox", id=4, text="Hi from the web.", sender="Dana")
    st.log("outreach", what="postcard", channel="web", text="A web postcard.", delivered=True)
    assert C.thread_lines(st, "Dana", now + 1) == ["Dana: Hi from the web.", "You (a postcard you sent): A web postcard."]


def test_a_text_is_cut_at_any_sentence_end_and_only_when_it_is_too_long():
    from app import happenings as H
    shout = "x" * 100 + "! " + "y" * 400
    assert H.trim(shout) == "x" * 100 + "!"
    ask = "x" * 100 + "? " + "y" * 400
    assert H.trim(ask) == "x" * 100 + "?"
    edge = "x" * 30 + ". " + "b" * (H.MAX_TEXT - 32)
    assert len(edge) == H.MAX_TEXT and H.trim(edge) == edge                                         # exactly the limit is not too long
    short = "x" * (H.MIN_TEXT - 2) + ". " + "y" * 500
    assert H.trim(short) == short                                                                   # cutting would leave too little
    just = "x" * (H.MIN_TEXT - 1) + ". " + "y" * 500
    assert H.trim(just) == "x" * (H.MIN_TEXT - 1) + "."                                             # exactly the least that may be left


def test_a_memory_lends_its_names_to_the_text(tmp_path):
    import asyncio
    from app import happenings as H
    from tests.test_happenings import CAND, StubGM
    mem = "Bram the miller showed me the slow way to dress a stone."
    gm = StubGM({"title": "The miller", "text": "You think of the day the miller called Bram showed you the slow way, and it lingers."})
    cand = {**CAND, "category": "memory", "names": [], "facts": {"memory": mem}, "line": ""}
    assert asyncio.run(H.author(gm, cand, {"period": "day", "names": [], "memory": mem}, []))[2] == "gm"


def test_a_place_only_heard_of_does_not_stop_the_search(tmp_path):
    from app import wishes as W
    s, st, gm, agent = make(tmp_path)
    st.add_place("Fen", "fen", kind="market", status="heard", created_at=1.0, heard_at=1.0, walk_minutes=10.0, loot=[])
    st.add_place("Brygdon", "brygdon", kind="market", status="real", created_at=2.0, heard_at=2.0, hours=[0, 24], daylight_only=0, walk_minutes=10.0,
                 loot=[["sticks", "material", 30, [2, 5], "s", {}]], verbs={"browse": ["see", None]})
    assert W.doings(st, s, None, "to run a stall of my own", {"sell": 1})[0].startswith("at Brygdon:")
