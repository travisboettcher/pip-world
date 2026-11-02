import time
from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from app import tools as T
from app.channels import FakeChannel
from app.config import Settings
from app.llm.base import LLMResponse, ToolCall, Usage
from app.llm.fake import FakeBackend
from app.main import create_app
from app.outreach import Outreach
from tests.test_projects import call, make


def daytime(s):
    h = datetime.now().hour
    s.bedtime_hour, s.wake_hour = (h + 3) % 24, (h + 8) % 24


def night(s):
    h = datetime.now().hour
    s.bedtime_hour, s.wake_hour = h, (h + 8) % 24


async def setup(tmp_path, mode="on", **kw):
    s, st, gm, agent = make(tmp_path, **kw)
    s.outreach = mode
    daytime(s)
    ch = FakeChannel()
    agent.outreach = Outreach(s, st, [ch], receive=agent.receive)
    agent.ctx.outreach = agent.outreach
    agent.tools["send_postcard"] = T.REGISTRY["send_postcard"]
    agent.tools["say"] = T.REGISTRY["say"]
    await agent.outreach.start()
    return s, st, agent, ch


@pytest.mark.asyncio
async def test_a_channel_message_becomes_a_visitor_message_with_its_source(tmp_path):
    s, st, agent, ch = await setup(tmp_path)
    assert await ch.inject("u1", "how is the clock?", message_id="a1")
    (m,) = st.pending_inbox()
    assert (m["text"], m["sender"], m["source"], m["external_id"]) == ("how is the clock?", "Sam", "fake", "a1") and m["conversation"]
    ev = [e for e in st.events(5) if e["kind"] == "inbox"][0]["data"]
    assert ev["source"] == "fake" and ev["conversation"] == m["conversation"] and ev["sender"] == "Sam"
    assert agent._wake.is_set() and agent._urgent                                # it wakes Pip like any visitor
    assert ch.read_calls == [(m["conversation"], "a1")]                          # and is acknowledged
    assert "the first time you heard from someone outside, through fake" in agent._perception("event", [])
    assert await ch.inject("x9", "hi", message_id="b1") is False and len(st.pending_inbox()) == 1


@pytest.mark.asyncio
async def test_the_core_ignores_a_message_it_has_already_seen(tmp_path):
    s, st, agent, ch = await setup(tmp_path)
    m = __import__("app.channels", fromlist=["Inbound"]).Inbound("u1", "Morgan", "hello", "t1", 0.0, "same")
    await agent.outreach._handler(ch)(m)
    await agent.outreach._handler(ch)(m)                                           # a flaky transport offers it twice
    assert len(st.pending_inbox()) == 1


@pytest.mark.asyncio
async def test_pips_answer_goes_back_the_way_the_message_came_into_the_same_thread(tmp_path):
    s, st, agent, ch = await setup(tmp_path)
    await ch.inject("u1", "how is the clock?", conversation="thread-A")
    web = agent.receive("and from the browser", "Morgan")                         # a web message in the same batch
    ids = [m["id"] for m in st.pending_inbox()]
    agent.ctx.visitor_ids = ids
    r = await call(agent, "say", text="It ticks now!")
    assert r.text == "said it"
    assert [(o.text, o.kind, conv) for o, conv, _ in ch.sent] == [("It ticks now!", "reply", "thread-A")]   # one reply, web not routed
    row = st.outreach_rows(5)[0]
    assert (row["kind"], row["channel"], row["conversation"], row["status"]) == ("reply", "fake", "thread-A", "sent")
    assert "first time you answered someone outside" in agent._perception("event", [])
    assert web  # the web message got its own place in the log and no channel send


@pytest.mark.asyncio
async def test_two_messages_in_one_thread_get_one_reply_and_web_only_gets_none(tmp_path):
    s, st, agent, ch = await setup(tmp_path)
    await ch.inject("u1", "one", conversation="T")
    await ch.inject("u1", "two", conversation="T")
    agent.ctx.visitor_ids = [m["id"] for m in st.pending_inbox()]
    await call(agent, "say", text="both heard")
    assert len(ch.sent) == 1
    ch.sent.clear()
    agent.ctx.visitor_ids = [agent.receive("only web", "Morgan")]
    await call(agent, "say", text="hi web")
    assert ch.sent == []


@pytest.mark.asyncio
async def test_typing_is_shown_where_pip_is_about_to_answer(tmp_path):
    s, st, agent, ch = await setup(tmp_path)
    await ch.inject("u1", "hello", conversation="T9")
    await agent.outreach.typing([m["id"] for m in st.pending_inbox()])
    assert ch.typing_calls == ["T9"]
    ch.typing_calls.clear()
    ch.capabilities = frozenset({"receive"})                                      # no typing capability: never called
    await agent.outreach.typing([m["id"] for m in st.pending_inbox()])
    assert ch.typing_calls == []


@pytest.mark.asyncio
async def test_a_postcard_starts_a_thread_and_the_answer_continues_it(tmp_path):
    s, st, agent, ch = await setup(tmp_path)
    r = await call(agent, "send_postcard", text="The clock ticks! Come see.")
    assert "on its way" in r.text and not r.followup
    (out, to, landed) = ch.sent[0]
    assert (out.kind, to) == ("postcard", "") and landed
    row = st.outreach_rows(1)[0]
    assert (row["kind"], row["status"], row["conversation"]) == ("postcard", "sent", landed)
    ev = [e for e in st.events(5) if e["kind"] == "outreach"][0]["data"]
    assert ev["delivered"] and ev["what"] == "postcard" and ev["text"] == "The clock ticks! Come see." and ev["channel"] == "fake"
    assert "the first time you sent something out into the world" in agent._perception("event", [])
    await ch.inject("u1", "On my way!", conversation=landed)                      # the human answers in that thread
    agent.ctx.visitor_ids = [m["id"] for m in st.pending_inbox()]
    await call(agent, "say", text="Wonderful.")
    assert ch.sent[-1][1] == landed and ch.sent[-1][0].kind == "reply"            # Pip's answer stays in the thread
    assert st.recall("clock ticks")                                                 # remembered


@pytest.mark.asyncio
async def test_postcards_are_plain_short_and_not_repeated(tmp_path):
    s, st, agent, ch = await setup(tmp_path, outreach_per_day=9, outreach_min_gap_hours=0)
    for text, why in (("hi", "say something"), ("x" * 241, "too long"), ("see https://example.com now", "no links"),
                      ("visit example.com today", "no links"), ("  \n  ", "say something")):
        r = await call(agent, "send_postcard", text=text)
        assert why in r.text and r.followup, text
    assert ch.sent == []
    r = await call(agent, "send_postcard", text="The clock\x00 now\x07 ticks steadily")
    assert "on its way" in r.text and ch.sent[0][0].text == "The clock now ticks steadily"      # control characters stripped
    r = await call(agent, "send_postcard", text="The clock now ticks steadily!")
    assert "already told them something like this" in r.text


@pytest.mark.asyncio
async def test_limits_per_day_gap_night_and_failures(tmp_path):
    s, st, agent, ch = await setup(tmp_path)                                       # 2 a day, 3 hours apart
    assert agent.outreach.can_send() and "You can start 2 more conversations" in agent._perception("event", [])
    assert "on its way" in (await call(agent, "send_postcard", text="First thing worth telling")).text
    r = await call(agent, "send_postcard", text="A second, different thing entirely")
    assert "too soon after your last one" in r.text and "Next possible after" in r.text
    assert agent.outreach.can_send() is False and "send_postcard" not in [sp.name for sp in T.specs_for(agent.tools, "workshop")
                                                                           if agent.outreach.can_send()]
    s.outreach_min_gap_hours = 0                                                 # the gap has passed (a day runs from local midnight, so no shifting timestamps)
    assert "on its way" in (await call(agent, "send_postcard", text="Another, new discovery today")).text
    r = await call(agent, "send_postcard", text="One more unrelated notion")
    assert "as many conversations as you can today" in r.text
    # night: nothing goes out
    (tmp_path / "n").mkdir()
    s2, st2, agent2, ch2 = await setup(tmp_path / "n")
    night(s2)
    assert "it's night" in (await call(agent2, "send_postcard", text="Midnight musings here")).text and ch2.sent == []
    # a dead channel: honest failure, capped
    (tmp_path / "f").mkdir()
    s3, st3, agent3, ch3 = await setup(tmp_path / "f", outreach_min_gap_hours=0, outreach_per_day=9)
    ch3.fail = True
    for n in range(3):
        r = await call(agent3, "send_postcard", text=f"attempt number {n} with other words {n * 7}")
        assert "couldn't be sent" in r.text and r.followup
    assert "isn't working right now" in (await call(agent3, "send_postcard", text="a fourth try entirely")).text
    assert [x["status"] for x in st3.outreach_rows(5)] == ["failed"] * 3


@pytest.mark.asyncio
async def test_log_mode_records_without_sending_and_off_removes_the_tool(tmp_path):
    s, st, agent, ch = await setup(tmp_path, mode="log")
    r = await call(agent, "send_postcard", text="Practising a message for later")
    assert "on its way" in r.text and ch.sent == []
    assert st.outreach_rows(1)[0]["status"] == "logged"
    ev = [e for e in st.events(5) if e["kind"] == "outreach"][0]["data"]
    assert ev["mode"] == "log" and ev["delivered"]
    s2 = Settings(tools=["say", "send_postcard"], outreach="on", outreach_channels=[])
    assert "send_postcard" not in T.enabled_tools(s2)                              # no channel configured: no tool
    s2.outreach_channels, s2.outreach = ["fake"], "off"
    assert "send_postcard" not in T.enabled_tools(s2)
    s2.outreach = "on"
    assert "send_postcard" in T.enabled_tools(s2)


@pytest.mark.asyncio
async def test_a_tick_offers_the_tool_only_when_a_postcard_could_go_out(tmp_path):
    s, st, agent, ch = await setup(tmp_path, outreach_per_day=1)
    agent.backend.script[:] = [LLMResponse("", [], Usage(1, 1)), LLMResponse("", [], Usage(1, 1))]
    await agent.tick("test")
    assert "send_postcard" in agent.backend.calls[-1]["tools"]
    await call(agent, "send_postcard", text="A single postcard for the day")
    await agent.tick("test")
    assert "send_postcard" not in agent.backend.calls[-1]["tools"]
    assert "You can start" not in agent._perception("event", [])


@pytest.mark.asyncio
async def test_a_channel_that_cannot_start_does_not_stop_pip(tmp_path):
    s, st, agent, ch = await setup(tmp_path)

    async def boom(on_message):
        raise RuntimeError("cannot reach the homeserver")
    ch.start = boom
    await agent.outreach.start()
    assert "cannot reach" in agent.outreach.status()[0]["error"]


def test_the_api_lists_channels_allowance_and_messages(tmp_path):
    s = Settings(db_path=str(tmp_path / "t.db"), persona_path="/x", pacing="manual",
                 outreach_channels=["fake"])
    with TestClient(create_app(s, FakeBackend())) as c:
        r = c.get("/outreach").json()
        assert r["mode"] == "on" and r["channels"][0]["name"] == "fake" and r["channels"][0]["primary"]
        assert r["allowance"]["remaining"] == 2 and r["items"] == []
        assert c.post("/inbox", json={"text": "hi", "sender": "Jade"}).json()["queued"]
        st = c.app.state.agent.state
        assert st.pending_inbox()[0]["source"] == "web"
        assert all("source" not in e["data"] for e in st.events(5) if e["kind"] == "inbox")      # web messages carry no source tag
