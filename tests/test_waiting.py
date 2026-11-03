"""Waiting: set_activity(minutes=N) tells the world Pip is waiting on something, so the heartbeat leaves it alone for that long."""
import asyncio
import time

import pytest

from app import guide
from app.config import Settings
from app.llm.base import LLMResponse, ToolCall, Usage
from tests.test_agent import make


def set_activity(**args):
    return LLMResponse("", [ToolCall("1", "set_activity", args)], Usage(1, 1))


@pytest.mark.asyncio
async def test_a_wait_leaves_the_heartbeat_alone_until_it_is_over(tmp_path):
    s, st, backend, agent = make(tmp_path, [set_activity(activity="waiting", description="Watching the carrots.", minutes=90)])
    await agent.tick("test")
    assert st.agent()["activity"] == "waiting"
    assert float(st.meta("wait_until")) - time.time() == pytest.approx(90 * 60, abs=5) and st.meta("wait_label") == "waiting"
    agent.pacing.next_delay = lambda now, last: 1.0
    with pytest.raises(asyncio.TimeoutError):                            # the 1 s heartbeat is stretched to the wait's end
        await asyncio.wait_for(agent._sleep(), timeout=0.3)
    agent.request_wake(urgent=True)                                      # a visitor, a ripe crop or an alert still gets through
    assert await asyncio.wait_for(agent._sleep(), timeout=3) == "event"
    st.update_agent(activity="tinkering")                                # a different activity is the end of the wait
    assert await asyncio.wait_for(agent._sleep(), timeout=3) == "timer"


@pytest.mark.asyncio
async def test_the_wait_ends_when_its_time_does(tmp_path):
    s, st, backend, agent = make(tmp_path)
    st.update_agent(activity="waiting")
    st.set_meta(wait_until=str(time.time() - 1), wait_label="waiting")
    agent.pacing.next_delay = lambda now, last: 0.05
    assert await asyncio.wait_for(agent._sleep(), timeout=3) == "timer"


@pytest.mark.asyncio
@pytest.mark.parametrize("minutes, shown", [(1, 5), (5, 5), (200, 200), (500, 240), ("45", 45)])
async def test_a_wait_is_between_five_minutes_and_four_hours(tmp_path, minutes, shown):
    s, st, backend, agent = make(tmp_path, [set_activity(activity="waiting", description="Watching the carrots.", minutes=minutes)])
    await agent.tick("test")
    assert float(st.meta("wait_until")) - time.time() == pytest.approx(shown * 60, abs=5)
    r = [e for e in st.events(10) if e["kind"] == "tool"][0]["data"]["result"]
    assert r == f"now waiting; you'll be left to it for about {shown} min unless something happens"


@pytest.mark.asyncio
@pytest.mark.parametrize("minutes", ["soon", None, 0, -3, True, [5]])
async def test_a_wait_needs_a_sensible_number_of_minutes(tmp_path, minutes):
    args = {"activity": "waiting", "description": "Watching the carrots."}
    if minutes is not None:
        args["minutes"] = minutes
    s, st, backend, agent = make(tmp_path, [set_activity(**args)])
    st.set_meta(wait_until=str(time.time() + 3600), wait_label="waiting")
    await agent.tick("test")
    assert float(st.meta("wait_until")) == 0                             # no (valid) minutes: any earlier wait is over
    r = [e for e in st.events(10) if e["kind"] == "tool"][0]["data"]["result"]
    assert r == "now waiting"


@pytest.mark.asyncio
async def test_asking_for_a_wait_while_restating_the_same_thing_still_sets_it(tmp_path):
    s, st, backend, agent = make(tmp_path, [
        set_activity(activity="waiting", description="Watching the carrots grow."),
        set_activity(activity="waiting", description="Watching the carrots grow.", minutes=60),
    ])
    await agent.tick("a")
    await agent.tick("b")
    assert float(st.meta("wait_until")) - time.time() == pytest.approx(3600, abs=5)
    r = [e for e in st.events(20) if e["kind"] == "tool"][0]["data"]
    assert r["result"] == "no change - you're already waiting: Watching the carrots grow.; you'll be left to it for about 60 min unless something happens"
    assert r["noop"] is True


@pytest.mark.asyncio
async def test_a_wait_does_not_outlast_a_visitor_or_a_ripe_crop(tmp_path):
    s, st, backend, agent = make(tmp_path, [set_activity(activity="waiting", description="Watching.", minutes=120)])
    await agent.tick("test")
    i = agent.receive("Hello!", "Morgan")
    assert agent._wake.is_set() and i
    agent.pacing.next_delay = lambda now, last: 1.0
    assert await asyncio.wait_for(agent._sleep(), timeout=3) == "event"


def test_the_guide_tells_pip_about_waiting_only_when_it_can_set_an_activity():
    text = guide.render(["set_activity"], Settings(), False)
    assert "waiting on something" in text and "minutes" in text
    assert "waiting on something" not in guide.render(["say"], Settings(), False)
