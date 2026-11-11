import time

import pytest

from app import companions as comp
from tests.test_creations import build
from tests.test_projects import FixedRng, call, make, report

BIRD = {"name": "Wren", "description": "a tin bird", "quirks": ["one wing squeaks"], "capabilities": [
    {"type": "companion", "persona": "A cheeky tin bird who loves shiny things.", "chatter_minutes": 60},
    {"type": "upkeep", "verb": "wind", "hours": 12}]}


def bird(st, now=None):
    c = build(st, BIRD, now=now)
    return c, comp.add_for_creation(st, FixedRng(), c)


@pytest.mark.asyncio
async def test_say_to_unknown_name_is_plain_speech(tmp_path):
    s, st, gm, agent = make(tmp_path)
    assert (await call(agent, "say", text="hello?", to="ghost")).text == "said it"


def test_conversation_with_one_name_and_earlier_lines_in_brief(tmp_path):
    s, st, gm, agent = make(tmp_path)
    st.log("companion", name="Marigold", text="Mind the step. It wobbles.", reply=True)  # no gist: its first sentence
    st.log("say", text="Hi Bramble!", to_name="Bramble")  # said to someone else
    st.log("say", text="Hi Marigold!", to_name="Marigold")
    st.log("companion", name="Marigold", text="Come in. Tea?", reply=True)
    since = st.events(1)[0]["ts"]  # this visit began with her last line
    assert comp.conversation(st, "Marigold", verbatim_since=since) == [
        "Marigold (in brief): Mind the step.", "Pip: Hi Marigold!", "Marigold: Come in. Tea?"]
    assert comp.conversation(st, "Marigold") == ["Marigold: Mind the step. It wobbles.", "Pip: Hi Marigold!",
                                                 "Marigold: Come in. Tea?"]


def test_conversation_looks_back_200_events(tmp_path):
    s, st, gm, agent = make(tmp_path)
    st.log("companion", name="Marigold", text="Long ago.", reply=True)
    for i in range(200):
        st.log("note", text=f"n{i}")
    assert comp.conversation(st, "Marigold") == []
