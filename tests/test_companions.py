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
async def test_companion_answers_pip_and_wakes_it(tmp_path):
    s, st, gm, agent = make(tmp_path, [report(text="Shiny? Where?!")])
    c, ch = bird(st)
    assert ch["name"] == "Wren" and ch["next_chatter_at"] > time.time() + 30 * 60  # 60 min x jitter
    r = await call(agent, "say", text="Look what I found, Wren", to="wren")
    assert "said it to Wren" in r.text
    await agent.resolve_world()
    assert agent._wake.is_set()
    e = st.events(1)[0]
    assert e["kind"] == "companion" and e["data"] == {"name": "Wren", "text": "Shiny? Where?!", "reply": True}
    prompt = gm.calls[0]["messages"][0]["content"]
    assert "A cheeky tin bird" in prompt and 'Pip just said to Wren: "Look what I found, Wren"' in prompt
    assert "one wing squeaks" in prompt
    assert st.characters()[0]["heard"] == []
    assert 'Wren said: "Shiny? Where?!" (answering you)' in agent._perception("event", [])


@pytest.mark.asyncio
async def test_chatter_when_due_does_not_wake(tmp_path):
    s, st, gm, agent = make(tmp_path, [report(text="*preens*")])
    c, ch = bird(st)
    assert await comp.step(st, s, agent.gm, agent.rng) is False and gm.calls == []  # not due yet
    assert await comp.step(st, s, agent.gm, agent.rng, now=ch["next_chatter_at"] + 1) is False
    assert st.events(1)[0]["data"]["text"] == "*preens*"
    assert "Nobody spoke to Wren" in gm.calls[0]["messages"][0]["content"]


@pytest.mark.asyncio
async def test_replies_are_capped_per_hour(tmp_path):
    s, st, gm, agent = make(tmp_path, [report(text=f"reply {i}") for i in range(3)], companion_replies_per_hour=2)
    c, ch = bird(st)
    for i in range(3):
        await call(agent, "say", text=f"hi {i}", to="Wren")
        await comp.step(st, s, agent.gm, agent.rng)
    assert [e["data"]["text"] for e in st.events(10) if e["kind"] == "companion"] == ["reply 1", "reply 0"]
    assert [h["text"] for h in st.characters()[0]["heard"]] == ["hi 2"]  # waits for the cap to clear


@pytest.mark.asyncio
async def test_stopped_companion_is_silent(tmp_path):
    s, st, gm, agent = make(tmp_path, [report(text="hello")])
    c, ch = bird(st, now=time.time() - 13 * 3600)  # ran down an hour ago
    await call(agent, "say", text="Wren?", to="Wren")
    assert await comp.step(st, s, agent.gm, agent.rng) is False and gm.calls == []


@pytest.mark.asyncio
async def test_say_to_unknown_name_is_plain_speech(tmp_path):
    s, st, gm, agent = make(tmp_path)
    assert (await call(agent, "say", text="hello?", to="ghost")).text == "said it"
