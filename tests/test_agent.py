import asyncio
import time

import pytest

from app.config import Settings
from app.llm.base import LLMResponse, ToolCall, Usage
from app.llm.fake import FakeBackend
from app.loop import Agent
from app.pacing import FixedTick, HeartbeatEvents, Manual, get_policy
from app.state import State


def make(tmp_path, script=None, **kw):
    s = Settings(db_path=str(tmp_path / "t.db"), persona_path="/nonexistent", persona_default_path="/nonexistent",
                 tools=["set_activity", "eat", "rest", "note_to_self"], min_tick_interval=0, **kw)
    st = State(s)
    backend = FakeBackend(script)
    return s, st, backend, Agent(s, st, backend, get_policy(s))


def test_decay_and_alert(tmp_path):
    s, st, *_ = make(tmp_path)
    a = st.agent()
    new = st.apply_decay(a["updated_at"] + 12 * 3600)  # 12h
    assert "hunger" in new  # 0.2 + 0.96 clamps to 1.0
    assert st.agent()["hunger"] == 1.0
    assert st.apply_decay(a["updated_at"] + 13 * 3600) == []  # edge-triggered


def test_resting_recovers_energy(tmp_path):
    s, st, *_ = make(tmp_path)
    st.update_agent(energy=0.1, activity="resting")
    t = st.agent()["updated_at"]
    st.apply_decay(t + 3600)
    assert st.agent()["energy"] == pytest.approx(0.4)


@pytest.mark.asyncio
async def test_tick_runs_tools_and_logs(tmp_path):
    script = [LLMResponse("Hungry!", [ToolCall("1", "eat", {}), ToolCall("2", "note_to_self", {"text": "ate"})], Usage(100, 20))]
    s, st, backend, agent = make(tmp_path, script)
    st.update_agent(hunger=0.9)
    st.add_inbox("hello pip")
    await agent.tick("test")
    assert st.agent()["hunger"] < 0.6
    assert st.recent_memories() == ["ate"]
    assert st.pending_inbox() == []
    assert st.usage_today()["total_tokens"] == 120
    kinds = [e["kind"] for e in st.events(20)]
    assert "say" in kinds and "tool" in kinds
    assert "hello pip" in backend.calls[0]["messages"][0]["content"]


@pytest.mark.asyncio
async def test_unknown_tool_is_logged_not_fatal(tmp_path):
    s, st, _, agent = make(tmp_path, [LLMResponse("", [ToolCall("1", "launch_missiles", {})], Usage(1, 1))])
    await agent.tick("test")
    assert any(e["kind"] == "tool_error" for e in st.events(10))


@pytest.mark.asyncio
async def test_budget_blocks_llm_calls(tmp_path):
    s, st, backend, agent = make(tmp_path, daily_token_budget=10)
    st.add_usage(8, 8)
    await agent.tick("test")
    await agent.tick("test")
    assert backend.calls == []
    assert sum(e["kind"] == "budget_exceeded" for e in st.events(10)) == 1


def test_pacing_policies(tmp_path):
    s = Settings(heartbeat_seconds=100, tick_seconds=50)
    assert HeartbeatEvents(s).next_delay(1000, 950) == 50
    assert HeartbeatEvents(s).next_delay(1000, 0) == 0
    assert FixedTick(s).next_delay(1000, 980) == 30
    assert Manual(s).next_delay(1000, 0) is None
    assert HeartbeatEvents(s).wakes_on_events and not FixedTick(s).wakes_on_events
    with pytest.raises(ValueError):
        get_policy(Settings(pacing="nope"))


@pytest.mark.asyncio
async def test_manual_only_wakes_when_forced(tmp_path):
    s, st, _, agent = make(tmp_path, pacing="manual")
    t = asyncio.create_task(agent._sleep())
    await asyncio.sleep(0.05)
    agent.request_wake()  # event: ignored by manual policy
    await asyncio.sleep(0.05)
    assert not t.done()
    agent.request_wake(force=True)
    assert await asyncio.wait_for(t, 1) == "forced"


@pytest.mark.asyncio
async def test_heartbeat_wakes_on_event(tmp_path):
    s, st, _, agent = make(tmp_path, heartbeat_seconds=3600)
    agent.last_tick = time.time()
    t = asyncio.create_task(agent._sleep())
    await asyncio.sleep(0.05)
    agent.request_wake()
    assert await asyncio.wait_for(t, 1) == "event"


# --- multi-call ticks ---------------------------------------------------
from app import tools as tools_mod  # noqa: E402
from app.tools import ToolResult  # noqa: E402


@tools_mod.tool("fake_search", "test", {"type": "object", "properties": {}, "required": []})
async def _fake_search(ctx, args):
    return ToolResult("found: cats are great", followup=True)


@pytest.mark.asyncio
async def test_followup_lets_model_use_tool_result(tmp_path):
    script = [
        LLMResponse("searching", [ToolCall("c1", "fake_search", {})], Usage(10, 5), raw="RAW1"),
        LLMResponse("", [ToolCall("c2", "note_to_self", {"text": "cats rule"})], Usage(20, 5)),
    ]
    s, st, backend, agent = make(tmp_path, script)
    agent.tools = tools_mod.enabled_tools(Settings(tools=["fake_search", "note_to_self"]))
    await agent.tick("test")
    assert len(backend.calls) == 2
    second = backend.calls[1]["messages"]
    assert [m["role"] for m in second] == ["user", "assistant", "tool"]
    assert second[1]["raw"] == "RAW1"
    assert second[2]["results"][0]["id"] == "c1" and "cats are great" in second[2]["results"][0]["content"]
    assert st.recent_memories() == ["cats rule"]
    assert st.usage_today()["calls"] == 2 and agent.ticks == 1


@pytest.mark.asyncio
async def test_no_followup_means_single_call(tmp_path):
    s, st, backend, agent = make(tmp_path, [LLMResponse("", [ToolCall("1", "rest", {})], Usage(1, 1))])
    await agent.tick("test")
    assert len(backend.calls) == 1


@pytest.mark.asyncio
async def test_call_cap_defers_to_next_tick(tmp_path):
    loop_forever = [LLMResponse("", [ToolCall(f"c{i}", "fake_search", {})], Usage(1, 1)) for i in range(10)]
    s, st, backend, agent = make(tmp_path, loop_forever, max_calls_per_tick=2)
    agent.tools = tools_mod.enabled_tools(Settings(tools=["fake_search"]))
    await agent.tick("test")
    assert len(backend.calls) == 2
    assert agent._wake.is_set()  # asked for an early tick to digest the last result


@pytest.mark.asyncio
async def test_budget_stops_midtick(tmp_path):
    script = [LLMResponse("", [ToolCall("c1", "fake_search", {})], Usage(40, 40)),
              LLMResponse("", [], Usage(1, 1))]
    s, st, backend, agent = make(tmp_path, script, daily_token_budget=50)
    agent.tools = tools_mod.enabled_tools(Settings(tools=["fake_search"]))
    await agent.tick("test")
    assert len(backend.calls) == 1
    assert any(e["kind"] == "budget_exceeded" for e in st.events(10))


@pytest.mark.asyncio
async def test_tool_error_is_returned_to_model(tmp_path):
    script = [LLMResponse("", [ToolCall("c1", "nope", {})], Usage(1, 1)), LLMResponse("ok", [], Usage(1, 1))]
    s, st, backend, agent = make(tmp_path, script)
    await agent.tick("test")
    res = backend.calls[1]["messages"][2]["results"][0]
    assert res["is_error"] and "unknown" in res["content"]


def test_message_translation():
    from app.llm.anthropic_backend import _to_api as a_api
    from app.llm.openai_compat import _to_api as o_api
    asst = {"role": "assistant", "content": "hm", "tool_calls": [ToolCall("c1", "eat", {"x": 1})], "raw": None}
    tool = {"role": "tool", "results": [{"id": "c1", "name": "eat", "content": "ok", "is_error": True}]}
    assert a_api(asst)["content"][1] == {"type": "tool_use", "id": "c1", "name": "eat", "input": {"x": 1}}
    assert a_api({**asst, "raw": ["BLOCKS"]})["content"] == ["BLOCKS"]
    assert a_api(tool) == {"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": "c1", "content": "ok", "is_error": True}]}
    assert o_api(asst)[0]["tool_calls"][0]["function"] == {"name": "eat", "arguments": '{"x": 1}'}
    assert o_api(tool) == [{"role": "tool", "tool_call_id": "c1", "content": "ok"}]
