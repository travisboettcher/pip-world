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
    s = Settings(db_path=str(tmp_path / "t.db"), persona_path="/x", pacing="manual")
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
    assert r.followup and r.text == "You remember:\n- just now, feeling curious (diary): I planted the first tomatoes."
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
    assert "asleep" in call0["system"] and call0["system"].startswith("You are Pip.")  # Pip's own instructions
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
    assert st.recall("patience")[0]["source"] == "portrait" and st.recall("re-checking")[0]["source"] == "insight"
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
    assert "How you have described yourself before (oldest first):" in task and "] I'm Pip, a maker" in task
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
    s = Settings(db_path=str(tmp_path / "t.db"), persona_path="/x", pacing="manual",
                 reflect_hour=99)
    backend = FakeBackend([report(**REFLECTION)])
    with TestClient(create_app(s, backend)) as c:
        c.post("/inbox", json={"text": "how's the garden?", "sender": "Morgan"})
        r = c.post("/reflect").json()["reflection"]
        assert r["people"] == ["Morgan"]
        m = c.get("/memory").json()
        assert m["self"].startswith("I'm Pip") and m["people"][0]["name"] == "Morgan" and len(m["insights"]) == 2
        assert c.get("/recall", params={"q": "garden"}).json()[0]["text"] == "Morgan said to you: how's the garden?"


def test_legacy_gift_messages_are_not_indexed_twice(tmp_path):
    s, st, *_ = make(tmp_path)
    st.log("gift", sender="Morgan", item="tiny needle file", qty=1, item_kind="tool")
    st.log("inbox", id=1, text="Morgan gave you 1 x tiny needle file (tool). For the clock!")  # pre-flag era
    assert [h["text"] for h in st.recall("needle file")] == ["Morgan gave you 1 x tiny needle file"]
    st.set_meta(recall_indexed="1")
    assert len(State(s).recall("needle file")) == 1  # an old index is rebuilt on start, without the duplicate


# --- cited reflections (DESIGN-self.md, mechanism 2) ---------------------------------------
def eid(st, kind="inbox"):
    return [e["id"] for e in st.events(50) if e["kind"] == kind][0]


def verdicts(*pairs):
    return report(verdicts=[{"index": i, "verdict": v} for i, v in pairs])


def test_event_importance_is_deterministic_and_firsts_add_weight(tmp_path):
    from app.memory import event_importance as imp
    assert imp("tick", {}) == 0 and imp("tool", {"tool": "set_activity"}) == 1
    assert imp("inbox", {}) == 6 and imp("work", {"result": "good", "project_done": True}) == 7
    assert imp("inbox", {}, [{"tier": "major"}]) == 9 and imp("tool", {"tool": "plant"}, [{"tier": "minor"}]) == 2
    assert imp("creation_made", {}, [{"tier": "major"}]) == 10  # clamped
    s, st, *_ = make(tmp_path)
    visit(st, "hi")
    ev = st.events(5)[0]
    assert ev["importance"] == 9 and ev["data"]["firsts"]  # a visitor, and the first one ever


def test_material_tags_ids_and_keeps_what_matters_when_over_budget(tmp_path):
    s, st, *_ = make(tmp_path)
    st.log("tool", tool="note_to_self", args={"section": "todo", "text": "tidy"}, result="wrote in todo")  # importance 2
    visit(st, "I brought you a present and a long story to go with it")
    for n in range(6):  # newer, routine
        st.log("tool", tool="note_to_self", args={"section": "todo", "text": f"routine thing number {n}"}, result="wrote in todo")
    lines, people, shown = mem.material(st, 0, time.time() + 1, 400)
    visit_id = eid(st)
    assert any(l.startswith(f"[e{visit_id} ") and "present" in l for l in lines)        # the visit survived the budget
    assert set(shown) == {int(l.split()[0][2:]) for l in lines} and shown[visit_id].startswith("Morgan said to you")
    assert [int(l.split()[0][2:]) for l in lines] == sorted(shown)                       # shown in time order
    assert "(first: " in "\n".join(mem.material(st, 0, time.time() + 1, 12000)[0])       # firsts annotate the line


@pytest.mark.asyncio
async def test_validation_hunches_and_the_support_check(tmp_path):
    s, st, gm, agent = make(tmp_path)
    visit(st, "I like your clock")
    v = eid(st)
    ref = dict(summary="A visit.", people=[], **{"self": "Pip."}, insights=[
        {"text": "People like my work.", "importance": 7, "because": [f"e{v}", "e99999", "junk", f"e{v}"]},
        {"text": "I might be getting better.", "importance": 5, "because": []},
        {"text": "I am the best maker alive.", "importance": 9, "because": [f"e{v}"]},
    ])
    gm.queue(report(**ref), verdicts((0, "supported"), (2, "unsupported")))
    d = await agent.reflect()
    rows = {r["text"]: r for r in st.reflections("insight")}
    a, b, c = rows["People like my work."], rows["I might be getting better."], rows["I am the best maker alive."]
    assert st.reflection_cites(a["id"]) == [("event", v)]                       # junk and unknown ids dropped, deduped
    assert (a["grounded"], a["support"]) == (1, "supported") and a["importance"] == 7
    assert (b["grounded"], b["support"], st.reflection_cites(b["id"])) == (0, "none", [])
    assert (c["grounded"], c["support"], c["importance"]) == (0, "unsupported", 3)   # demoted, not deleted
    check = gm.calls[1]["messages"][0]["content"]
    assert "Claim: People like my work." in check and "I like your clock" in check and "[1]" not in check
    assert [i["support"] for i in d["insights"]] == ["supported", "none", "unsupported"]


@pytest.mark.asyncio
async def test_support_check_can_be_off_or_fail_without_losing_insights(tmp_path):
    for verify, script in ((False, [None]), (True, [LLMResponse("no", [], Usage(1, 1))])):
        sub = tmp_path / str(verify)
        sub.mkdir()
        s, st, gm, agent = make(sub, verify_insights=verify)
        visit(st, "hello")
        v = eid(st)
        ref = dict(summary="A visit.", people=[], **{"self": "Pip."},
                   insights=[{"text": "Visitors matter.", "importance": 6, "because": [f"e{v}"]}])
        gm.queue(report(**ref), *[x for x in script if x])
        await agent.reflect()
        (r,) = st.reflections("insight")
        assert (r["grounded"], r["support"]) == (1, "unchecked")                  # kept, just not checked
        assert len(gm.calls) == (1 if not verify else 2)


@pytest.mark.asyncio
async def test_later_insights_can_build_on_earlier_ones_by_id(tmp_path):
    s, st, gm, agent = make(tmp_path, verify_insights=False)
    visit(st, "first visit")
    gm.queue(report(summary="Day one.", people=[], **{"self": "Pip."},
                    insights=[{"text": "Visitors bring what I need.", "importance": 8, "because": [f"e{eid(st)}"]}]))
    await agent.reflect()
    (old,) = st.reflections("insight")
    visit(st, "second visit")
    gm.queue(report(summary="Day two.", people=[], **{"self": "Pip."},
                    insights=[{"text": "Morgan always comes through.", "importance": 7, "because": [f"i{old['id']}", f"e{eid(st)}"]}]))
    await agent.reflect()
    task = gm.calls[1]["messages"][0]["content"]
    assert f"[i{old['id']}] Visitors bring what I need." in task
    new = st.reflections("insight", limit=1)[0]
    assert ("reflection", old["id"]) in st.reflection_cites(new["id"]) and len(st.reflection_cites(new["id"])) == 2


@pytest.mark.asyncio
async def test_hunches_are_shown_apart_from_beliefs_and_recall_shows_the_evidence(tmp_path):
    s, st, gm, agent = make(tmp_path, verify_insights=False)
    visit(st, "I really love the escapement you made")
    ref = dict(summary="A visit.", people=[], **{"self": "Pip."}, insights=[
        {"text": "Compliments follow careful escapements.", "importance": 8, "because": [f"e{eid(st)}"]},
        {"text": "Maybe the garden likes me.", "importance": 5}])
    gm.queue(report(**ref))
    await agent.reflect()
    p = agent._perception("timer", [])
    belief = p.split("Things you've come to believe:\n")[1].split("\n")[0]
    assert belief == "- Compliments follow careful escapements."
    assert "Hunches (nothing you can point to yet):\n- Maybe the garden likes me." in p
    r = await call(agent, "recall", query="escapements")
    assert "Compliments follow careful escapements." in r.text and "because: Morgan said to you: I really love the escapement" in r.text


# --- versioned portrait, changes, and day counts --------------------------------------------------
@pytest.mark.asyncio
async def test_every_portrait_is_kept_and_the_next_reflection_sees_them_dated(tmp_path):
    s, st, gm, agent = make(tmp_path, verify_insights=False)
    visit(st, "first")
    gm.queue(report(summary="One.", people=[], insights=[], **{"self": "I am careful and slow."}),
             report(summary="Two.", people=[], insights=[], **{"self": "I am bolder than I was."}))
    await agent.reflect()
    visit(st, "second")
    await agent.reflect()
    assert [p["text"] for p in st.reflections("portrait")] == ["I am bolder than I was.", "I am careful and slow."]
    assert st.meta("self_portrait") == "I am bolder than I was."
    assert "I am careful and slow." in gm.calls[1]["messages"][0]["content"]


def test_an_existing_portrait_becomes_the_first_version(tmp_path):
    s, st, *_ = make(tmp_path)
    st.set_meta(self_portrait="I'm Pip.", last_reflection_ts="100")
    State(s)  # restart
    (p,) = st.reflections("portrait")
    assert p["text"] == "I'm Pip." and p["support"] == "legacy"
    State(s)
    assert len(st.reflections("portrait")) == 1


@pytest.mark.asyncio
async def test_changes_cite_evidence_are_shown_to_pip_and_recalled(tmp_path):
    s, st, gm, agent = make(tmp_path, verify_insights=False)
    for i in range(2):
        st.log("work", project="clock", stage="s", text="t", result="blowup", project_done=False, interrupted=False,
               minutes=60, approach="", finished_stage=False, percent=10)
    ref = dict(summary="Two bad days.", people=[], insights=[], **{"self": "I rush more than I thought."},
               changed=[{"text": "I used to check before cutting; now I rush (0 of 2 sessions had an approach).",
                         "importance": 7, "because": [f"e{eid(st, 'work')}"]},
                        {"text": "I feel different somehow.", "importance": 3}])
    gm.queue(report(**ref))
    d = await agent.reflect()
    ch = st.reflections("change")
    assert {c["text"][:20]: c["grounded"] for c in ch} == {"I used to check befo": 1, "I feel different som": 0}
    assert len(d["changes"]) == 2
    p = agent._perception("timer", [])
    assert "How you've changed:\n- I used to check before cutting" in p and "feel different somehow" not in p
    r = await call(agent, "recall", query="rush")
    assert "something you noticed changing in yourself" in r.text and "because:" in r.text


@pytest.mark.asyncio
async def test_day_counts_are_plain_facts_in_the_prompt_and_stored(tmp_path):
    s, st, gm, agent = make(tmp_path, verify_insights=False)
    st.log("work", project="clock", stage="s", text="t", result="setback", project_done=False, interrupted=False,
           minutes=60, approach="measure first")
    st.log("work", project="clock", stage="s", text="t", result="good", project_done=False, interrupted=False,
           minutes=30, approach="")
    visit(st, "hi")
    gm.queue(report(summary="A day.", people=[], insights=[], **{"self": "Pip."}))
    d = await agent.reflect()
    assert d["stats"]["work_sessions"] == 2 and d["stats"]["minutes_worked"] == 90 and d["stats"]["with_approach"] == 1
    assert d["stats"]["setbacks"] == 1 and d["stats"]["visitor_messages"] == 1
    task = gm.calls[0]["messages"][0]["content"]
    assert "2 work sessions, 90 minutes worked, 1 sessions where you described your approach, 1 setbacks" in task
    ((day, stored),) = st.day_stats(5)
    assert stored == d["stats"]


# --- the searchable text of each kind of event (exact; pinned by mutation testing) ----------------------------
@pytest.mark.parametrize("kind, data, text", [
    ("inbox", {"letter": True, "text": "A letter from Briar: hello"}, "A letter from Briar: hello"),
    ("reading", {"title": "Walden", "summary": "about a pond"}, "You read Walden: about a pond"),
    ("reading", {"title": "Walden", "summary": "a pond", "quotes": ["simplify", "go slow"]},
     'You read Walden: a pond "simplify" "go slow"'),
    ("letter_sent", {"to": "Briar", "text": "hello"}, "You wrote to Briar: hello"),
    ("letter_sent", {"to": "Briar", "text": "hello", "enclosed": "a spring"}, "You wrote to Briar: hello (enclosed: a spring)"),
    ("inbox", {"text": "hi Pip", "sender": "Morgan"}, "Morgan said to you: hi Pip"),
    ("inbox", {"text": "hi Pip"}, "A visitor said to you: hi Pip"),
    ("inbox", {"text": "hi Pip", "gift": True}, None),
    ("inbox", {"text": "Morgan gave you 2 x brass wire"}, None),
    ("say", {"text": "hello", "to_name": "Briar"}, "You said to Briar: hello"),
    ("say", {"text": "hello"}, "You said: hello"),
    ("gift", {"sender": "Morgan", "qty": 2, "item": "brass wire"}, "Morgan gave you 2 x brass wire"),
    ("work", {"project": "clock", "stage": "gears", "result": "progress", "text": "it turns"},
     "Working on clock (gears), progress: it turns"),
    ("work", {"project": "clock", "stage": "gears", "result": "setback", "text": "it jams", "learned": "oil it",
              "expectation": "as expected"}, "Working on clock (gears), setback: it jams You learned: oil it (as expected)"),
    ("work", {"project": "clock", "interrupted": True}, None),
    ("experiment", {"project": "clock", "hypothesis": "oil helps", "text": "it did"}, "Experiment on clock (oil helps): it did"),
    ("experiment", {"project": "clock", "hypothesis": "oil helps", "text": "it did", "finding": "oil helps",
                    "expectation": "a surprise"}, "Experiment on clock (oil helps): it did You learned: oil helps (a surprise)"),
    ("experiment", {"project": "clock", "interrupted": True}, None),
    ("world_changed", {"text": "Snow fell."}, "Snow fell."),
    ("revised_work", {"title": "Gulls"}, "You looked at your drawing 'Gulls' and redrew it"),
    ("made_work", {"what": "drawing", "title": "Gulls"}, "You drew 'Gulls'"),
    ("made_work", {"what": "drawing", "title": "Gulls", "caption": "three gulls"}, "You drew 'Gulls': three gulls"),
    ("made_work", {"what": "poem", "title": "Tide", "text": "in and out"}, "You wrote 'Tide': in and out"),
    ("made_work", {"what": "poem", "title": "Tide"}, "You wrote 'Tide': "),
    ("outreach", {"text": "hi", "what": "postcard"}, None),
    ("outreach", {"text": "hi", "what": "postcard", "delivered": True}, "You sent a postcard to a friend outside: hi"),
    ("outreach", {"text": "hi", "what": "reply", "delivered": True}, "You answered a friend outside: hi"),
    ("gathered", {"text": "You find 2 sticks.", "items": [{"name": "sticks"}]}, "You find 2 sticks."),
    ("gathered", {"text": "You find 2 sticks.", "interrupted": True, "items": [{"name": "sticks"}]}, "You find 2 sticks."),
    ("gathered", {"text": "Nothing.", "interrupted": True, "items": []}, None),
    ("gathered", {"text": "Nothing.", "items": []}, "Nothing."),
    ("creation_made", {"name": "Tock", "description": "a clockwork bird"}, "You finished making Tock: a clockwork bird"),
    ("companion", {"name": "Tock", "text": "tick"}, "Tock said: tick"),
    ("heard_of_place", {"by": "Briar", "place": "Saltholm", "there": "an ironmonger"}, "Briar told you about Saltholm: an ironmonger"),
    ("heard_of_place", {"by": "Briar", "place": "Saltholm", "there": ""}, "Briar told you about Saltholm"),
    ("tick", {}, None),
])
def test_recall_text_for_each_kind_of_event(kind, data, text):
    assert mem.recall_text(kind, data) == text
