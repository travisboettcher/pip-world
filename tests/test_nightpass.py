import time

import pytest

from app import nightpass as N
from tests.test_memory import visit
from app import modules as M
from app import projects as proj
from tests.test_projects import PIP_STEPS, PLAN, call, given, make, report

DAY = 86400


def note(st, text, section="todo", age_days=5, edited_days_ago=None):
    i = st.add_memory(text, section)
    st.db.execute("UPDATE memories SET ts = ?, edited_at = ? WHERE id = ?",
                  (time.time() - age_days * DAY, time.time() - edited_days_ago * DAY if edited_days_ago else None, i))
    st.db.commit()
    return i


def facts(st, s):
    return N.facts(st, s, time.time())


def check(st, s, ops, shown=None):
    return N.validate(st, s, ops, facts(st, s), shown or {}, time.time())


async def statuses(st, s):
    """The crafting module's projects once it has taken its next step (where the night pass's requests are done): {id: status}."""
    await M.step(st, s, M.LocalRunner())
    return {p["id"]: p["status"] for p in proj.published(st)["projects"]}


STAGE = [{"name": "cut", "minutes": 60}]


def test_a_decision_needs_a_known_op_real_citations_and_age(tmp_path):
    s, st, *_ = make(tmp_path, night_pass="apply")
    old, new = note(st, "Find brass wire for the clock", age_days=5), note(st, "Oil the hinges tomorrow", age_days=0.1)
    fresh_edit = note(st, "Sand the frame smooth with fine paper", age_days=9, edited_days_ago=0.2)
    ok, rej = check(st, s, [
        {"op": "archive_note", "id": old, "because": [f"n{old}"], "reason": "outgrown"},
        {"op": "archive_note", "id": new, "because": [f"n{new}"]},                  # too new
        {"op": "archive_note", "id": fresh_edit, "because": [f"n{fresh_edit}"]},    # edited in the last day
        {"op": "archive_note", "id": old, "because": []},                           # nothing cited
        {"op": "archive_note", "id": old, "because": ["e999", "n99999"]},          # citations that point at nothing
        {"op": "delete_everything", "because": ["n1"]},                            # not in the vocabulary
        "junk"])
    assert [o["summary"] for o in ok] == [f"archived your todo #{old} (Find brass wire for the clock)"]
    assert any("too new" in r for r in rej) and any("edited in the last day" in r for r in rej)
    assert sum("nothing cited" in r for r in rej) == 2 and any("unknown decision" in r for r in rej)


async def test_resolve_merge_pause_resume_adopt_rules(tmp_path):
    s, st, *_ = make(tmp_path, night_pass="apply", max_active_projects=2, max_night_ops=5)
    a, b = note(st, "Ask Morgan for tomato seeds next visit", age_days=4), note(st, "Ask Morgan for seeds at his visit", age_days=4)
    wish = note(st, "A tiny file", "wishlist", age_days=1)                           # wishes need 3 days
    m = await given(st, {"name": "clock", "stages": STAGE}, {"name": "kite", "craft": "kitemaking", "status": "paused", "stages": STAGE})
    p1, p2 = 1, 2
    cites = [f"n{a}"]
    ok, rej = check(st, s, [
        {"op": "resolve_note", "id": a, "outcome": "", "because": cites},                       # no outcome
        {"op": "merge_notes", "ids": [a, b], "text": "Ask Morgan for tomato seeds", "because": cites},
        {"op": "merge_notes", "ids": [a, wish], "text": "x", "because": cites},                 # two sections
        {"op": "archive_note", "id": wish, "because": [f"n{wish}"]},                            # wish too new
        {"op": "pause_project", "id": p1, "because": [f"p{p1}"], "reason": "idle"},
        {"op": "resume_project", "id": p2, "because": [f"p{p2}"]},
        {"op": "adopt", "section": "ambitions", "text": "Build a clock that keeps true time", "because": cites},
        {"op": "adopt", "section": "todo", "text": "Ask Morgan for tomato seeds again soon", "because": cites}])  # second adopt / overlaps
    assert [o["op"] for o in ok] == ["merge_notes", "pause_project", "resume_project", "adopt"]
    assert len(rej) == 4
    st.update_module(m["id"], facts={**m["facts"], "project_limit": 1})              # now resuming would exceed the limit
    ok, rej = check(st, s, [{"op": "resume_project", "id": p2, "because": [f"p{p2}"]}])
    assert ok == [] and "too many projects going" in rej[0]


def test_the_cap_limits_a_nights_decisions(tmp_path):
    s, st, *_ = make(tmp_path, night_pass="apply", max_night_ops=2)
    ids = [note(st, f"unique old task number {n} about {w}", age_days=6) for n, w in enumerate(["bees", "kites", "soup", "paint"])]
    ok, rej = check(st, s, [{"op": "archive_note", "id": i, "because": [f"n{i}"]} for i in ids])
    assert len(ok) == 2 and "more decisions than allowed" in rej[0]


async def test_every_decision_can_be_undone(tmp_path):
    s, st, *_ = make(tmp_path, night_pass="apply", max_active_projects=3)
    a, b = note(st, "Ask Morgan for tomato seeds next visit", age_days=4), note(st, "Ask Morgan for seeds at his visit", age_days=4)
    c = note(st, "Check the pendulum swing", age_days=4)
    await given(st, {"name": "clock", "stages": STAGE})
    p = 1
    ops, _ = check(st, s, [
        {"op": "merge_notes", "ids": [a, b], "text": "Ask Morgan for tomato seeds", "because": [f"n{a}"]},
        {"op": "resolve_note", "id": c, "outcome": "it swings true", "because": [f"n{c}"]},
        {"op": "pause_project", "id": p, "because": [f"p{p}"]}])
    ids = [N.apply(st, s, o) for o in ops]
    assert st.memory(a)["text"] == "Ask Morgan for tomato seeds" and st.memory(b)["status"] == "archived"
    assert st.memory(c)["status"] == "done" and await statuses(st, s) == {p: "paused"}
    for i in ids:
        assert N.undo(st, s, i).startswith("undone")
    assert (st.memory(a)["text"], st.memory(b)["status"], st.memory(c)["status"], st.memory(c)["outcome"],
            await statuses(st, s)) == ("Ask Morgan for tomato seeds next visit", "open", "open", "", {p: "active"})
    assert "already undone" in N.undo(st, s, ids[0]) and "no decision" in N.undo(st, s, 999)
    new_ops, _ = check(st, s, [{"op": "adopt", "section": "ambitions", "text": "Make a clock that never needs winding", "because": [f"n{a}"]}])
    d = N.apply(st, s, new_ops[0])
    assert st.memories("ambitions")[0]["text"].startswith("Make a clock") and N.undo(st, s, d).startswith("undone")
    assert st.memories("ambitions") == []


def pass_script(decisions=(), focus=(), review=()):
    return [report(summary="A day.", people=[], insights=[], **{"self": "Pip."}),
            report(decisions=list(decisions), focus=list(focus), review=list(review))]


@pytest.mark.asyncio
async def test_apply_mode_changes_goals_announces_them_and_sets_a_focus(tmp_path):
    s, st, gm, agent = make(tmp_path, night_pass="apply", verify_insights=False)
    visit(st, "hello")
    old = note(st, "Find brass wire for the clock", age_days=6)
    await given(st, {"name": "clock", "stages": STAGE})
    p = 1
    gm.queue(*pass_script(
        decisions=[{"op": "archive_note", "id": old, "because": [f"n{old}"], "reason": "I have wire now"}],
        focus=[{"text": "finish the clock frame", "ref": f"p{p}"}, {"text": "write to Briar"}]))
    await agent.reflect()
    assert st.memory(old)["status"] == "archived"
    (d,) = st.decisions(5)
    assert d["applied"] == 1 and d["reason"] == "I have wire now" and d["cites"] == [f"n{old}"]
    assert [(f["text"], f["ref_kind"], f["ref_id"]) for f in st.focus("open")] == [
        ("finish the clock frame", "project", p), ("write to Briar", "", None)]
    task = gm.calls[1]["messages"][0]["content"]
    assert f"[n{old}] (todo, written" in task and f"[p{p}] clock (active)" in task and "An unmet wish is not a reason" in task
    ev = [e for e in st.events(20) if e["kind"] == "night_pass"][0]["data"]
    assert ev["applied"] == 1 and ev["decisions"] == [d["summary"]]
    pc = agent._perception("timer", [])
    assert f"While you slept you decided (undo_decision takes any of it back):\n- #{d['id']}: archived your todo #{old}" in pc
    assert "Your focus today (you chose it in your sleep):\n- finish the clock frame\n- write to Briar" in pc
    assert "the first time you changed your plans in your sleep" in pc
    r = await call(agent, "undo_decision", id=d["id"])
    assert r.text.startswith("undone") and st.memory(old)["status"] == "open"
    assert "While you slept you decided" not in agent._perception("timer", [])


@pytest.mark.asyncio
async def test_log_mode_records_but_changes_nothing(tmp_path):
    s, st, gm, agent = make(tmp_path, night_pass="log", verify_insights=False)
    visit(st, "hello")
    old = note(st, "Find brass wire for the clock", age_days=6)
    gm.queue(*pass_script(decisions=[{"op": "archive_note", "id": old, "because": [f"n{old}"], "reason": "r"}],
                          focus=[{"text": "something"}]))
    await agent.reflect()
    assert st.memory(old)["status"] == "open" and st.focus("open") == []
    (d,) = st.decisions(5)
    assert d["applied"] == 0 and "While you slept" not in agent._perception("timer", [])
    assert [e for e in st.events(20) if e["kind"] == "night_pass"][0]["data"]["applied"] == 0


@pytest.mark.asyncio
async def test_off_makes_no_second_call_and_a_pass_is_not_repeated_within_hours(tmp_path):
    s, st, gm, agent = make(tmp_path, night_pass="off", verify_insights=False)
    visit(st, "hello")
    note(st, "Find brass wire", age_days=6)
    gm.queue(pass_script()[0])
    await agent.reflect()
    assert len(gm.calls) == 1
    s.night_pass = "apply"
    visit(st, "again")
    gm.queue(*pass_script())
    await agent.reflect()
    assert len(gm.calls) == 3                       # reflection + pass
    visit(st, "and again")
    gm.queue(*pass_script())
    await agent.reflect()
    assert len(gm.calls) == 4                       # the reflection ran, but the pass waited (6 h between passes)


@pytest.mark.asyncio
async def test_focus_is_reviewed_deterministically_then_by_pip_and_counted(tmp_path):
    s, st, gm, agent = make(tmp_path, night_pass="apply", verify_insights=False)
    visit(st, "hello")
    done_note, stale_note = note(st, "Mend the sieve", age_days=2), note(st, "Whittle a spoon", age_days=2)
    st.add_focus("2026-11-01", "mend the sieve", "note", done_note)
    st.add_focus("2026-11-01", "whittle a spoon", "note", stale_note)
    st.add_focus("2026-11-01", "think about birds")
    st.resolve_memory(done_note, "mended")
    leftover_ids = [f["id"] for f in st.focus("open")][1:]
    gm.queue(*pass_script(review=[{"id": leftover_ids[0], "status": "carried", "reason": "still want it"}],
                          focus=[{"text": "whittle a spoon", "ref": f"n{stale_note}"}]))
    await agent.reflect()
    by_text = {f["text"]: f for f in st.focus(None)}
    assert by_text["mend the sieve"]["status"] == "kept"
    assert by_text["whittle a spoon"]["status"] == "carried" or by_text["whittle a spoon"]["status"] == "open"
    assert by_text["think about birds"]["status"] == "dropped" and by_text["think about birds"]["note"] == "not reviewed"
    ((day, stats),) = st.day_stats(3)
    assert stats["focus_kept"] == 1 and stats["focus_total"] == 3
    assert "[f%d] whittle a spoon" % leftover_ids[0] in gm.calls[1]["messages"][0]["content"]


@pytest.mark.asyncio
async def test_unsupported_decisions_are_dropped_by_the_support_check(tmp_path):
    s, st, gm, agent = make(tmp_path, night_pass="apply", verify_insights=True)
    visit(st, "hello")
    old = note(st, "Find brass wire for the clock", age_days=6)
    gm.queue(*pass_script(decisions=[{"op": "archive_note", "id": old, "because": [f"n{old}"], "reason": "sure"}]),
             report(verdicts=[{"index": 0, "verdict": "unsupported"}]))   # the reflection has no insights, so only the pass is checked
    await agent.reflect()
    assert st.memory(old)["status"] == "open" and st.decisions(5) == []
    ev = [e for e in st.events(20) if e["kind"] == "night_pass"][0]["data"]
    assert any("evidence doesn't show it" in r for r in ev["rejected"])


@pytest.mark.asyncio
async def test_paused_projects_leave_the_active_list_and_can_be_resumed(tmp_path):
    s, st, gm, agent = make(tmp_path, [report(**PLAN)], work_speed=10**6)
    st.add_item("brass wire", 4, "material")
    await call(agent, "start_project", name="gear clock", steps=PIP_STEPS)
    M.queue_request(st, "crafting", "pause", {"project": "#1"}, by="night pass")
    assert await statuses(st, s) == {1: "paused"}
    assert "On hold (resume_project to pick one back up): gear clock" in agent._perception("timer", [])
    assert "error" in (await call(agent, "work_on", project="gear clock")).text
    r = await call(agent, "resume_project", project="gear clock")
    assert r.text == "you pick gear clock back up" and proj.published(st)["projects"][0]["status"] == "active"


async def test_resuming_is_asked_of_the_crafting_module_and_undone_by_pausing(tmp_path):
    s, st, *_ = make(tmp_path, night_pass="apply", max_active_projects=2)
    await given(st, {"name": "clock", "stages": STAGE}, {"name": "kite", "status": "paused", "stages": STAGE})
    ops, _ = check(st, s, [{"op": "resume_project", "id": 2, "because": ["p2"]}])
    d = N.apply(st, s, ops[0])
    asked = M.live_named(st, "crafting")["requests"]
    assert [(r["what"], r["args"], r["from"]) for r in asked] == [("resume", {"project": "#2"}, "night pass")] and asked[0]["ts"] > 0
    assert st.decision(d)["before"] == {"status": "paused"} and await statuses(st, s) == {1: "active", 2: "active"}
    assert N.undo(st, s, d).startswith("undone")
    assert [(r["what"], r["args"], r["from"]) for r in M.live_named(st, "crafting")["requests"]] == [("pause", {"project": "#2"}, "night pass")]
    assert await statuses(st, s) == {1: "active", 2: "paused"}


async def test_a_pause_is_undone_only_with_room_for_the_project(tmp_path):
    s, st, *_ = make(tmp_path, night_pass="apply", max_active_projects=2)
    m = await given(st, {"name": "clock", "stages": STAGE}, {"name": "kite", "stages": STAGE}, {"name": "lamp", "status": "paused", "stages": STAGE})
    ops, _ = check(st, s, [{"op": "pause_project", "id": 1, "because": ["p1"]}])
    d = N.apply(st, s, ops[0])
    assert st.decision(d)["before"] == {"status": "active"} and M.live_named(st, "crafting")["requests"][0]["from"] == "night pass"
    assert await statuses(st, s) == {1: "paused", 2: "active", 3: "paused"}
    m = M.live_named(st, "crafting")
    st.update_module(m["id"], facts={**m["facts"], "project_limit": 1})               # one going is as many as there is room for now
    assert N.undo(st, s, d) == "you already have as many projects going as you can; finish or pause one first"
    st.update_module(m["id"], facts={**m["facts"], "project_limit": 2})                # one going, two on hold: room for one more
    assert N.undo(st, s, d).startswith("undone")
    assert [(r["what"], r["args"], r["from"]) for r in M.live_named(st, "crafting")["requests"]] == [("resume", {"project": "#1"}, "night pass")]
    assert await statuses(st, s) == {1: "active", 2: "active", 3: "paused"}


async def test_the_pass_sees_projects_going_and_on_hold_but_not_finished_ones(tmp_path):
    s, st, *_ = make(tmp_path, night_pass="apply")
    await given(st, {"name": "clock", "stages": STAGE}, {"name": "kite", "status": "paused", "stages": STAGE},
                {"name": "lamp", "status": "done", "stages": STAGE})
    f = facts(st, s)
    assert set(f["projects"]) == {1, 2} and [line.split(":")[0] for line in f["project_lines"]] == ["[p1] clock (active)", "[p2] kite (paused)"]


async def test_without_a_crafting_module_there_is_no_room_for_a_project(tmp_path):
    s, st, *_ = make(tmp_path, night_pass="apply")
    assert N._limit(st) == 0 and N._projects(st) == {} and N._last_worked({}) == 0.0
    await given(st, {"name": "kite", "status": "paused", "stages": STAGE})
    assert N._limit(st) == s.max_active_projects
    m = M.live_named(st, "crafting")
    st.update_module(m["id"], facts={**m["facts"], "project_limit": "3"})
    assert N._limit(st) == 0


async def test_last_nights_focus_on_a_project_is_kept_when_it_was_worked_on_or_finished(tmp_path):
    s, st, *_ = make(tmp_path, night_pass="apply")
    now = time.time()
    worked = [{"ts": now + 100, "stage": "cut", "result": "good", "minutes": 15, "text": "t"}]
    before = [{"ts": now - 100, "stage": "cut", "result": "good", "minutes": 15, "text": "t"}]
    await given(st, {"name": "clock", "stages": STAGE, "history": worked}, {"name": "lamp", "status": "done", "stages": STAGE, "history": before},
                {"name": "kite", "stages": STAGE, "history": before})
    for ref in (1, 2, 3, 99):
        st.add_focus("today", f"work on #{ref}", "project", ref)
    left, kept = N.review_focus(st, now)
    assert kept == 2 and [f["ref_id"] for f in left] == [3, 99]
    assert {f["ref_id"]: f["status"] for f in st.focus(None)} == {1: "kept", 2: "kept", 3: "open", 99: "open"}


async def test_an_active_project_left_alone_is_noticed_but_not_one_on_hold(tmp_path):
    s, st, *_ = make(tmp_path, night_pass="apply")
    old = [{"ts": time.time() - 30 * DAY, "stage": "cut", "result": "good", "minutes": 15, "text": "t"}]
    await given(st, {"name": "clock", "stages": STAGE, "history": old}, {"name": "kite", "status": "paused", "stages": STAGE, "history": old},
                {"name": "lamp", "stages": STAGE})
    assert facts(st, s)["quiet"] == ["you haven't worked on clock for 30 days"]
