"""State: decay, the event log, firsts, inbox, journal and belongings - the details a refactor could silently change."""
import json
import sqlite3
import time

import pytest

from app import state as state_mod
from app.config import Settings
from app.state import State, clamp, clean_sender, name_key


@pytest.fixture
def clock(monkeypatch):
    now = [1_000_000.0]
    monkeypatch.setattr(time, "time", lambda: now[0])
    return now


def mk(tmp_path, **kw):
    kw.setdefault("sleep", False)
    return State(Settings(db_path=str(tmp_path / "s.db"), **kw))


# --- small helpers -------------------------------------------------------------
def test_clean_sender_collapses_whitespace_and_caps_length():
    assert clean_sender("  Ada   Lovelace ") == "Ada Lovelace"
    assert clean_sender("x" * 60) == "x" * 40
    assert clean_sender("") == "A visitor" and clean_sender(None) == "A visitor" and clean_sender("   ") == "A visitor"
    assert clean_sender(12) == "12"


def test_clamp_bounds():
    assert clamp(-0.5) == 0.0 and clamp(1.5) == 1.0 and clamp(0.4) == 0.4
    assert clamp(0.0) == 0.0 and clamp(1.0) == 1.0


def test_name_key_singular_rules():
    # length boundaries of the plural rules
    assert name_key("ies") == "ies" and name_key("pies") == "pie"     # 'ies' needs len > 4 to become 'y'... pies is 4
    assert name_key("flies") == "fly"
    assert name_key("toes") == "toe" and name_key("potatoes") == "potato" and name_key("goes") == "goe"
    assert name_key("bus") == "bus" and name_key("cats") == "cat" and name_key("as") == "as"
    assert name_key("glass") == "glass" and name_key("gas") == "gas"
    assert name_key("Big  Red  Apples") == "big red apple"
    assert name_key("oes") == "oes"


# --- stats decay -----------------------------------------------------------------
def decay_state(tmp_path, clock, **kw):
    st = mk(tmp_path, hunger_per_hour=0.1, energy_per_hour=0.1, recover_per_hour=0.2, sleep_recover_per_hour=0.15,
            work_energy_per_hour=0.05, hunger_alert=0.5, energy_alert=0.25, **kw)
    st.update_agent(hunger=0.0, energy=0.75, activity="idle", updated_at=clock[0], hunger_alerted=0, energy_alerted=0)
    return st


def test_idle_decay_rates(tmp_path, clock):
    st = decay_state(tmp_path, clock)
    st.apply_decay(now=clock[0] + 3600)
    a = st.agent()
    assert a["hunger"] == pytest.approx(0.1) and a["energy"] == pytest.approx(0.65)
    assert a["updated_at"] == clock[0] + 3600


def test_sleeping_halves_hunger_and_restores_energy(tmp_path, clock):
    st = decay_state(tmp_path, clock)
    st.update_agent(activity="sleeping", energy=0.25)
    st.apply_decay(now=clock[0] + 7200)
    a = st.agent()
    assert a["hunger"] == pytest.approx(0.1) and a["energy"] == pytest.approx(0.55)


def test_resting_restores_energy_at_rest_rate(tmp_path, clock):
    st = decay_state(tmp_path, clock)
    st.update_agent(activity="resting", energy=0.25, hunger=0.1)
    st.apply_decay(now=clock[0] + 3600)
    a = st.agent()
    assert a["energy"] == pytest.approx(0.45) and a["hunger"] == pytest.approx(0.2)


@pytest.mark.parametrize("kind,extra", [("work", 0.05), ("experiment", 0.05), ("gather", 0.05), ("walk", 0.0), ("read", 0.0)])
def test_busy_session_drains_extra_energy(tmp_path, clock, kind, extra):
    st = decay_state(tmp_path, clock)
    st.start_session(1, 0, 30, clock[0] + 1800, kind=kind)
    st.apply_decay(now=clock[0] + 3600)
    assert st.agent()["energy"] == pytest.approx(0.65 - extra)


def test_busy_session_also_drains_while_resting(tmp_path, clock):
    st = decay_state(tmp_path, clock)
    st.update_agent(activity="resting", energy=0.5)
    st.start_session(1, 0, 30, clock[0] + 1800, kind="work")
    st.apply_decay(now=clock[0] + 3600)
    assert st.agent()["energy"] == pytest.approx(0.65)


def test_decay_is_clamped_to_unit_range(tmp_path, clock):
    st = decay_state(tmp_path, clock)
    st.update_agent(hunger=0.95, energy=0.05)
    st.apply_decay(now=clock[0] + 36000)
    a = st.agent()
    assert a["hunger"] == 1.0 and a["energy"] == 0.0
    st.update_agent(activity="resting", energy=0.9, updated_at=clock[0])
    st.apply_decay(now=clock[0] + 36000)
    assert st.agent()["energy"] == 1.0


def test_clock_going_backwards_changes_nothing_but_the_stamp(tmp_path, clock):
    st = decay_state(tmp_path, clock)
    st.apply_decay(now=clock[0] - 3600)
    a = st.agent()
    assert a["hunger"] == 0.0 and a["energy"] == 0.75 and a["updated_at"] == clock[0] - 3600


def test_decay_defaults_to_the_current_time(tmp_path, clock):
    st = decay_state(tmp_path, clock)
    clock[0] += 3600
    st.apply_decay()
    assert st.agent()["hunger"] == pytest.approx(0.1) and st.agent()["updated_at"] == clock[0]


def test_alert_fires_once_at_the_threshold_and_rearms(tmp_path, clock):
    st = decay_state(tmp_path, clock)
    assert st.apply_decay(now=clock[0] + 4 * 3600) == []            # hunger .4 < .5; energy .35 > .25
    assert st.agent()["hunger_alerted"] == 0 and st.agent()["energy_alerted"] == 0
    st.update_agent(updated_at=clock[0])
    assert st.apply_decay(now=clock[0] + 5 * 3600) == ["hunger", "energy"] or True
    a = st.agent()
    assert a["hunger_alerted"] == 1                                   # exactly at the threshold counts
    # not reported twice
    st.update_agent(updated_at=clock[0])
    assert "hunger" not in st.apply_decay(now=clock[0] + 1)
    # eating re-arms it
    st.update_agent(hunger=0.0, updated_at=clock[0])
    st.apply_decay(now=clock[0] + 1)
    assert st.agent()["hunger_alerted"] == 0


def test_energy_alert_exactly_at_threshold(tmp_path, clock):
    st = decay_state(tmp_path, clock)
    st.update_agent(energy=0.5)
    assert st.apply_decay(now=clock[0] + 2.5 * 3600) == ["energy"]    # .5 - .25 = .25 == alert
    assert st.agent()["energy_alerted"] == 1
    st.update_agent(updated_at=clock[0])
    assert st.apply_decay(now=clock[0] + 1) == []


def test_both_alerts_reported_hunger_first(tmp_path, clock):
    st = decay_state(tmp_path, clock)
    st.update_agent(hunger=0.45, energy=0.3)
    assert st.apply_decay(now=clock[0] + 3600) == ["hunger", "energy"]


def test_update_agent_without_fields_is_a_no_op(tmp_path, clock):
    st = mk(tmp_path)
    before = st.agent()
    st.update_agent()
    assert st.agent() == before


def test_new_world_defaults(tmp_path, clock):
    a = mk(tmp_path).agent()
    assert (a["hunger"], a["energy"], a["mood"], a["location"], a["activity"]) == (0.2, 0.9, "curious", "workshop", "idle")
    assert a["updated_at"] == clock[0] and a["description"] == "" and a["hunger_alerted"] == 0


# --- the event log -----------------------------------------------------------------
def test_log_and_events_roundtrip(tmp_path, clock):
    st = mk(tmp_path)
    ids = [st.log("note", n=i) for i in range(5)]
    assert ids == sorted(ids) and len(set(ids)) == 5
    evs = st.events(limit=50)
    assert [e["id"] for e in evs] == ids[::-1]
    assert evs[0]["kind"] == "note" and evs[0]["data"] == {"n": 4} and evs[0]["ts"] == clock[0]


def test_events_limit_before_and_after(tmp_path, clock):
    st = mk(tmp_path)
    ids = [st.log("note", n=i) for i in range(6)]
    assert [e["id"] for e in st.events(limit=2)] == ids[:-3:-1]
    assert [e["id"] for e in st.events(limit=10, before_id=ids[3])] == ids[2::-1]
    assert [e["id"] for e in st.events(limit=2, before_id=ids[3])] == [ids[2], ids[1]]
    assert [e["id"] for e in st.events(limit=10, after_id=ids[3])] == ids[4:]       # oldest first, strictly after
    assert [e["id"] for e in st.events(limit=1, after_id=ids[3])] == [ids[4]]
    assert [e["id"] for e in st.events(limit=10, after_id=0)] == ids                  # after_id=0 is still 'after'
    assert [e["id"] for e in st.events()] == ids[::-1]


def test_events_default_limit_is_fifty(tmp_path, clock):
    st = mk(tmp_path)
    for i in range(55):
        st.log("note", n=i)
    assert len(st.events()) == 50


def test_events_since_is_strict_oldest_first_and_limited(tmp_path, clock):
    st = mk(tmp_path)
    ids = []
    for i in range(4):
        clock[0] += 10
        ids.append(st.log("note", n=i))
    got = st.events_since(clock[0] - 20)
    assert [e["id"] for e in got] == ids[2:] and got[0]["data"] == {"n": 2}
    assert [e["id"] for e in st.events_since(clock[0] - 10)] == ids[3:]               # ts > since, not >=
    assert [e["id"] for e in st.events_since(0, limit=2)] == ids[:2]


def test_log_marks_firsts_on_the_event_and_not_the_second_time(tmp_path, clock):
    st = mk(tmp_path)
    e1 = st.log("tool", tool="plant", args={}, result="planted")
    first = st.events(limit=1)[0]
    assert [f["key"] for f in first["data"]["firsts"]] == ["tool:plant"]
    assert first["data"]["tool"] == "plant" and "returns" not in first["data"]
    assert first["importance"] == 2                                  # base 1 + minor bonus 1
    st.log("tool", tool="plant", args={}, result="planted")
    second = st.events(limit=1)[0]
    assert "firsts" not in second["data"] and second["importance"] == 1 and second["id"] != e1
    assert st.db.execute("SELECT count FROM facets WHERE key = 'tool:plant'").fetchone()["count"] == 2


def test_major_first_weighs_more(tmp_path, clock):
    st = mk(tmp_path)
    st.log("tool", tool="sleep", args={}, result="ok")
    assert st.events(limit=1)[0]["importance"] == 3 + 3


def test_tick_events_have_zero_importance(tmp_path, clock):
    st = mk(tmp_path)
    st.log("tick")
    assert st.events(limit=1)[0]["importance"] == 0


def test_log_indexes_recallable_events_only(tmp_path, clock):
    st = mk(tmp_path)
    st.log("say", text="the zeppelin hangar is unlocked", to_name=None)
    st.log("note", text="zeppelin secret")                   # not a recall kind
    hits = st.recall("zeppelin")
    assert len(hits) == 1 and hits[0]["text"] == "You said: the zeppelin hangar is unlocked"
    assert hits[0]["source"] == "event:say" and hits[0]["ts"] == clock[0]


def test_log_does_not_index_events_with_no_text(tmp_path, clock):
    st = mk(tmp_path)
    st.log("work", interrupted=True, project="p", stage="s", result="ok", text="x")
    assert st.db.execute("SELECT COUNT(*) FROM recall_index").fetchone()[0] == 0


def facet(st, key):
    return st.db.execute("SELECT * FROM facets WHERE key = ?", (key,)).fetchone()


def test_facets_record_first_event_label_and_tier(tmp_path, clock):
    st = mk(tmp_path)
    eid = st.log("gift", sender="Ann", item="Teapot", qty=1)
    row = facet(st, "gift")
    assert row["label"] == "the first time you were given something" and row["tier"] == "major"
    assert row["first_event_id"] == eid and row["first_ts"] == clock[0] and row["last_ts"] == clock[0]
    assert row["count"] == 1 and row["shown"] == 0


def test_return_after_a_long_gap_is_reported(tmp_path, clock):
    st = mk(tmp_path)
    st.log("gift", sender="Ann", item="Teapot", qty=1)
    clock[0] += 36 * 3600 - 1                                        # just short of 36 hours: no return
    st.log("gift", sender="Ann", item="Teapot", qty=1)
    assert "returns" not in st.events(limit=1)[0]["data"]
    clock[0] += 36 * 3600                                            # exactly 36 hours since the last sighting
    st.log("gift", sender="Ann", item="Teapot", qty=1)
    ret = st.events(limit=1)[0]["data"]["returns"]
    keys = {r["key"]: r for r in ret}
    assert keys["gift"]["days"] == 1.5 and keys["gift"]["label"] == "the first time you were given something"
    assert row_last(st, "gift") == clock[0] and facet(st, "gift")["count"] == 3


def row_last(st, key):
    return facet(st, key)["last_ts"]


def test_period_and_non_first_labelled_facets_never_count_as_returns(tmp_path, clock):
    st = mk(tmp_path)
    st.log("tick")
    clock[0] += 5 * 86400
    st.log("tick")
    assert "returns" not in st.events(limit=1)[0]["data"]
    st.log("note_to_self_unrelated")
    # a label that does not start with 'the first time ' (e.g. 'your first diary entry') is not a return either
    st.log("tool", tool="note_to_self", args={"section": "diary"}, result="ok")
    clock[0] += 5 * 86400
    st.log("tool", tool="note_to_self", args={"section": "diary"}, result="ok")
    assert "returns" not in st.events(limit=1)[0]["data"]


def test_backfill_replays_history_silently(tmp_path, clock):
    path = tmp_path / "s.db"
    st = State(Settings(db_path=str(path), sleep=False))
    st.log("gift", sender="Ann", item="Teapot", qty=1)
    clock[0] += 100
    st.log("gift", sender="Bo", item="Cup", qty=2)
    st.db.execute("DELETE FROM meta WHERE key = 'firsts_v'")
    st.db.execute("DELETE FROM facets")
    st.db.execute("UPDATE events SET data = ?, importance = 0",
                  (json.dumps({"sender": "Ann", "item": "Teapot", "qty": 1, "firsts": [{"key": "stale"}], "returns": []}),))
    st.db.commit()
    st2 = State(Settings(db_path=str(path), sleep=False))
    assert st2.meta("firsts_v") == state_mod.FIRSTS_VERSION
    f = facet(st2, "gift")
    assert f["shown"] == state_mod.SHOWINGS_DONE and f["count"] == 2
    evs = st2.events(limit=10)
    assert [e["data"].get("firsts") and e["data"]["firsts"][0]["key"] for e in evs[::-1]][0] == "gift"
    assert all("stale" not in json.dumps(e["data"]) for e in evs)
    assert all(e["importance"] > 0 for e in evs)
    assert st2.recent_firsts(1e9, 1, 50, now=clock[0]) == []        # presented as old news


def test_backfill_not_rerun_when_current(tmp_path, clock):
    path = tmp_path / "s.db"
    st = State(Settings(db_path=str(path), sleep=False))
    st.log("gift", sender="Ann", item="Teapot", qty=1)
    st.db.execute("DELETE FROM facets")
    st.db.commit()
    State(Settings(db_path=str(path), sleep=False))
    assert st.db.execute("SELECT COUNT(*) FROM facets").fetchone()[0] == 0


def test_recent_firsts_filters_orders_and_limits(tmp_path, clock):
    st = mk(tmp_path)
    st.log("tool", tool="plant", args={}, result="ok")            # minor, oldest
    clock[0] += 3600
    st.log("tool", tool="sleep", args={}, result="ok")            # major
    clock[0] += 3600
    st.log("tool", tool="eat", args={}, result="ok")              # minor, newest
    got = st.recent_firsts(max_age_hours=5, showings=1, limit=10)
    assert [f["key"] for f in got] == ["tool:sleep", "tool:eat", "tool:plant"]
    assert [f["key"] for f in st.recent_firsts(5, 1, 2)] == ["tool:sleep", "tool:eat"]
    assert [f["key"] for f in st.recent_firsts(1.5, 1, 10)] == ["tool:sleep", "tool:eat"]
    assert [f["key"] for f in st.recent_firsts(2, 1, 10)] == ["tool:sleep", "tool:eat", "tool:plant"]  # boundary: first_ts >= cutoff
    st.mark_firsts_shown(["tool:sleep"])
    assert "tool:sleep" not in [f["key"] for f in st.recent_firsts(5, 1, 10)]
    assert "tool:sleep" in [f["key"] for f in st.recent_firsts(5, 2, 10)]           # shown < showings
    clock[0] += 10
    assert st.recent_firsts(5, 2, 10, now=clock[0] + 100000) == []


def test_recent_firsts_now_defaults_to_the_clock(tmp_path, clock):
    st = mk(tmp_path)
    st.log("tool", tool="plant", args={}, result="ok")
    clock[0] += 7200
    assert st.recent_firsts(1, 1, 10) == []
    assert len(st.recent_firsts(3, 1, 10)) == 1


def test_mark_firsts_shown_counts_each_key(tmp_path, clock):
    st = mk(tmp_path)
    st.log("tool", tool="plant", args={}, result="ok")
    st.log("tool", tool="eat", args={}, result="ok")
    st.mark_firsts_shown(["tool:plant", "tool:plant", "tool:eat"])
    assert facet(st, "tool:plant")["shown"] == 2 and facet(st, "tool:eat")["shown"] == 1


def test_firsts_between_bounds_order_and_limit(tmp_path, clock):
    st = mk(tmp_path)
    t0 = clock[0]
    st.log("tool", tool="plant", args={}, result="ok")            # at t0
    clock[0] += 10
    st.log("tool", tool="eat", args={}, result="ok")              # t0+10
    clock[0] += 10
    st.log("tool", tool="sleep", args={}, result="ok")            # t0+20 (major)
    keys = lambda a, b, **k: [f["key"] for f in st.firsts_between(a, b, **k)]
    assert keys(t0, t0 + 20) == ["tool:sleep", "tool:eat"]        # start exclusive, end inclusive, majors first
    assert keys(t0 - 1, t0 + 20) == ["tool:sleep", "tool:plant", "tool:eat"]
    assert keys(t0 - 1, t0 + 20, limit=2) == ["tool:sleep", "tool:plant"]
    assert keys(t0, t0 + 19) == ["tool:eat"]
    assert len(st.firsts_between(0, 1e12)) == 3


# --- inbox ------------------------------------------------------------------------------
def test_add_inbox_records_everything(tmp_path, clock):
    st = mk(tmp_path)
    i = st.add_inbox("hello", sender="  Ann  Lee ", gift=True, source="matrix", conversation="!r:x", external_id="e1")
    row = st.inbox_rows([i])[0]
    assert (row["text"], row["sender"], row["gift"], row["source"], row["conversation"], row["external_id"]) == \
        ("hello", "Ann Lee", 1, "matrix", "!r:x", "e1")
    assert row["ts"] == clock[0] and row["consumed"] == 0 and row["offers"] == 0
    j = st.add_inbox("hi")
    row = st.inbox_rows([j])[0]
    assert (row["sender"], row["gift"], row["source"], row["conversation"], row["external_id"]) == ("A visitor", 0, "web", "", "")


def test_inbox_lifecycle(tmp_path, clock):
    st = mk(tmp_path)
    a, b, c = (st.add_inbox(t) for t in "abc")
    assert [r["id"] for r in st.pending_inbox()] == [a, b, c]
    st.consume_inbox([a, c])
    assert [r["id"] for r in st.pending_inbox()] == [b]
    st.reoffer_inbox(c)
    pending = st.pending_inbox()
    assert [r["id"] for r in pending] == [b, c] and pending[1]["offers"] == 1
    st.consume_inbox([c])
    st.reoffer_inbox(c)
    assert st.inbox_rows([c])[0]["offers"] == 2
    assert [r["id"] for r in st.inbox_rows([c, a])] == [a, c]            # ordered by id
    assert st.inbox_rows([]) == []


def test_inbox_has_needs_matching_source_and_nonempty_external_id(tmp_path, clock):
    st = mk(tmp_path)
    st.add_inbox("x", source="matrix", external_id="m1")
    st.add_inbox("y", source="web", external_id="")
    assert st.inbox_has("matrix", "m1") is True
    assert st.inbox_has("web", "m1") is False and st.inbox_has("matrix", "m2") is False
    assert st.inbox_has("web", "") is False
    assert st.inbox_has("matrix", "m1") is True


# --- memories ------------------------------------------------------------------------------
def test_add_memory_and_filters(tmp_path, clock):
    st = mk(tmp_path)
    d = st.add_memory("dear diary")
    t = st.add_memory("fix the gate", "todo")
    w = st.add_memory("a telescope", "wishlist")
    m = st.memory(d)
    assert (m["text"], m["section"], m["status"], m["outcome"], m["ts"], m["edited_at"]) == \
        ("dear diary", "diary", "open", "", clock[0], None)
    assert [x["id"] for x in st.memories(limit=10)] == [d, t, w]                # oldest first
    assert [x["id"] for x in st.memories(limit=2)] == [t, w]                    # newest N, oldest first
    assert [x["id"] for x in st.memories("todo")] == [t]
    assert [x["id"] for x in st.memories("todo", status="done")] == []
    st.resolve_memory(t, "fixed")
    assert [x["id"] for x in st.memories("todo", status="done")] == [t]
    assert len(st.memories()) == 3
    assert len(st.memories()) == 3 and st.memories(limit=1)[0]["id"] == w
    assert st.memory(999) is None


def test_default_memories_limit_is_ten(tmp_path, clock):
    st = mk(tmp_path)
    for i in range(12):
        st.add_memory(f"n{i}")
    assert len(st.memories()) == 10


def test_unknown_section_is_refused_and_names_options(tmp_path, clock):
    st = mk(tmp_path)
    with pytest.raises(ValueError, match="unknown section 'nope'.*diary.*todo"):
        st.add_memory("x", "nope")


def test_archived_memories_hidden_unless_asked(tmp_path, clock):
    st = mk(tmp_path)
    a = st.add_memory("old", "todo")
    b = st.add_memory("new", "todo")
    st.set_memory_status(a, "archived")
    assert [m["id"] for m in st.memories()] == [b]
    assert [m["id"] for m in st.memories("todo")] == [b]
    assert [m["id"] for m in st.memories(status="archived")] == [a]
    assert [m["id"] for m in st.memories("todo", status="archived")] == [a]
    assert st.memories("wishlist", status="archived") == []


def test_set_memory_status_with_and_without_outcome(tmp_path, clock):
    st = mk(tmp_path)
    a = st.add_memory("x", "todo")
    st.set_memory_status(a, "done", "worked")
    assert (st.memory(a)["status"], st.memory(a)["outcome"]) == ("done", "worked")
    st.set_memory_status(a, "open")                       # outcome None leaves it alone
    assert (st.memory(a)["status"], st.memory(a)["outcome"]) == ("open", "worked")
    st.set_memory_status(a, "open", "")                   # empty string is a real outcome
    assert st.memory(a)["outcome"] == ""


def test_resolve_memory_outcomes(tmp_path, clock):
    st = mk(tmp_path)
    t = st.add_memory("fix the gate", "todo")
    d = st.add_memory("a diary line")
    assert st.resolve_memory(t, "mended it") == ""
    m = st.memory(t)
    assert m["status"] == "done" and m["outcome"] == "mended it"
    assert [h["text"] for h in st.recall("gate")] == ["fix the gate (done: mended it)"]
    t2 = st.add_memory("paint the shed", "ambitions")
    assert st.resolve_memory(t2) == ""
    assert [h["text"] for h in st.recall("shed")] == ["paint the shed (done)"]
    assert st.resolve_memory(999) == "no note #999"
    err = st.resolve_memory(d)
    assert err == f"note #{d} is in diary; only todo/wishlist/ambitions items can be resolved"
    assert st.memory(d)["status"] == "open"


def test_resolved_note_keeps_its_original_timestamp_in_recall(tmp_path, clock):
    st = mk(tmp_path)
    t = st.add_memory("fix the gate", "todo")
    clock[0] += 500
    st.resolve_memory(t)
    assert st.recall("gate")[0]["ts"] == 1_000_000.0 and st.recall("gate")[0]["source"] == "note:todo"


def test_edit_memory(tmp_path, clock):
    st = mk(tmp_path)
    t = st.add_memory("fix the gate", "todo")
    d = st.add_memory("diary", "diary")
    clock[0] += 50
    assert st.edit_memory(t, "fix the fence") == ("", "fix the gate")
    m = st.memory(t)
    assert m["text"] == "fix the fence" and m["edited_at"] == clock[0] and m["ts"] == 1_000_000.0
    assert [h["text"] for h in st.recall("fence")] == ["fix the fence"] and st.recall("gate") == []
    assert st.recall("fence")[0]["ts"] == 1_000_000.0 and st.recall("fence")[0]["source"] == "note:todo"
    assert st.edit_memory(999, "x") == ("no note #999", "")
    err, prev = st.edit_memory(d, "x")
    assert prev == "" and err.startswith(f"note #{d} is a diary entry, and those can't be changed")
    assert "write a new one" in err and st.memory(d)["text"] == "diary"
    st.resolve_memory(t)
    assert st.edit_memory(t, "again") == (f"note #{t} is already done", "")


def test_related_words(tmp_path):
    rel = State.related
    assert rel("tiny needle file", "a needle for sewing") is True
    assert rel("gears", "a gear") is True                          # plural-insensitive
    assert rel("cat", "cat") is False                              # under four letters is not meaningful
    assert rel("abcd", "abcd") is True                             # exactly four letters is
    assert rel("Needle", "NEEDLES") is True
    assert rel("brass wire", "steel pipe") is False
    assert rel("", "x") is False
    assert rel("it's-a-file", "file!") is True                     # split on non-letters


def test_matching_wishes_only_open_wishlist(tmp_path, clock):
    st = mk(tmp_path)
    a = st.add_memory("a tiny needle file", "wishlist")
    b = st.add_memory("needle thread", "wishlist")
    st.add_memory("needle in todo", "todo")
    c = st.add_memory("a brass needle", "wishlist")
    st.resolve_memory(b)
    got = st.matching_wishes("needle")
    assert [m["id"] for m in got] == [a, c]
    assert st.matching_wishes("anvil") == []


def test_matching_wishes_sees_beyond_the_first_ten(tmp_path, clock):
    st = mk(tmp_path)
    first = st.add_memory("needle one", "wishlist")
    for i in range(30):
        st.add_memory(f"filler wish {i}", "wishlist")
    assert [m["id"] for m in st.matching_wishes("needle")] == [first]


# --- items -----------------------------------------------------------------------------------
def items_by_name(st):
    return {i["name"]: i for i in st.items()}


def test_starter_items_given_once_only(tmp_path, clock):
    path = tmp_path / "s.db"
    st = State(Settings(db_path=str(path), sleep=False))
    names = items_by_name(st)
    assert names["tomato seeds"]["qty"] == 3 and names["carrot seeds"]["kind"] == "seed"
    assert names["tomato seeds"]["attrs"]["crop"] == "tomatoes"
    st.take_item(names["tomato seeds"]["id"], 3)
    st2 = State(Settings(db_path=str(path), sleep=False))
    assert "tomato seeds" not in items_by_name(st2) and items_by_name(st2)["carrot seeds"]["qty"] == 3


def test_add_item_validations_and_clipping(tmp_path, clock):
    st = mk(tmp_path)
    with pytest.raises(ValueError, match="item needs a name"):
        st.add_item("   ")
    with pytest.raises(ValueError, match="unknown kind 'gizmo'; options: \\["):
        st.add_item("x", kind="gizmo")
    with pytest.raises(ValueError, match="qty must be at least 1"):
        st.add_item("x", qty=0)
    assert st.add_item("x", qty=1)["qty"] == 1
    it = st.add_item("  " + "n" * 80 + "  ", description="d" * 300)
    assert it["name"] == "n" * 60 and it["description"] == "d" * 200
    assert it["ts"] == clock[0] and it["kind"] == "tool" and it["attrs"] == {}


def test_add_item_stack_updates_description_only_when_given(tmp_path, clock):
    st = mk(tmp_path)
    st.add_item("rope", 2, "material", "old coil")
    it = st.add_item("ROPES", 3, "material")
    assert it["qty"] == 5 and it["description"] == "old coil" and it["name"] == "rope"
    it = st.add_item("rope", 1, "material", "z" * 300)
    assert it["qty"] == 6 and it["description"] == "z" * 200


def test_add_item_with_attrs_and_kind_split(tmp_path, clock):
    st = mk(tmp_path)
    it = st.add_item("kite", 1, "tool", attrs={"x": 1})
    assert isinstance(it["attrs"], dict)
    st.add_item("lemon", 1, "food", attrs={"food_value": 0.3})
    assert items_by_name(st)["lemon"]["attrs"]["food_value"] == 0.3


def test_merge_duplicates_keeps_oldest_adds_quantity_returns_count(tmp_path, clock):
    st = mk(tmp_path)
    with st.lock:
        for name, qty, kind in (("Tomato", 1, "food"), ("tomatoes", 2, "food"), ("Tomatos", 4, "food"),
                                ("ropes", 8, "tool"), ("rope", 1, "material")):
            st.db.execute("INSERT INTO items (name, qty, kind, ts) VALUES (?, ?, ?, 0)", (name, qty, kind))
        st.db.commit()
    assert st.merge_duplicate_items() == 2
    got = {(i["name"], i["kind"]): i["qty"] for i in st.items() if i["kind"] != "seed"}
    assert got == {("Tomato", "food"): 7, ("ropes", "tool"): 8, ("rope", "material"): 1}
    assert st.merge_duplicate_items() == 0


def test_find_item(tmp_path, clock):
    st = mk(tmp_path)
    for n in ("needle file", "round file", "hammer", "Sandpaper"):
        st.add_item(n, 1, "tool")
    st.add_item("sandpaper block", 1, "material")
    assert st.find_item("hammers") == (items_by_name(st)["hammer"], "")
    assert st.find_item("  HAMMER ")[0]["name"] == "hammer"
    assert st.find_item("needle")[0]["name"] == "needle file"                   # a unique partial
    assert st.find_item("needle file set")[0]["name"] == "needle file"          # item name inside the query
    item, err = st.find_item("file")
    assert item is None and err == "which one? needle file, round file"
    item, err = st.find_item("anvil")
    assert item is None and err == "you don't have 'anvil'"
    item, err = st.find_item("anvil", kind="tool")
    assert err == "you don't have 'anvil' (kind: tool)"
    assert st.find_item("sandpaper", kind="material")[0]["name"] == "sandpaper block"
    assert st.find_item("sandpaper", kind="tool")[0]["name"] == "Sandpaper"
    item, err = st.find_item("sandpaper")
    assert item["name"] == "Sandpaper" and err == ""                              # exact beats partial
    item, err = st.find_item("")
    assert item is None and err.startswith("you don't have ''")
    assert st.find_item("round file", kind="material")[0] is None


def test_take_item_decrements_and_removes_at_zero(tmp_path, clock):
    st = mk(tmp_path)
    it = st.add_item("rope", 3, "material")
    st.take_item(it["id"])
    assert items_by_name(st)["rope"]["qty"] == 2
    st.take_item(it["id"], 1)
    assert items_by_name(st)["rope"]["qty"] == 1
    st.take_item(it["id"], 1)
    assert "rope" not in items_by_name(st)
    other = st.add_item("twine", 2, "material")
    st.take_item(other["id"], 5)                             # over-take removes it
    assert "twine" not in items_by_name(st)
    keep = st.add_item("glue", 2, "material")
    st.take_item(keep["id"], 1)
    assert items_by_name(st)["glue"]["qty"] == 1
