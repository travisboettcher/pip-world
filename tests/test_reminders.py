"""What comes to mind (memory step 3, docs/DESIGN-reminders.md): memories keep their context, fade unless used, and the best of them
come to mind by themselves when the situation cues them."""
import json
import math
import os
import time

import pytest

from app import reminders as R
from app import tools as T
from app.config import Settings
from app.state import State
from tests.test_neighbor import neighbor
from tests.test_projects import PIP_STEPS, FixedRng, call, crafting, make, report

import app.neighbors as nb

DAY = 86400


def old_note(st, text, section="todo"):
    """A note that is no longer on show (done), so it can come to mind."""
    i = st.add_memory(text, section)
    if section in ("todo", "wishlist", "ambitions"):
        st.set_memory_status(i, "done")
    return ("note:" + section, str(i))


def on(tmp_path, **kw):
    """A world with reminders on and a few dozen everyday notes, so a rare word stands out as it does in a real memory."""
    kw.setdefault("reminders", "on")
    s, st, gm, agent = make(tmp_path, **kw)
    for i in range(40):
        old_note(st, f"Everyday chore {i}: sorted the shelf, swept, tidied.")
    return s, st, gm, agent


def rel(st, words, key):
    r = [m for m in st.recall_scored(R.words(words), 30) if (m["source"], str(m["ref"])) == key][0]
    return min(1.0, -r["score"] / R.REL_FULL)


# --- 1. context ----------------------------------------------------------------------------------------------------------------------
def test_a_memory_keeps_where_who_doing_and_feeling(tmp_path):
    s, st, gm, agent = make(tmp_path)
    st.update_agent(activity="tinkering", mood="content")
    st.set_emotion("joy", 70, time.time())
    eid = st.log("inbox", id=1, text="Hello from the coast!", sender="Travis")
    c = st.memory_context("event:inbox", eid)
    assert {k: c[k] for k in ("place", "people", "activity", "mood", "feeling", "project", "importance")} == \
        {"place": "workshop", "people": ["Travis"], "activity": "tinkering", "mood": "content", "feeling": "joy", "project": None, "importance": 9}
    assert c["uses"] == [c["ts"]] and c["faded"] == 0 and c["shown_at"] == 0


def test_a_feeling_only_counts_when_it_stands_out_and_names_only_people(tmp_path):
    s, st, gm, agent = make(tmp_path)
    st.set_emotion("joy", 50, time.time())                                         # 5 over its baseline: not notable
    eid = st.log("creation_made", name="Gear Clock", quality="fine", description="It ticks.")
    c = st.memory_context("event:creation_made", eid)
    assert c["feeling"] is None and c["people"] == []
    st.log("say", text="Hi!", to="Pip")
    assert st.memory_context("event:say", st.events(1)[0]["id"])["people"] == []


@pytest.mark.asyncio
async def test_at_a_neighbors_home_she_is_part_of_every_memory_and_a_walk_has_no_place(tmp_path):
    s, st, gm, agent = make(tmp_path, [report(text="A low cottage."), report(text="Pip! Come in.")], work_speed=1e6)
    agent.tools.update({n: T.REGISTRY[n] for n in ("go_to",)})
    neighbor(st, s)
    await call(agent, "go_to", place="Marigold")
    walking = old_note(st, "Halfway there.", "diary")
    assert st.memory_context(*walking)["place"] is None
    time.sleep(0.01)
    await agent.finish_work()
    await nb.step(st, s, agent.gm, FixedRng(), time.time())
    said = [e for e in st.events(10) if e["kind"] == "companion"][0]
    c = st.memory_context("event:companion", said["id"])
    assert c["place"] == "Marigold's home" and c["people"] == ["Marigold"] and c["importance"] == 4
    note = st.memory_context(*old_note(st, "Bees everywhere.", "diary"))
    assert note["people"] == ["Marigold"] and note["importance"] == 4


@pytest.mark.asyncio
async def test_a_memory_made_while_working_keeps_the_project(tmp_path):
    s, st, gm, agent = make(tmp_path, [report(**__import__("tests.test_projects", fromlist=["PLAN"]).PLAN)])
    st.add_item("brass wire", 9, "material")
    crafting(st)
    await call(agent, "start_project", name="Gear clock", goal="a clock", steps=PIP_STEPS)
    await call(agent, "work_on", project="#1")
    c = st.memory_context(*old_note(st, "The escapement is fiddly.", "diary"))
    assert c["project"] == "Gear clock"


def test_people_notes_reflections_and_works_have_their_importance(tmp_path):
    s, st, gm, agent = make(tmp_path)
    st.upsert_person("Travis", "Kind.", time.time())
    assert st.memory_context("person", "Travis")["people"] == ["Travis"] and st.memory_context("person", "Travis")["importance"] == 5
    rid = st.add_reflection("insight", "Small steps work.", 8, 0, time.time())
    assert st.memory_context("insight", rid)["importance"] == 8
    wid = st.add_work("drawing", "Gears", "<svg/>", "a sketch", "workshop")
    assert st.memory_context("work:drawing", wid)["importance"] == 5
    assert st.memory_context(*old_note(st, "Buy wire."))["importance"] == 3


def test_writing_a_memory_again_is_a_use(tmp_path):
    s, st, gm, agent = make(tmp_path)
    i = st.add_memory("Fix the hinge.", "todo")
    st.edit_memory(i, "Fix the gate hinge.")
    c = st.memory_context("note:todo", i)
    assert len(c["uses"]) == 2 and c["uses"][1] >= c["uses"][0]
    st.upsert_person("Travis", "Kind.", time.time())
    st.upsert_person("Travis", "Kind and patient.", time.time())
    assert len(st.memory_context("person", "Travis")["uses"]) == 2


def test_uses_are_capped(tmp_path):
    s, st, gm, agent = make(tmp_path)
    key = old_note(st, "Fix the hinge.")
    for i in range(30):
        st.use_memories([key], 1000.0 + i)
    uses = st.memory_context(*key)["uses"]
    assert len(uses) == 20 and uses[-1] == 1029.0


def test_older_memories_get_who_and_how_much_once(tmp_path):
    s, st, gm, agent = make(tmp_path)
    eid = st.log("inbox", id=1, text="Hello!", sender="Travis")
    i = st.add_memory("A thought.", "diary")
    rid = st.add_reflection("day", "A long day.", 6, 0, time.time())
    st.upsert_person("Travis", "Kind.", time.time())
    wid = st.add_work("writing", "Rain", "It rained.", "", "workshop")
    st.db.execute("DELETE FROM memory_context")
    st.db.execute("DELETE FROM meta WHERE key = 'memory_context'")
    st.db.commit()
    st2 = State(s)
    c = st2.memory_context("event:inbox", eid)
    assert c["people"] == ["Travis"] and c["importance"] == 9 and c["place"] is None and c["mood"] is None
    assert st2.memory_context("note:diary", i)["importance"] == 4
    assert st2.memory_context("day", rid)["importance"] == 6
    assert st2.memory_context("person", "Travis")["people"] == ["Travis"]
    assert st2.memory_context("work:writing", wid)["importance"] == 5
    assert st2.memory_context("event:inbox", eid)["uses"] == [c["ts"]]
    st2.use_memories([("event:inbox", eid)], time.time())
    assert len(State(s).memory_context("event:inbox", eid)["uses"]) == 2           # not redone on the next start


def test_rebuilding_the_index_is_not_a_use(tmp_path):
    s, st, gm, agent = make(tmp_path)
    key = old_note(st, "Fix the hinge.")
    st.db.execute("DELETE FROM meta WHERE key = 'recall_indexed'")
    st.db.commit()
    assert State(s).memory_context(*key)["uses"] == st.memory_context(*key)["uses"]


# --- 2. activation and fading ---------------------------------------------------------------------------------------------------------
def test_activation_fades_with_time_and_use_brings_it_back():
    assert R.activation([0], 3600) == pytest.approx(0.0)
    assert R.activation([0], 4 * 3600) == pytest.approx(math.log(0.5))
    assert R.activation([0], 0) == pytest.approx(math.log(R.MIN_HOURS ** -0.5))
    assert R.activation([0, 3 * 3600], 4 * 3600) == pytest.approx(math.log(0.5 + 1))
    assert R.activation([], 10) == -math.inf


def test_important_memories_fade_more_slowly():
    assert R.fade_line(5) == pytest.approx(math.log((14 * 24) ** -0.5))
    assert R.fade_line(10) == pytest.approx(math.log((28 * 24) ** -0.5)) and R.fade_line(20) == R.fade_line(10)
    assert R.fade_line(1) == pytest.approx(math.log((7 * 24) ** -0.5)) and R.fade_line(2) == R.fade_line(1)
    assert R.fade_line(4) == pytest.approx(math.log((14 * 24 * 0.8) ** -0.5))


def test_an_unused_memory_fades_once_and_recall_still_finds_it(tmp_path):
    s, st, gm, agent = make(tmp_path)
    old = old_note(st, "The kiln cracked in the frost.")
    kept = old_note(st, "Bring the ladder in.")
    later = time.time() + 15 * DAY
    st.use_memories([kept], later - DAY)
    assert R.fade(st, later) == [old]
    assert st.memory_context(*old)["faded"] == 1 and st.memory_context(*kept)["faded"] == 0
    ev = [e["data"] for e in st.events(5) if e["kind"] == "faded"][0]
    assert ev == {"count": 1, "memories": [f"{old[0]}#{old[1]}"]}
    assert R.fade(st, later + 60) == []                                              # checked at most once an hour
    assert R.fade(st, later + 3601) == []                                            # and logged once
    hits = st.recall("kiln")
    text = R.recall_lines(st, hits, {}, later)
    assert text.endswith("The kiln cracked in the frost. (you had half forgotten this)")
    assert st.memory_context(*old)["faded"] == 0 and st.memory_context(*old)["uses"][-1] == later


@pytest.mark.asyncio
async def test_the_recall_tool_frames_its_answers_and_counts_as_a_use(tmp_path):
    s, st, gm, agent = make(tmp_path)
    agent.tools["recall"] = T.REGISTRY["recall"]
    st.update_agent(location="library", activity="reading", mood="calm")
    key = old_note(st, "The library has a map of the coast.", "diary")
    r = await call(agent, "recall", query="coast map")
    assert r.text == "You remember:\n- just now, at the library, while you were reading, feeling calm (diary): The library has a map of the coast."
    assert len(st.memory_context(*key)["uses"]) == 2


# --- 3. the cue ------------------------------------------------------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_the_cue_is_who_where_what_and_the_newest_words(tmp_path):
    s, st, gm, agent = make(tmp_path, [report(**__import__("tests.test_projects", fromlist=["PLAN"]).PLAN)])
    st.log("happening", id=1, title="A hedgehog in the shed", text="x", tone="good", severity="minor", category="visitor", lens="joy")
    st.log("gift", sender="Travis", item="brass wire", qty=1, item_kind="material")
    st.add_item("brass wire", 9, "material")
    inbox = [{"sender": "Travis", "text": "How is the clock?", "gift": False}, {"sender": "Travis", "text": "Travis gave you wire", "gift": True}]
    crafting(st)
    await call(agent, "start_project", name="Gear clock", goal="a clock", steps=PIP_STEPS)
    await call(agent, "work_on", project="#1")
    c = R.cue(st, inbox, time.time())
    assert c.people == ["Travis"] and c.place is None and c.project == "Gear clock"
    assert c.words == "How is the clock? Travis gave you wire working on Gear clock: cut the wheels A hedgehog in the shed brass wire"
    assert c.context() == ["Travis", "Gear clock"]
    assert R.cue(st, inbox, time.time() + 7 * 3600).words.endswith("cut the wheels")       # old happenings and gifts drop out


@pytest.mark.asyncio
async def test_the_cue_at_a_neighbors_is_her_and_her_last_line(tmp_path):
    s, st, gm, agent = make(tmp_path, [report(text="A low cottage."), report(text="Pip! Come in.")], work_speed=1e6)
    agent.tools.update({n: T.REGISTRY[n] for n in ("go_to",)})
    ch = neighbor(st, s)
    await call(agent, "go_to", place="Marigold")
    time.sleep(0.01)
    await agent.finish_work()
    st.log("companion", name="Marigold", text="Before this visit, long ago.", visit=True)
    st.set_meta(arrived_at=str(time.time()))
    await nb.step(st, s, agent.gm, FixedRng(), time.time())
    c = R.cue(st, [], time.time(), ch)
    assert c.people == ["Marigold"] and c.place == "Marigold's home" and c.words == "Pip! Come in." and c.project is None


def test_words_leave_out_the_small_ones():
    assert R.words("Did Pip see THE red kite at 5?") == ["red", "kite"]
    assert R.words("Come sit, Pip. How are the carrots coming along?") == ["carrots"]


# --- 4. choosing what comes to mind ----------------------------------------------------------------------------------------------------
def test_the_memory_the_situation_cues_comes_to_mind_with_its_frame(tmp_path):
    s, st, gm, agent = on(tmp_path)
    st.update_agent(activity="gardening", mood="cheerful")
    key = old_note(st, "Ask Travis about the brass wire for the clock.")
    old_note(st, "Sweep the floor.")
    now = time.time() + 3 * DAY
    lines = R.step(st, s, R.Cue(words="Do you still want brass wire?"), now, 2)
    when = "on " + time.strftime("%A", time.localtime(st.memory_context(*key)["ts"]))
    assert lines == ["This brings to mind:", f"- {when}, while you were gardening, feeling cheerful (todo): Ask Travis about the brass wire for the clock."]
    ev = [e["data"] for e in st.events(5) if e["kind"] == "reminded"][0]
    assert [(w["source"], w["ref"]) for w in ev["shown"]] == [key] and ev["nearly"] == [] and ev["cue"] == []
    assert st.memory_context(*key)["shown_at"] == now and st.meta("reminded_event") == str(st.events(5)[0]["id"])


def test_nothing_comes_to_mind_without_a_cue_or_below_the_bar(tmp_path, monkeypatch):
    monkeypatch.setattr(R, "REMIND_MIN", 1.1)
    s, st, gm, agent = on(tmp_path)
    old_note(st, "Ask Travis about the brass wire for the clock.")
    now = time.time() + 3 * DAY
    assert R.step(st, s, R.Cue(words="nothing in common here"), now, 2) == []
    assert not [e for e in st.events(5) if e["kind"] == "reminded"]
    key = old_note(st, "wire")                                                    # a weak match: importance 3, a long-unused memory
    st.db.execute("UPDATE memory_context SET importance = 0, uses = ? WHERE ref = ?", (json.dumps([now - 13 * DAY]), key[1]))
    st.db.execute("UPDATE memory_context SET faded = 1 WHERE ref != ?", (key[1],))
    st.db.commit()
    w, rest = R.choose(st, s, R.Cue(words="wire"), now, 2, set())
    assert w == [] and [m["ref"] for m in rest] == [key[1]] and rest[0]["score"] < R.REMIND_MIN
    assert R.choose(st, s, R.Cue(words="tidied"), now, 2, set()) == ([], [])          # a word in everything means nothing


def test_what_is_in_view_young_faded_or_lately_shown_stays_out(tmp_path):
    s, st, gm, agent = on(tmp_path)
    k = old_note(st, "The kite string snapped in the wind.")
    now = time.time() + 3 * DAY
    c = R.Cue(words="kite string")
    assert R.choose(st, s, c, now, 2, {k})[0] == []                                  # in view
    assert R.choose(st, s, c, time.time() + 5 * 3600, 2, set())[0] == []             # too young: still in view
    assert [m["ref"] for m in R.choose(st, s, c, time.time() + 6 * 3600 + 5, 2, set())[0]] == [k[1]]
    st.mark_shown([k], now, [])
    assert R.choose(st, s, c, now + 11 * 3600, 2, set())[0] == []                    # brought to mind lately
    assert R.choose(st, s, c, now + 13 * 3600, 2, set())[0] != []
    st.set_faded([k])
    assert R.choose(st, s, c, now + 13 * 3600, 2, set())[0] == []


def test_someone_new_brings_a_lately_shown_memory_back(tmp_path):
    s, st, gm, agent = on(tmp_path)
    eid = st.log("inbox", id=1, text="The kite string snapped, did you fix it?", sender="Travis")
    k = ("event:inbox", str(eid))
    now = time.time() + 3 * DAY
    st.mark_shown([k], now, [])
    assert R.choose(st, s, R.Cue(words="kite"), now + 3600, 2, set())[0] == []
    assert R.choose(st, s, R.Cue(people=["Travis"], words="kite"), now + 3600, 2, set())[0] != []
    st.mark_shown([k], now, ["Travis"])
    assert R.choose(st, s, R.Cue(people=["Travis"], words="kite"), now + 3600, 2, set())[0] == []


def test_the_score_is_relevance_importance_activation_and_context(tmp_path):
    s, st, gm, agent = on(tmp_path)
    st.update_agent(location="library")
    eid = st.log("inbox", id=1, text="The library has old sea charts.", sender="Travis")
    st.update_agent(location="workshop")
    now = time.time() + 2 * DAY
    act = 1 / (1 + math.exp(-R.activation(st.memory_context("event:inbox", eid)["uses"], now)))
    k = ("event:inbox", str(eid))
    r = rel(st, "sea charts", k)
    assert 0 < r <= 1
    (m,), _ = R.choose(st, s, R.Cue(words="sea charts"), now, 2, set())
    assert m["score"] == round(r + 0.9 + act, 3)
    (m,), _ = R.choose(st, s, R.Cue(people=["Travis"], place="library", words="sea charts"), now, 2, set())
    assert m["score"] == round(r + 0.9 + act + 1.0, 3)
    (m,), _ = R.choose(st, s, R.Cue(place="library", words="nothing"), now, 2, set())
    assert m["score"] == round(0.9 + act + 0.5, 3)                                    # brought by the place alone
    (m,), _ = R.choose(st, s, R.Cue(people=["Travis"], words="nothing"), now, 2, set())
    assert m["score"] == round(0.9 + act + 0.5, 3)
    assert R.choose(st, s, R.Cue(people=["Someone"], project="library", words="nothing"), now, 2, set()) == ([], [])


def test_one_per_source_and_the_best_first(tmp_path):
    s, st, gm, agent = on(tmp_path)
    a = old_note(st, "Clock gears need oil.")
    b = old_note(st, "Clock face needs paint.")
    c = old_note(st, "The clock chimed at noon.", "diary")
    for _ in range(4):
        old_note(st, "Filler entry.", "diary")
    now = time.time() + 2 * DAY
    st.use_memories([b], now - 3600)
    w, rest = R.choose(st, s, R.Cue(words="clock"), now, 2, set())
    assert [(m["source"], m["ref"]) for m in w] == [b, c] and [(m["source"], m["ref"]) for m in rest] == [a]
    assert [m["ref"] for m in R.choose(st, s, R.Cue(words="clock"), now, 1, set())[0]] == [b[1]]


def test_what_is_already_on_show_is_not_brought_to_mind(tmp_path):
    s, st, gm, agent = on(tmp_path)
    shown = st.add_memory("Oil the clock gears.", "todo")
    diary = st.add_memory("The clock ran all night.", "diary")
    rid = st.add_reflection("insight", "Clocks need patience.", 9, 0, time.time())
    st.upsert_person("Clockmaker Jo", "Knows clocks.", time.time())
    eid = st.log("inbox", id=1, text="clock?", sender="Travis")
    view = R.in_view(st)
    assert {("note:todo", str(shown)), ("note:diary", str(diary)), ("insight", str(rid)), ("person", "Clockmaker Jo"),
            ("event:inbox", str(eid))} <= view
    for i in range(31):
        st.log("tick_start")
    assert ("event:inbox", str(eid)) not in R.in_view(st)


# --- 5. a turn of reminding ---------------------------------------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_a_reminder_taken_up_is_a_use_and_one_ignored_is_not(tmp_path):
    s, st, gm, agent = on(tmp_path)
    k = old_note(st, "Ask Travis about the brass wire for the clock.")
    now = time.time() + 3 * DAY
    assert R.step(st, s, R.Cue(words="brass wire"), now, 2)
    uses = len(st.memory_context(*k)["uses"])
    assert R.taken_up(st, now) == []                                                 # Pip hasn't acted yet
    st.log("tool", tool="note_to_self", args={"text": "Ask Travis whether the brass wire would suit the clock."}, result="ok")
    assert R.taken_up(st, now + 60) == [k] and len(st.memory_context(*k)["uses"]) == uses + 1
    assert R.taken_up(st, now + 120) == []                                           # counted once
    k2 = old_note(st, "The garden gate squeaks.")
    later = now + DAY
    assert R.step(st, s, R.Cue(words="gate squeaks"), later, 2)
    st.log("tool", tool="eat", args={"item": "apple"}, result="ok")
    assert R.taken_up(st, later + 60) == [] and len(st.memory_context(*k2)["uses"]) == 1


def test_log_mode_chooses_without_showing_and_off_does_nothing(tmp_path):
    s, st, gm, agent = on(tmp_path, reminders="log")
    k = old_note(st, "The kite string snapped in the wind.")
    now = time.time() + 3 * DAY
    assert R.step(st, s, R.Cue(words="kite"), now, 2) == []
    assert [e for e in st.events(5) if e["kind"] == "reminded"] and st.memory_context(*k)["shown_at"] == now
    s.reminders = "off"
    n = len(st.events(100))
    assert R.step(st, s, R.Cue(words="kite"), now + DAY, 2) == [] and len(st.events(100)) == n
    s.reminders = "on"
    assert R.step(st, s, R.Cue(words="kite"), now + DAY, 0) == []


def test_runners_up_alone_are_logged_but_nothing_is_shown(tmp_path, monkeypatch):
    monkeypatch.setattr(R, "REMIND_MIN", 1.1)
    s, st, gm, agent = on(tmp_path)
    k = old_note(st, "wire")
    now = time.time() + 3 * DAY
    st.db.execute("UPDATE memory_context SET importance = 0, uses = ? WHERE ref = ?", (json.dumps([now - 5 * DAY]), k[1]))
    st.db.commit()
    assert R.step(st, s, R.Cue(words="wire"), now, 2) == []
    ev = [e["data"] for e in st.events(5) if e["kind"] == "reminded"][0]
    assert ev["shown"] == [] and ev["nearly"][0]["ref"] == k[1] and st.meta("reminded_event") is None
    assert st.memory_context(*k)["shown_at"] == 0


def test_the_frame_says_only_what_is_known(tmp_path):
    now = time.time()
    ctx = {"ts": now - 3 * 3600, "place": "workshop", "activity": "idle", "feeling": None, "mood": None}
    assert R.frame("insight", "Small steps.", ctx, now) == "- 3 hours ago (something you came to believe): Small steps."
    ctx = {"ts": now - 20 * DAY, "place": "Saltholm", "activity": "trading", "feeling": "joy", "mood": "busy"}
    assert R.frame("event:say", "x", ctx, now).startswith("- on ") and ", at Saltholm, while you were trading, feeling joy: x" in R.frame("event:say", "x", ctx, now)
    assert R.frame("person", "y" * 300, None, now) == f"- just now (what you think of them): {'y' * 257}..." or \
        R.frame("person", "y" * 300, None, now).startswith("- just now (what you think of them): yyy")
    assert R.when(now - 3 * DAY, now) == "on " + time.strftime("%A", time.localtime(now - 3 * DAY))
    assert R.when(now - 7 * DAY, now) == "7 days ago" and R.when(now - DAY, now) == "yesterday"


# --- 6. in the prompt ---------------------------------------------------------------------------------------------------------------
def test_reminders_appear_in_the_world_turn_and_stay_out_of_recent_events(tmp_path):
    s, st, gm, agent = on(tmp_path)
    k = old_note(st, "Travis said the brass wire is coming.")
    st.db.execute("UPDATE memory_context SET ts = ts - ? WHERE ref = ?", (1.5 * DAY, k[1]))
    st.db.commit()
    agent.receive("Did the brass wire arrive?", "Travis")
    p = agent._perception("event", st.pending_inbox())
    assert "This brings to mind:\n- 2 days ago" in p and "Travis said the brass wire is coming." in p
    assert p.index("This brings to mind:") > p.index("Your diary") or "This brings to mind:" in p
    assert "reminded" not in p.split("Recent events:")[-1]
    s.reminders = "off"
    assert "This brings to mind" not in agent._perception("event", st.pending_inbox())


def test_the_talk_prompt_carries_what_comes_to_mind():
    from app import talk
    from types import SimpleNamespace
    st = SimpleNamespace(people=lambda: [], memories=lambda *a, **k: [], items=lambda: [], meta=lambda k: None, coins=lambda: 3,
                         agent=lambda: {"location": "workshop", "activity": "idle", "description": "", "mood": "calm"}, events=lambda n: [])
    got = talk.prompt(st, {"name": "Marigold"}, "It is noon.", time.time(), ["This brings to mind:", "- yesterday: bees."])
    assert "3 coins.\nThis brings to mind:\n- yesterday: bees.\nTalking with Marigold" in got


def test_the_settings():
    assert Settings().reminders == "off" and Settings().reminders_shown == 2 and Settings().remind_cooldown_hours == 12
    keys = ("REMINDERS", "REMINDERS_SHOWN", "REMIND_COOLDOWN_HOURS")
    old = {k: os.environ.pop(k, None) for k in keys}
    try:
        assert Settings.from_env().reminders == "on"
        os.environ.update(REMINDERS="LOG", REMINDERS_SHOWN="1", REMIND_COOLDOWN_HOURS="6")
        e = Settings.from_env()
        assert (e.reminders, e.reminders_shown, e.remind_cooldown_hours) == ("log", 1, 6)
        os.environ["REMINDERS"] = "maybe"
        assert Settings.from_env().reminders == "on"
    finally:
        for k in keys:
            os.environ.pop(k, None)
            if old[k] is not None:
                os.environ[k] = old[k]


# --- 7. the guide, the API and the scene --------------------------------------------------------------------------------------------
def test_the_guide_mentions_reminders_only_when_they_are_on(tmp_path):
    from app import guide
    s, st, gm, agent = on(tmp_path)
    assert "This brings to mind" in guide.render(agent.tools, s, False)
    s.reminders = "log"
    assert "This brings to mind" not in guide.render(agent.tools, s, False)


def test_the_owner_sees_what_was_last_on_pips_mind_and_the_public_does_not(tmp_path):
    from fastapi.testclient import TestClient
    from app.main import create_app
    from app.llm.fake import FakeBackend
    s = Settings(db_path=str(tmp_path / "t.db"), persona_path="/x", pacing="manual", public_hosts=["pip.example.org"], reminders="on")
    with TestClient(create_app(s, FakeBackend())) as c:
        st = c.app.state.agent.state
        for i in range(40):
            old_note(st, f"Everyday chore {i}: sorted the shelf, swept, tidied.")
        old_note(st, "The kite string snapped in the wind.")
        R.step(st, s, R.Cue(words="kite string"), time.time() + 3 * DAY, 2)
        mine = c.get("/memory").json()
        assert mine["on_mind"]["shown"][0]["text"] == "The kite string snapped in the wind."
        assert "on_mind" not in c.get("/memory", headers={"Host": "pip.example.org"}).json()


@pytest.mark.asyncio
async def test_in_a_talk_one_memory_of_her_comes_to_mind(tmp_path):
    from app.llm.base import LLMResponse, ToolCall, Usage
    from app.llm.fake import FakeBackend
    s, st, gm, agent = on(tmp_path, work_speed=1e6)
    s.talk_scenes = "on"
    gm.script = [report(text="A low cottage humming with bees."), report(text="Pip! Come in."), report(text="Go well.", goodbye=True)]
    agent.tools.update({n: T.REGISTRY[n] for n in ("say", "go_to")})
    neighbor(st, s)
    st.log("letter_sent", to="Marigold", text="I hope the honey harvest went well, Marigold.")
    st.log("say", text="Your lavender smelled wonderful.", to="Marigold")
    st.db.execute("UPDATE memory_context SET ts = ts - ? WHERE people LIKE '%Marigold%'", (2 * DAY,))
    for i in range(31):
        st.log("tick_start")
    st.db.commit()
    await call(agent, "go_to", place="Marigold")
    time.sleep(0.01)
    await agent.finish_work()
    await nb.step(st, s, agent.gm, FixedRng(), time.time())
    agent.backend = FakeBackend([LLMResponse("", [ToolCall("s", "say", {"text": "Hello! How did the honey go?", "goodbye": True})], Usage(1, 1))])
    await agent.tick("event")
    p = agent.backend.calls[0]["messages"][0]["content"]
    block = p.split("This brings to mind:\n")[1].split("\nTalking with")[0]
    assert block.count("\n- ") == 0 and block.startswith("- ") and "Marigold" in block


# --- 8. edges ------------------------------------------------------------------------------------------------------------------------
def test_in_view_is_exactly_what_the_prompt_shows(tmp_path):
    from app import loop
    s, st, gm, agent = make(tmp_path)
    notes = {sec: [st.add_memory(f"{sec} {i}", sec) for i in range(12)] for sec in ("diary", "learned", "todo", "wishlist", "ambitions")}
    st.set_memory_status(notes["todo"][-1], "done")
    refl = {k: [st.add_reflection(k, f"{k} {i}", 5, 0, time.time()) for i in range(6)] for k in ("portrait", "day", "change", "turning")}
    for i in range(7):
        st.upsert_person(f"Person{i}", "x", time.time() + i)
    view = R.in_view(st)
    ids = lambda sec: {int(r) for s_, r in view if s_ == f"note:{sec}"}
    assert ids("diary") == set(notes["diary"][-loop.DIARY_SHOWN:]) and ids("learned") == set(notes["learned"][-loop.LEARNED_SHOWN:])
    for sec in ("wishlist", "ambitions"):
        assert ids(sec) == set(notes[sec][-loop.LIST_SHOWN:])
    assert ids("todo") == set(notes["todo"][-loop.LIST_SHOWN - 1:-1])
    got = lambda k: {int(r) for s_, r in view if s_ == k}
    assert got("portrait") == {refl["portrait"][-1]} and got("day") == set(refl["day"][-3:])
    assert got("change") == set(refl["change"][-2:]) and got("turning") == set(refl["turning"][-2:])
    assert {r for s_, r in view if s_ == "person"} == {f"Person{i}" for i in range(2, 7)}


def test_beliefs_and_hunches_on_show_are_in_view(tmp_path):
    s, st, gm, agent = make(tmp_path)
    loud = st.add_reflection("insight", "an important hunch", 10, 0, time.time(), grounded=False)
    top = [st.add_reflection("insight", f"belief {i}", 9, 0, time.time()) for i in range(5)]
    hunches = [st.add_reflection("insight", f"hunch {i}", 5, 0, time.time(), grounded=False) for i in range(2)]
    low = st.add_reflection("insight", "minor belief", 2, 0, time.time())
    got = {int(r) for s_, r in R.in_view(st) if s_ == "insight"}
    assert got == set(top) | set(hunches) and low not in got and loud not in got
    c = st.add_reflection("change", "grounded change", 5, 0, time.time())
    t = st.add_reflection("turning", "grounded day", 5, 0, time.time())
    nc = st.add_reflection("change", "ungrounded change", 5, 0, time.time(), grounded=False)
    nt = st.add_reflection("turning", "ungrounded day", 5, 0, time.time(), grounded=False)
    view = R.in_view(st)
    assert ("change", str(c)) in view and ("turning", str(t)) in view and ("change", str(nc)) not in view and ("turning", str(nt)) not in view


def test_backfill_details(tmp_path):
    s, st, gm, agent = make(tmp_path)
    a = st.log("inbox", id=1, text="first", sender="Travis")
    b = st.log("inbox", id=2, text="second", sender="Jo")
    rid = st.add_reflection("insight", "A thought.", 7, 0, time.time())
    st.db.execute("UPDATE events SET importance = 0 WHERE id = ?", (b,))
    st.db.execute("DELETE FROM memory_context WHERE NOT (source = 'event:inbox' AND ref = ?)", (str(a),))   # the first one keeps its context
    st.db.execute("UPDATE memory_context SET importance = 2 WHERE source = 'event:inbox' AND ref = ?", (str(a),))
    st.db.execute("INSERT INTO recall_index (text, source, ref, ts) VALUES ('gone', 'event:inbox', '9999', 1)")
    st.db.execute("INSERT INTO recall_index (text, source, ref, ts) VALUES ('gone', 'insight', '9999', 1)")
    st.db.execute("DELETE FROM meta WHERE key = 'memory_context'")
    st.db.commit()
    st2 = State(s)
    assert st2.memory_context("event:inbox", a)["importance"] == 2                   # kept, and the rest still filled in
    assert st2.memory_context("event:inbox", b)["importance"] == 3 and st2.memory_context("event:inbox", b)["people"] == ["Jo"]
    assert st2.memory_context("insight", rid)["importance"] == 7
    assert st2.memory_context("event:inbox", 9999)["importance"] == 3 and st2.memory_context("insight", 9999)["importance"] == 5
    assert st2.memory_context("note:todo", st2.add_memory("x", "todo"))["importance"] == 3
    assert st2.memory_context("person", "Nobody") is None and st2.recall_text_of("person", "Nobody") is None


def test_the_strongest_feeling_wins_and_ten_over_is_enough(tmp_path):
    from app.emotions import BASELINE, NOTABLE
    s, st, gm, agent = make(tmp_path)
    st.set_emotion("anger", BASELINE["anger"] + 30, time.time())
    st.set_emotion("trust", BASELINE["trust"] + 15, time.time())
    assert st.memory_context(*old_note(st, "a", "diary"))["feeling"] == "anger"
    st.set_emotion("anger", BASELINE["anger"], time.time())
    st.set_emotion("trust", BASELINE["trust"] + NOTABLE, time.time())
    assert st.memory_context(*old_note(st, "b", "diary"))["feeling"] == "trust"


def test_a_module_session_about_something_is_its_project(tmp_path):
    s, st, gm, agent = make(tmp_path)
    st.start_session(0, 0, 30, time.time() + 600, kind="module", target="crafting", expect="experimenting on Kite", about="Kite")
    assert st.memory_context(*old_note(st, "c", "diary"))["project"] == "Kite"
    c = R.cue(st, [], time.time())
    assert (c.project, c.words) == ("Kite", "experimenting on Kite")
    st.end_session()
    st.start_session(0, 0, 30, time.time() + 600, kind="module", target="reading", expect="reading A book")
    c = R.cue(st, [], time.time())
    assert st.memory_context(*old_note(st, "d", "diary"))["project"] is None and (c.project, c.words) == (None, "reading A book")
    st.end_session()
    st.start_session(0, 0, 30, time.time() + 600, kind="walk", target="woods")
    c = R.cue(st, [], time.time())
    assert st.memory_context(*old_note(st, "e", "diary"))["project"] is None and (c.project, c.words) == (None, "")


def test_the_cue_leaves_out_gift_givers(tmp_path):
    s, st, gm, agent = make(tmp_path)
    c = R.cue(st, [{"sender": "Jo", "text": "Jo gave you a kite", "gift": True}], time.time())
    assert c.people == [] and c.words == "Jo gave you a kite"


@pytest.mark.asyncio
async def test_the_cue_takes_only_her_latest_line_of_this_visit(tmp_path):
    s, st, gm, agent = make(tmp_path)
    ch = neighbor(st, s)
    st.log("companion", name="Marigold", text="Old words.", visit=True)
    st.set_meta(arrived_at=str(st.events(1)[0]["ts"]))
    assert R.cue(st, [], time.time(), ch).words == "Old words."                     # said at the moment of arrival counts
    st.log("companion", name="Marigold", text="Newer words.", visit=True)
    st.log("companion", name="Someone", text="Not hers.", visit=True)
    assert R.cue(st, [], time.time(), ch).words == "Newer words."
    st.set_meta(arrived_at=str(time.time() + 5))
    assert R.cue(st, [], time.time(), ch).words == ""




def test_the_place_and_project_bonus_needs_a_real_match(tmp_path):
    s, st, gm, agent = on(tmp_path)
    st.update_agent(location="woods")
    st.start_session(0, 0, 10, time.time() + 600, kind="walk", target="woods")
    k = old_note(st, "The fox den by the stream.", "diary")                           # written while walking: no place
    st.end_session()
    now = time.time() + 2 * DAY
    base = R.choose(st, s, R.Cue(words="fox den"), now, 2, set())[0][0]["score"]
    assert R.choose(st, s, R.Cue(project="Kite", words="fox den"), now, 2, set())[0][0]["score"] == base
    st.db.execute("UPDATE memory_context SET project = 'Kite' WHERE ref = ?", (k[1],))
    st.db.commit()
    assert R.choose(st, s, R.Cue(project="Kite", words="fox den"), now, 2, set())[0][0]["score"] == round(base + 0.5, 3)
    assert R.choose(st, s, R.Cue(project="Kite", words="nothing"), now, 2, set())[0][0]["ref"] == k[1]
    assert R.choose(st, s, R.Cue(project="Other", words="nothing"), now, 2, set()) == ([], [])


def test_the_edges_of_young_cooldown_and_the_bar(tmp_path, monkeypatch):
    s, st, gm, agent = on(tmp_path)
    k = old_note(st, "The kite string snapped in the wind.")
    ts = st.memory_context(*k)["ts"]
    c = R.Cue(words="kite string")
    assert R.choose(st, s, c, ts + 6 * 3600, 2, set())[0] != []                       # exactly six hours: no longer young
    st.mark_shown([k], ts + DAY, [])
    assert R.choose(st, s, c, ts + DAY + 12 * 3600, 2, set())[0] != []                # exactly the cooldown: free again
    assert R.choose(st, s, c, ts + DAY + 12 * 3600 - 1, 2, set())[0] == []
    (m,), _ = R.choose(st, s, c, ts + 3 * DAY, 2, set())
    monkeypatch.setattr(R, "REMIND_MIN", m["score"])
    assert R.choose(st, s, c, ts + 3 * DAY, 2, set())[0] != []                        # the bar itself is enough


def test_relevance_below_full_counts_in_part(tmp_path):
    s, st, gm, agent = on(tmp_path)
    for i in range(3):
        old_note(st, f"Kite day {i}: the kite flew and the kite string held, kite after kite.")
    k = old_note(st, "A long note that mentions a kite once among many other words about the garden, the gate and the weather today.")
    r = rel(st, "kite", k)
    assert 0 < r < 1
    got = [m for m in R.choose(st, s, R.Cue(words="kite"), time.time() + 2 * DAY, 9, set())[0] + R.choose(st, s, R.Cue(words="kite"), time.time() + 2 * DAY, 9, set())[1]
           if m["ref"] == k[1]]
    ctx = st.memory_context(*k)
    act = 1 / (1 + math.exp(-R.activation(ctx["uses"], time.time() + 2 * DAY)))
    assert got and abs(got[0]["score"] - (r + 0.3 + act)) < 0.01


def test_a_thought_counts_as_taking_a_reminder_up_but_three_words_are_needed(tmp_path):
    s, st, gm, agent = on(tmp_path)
    k = old_note(st, "Ask Travis about the brass wire for the clock.")
    now = time.time() + 3 * DAY
    assert R.step(st, s, R.Cue(words="brass wire"), now, 2)
    st.log("tick", text="Travis might have brass wire.")
    st.log("tool", tool="eat", args={"item": "apple"}, result="ok")
    assert R.taken_up(st, now + 60) == [k]
    k2 = old_note(st, "Paint the brass gate green.")
    later = now + DAY
    assert R.step(st, s, R.Cue(words="gate green"), later, 2)
    st.log("tool", tool="note_to_self", args={"text": "The gate could be green."}, result="ok")
    assert R.taken_up(st, later + 60) == []                                           # two words is not enough


def test_taking_up_only_looks_after_the_reminder(tmp_path):
    s, st, gm, agent = on(tmp_path)
    st.log("tool", tool="note_to_self", args={"text": "Ask Travis about brass wire for the clock."}, result="ok")
    k = old_note(st, "Ask Travis about the brass wire for the clock.")
    now = time.time() + 3 * DAY
    assert R.step(st, s, R.Cue(words="brass wire"), now, 2)
    st.log("tool", tool="eat", args={"item": "apple"}, result="ok")
    assert R.taken_up(st, now + 60) == []


def test_backfilled_notes_people_and_everything_listed(tmp_path):
    s, st, gm, agent = make(tmp_path)
    t = st.add_memory("A plain to-do.", "todo")
    st.upsert_person("Jo", "Friendly.", time.time())
    st.db.execute("DELETE FROM memory_context")
    st.db.execute("DELETE FROM meta WHERE key = 'memory_context'")
    st.db.commit()
    st2 = State(s)
    assert st2.memory_context("note:todo", t)["importance"] == 3 and st2.memory_context("person", "Jo")["importance"] == 5
    st2.set_faded([("note:todo", t)])
    assert len(st2.memory_contexts()) == 2 and [c["ref"] for c in st2.memory_contexts(faded=True)] == [str(t)]
    assert [c["ref"] for c in st2.memory_contexts(faded=False)] == ["Jo"]


def test_who_a_memory_is_about(tmp_path):
    s, st, gm, agent = make(tmp_path)
    assert st.memory_context("event:companion", st.log("companion", name="Wren", text="Shiny!"))["people"] == ["Wren"]
    assert st.memory_context("event:heard_of_place", st.log("heard_of_place", by="Jo", place="Brygdon", there="a market"))["people"] == ["Jo"]
    assert st.memory_context("event:inbox", st.log("inbox", id=1, text="hi", sender="A visitor"))["people"] == []


def test_when_switches_to_the_weekday_from_two_days_to_a_week():
    assert R.when(1000.0, 1000.0 + 86400) == "yesterday"
    assert R.when(1000.0, 1000.0 + 2 * 86400).startswith("on ")
    assert R.when(1000.0, 1000.0 + 2 * 86400 - 1) == "2 days ago"
    assert R.when(1000.0, 1000.0 + 7 * 86400) == "7 days ago"


def test_the_frame_clips_long_memories_at_260():
    t = "x" * 260
    assert R.frame("note:todo", t, None, 0).endswith(": " + t)
    assert not R.frame("note:todo", t + "y", None, 0).endswith("y")


def test_recall_lines_join_hits_and_their_evidence(tmp_path):
    s, st, gm, agent = make(tmp_path)
    a = old_note(st, "First thing.", "diary")
    b = old_note(st, "Second thing.", "diary")
    hits = [{"source": a[0], "ref": a[1], "text": "First thing."}, {"source": b[0], "ref": b[1], "text": "Second thing."}]
    out = R.recall_lines(st, hits, {(a[0], a[1]): ["one", "two"]}, time.time())
    assert out.split("\n")[1] == "    because: one; two" and out.split("\n")[2].endswith("(diary): Second thing.")


def test_a_cue_has_both_the_visitors_words_and_hers(tmp_path):
    s, st, gm, agent = make(tmp_path)
    ch = neighbor(st, s)
    st.set_meta(arrived_at=str(time.time() - 5))
    st.log("companion", name="Marigold", text="Bees today.", visit=True)
    assert R.cue(st, [{"sender": "Travis", "text": "How are you?"}], time.time(), ch).words == "How are you? Bees today."


def test_the_best_match_left_out_does_not_stop_the_next(tmp_path):
    s, st, gm, agent = on(tmp_path)
    a = old_note(st, "The kite string snapped, the kite string!")
    b = old_note(st, "A kite in the tree.", "diary")
    now = time.time() + 2 * DAY
    w, _ = R.choose(st, s, R.Cue(words="kite string"), now, 2, {a})
    assert [m["ref"] for m in w] == [b[1]]
    st.set_faded([a])
    assert [m["ref"] for m in R.choose(st, s, R.Cue(words="kite string"), now, 2, set())[0]] == [b[1]]
    st.db.execute("UPDATE memory_context SET faded = 0")
    st.mark_shown([a], now, [])
    assert [m["ref"] for m in R.choose(st, s, R.Cue(words="kite string"), now + 60, 2, set())[0]] == [b[1]]
    c = old_note(st, "Another kite string note.")
    assert len(R.choose(st, s, R.Cue(words="kite string"), now + DAY, 3, set())[0]) == 2   # one per source, however many slots


def test_fading_is_checked_at_most_hourly_from_the_last_check(tmp_path):
    s, st, gm, agent = make(tmp_path)
    old_note(st, "Something from today.")
    t0 = time.time() + 30 * DAY
    assert R.fade(st, t0) != []                                                       # everything from today has faded by now
    def stale(ref):
        st.db.execute("INSERT INTO memory_context (source, ref, ts, uses) VALUES ('note:todo', ?, 0, ?)", (ref, json.dumps([0.0])))
        st.db.commit()
    stale("a")
    assert R.fade(st, t0 + 60) == []
    assert R.fade(st, t0 + 3600) == [("note:todo", "a")]
    for i in range(25):
        stale(f"b{i}")
    R.fade(st, t0 + 7200)
    ev = [e["data"] for e in st.events(5) if e["kind"] == "faded"][0]
    assert ev["count"] == 25 and len(ev["memories"]) == 20


def test_a_turn_with_no_slots_logs_nothing(tmp_path):
    s, st, gm, agent = on(tmp_path)
    old_note(st, "The kite string snapped in the wind.")
    n = len(st.events(500))
    assert R.step(st, s, R.Cue(words="kite"), time.time() + 3 * DAY, 0) == [] and len(st.events(500)) == n


def test_the_reminded_event_and_the_cooldown_remember_the_cue(tmp_path):
    s, st, gm, agent = on(tmp_path)
    eid = st.log("inbox", id=1, text="The kite string snapped: " + "a" * 130, sender="Travis")
    for i in range(31):
        st.log("tick_start")
    now = time.time() + 3 * DAY
    assert R.step(st, s, R.Cue(people=["Travis"], words="kite"), now, 2)
    ev = [e["data"] for e in st.events(5) if e["kind"] == "reminded"][0]
    assert set(ev["shown"][0]) == {"source", "ref", "score", "text"} and len(ev["shown"][0]["text"]) <= 120
    assert ev["cue"] == ["Travis"] and st.memory_context("event:inbox", eid)["shown_with"] == ["Travis"]
    assert R.choose(st, s, R.Cue(people=["Travis"], words="kite"), now + 60, 2, set())[0] == []


def test_taking_up_is_counted_at_the_turns_own_time(tmp_path):
    s, st, gm, agent = on(tmp_path)
    k = old_note(st, "Ask Travis about the brass wire for the clock.")
    now = time.time() + 3 * DAY
    R.step(st, s, R.Cue(words="brass wire"), now, 2)
    st.log("tool", tool="note_to_self", args={"text": "Ask Travis about brass wire for the clock"}, result="ok")
    R.step(st, s, R.Cue(words="nothing"), now + 600, 2)
    assert st.memory_context(*k)["uses"][-1] == now + 600
