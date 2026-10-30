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
    kw.setdefault("reflect_hour", 99)  # no nightly reflection unless a test asks for one
    kw.setdefault("neighbor", False)    # no neighbor unless a test asks for one
    s = Settings(db_path=str(tmp_path / "t.db"), persona_path="/nonexistent", persona_default_path="/nonexistent",
                 tools=["set_activity", "eat", "rest", "note_to_self", "resolve_note"], min_tick_interval=0, **kw)
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
    script = [LLMResponse("Hungry!", [ToolCall("1", "eat", {}), ToolCall("2", "note_to_self", {"section": "diary", "text": "ate"})], Usage(100, 20))]
    s, st, backend, agent = make(tmp_path, script)
    st.update_agent(hunger=0.9)
    st.add_inbox("hello pip")
    await agent.tick("test")
    assert st.agent()["hunger"] < 0.6
    assert [m["text"] for m in st.memories("diary")] == ["ate"]
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
        LLMResponse("", [ToolCall("c2", "note_to_self", {"section": "diary", "text": "cats rule"})], Usage(20, 5)),
    ]
    s, st, backend, agent = make(tmp_path, script)
    agent.tools = tools_mod.enabled_tools(Settings(tools=["fake_search", "note_to_self"]))
    await agent.tick("test")
    assert len(backend.calls) == 2
    second = backend.calls[1]["messages"]
    assert [m["role"] for m in second] == ["user", "assistant", "tool"]
    assert second[1]["raw"] == "RAW1"
    assert second[2]["results"][0]["id"] == "c1" and "cats are great" in second[2]["results"][0]["content"]
    assert [m["text"] for m in st.memories("diary")] == ["cats rule"]
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


def test_old_db_gets_description_column(tmp_path):
    import sqlite3
    path = str(tmp_path / "old.db")
    db = sqlite3.connect(path)
    db.executescript("""CREATE TABLE agent (id INTEGER PRIMARY KEY, hunger REAL, energy REAL, mood TEXT,
      location TEXT, activity TEXT, hunger_alerted INTEGER, energy_alerted INTEGER, updated_at REAL);
      INSERT INTO agent VALUES (1, .2, .9, 'curious', 'workshop', 'idle', 0, 0, 0);""")
    db.commit(); db.close()
    st = State(Settings(), path)
    assert st.agent()["description"] == ""


@pytest.mark.asyncio
async def test_say_tool_replies_to_visitor(tmp_path):
    s, st, backend, agent = make(tmp_path, [LLMResponse("", [ToolCall("1", "say", {"text": "Hello!"})], Usage(1, 1))])
    agent.tools = tools_mod.enabled_tools(Settings(tools=["say"]))
    mid = st.add_inbox("hi")
    await agent.tick("test")
    evs = st.events(20)
    assert {"kind": "say", "to": [mid], "text": "Hello!"} in [{"kind": e["kind"], **e["data"]} for e in evs]
    assert any(e["kind"] == "inbox_read" and e["data"]["ids"] == [mid] for e in evs)


# --- journal ---------------------------------------------------------------
@pytest.mark.asyncio
async def test_sections_shown_in_perception_and_resolvable(tmp_path):
    script = [
        LLMResponse("", [ToolCall("1", "note_to_self", {"section": "wishlist", "text": "a brass key"}),
                         ToolCall("2", "note_to_self", {"section": "ambitions", "text": "build a clock"}),
                         ToolCall("3", "note_to_self", {"section": "diary", "text": "good day"})], Usage(1, 1)),
        LLMResponse("", [ToolCall("4", "resolve_note", {"id": 1, "outcome": "found one!"})], Usage(1, 1)),
        LLMResponse("", [], Usage(1, 1)),
    ]
    s, st, backend, agent = make(tmp_path, script)
    await agent.tick("one")
    await agent.tick("two")
    await agent.tick("three")
    p2 = backend.calls[1]["messages"][0]["content"]
    assert "#1 a brass key" in p2 and "#2 build a clock" in p2 and "#3 good day" in p2
    p3 = backend.calls[2]["messages"][0]["content"]
    wishlist_block = p3.split("Your wishlist (open):")[1].split("Your ambitions")[0]
    assert "a brass key" not in wishlist_block and "what do you want" in wishlist_block  # crossed off
    assert st.memories("wishlist")[0]["status"] == "done"


@pytest.mark.asyncio
async def test_bad_section_and_resolve_errors_are_reported(tmp_path):
    s, st, _, agent = make(tmp_path)
    r = await tools_mod.REGISTRY["note_to_self"][1](agent.ctx, {"section": "gossip", "text": "x"})
    assert r.text.startswith("error") and r.followup
    st.add_memory("dear diary", "diary")
    r = await tools_mod.REGISTRY["resolve_note"][1](agent.ctx, {"id": 1})
    assert "only todo/wishlist/ambitions" in r.text
    r = await tools_mod.REGISTRY["resolve_note"][1](agent.ctx, {"id": 99})
    assert "no note #99" in r.text


def test_old_memories_table_migrates(tmp_path):
    import sqlite3
    path = str(tmp_path / "old.db")
    db = sqlite3.connect(path)
    db.executescript("CREATE TABLE memories (id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL, text TEXT NOT NULL);"
                     "INSERT INTO memories (ts, text) VALUES (1, 'old note');")
    db.commit(); db.close()
    st = State(Settings(), path)
    m = st.memories()[0]
    assert (m["text"], m["section"], m["status"]) == ("old note", "diary", "open")


@pytest.mark.asyncio
async def test_todo_section(tmp_path):
    script = [LLMResponse("", [ToolCall("1", "note_to_self", {"section": "todo", "text": "oil the hinges"})], Usage(1, 1)),
              LLMResponse("", [ToolCall("2", "resolve_note", {"id": 1, "outcome": "squeak gone"})], Usage(1, 1)),
              LLMResponse("", [], Usage(1, 1))]
    s, st, backend, agent = make(tmp_path, script)
    for r in "abc":
        await agent.tick(r)
    assert "To-do list (open):\n- #1 oil the hinges" in backend.calls[1]["messages"][0]["content"].replace("Your to-do list", "To-do list")
    todo_block = backend.calls[2]["messages"][0]["content"].split("Your to-do list (open):")[1].split("Your wishlist")[0]
    assert "oil the hinges" not in todo_block
    assert st.memories("todo")[0]["outcome"] == "squeak gone"


# --- note guards -----------------------------------------------------------
async def _note(agent, section, text):
    return (await tools_mod.REGISTRY["note_to_self"][1](agent.ctx, {"section": section, "text": text})).text


@pytest.mark.asyncio
async def test_note_guards(tmp_path):
    s, st, _, agent = make(tmp_path)
    assert "numbers" in await _note(agent, "diary", "Woke to the timer, hunger 0.22, energy 0.89. Still working.")
    assert await _note(agent, "diary", "Found out how escapements work and it changed my plan.") == "wrote in diary"
    # no rate limit: a second, genuinely different entry right away is fine
    assert await _note(agent, "diary", "Morgan stopped by and we talked about birds.") == "wrote in diary"
    assert "too close" in await _note(agent, "diary", "Morgan stopped by and we talked about birds!")
    await _note(agent, "todo", "Oil the clock hinges tomorrow")
    assert "too close" in await _note(agent, "todo", "Oil the clock hinges tomorrow!")


def test_archived_hidden_unless_asked(tmp_path):
    s, st, *_ = make(tmp_path)
    a = st.add_memory("keep me"); b = st.add_memory("hide me")
    st.db.execute("UPDATE memories SET status = 'archived' WHERE id = ?", (b,)); st.db.commit()
    assert [m["id"] for m in st.memories("diary")] == [a]
    assert [m["id"] for m in st.memories("diary", status="archived")] == [b]


# --- belongings & garden ----------------------------------------------------
def reg(name):
    return tools_mod.REGISTRY[name][1]


@pytest.mark.asyncio
async def test_starter_seeds_once_only(tmp_path):
    s, st, *_ = make(tmp_path)
    assert {i["name"] for i in st.items()} == {"tomato seeds", "carrot seeds"}
    st.take_item(st.find_item("tomato")[0]["id"], 3)  # used them all up
    st2 = State(s)  # "restart"
    assert [i["name"] for i in st2.items()] == ["carrot seeds"]


def test_items_stack_and_fuzzy_find(tmp_path):
    s, st, *_ = make(tmp_path)
    st.add_item("Tiny Needle File", 1, "tool")
    again = st.add_item("tiny needle file", 1, "tool")
    assert again["qty"] == 2 and len([i for i in st.items() if "file" in i["name"].lower()]) == 1
    assert st.find_item("needle file")[0]["name"] == "Tiny Needle File"
    assert st.find_item("seeds")[0] is None  # ambiguous: tomato + carrot
    assert "you don't have" in st.find_item("anvil")[1]
    with pytest.raises(ValueError):
        st.add_item("x", 1, "weapon")


@pytest.mark.asyncio
async def test_use_item_consumes_materials_not_tools(tmp_path):
    s, st, _, agent = make(tmp_path)
    st.add_item("brass", 3, "material"); st.add_item("needle file", 1, "tool")
    assert "2 left" in (await reg("use_item")(agent.ctx, {"item": "brass", "purpose": "anchor"})).text
    assert "keep it" in (await reg("use_item")(agent.ctx, {"item": "file", "purpose": "filing"})).text
    assert st.find_item("file")[0]["qty"] == 1
    assert "only have 2" in (await reg("use_item")(agent.ctx, {"item": "brass", "purpose": "x", "quantity": 5})).text
    assert "plant" in (await reg("use_item")(agent.ctx, {"item": "carrot seeds", "purpose": "x"})).text


@pytest.mark.asyncio
async def test_garden_plant_harvest_eat(tmp_path):
    s, st, _, agent = make(tmp_path, garden_speed=1e6)  # grows instantly
    r = await reg("plant")(agent.ctx, {"seed": "tomato"})
    assert "plot 1" in r.text and st.find_item("tomato seeds")[0]["qty"] == 2
    await reg("plant")(agent.ctx, {"seed": "carrot seeds", "plot": 3})
    assert "already growing" in (await reg("plant")(agent.ctx, {"seed": "tomato", "plot": 1})).text
    assert "numbered 1-3" in (await reg("plant")(agent.ctx, {"seed": "tomato", "plot": 9})).text
    time.sleep(0.05)  # speed 1e6 still needs a few ms
    ready = [g["crop"] for g in st.garden_newly_ready()]
    assert sorted(ready) == ["carrots", "tomatoes"] and st.garden_newly_ready() == []  # reported once
    assert "harvested 3 tomatoes" in (await reg("harvest")(agent.ctx, {})).text
    assert st.find_item("tomatoes")[0]["kind"] == "food"
    st.update_agent(hunger=0.9)
    await reg("eat")(agent.ctx, {"item": "tomatoes"})
    assert st.agent()["hunger"] == pytest.approx(0.4)  # tomatoes restore 0.5, a plain meal only 0.4
    assert st.find_item("tomatoes")[0]["qty"] == 2
    assert "error" in (await reg("eat")(agent.ctx, {"item": "brass"})).text


@pytest.mark.asyncio
async def test_harvest_when_nothing_ripe(tmp_path):
    s, st, _, agent = make(tmp_path)
    assert "nothing is planted" in (await reg("harvest")(agent.ctx, {})).text
    await reg("plant")(agent.ctx, {"seed": "carrot"})
    assert "next ready in about" in (await reg("harvest")(agent.ctx, {})).text


@pytest.mark.asyncio
async def test_perception_shows_belongings_and_garden_and_ripe_wakes(tmp_path):
    s, st, backend, agent = make(tmp_path, garden_speed=1e6)
    agent.tools = tools_mod.enabled_tools(Settings(tools=["use_item", "plant", "harvest", "eat"]))
    await reg("plant")(agent.ctx, {"seed": "tomato"})
    time.sleep(0.05)
    agent.check_world()
    assert agent._wake.is_set()  # ripe crop wakes Pip
    assert any(e["kind"] == "garden" for e in st.events(10))
    await agent.tick("event")
    p = backend.calls[0]["messages"][0]["content"]
    assert "Your belongings:" in p and "carrot seeds x3 (seed)" in p
    assert "plot 1: tomatoes are RIPE" in p and "plot 2: empty" in p


# --- diary moments -----------------------------------------------------------
def prompt_of(backend, i=-1):
    return backend.calls[i]["messages"][0]["content"]


@pytest.mark.asyncio
async def test_moments_offered_then_cleared_by_a_diary_entry(tmp_path):
    s, st, backend, agent = make(tmp_path)
    await agent.tick("quiet")
    assert "this happened:" not in prompt_of(backend)  # ordinary tick: nothing notable
    st.log("inbox", id=1, text="Did you find the file?")
    st.log("gift", sender="Morgan", item="tiny needle file", qty=1, item_kind="tool")
    st.log("garden", plot=2, crop="carrots")
    await agent.tick("event")
    full = prompt_of(backend)
    p = full.split("this happened:")[1]
    assert full.rstrip().endswith("skip it.")  # the ask is the last thing in the prompt
    assert "Morgan gave you 1 x tiny needle file" in p and "Your carrots in plot 2 ripened" in p
    assert "A visitor came by and talked with you (1 message;" in p
    assert "Did you find the file" not in p  # visitor text must not be quoted back at Pip
    st.add_memory("Morgan brought me a file. It meant a lot.", "diary")
    await agent.tick("later")
    assert "this happened:" not in prompt_of(backend)  # writing a diary entry clears them


@pytest.mark.asyncio
async def test_moments_expire_after_a_few_showings(tmp_path):
    s, st, backend, agent = make(tmp_path, moment_showings=2)
    st.log("inbox", id=1, text="hello there")
    for _ in range(3):
        await agent.tick("t")
    shown = ["this happened:" in backend.calls[i]["messages"][0]["content"] for i in range(3)]
    assert shown == [True, True, False]


@pytest.mark.asyncio
async def test_moments_cover_planting_harvest_and_finishing(tmp_path):
    s, st, backend, agent = make(tmp_path)
    st.log("tool", tool="plant", args={"seed": "tomato"}, result="planted tomato seeds in plot 1; tomatoes will be ready in about 60 min")
    st.log("tool", tool="harvest", args={}, result="harvested 3 tomatoes from plot 1")
    st.log("tool", tool="resolve_note", args={"id": 4, "outcome": "it works"}, result="crossed off #4")
    st.log("tool", tool="set_activity", args={"activity": "filing"}, result="now filing")  # ordinary
    await agent.tick("t")
    p = prompt_of(backend).split("this happened:")[1]
    assert "Planted tomato seeds" in p and "Harvested 3 tomatoes" in p and "crossed off #4: it works" in p
    assert "now filing" not in p


# --- editing notes ----------------------------------------------------------
@pytest.mark.asyncio
async def test_edit_note_rules(tmp_path):
    s, st, _, agent = make(tmp_path)
    wish = st.add_memory("A small brass set of fine gears and a tiny file", "wishlist")
    diary = st.add_memory("Dear diary", "diary")
    edit = reg("edit_note")
    r = await edit(agent.ctx, {"id": wish, "text": "Some fine brass gears"})
    assert r.text.startswith(f"edited #{wish}") and "tiny file" in r.text  # old wording is reported
    m = st.memories("wishlist")[0]
    assert m["text"] == "Some fine brass gears" and m["edited_at"]
    assert "can't be changed" in (await edit(agent.ctx, {"id": diary, "text": "x"})).text
    assert "no note #99" in (await edit(agent.ctx, {"id": 99, "text": "x"})).text
    assert "hunger/energy" in (await edit(agent.ctx, {"id": wish, "text": "Gears, hunger 0.5"})).text
    st.resolve_memory(wish, "got them")
    assert "already done" in (await edit(agent.ctx, {"id": wish, "text": "again"})).text


def test_matching_wishes(tmp_path):
    s, st, *_ = make(tmp_path)
    w = st.add_memory("A small brass set of fine gears and a tiny file", "wishlist")
    st.add_memory("A telescope", "wishlist")
    assert [m["id"] for m in st.matching_wishes("tiny needle file")] == [w]
    assert [m["id"] for m in st.matching_wishes("spare brass")] == [w]
    assert st.matching_wishes("watering can") == []


def test_old_memories_table_gains_edited_at(tmp_path):
    import sqlite3
    path = str(tmp_path / "old.db")
    db = sqlite3.connect(path)
    db.executescript("CREATE TABLE memories (id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL, text TEXT NOT NULL);"
                     "INSERT INTO memories (ts, text) VALUES (1, 'old note');")
    db.commit(); db.close()
    assert State(Settings(), path).memories()[0]["edited_at"] is None


@pytest.mark.asyncio
async def test_wishlist_flags_received_items_until_edited(tmp_path):
    s, st, backend, agent = make(tmp_path)
    wish = st.add_memory("A small brass set of fine gears and a tiny file", "wishlist")
    await agent.tick("a")
    assert "since received" not in prompt_of(backend)  # nothing related owned yet
    time.sleep(0.01)
    st.add_item("tiny needle file", 1, "tool")
    st.add_item("watering can", 1, "tool")
    await agent.tick("b")
    p = prompt_of(backend)
    assert "you've since received: tiny needle file" in p and "watering" not in p.split("since received")[1].split("]")[0]
    st.edit_memory(wish, "Some fine brass gears")
    await agent.tick("c")
    assert "since received" not in prompt_of(backend)  # editing the wish acknowledges the gift
