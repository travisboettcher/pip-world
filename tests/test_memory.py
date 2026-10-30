import time
from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from app import memory as mem
from app.config import Settings
from app.llm.base import LLMResponse, Usage
from app.llm.fake import FakeBackend
from app.main import create_app
from app.state import State
from tests.test_projects import call, make, report

REFLECTION = dict(
    summary="Morgan came by twice and I finally started the clock properly.",
    insights=[{"text": "I work better when I stop re-checking.", "importance": 8},
              {"text": "", "importance": 3},                       # empty: dropped
              {"text": "Gardens keep going without me.", "importance": 40}],  # clamped to 10
    people=[{"name": "morgan", "notes": "Kind; brings exactly what I need."},
            {"name": "Mysterious Stranger", "notes": "Never met them."}],    # not in the material: dropped
    self="I'm Pip, a maker who is learning patience.",
)


def visit(st, text, sender="Morgan"):
    i = st.add_inbox(text, sender)
    st.log("inbox", id=i, text=text, sender=sender)


# --- step 0: who's talking -------------------------------------------------------
@pytest.mark.asyncio
async def test_perception_and_moments_name_the_visitor(tmp_path):
    s, st, gm, agent = make(tmp_path)
    visit(st, "hello Pip")
    st.add_inbox("Jade gave you 2 x string (material).", "Jade", gift=True)
    p = agent._perception("event", st.pending_inbox())
    assert "- Morgan: hello Pip" in p and "- Jade gave you 2 x string (material)." in p
    assert "Morgan came by and talked with you (1 message" in p


def test_inbox_api_takes_a_sender(tmp_path):
    s = Settings(db_path=str(tmp_path / "t.db"), persona_path="/x", persona_default_path="/x", pacing="manual")
    with TestClient(create_app(s, FakeBackend())) as c:
        c.post("/inbox", json={"text": "hi", "sender": "  Jade   B "})
        c.post("/inbox", json={"text": "anon"})
        st = c.app.state.agent.state
        assert [m["sender"] for m in st.pending_inbox()] == ["Jade B", "A visitor"]
        assert [e["data"]["sender"] for e in st.events(5) if e["kind"] == "inbox"] == ["A visitor", "Jade B"]


# --- step 2: recall ---------------------------------------------------------------------
@pytest.mark.asyncio
async def test_recall_finds_notes_and_events_by_prefix(tmp_path):
    s, st, gm, agent = make(tmp_path)
    st.add_memory("The clock's escapement finally ticked evenly.", "diary")
    todo = st.add_memory("Find more brass wire", "todo")
    visit(st, "How are the clocks coming along?")
    st.log("say", text="Slowly, but they tick now!", to=[1])
    st.log("tick", text="clock clock clock")  # not a remembered kind
    texts = [h["text"] for h in st.recall("what did Morgan say about the clock?")]
    assert texts == ["The clock's escapement finally ticked evenly.", "Morgan said to you: How are the clocks coming along?"]
    st.edit_memory(todo, "Find more copper wire")
    assert [h["text"] for h in st.recall("brass")] == [] and st.recall("copper")[0]["source"] == "note:todo"
    st.resolve_memory(todo, "Jade had some")
    assert st.recall("copper")[0]["text"] == "Find more copper wire (done: Jade had some)"
    assert st.recall("the and of it") == [] and st.recall('"); DROP TABLE x; --') == []


@pytest.mark.asyncio
async def test_recall_tool_formats_with_relative_time(tmp_path):
    s, st, gm, agent = make(tmp_path)
    st.add_memory("I planted the first tomatoes.", "diary")
    r = await call(agent, "recall", query="tomatoes")
    assert r.followup and r.text == "You remember:\n- just now (diary): I planted the first tomatoes."
    assert (await call(agent, "recall", query="volcano")).text == "nothing comes to mind"


def test_existing_data_is_backfilled_once(tmp_path):
    s, st, *_ = make(tmp_path)
    st.add_memory("Old diary entry about kites.", "diary")
    st.db.execute("DELETE FROM recall_index")
    st.db.execute("DELETE FROM meta WHERE key = 'recall_indexed'")
    st.db.commit()
    assert st.recall("kites") == []
    assert State(s).recall("kites")[0]["text"] == "Old diary entry about kites."  # restart backfills


def test_ago():
    now = 1_000_000.0
    assert [mem.ago(now - x, now) for x in (30, 600, 3600, 5 * 3600, 86400, 3 * 86400)] == [
        "just now", "10 minutes ago", "an hour ago", "5 hours ago", "yesterday", "3 days ago"]


# --- step 1: reflection ------------------------------------------------------------------
@pytest.mark.asyncio
async def test_reflection_consolidates_the_day_in_pips_voice(tmp_path):
    s, st, gm, agent = make(tmp_path, [report(**REFLECTION)])
    visit(st, "How's the clock?")
    st.log("gift", sender="Morgan", item="brass wire", qty=2, item_kind="material")
    st.log("tool", tool="note_to_self", args={"section": "diary", "text": "Morgan's wire came just in time."},
           result="wrote in diary")
    st.log("tick", text="(not material)")
    data = await agent.reflect()
    call0 = gm.calls[0]
    assert "asleep" in call0["system"] and "small autonomous creature" in call0["system"]  # Pip's own persona
    task = call0["messages"][0]["content"]
    assert "Morgan said to you: How's the clock?" in task and "Morgan gave you 2 x brass wire" in task
    assert "You wrote (diary): Morgan's wire came just in time." in task and "not material" not in task
    assert "Only these names: Morgan." in task and "You haven't described yourself before." in task
    assert data["people"] == ["Morgan"] and len(data["insights"]) == 2
    assert [(r["text"], r["importance"]) for r in st.reflections("insight", by_importance=True)] == [
        ("Gardens keep going without me.", 10), ("I work better when I stop re-checking.", 8)]
    assert st.people()[0]["notes"] == "Kind; brings exactly what I need."
    assert st.meta("self_portrait") == "I'm Pip, a maker who is learning patience."
    assert st.events(1)[0]["kind"] == "reflection"
    p = agent._perception("timer", [])
    assert "Who you are (in your own words" in p and "I'm Pip, a maker who is learning patience." in p
    assert "- Morgan (last seen just now): Kind; brings exactly what I need." in p
    assert "- just now: Morgan came by twice" in p and "- Gardens keep going without me." in p
    assert st.recall("patience") == [] and st.recall("re-checking")[0]["source"] == "insight"
    assert "person" in {h["source"] for h in st.recall("morgan")}


@pytest.mark.asyncio
async def test_next_reflection_only_reads_new_material_and_sees_its_old_self(tmp_path):
    s, st, gm, agent = make(tmp_path, [report(**REFLECTION), report(summary="A quiet day of filing.", self="Still Pip.")])
    visit(st, "first visit")
    await agent.reflect()
    visit(st, "second visit")
    await agent.reflect()
    task = gm.calls[1]["messages"][0]["content"]
    assert "second visit" in task and "first visit" not in task
    assert "How you described yourself last time:\nI'm Pip, a maker" in task
    assert "- Morgan: Kind; brings exactly what I need." in task
    assert st.meta("self_portrait") == "Still Pip." and st.people()[0]["notes"] == "Kind; brings exactly what I need."


@pytest.mark.asyncio
async def test_quiet_day_skips_the_call_and_failure_retries_later(tmp_path):
    s, st, gm, agent = make(tmp_path, [LLMResponse("zzz", [], Usage(1, 1))], reflect_hour=0)
    assert await agent.reflect() is None and gm.calls == []  # nothing happened: no LLM call
    assert not mem.due(st, s, time.time())  # ...but today counts as done
    visit(st, "hello")
    st.set_meta(last_reflection_day="")
    assert await agent.reflect() is None and len(gm.calls) == 1  # unusable answer
    assert st.events(1)[0]["kind"] == "reflection_error" and not mem.due(st, s, time.time())  # wait an hour
    assert mem.due(st, s, time.time() + 3601) and st.reflections() == []


def test_due_after_the_reflect_hour_once_a_day(tmp_path):
    s, st, *_ = make(tmp_path, reflect_hour=3)
    day = datetime(2026, 11, 2)
    at = lambda h: day.replace(hour=h).timestamp()  # noqa: E731
    assert not mem.due(st, s, at(2)) and mem.due(st, s, at(3)) and mem.due(st, s, at(23))
    st.set_meta(last_reflection_day="2026-11-02")
    assert not mem.due(st, s, at(4))
    assert mem.due(st, s, datetime(2026, 11, 3, 3).timestamp())


@pytest.mark.asyncio
async def test_monitor_runs_the_reflection_when_due(tmp_path):
    s, st, gm, agent = make(tmp_path, [report(**REFLECTION)], reflect_hour=0)
    visit(st, "hello")
    await agent.resolve_world()
    assert st.reflections("day")[0]["text"].startswith("Morgan came by")
    await agent.resolve_world()
    assert len(gm.calls) == 1  # once a day


def test_memory_api(tmp_path):
    s = Settings(db_path=str(tmp_path / "t.db"), persona_path="/x", persona_default_path="/x", pacing="manual",
                 reflect_hour=99)
    backend = FakeBackend([report(**REFLECTION)])
    with TestClient(create_app(s, backend)) as c:
        c.post("/inbox", json={"text": "how's the garden?", "sender": "Morgan"})
        r = c.post("/reflect").json()["reflection"]
        assert r["people"] == ["Morgan"]
        m = c.get("/memory").json()
        assert m["self"].startswith("I'm Pip") and m["people"][0]["name"] == "Morgan" and len(m["insights"]) == 2
        assert c.get("/recall", params={"q": "garden"}).json()[0]["text"] == "Morgan said to you: how's the garden?"
