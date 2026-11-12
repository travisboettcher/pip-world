import time

import pytest

from app import firsts as F
from app.config import Settings
from app.llm.base import LLMResponse, ToolCall, Usage
from app.state import State
from tests.test_projects import call, make, report


def keys(st):
    return {r["key"] for r in st.db.execute("SELECT key FROM facets")}


def tool_event(st, name, result="ok", **args):
    first = {"plant": "planted something", "harvest": "harvested something"}.get(name)          # the garden module's tools say their own
    return st.log("tool", tool=name, args=args, result=result, **({"first": first} if first else {}))


def test_a_first_is_marked_once_and_counted_after(tmp_path):
    s, st, *_ = make(tmp_path)
    a = tool_event(st, "plant", "planted tomatoes", seed="tomato")
    b = tool_event(st, "plant", "planted carrots", seed="carrot")
    events = {e["id"]: e for e in st.events(10)}
    assert [f["label"] for f in events[a]["data"]["firsts"]] == ["the first time you planted something"]
    assert "firsts" not in events[b]["data"]
    row = st.db.execute("SELECT * FROM facets WHERE key = 'tool:plant'").fetchone()
    assert row["count"] == 2 and row["first_event_id"] == a and row["last_ts"] >= row["first_ts"] and row["tier"] == "minor"


def test_routine_failed_and_no_op_calls_are_not_firsts(tmp_path):
    s, st, *_ = make(tmp_path)
    tool_event(st, "set_activity", "now tinkering", activity="tinkering")
    tool_event(st, "say", "said", text="hi")
    tool_event(st, "plant", "error: every plot is in use")
    tool_event(st, "harvest", "not ready")
    st.log("tool", tool="rest", args={}, result="no change", noop=True)
    assert keys(st) == set()


def test_who_and_what_each_have_their_own_facets(tmp_path):
    s, st, *_ = make(tmp_path)
    st.log("inbox", text="hello", sender="Morgan")
    st.log("inbox", text="hello again", sender="Jade")
    st.log("inbox", text="anonymous")
    st.log("gift", sender="Morgan", item="needle file", qty=1)
    st.log("work", project="clock", stage="s", text="t", result="blowup", project_done=False, interrupted=False)
    st.log("work", project="clock", stage="s", text="t", result="good", project_done=True, interrupted=False)
    assert {"visitor", "person:Morgan", "person:Jade", "gift", "gift_from:Morgan", "gift_item:needle file",
            "work:blowup", "project:done"} <= keys(st)
    assert st.db.execute("SELECT count FROM facets WHERE key = 'visitor'").fetchone()["count"] == 3
    assert "person:A visitor" not in keys(st)
    assert st.db.execute("SELECT tier FROM facets WHERE key = 'person:Morgan'").fetchone()["tier"] == "major"
    assert st.db.execute("SELECT tier FROM facets WHERE key = 'gift_item:needle file'").fetchone()["tier"] == "minor"


def test_period_firsts_use_the_tick_time(tmp_path):
    s = Settings(bedtime_hour=22, wake_hour=6)
    from datetime import datetime
    at = lambda h: datetime(2026, 11, 2, h, 30).timestamp()  # noqa: E731
    assert [k for k, *_ in F.facets("tick", {}, s, at(23))] == ["period:night"]
    assert F.facets("tick", {}, s, at(9))[0][1] == "your first morning here"


def test_backfill_gives_history_its_true_first_dates_silently(tmp_path):
    s, st, *_ = make(tmp_path)
    st.log("gift", sender="Morgan", item="needle file", qty=1)
    time.sleep(0.01)
    tool_event(st, "plant", "planted", seed="tomato")
    first = {r["key"]: r["first_ts"] for r in st.db.execute("SELECT key, first_ts FROM facets")}
    st.db.execute("DELETE FROM facets")
    st.db.execute("UPDATE events SET data = json_remove(data, '$.firsts')")
    st.set_meta(firsts_v="0")
    st.db.commit()
    st2 = State(s)  # "restart" triggers the one-time backfill
    again = {r["key"]: r for r in st2.db.execute("SELECT * FROM facets")}
    assert set(again) == set(first) and all(again[k]["first_ts"] == pytest.approx(first[k]) for k in first)
    assert st2.recent_firsts(24, 3, 10) == []                      # nothing from history is presented as new
    assert any("firsts" in e["data"] for e in st2.events(10))      # but the events are marked again
    assert st2.meta("firsts_v") == "6"
    State(s)                                                       # idempotent
    assert st2.db.execute("SELECT count FROM facets WHERE key = 'tool:plant'").fetchone()["count"] == 1


@pytest.mark.asyncio
async def test_new_for_you_block_is_capped_ordered_and_fades(tmp_path):
    s, st, gm, agent = make(tmp_path, firsts_shown=3, firsts_showings=2)
    for t in ("read", "recall", "tend"):
        tool_event(st, t, "ok")
    st.log("inbox", text="hi", sender="Morgan")  # major
    st.log("tick", reason="timer", step=0, text="")
    p = agent._perception("timer", [])
    block = p.split("New for you:\n")[1].split("\n")
    assert len([l for l in block if l.startswith("- ")]) >= 3
    first_lines = [l for l in block if l.startswith("- ")][:3]
    assert "someone came to talk to you" in first_lines[0] or "your first message from Morgan" in first_lines[0]  # majors first
    for _ in range(6):                       # the cap rotates the rest in; each first is shown at most twice
        if "New for you" not in agent._perception("timer", []):
            break
    else:
        pytest.fail("firsts never faded")
    assert st.db.execute("SELECT MAX(shown) FROM facets").fetchone()[0] == 2


@pytest.mark.asyncio
async def test_only_major_firsts_prompt_the_diary(tmp_path):
    s, st, gm, agent = make(tmp_path)
    agent.tools["note_to_self"] = tools_entry(agent)
    tool_event(st, "recall", "ok")            # minor first: no diary prompt
    assert "Since you last wrote in your diary" not in agent._perception("timer", [])
    st.log("letter_sent", to="Marigold", text="Dear Marigold", enclosed=None)    # major first
    p = agent._perception("timer", [])
    assert "Since you last wrote in your diary" in p and "The first time you sent a letter" in p


def tools_entry(agent):
    from app import tools as tm
    return tm.REGISTRY["note_to_self"]


@pytest.mark.asyncio
async def test_reflection_is_told_what_happened_for_the_first_time(tmp_path):
    s, st, gm, agent = make(tmp_path, [report(summary="A day.", insights=[], people=[], **{"self": "Pip."})])
    st.log("gift", sender="Morgan", item="needle file", qty=1)
    await agent.reflect()
    task = gm.calls[0]["messages"][0]["content"]
    assert "Things that happened for the first time since you last slept:" in task
    assert "- the first time you were given something" in task


@pytest.mark.asyncio
async def test_sleeping_and_waking_are_recorded_as_firsts(tmp_path):
    from datetime import datetime
    s, st, gm, agent = make(tmp_path, sleep=True)
    h = datetime.now().hour
    s.bedtime_hour, s.wake_hour = h, (h + 8) % 24
    await agent._run_tool(ToolCall("1", "sleep", {}), 0)
    assert {"tool:sleep"} <= keys(st)
    st.set_meta(sleep_started=time.time() - 3600, sleep_until=time.time() - 1)
    await agent.tick("timer")
    assert {"woke", "period:night"} <= keys(st)
