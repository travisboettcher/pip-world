"""State: legacy-database migrations, replay of old data, search boundaries and error messages."""
import json
import sqlite3
import threading
import time

import pytest

from app import state as state_mod
from app.config import Settings
from app.memory import event_importance
from app.state import State, name_key


@pytest.fixture
def clock(monkeypatch):
    now = [3_000_000.0]
    monkeypatch.setattr(time, "time", lambda: now[0])
    return now


def mk(tmp_path, **kw):
    kw.setdefault("sleep", False)
    return State(Settings(db_path=str(tmp_path / "s.db"), **kw))


# --- migrations of databases created before a column existed ------------------------------------
MIGRATED = {
    ("agent", "description"): ("TEXT", "''"),
    ("memories", "section"): ("TEXT", "'diary'"),
    ("memories", "status"): ("TEXT", "'open'"),
    ("memories", "outcome"): ("TEXT", "''"),
    ("memories", "edited_at"): ("REAL", None),
    ("inbox", "sender"): ("TEXT", "'A visitor'"),
    ("inbox", "gift"): ("INTEGER", "0"),
    ("characters", "about"): ("TEXT", "''"),
    ("characters", "life"): ("TEXT", "'[]'"),
    ("creations", "given_to"): ("TEXT", None),
    ("inbox", "offers"): ("INTEGER", "0"),
    ("inbox", "source"): ("TEXT", "'web'"),
    ("inbox", "conversation"): ("TEXT", "''"),
    ("inbox", "external_id"): ("TEXT", "''"),
    ("works", "revisions"): ("INTEGER", "0"),
    ("events", "importance"): ("INTEGER", "0"),
    ("reflections", "grounded"): ("INTEGER", "1"),
    ("reflections", "support"): ("TEXT", "'legacy'"),
    ("projects", "questions"): ("TEXT", "'[]'"),
    ("projects", "hidden"): ("TEXT", "'[]'"),
    ("projects", "findings"): ("TEXT", "'[]'"),
    ("projects", "dry"): ("INTEGER", "0"),
    ("projects", "revised_at"): ("INTEGER", "0"),
    ("work_session", "expect"): ("TEXT", "''"),
    ("work_session", "kind"): ("TEXT", "'work'"),
    ("work_session", "target"): ("TEXT", "''"),
}


def columns(path, table):
    db = sqlite3.connect(path)
    try:
        return {r[1]: (r[2], r[4]) for r in db.execute(f"PRAGMA table_info({table})")}
    finally:
        db.close()


def test_every_late_column_is_added_to_an_old_database_with_its_type_and_default(tmp_path, clock):
    path = str(tmp_path / "old.db")
    State(Settings(db_path=path, sleep=False)).db.close()
    db = sqlite3.connect(path)
    for table, col in MIGRATED:
        db.execute(f"ALTER TABLE {table} DROP COLUMN {col}")
    db.commit()
    db.close()
    for table, col in MIGRATED:
        assert col not in columns(path, table)
    State(Settings(db_path=path, sleep=False)).db.close()
    for (table, col), expected in MIGRATED.items():
        assert columns(path, table).get(col) == expected, (table, col)


def test_migrated_defaults_apply_to_rows_that_already_existed(tmp_path, clock):
    path = str(tmp_path / "old.db")
    State(Settings(db_path=path, sleep=False)).db.close()
    db = sqlite3.connect(path)
    db.execute("INSERT INTO inbox (ts, text) VALUES (1, 'old hello')")
    db.execute("ALTER TABLE inbox DROP COLUMN sender")
    db.execute("ALTER TABLE inbox DROP COLUMN source")
    db.commit()
    db.close()
    row = State(Settings(db_path=path, sleep=False)).pending_inbox()[0]
    assert row["sender"] == "A visitor" and row["source"] == "web" and row["gift"] == 0 and row["offers"] == 0


def test_opening_a_current_database_twice_is_harmless(tmp_path, clock):
    mk(tmp_path).db.close()
    st = mk(tmp_path)
    assert st.agent()["id"] == 1


def test_state_can_be_used_from_another_thread(tmp_path, clock):
    st = mk(tmp_path)
    out = []
    t = threading.Thread(target=lambda: out.append(st.add_memory("from a thread")))
    t.start()
    t.join()
    assert out and st.memory(out[0])["text"] == "from a thread"


# --- naming ------------------------------------------------------------------------------------
def test_names_ending_in_oes_drop_the_es_from_five_letters_up():
    assert name_key("shoes") == "sho"          # documents the rule's quirk: it is length based, not a word list
    assert name_key("heroes") == "hero"


# --- decay alert boundary -------------------------------------------------------------------------
def test_hunger_alert_fires_at_exactly_the_threshold(tmp_path, clock):
    st = mk(tmp_path, hunger_per_hour=0.1, energy_per_hour=0.0, hunger_alert=0.5, energy_alert=0.0)
    st.update_agent(hunger=0.0, energy=0.9, activity="idle", updated_at=clock[0], hunger_alerted=0, energy_alerted=0)
    assert st.apply_decay(now=clock[0] + 4 * 3600) == []
    assert st.apply_decay(now=clock[0] + 5 * 3600) == ["hunger"]
    assert st.agent()["hunger_alerted"] == 1


# --- facets and their replay -------------------------------------------------------------------------
def test_return_days_are_rounded_to_one_decimal(tmp_path, clock):
    st = mk(tmp_path)
    st.log("gift", sender="Ann", item="Teapot", qty=1)
    clock[0] += 40.37 * 3600                                    # 1.6821 days
    st.log("gift", sender="Ann", item="Teapot", qty=1)
    ret = {r["key"]: r for r in st.events(limit=1)[0]["data"]["returns"]}
    assert ret["gift"]["days"] == 1.7


def test_recent_firsts_age_limit_is_inclusive(tmp_path, clock):
    st = mk(tmp_path)
    st.log("gift", sender="Ann", item="Teapot", qty=1)
    assert "gift" in [f["key"] for f in st.recent_firsts(10, 5, 50, now=clock[0] + 36000)]
    assert st.recent_firsts(10, 5, 50, now=clock[0] + 36001) == []


def test_backfill_rebuilds_firsts_returns_event_ids_and_importance_from_the_log(tmp_path, clock):
    path = tmp_path / "s.db"
    st = State(Settings(db_path=str(path), sleep=False))
    e1 = st.log("gift", sender="Ann", item="Teapot", qty=1)
    clock[0] += 2 * 86400
    e2 = st.log("gift", sender="Ann", item="Cup", qty=1)
    e3 = st.log("gift", sender="Ann", item="Cup", qty=1)                   # nothing new, no long gap
    first_imp = {e["id"]: e["importance"] for e in st.events(limit=10)}
    assert "firsts" not in st.events(limit=1)[0]["data"] and "returns" not in st.events(limit=1)[0]["data"]
    assert st.events(limit=10)[1]["data"]["returns"][0]["days"] == 2.0
    # simulate a database whose facets predate this version: stale markers inside the stored data, no facet rows
    stale = {"sender": "Ann", "item": "Teapot", "qty": 1, "firsts": [{"key": "stale"}], "returns": [{"key": "stale"}]}
    st.db.execute("UPDATE events SET data = ?, importance = 0 WHERE id = ?", (json.dumps(stale), e1))
    st.db.execute("UPDATE events SET data = ?, importance = 0 WHERE id = ?",
                  (json.dumps({**stale, "item": "Cup"}), e2))
    st.db.execute("UPDATE events SET data = ?, importance = 0 WHERE id = ?",
                  (json.dumps({"sender": "Ann", "item": "Cup", "qty": 1}), e3))
    st.db.execute("DELETE FROM facets")
    st.db.execute("DELETE FROM meta WHERE key = 'firsts_v'")
    st.db.commit()
    st.db.close()

    st2 = State(Settings(db_path=str(path), sleep=False))
    by_id = {e["id"]: e for e in st2.events(limit=10)}
    d1, d2 = by_id[e1]["data"], by_id[e2]["data"]
    assert [f["key"] for f in d1["firsts"]] == ["gift", *[f["key"] for f in d1["firsts"][1:]]]
    assert "stale" not in json.dumps(d1) and "stale" not in json.dumps(d2)
    assert [r["key"] for r in d2["returns"]] == ["gift"] and d2["returns"][0]["days"] == 2.0
    assert "returns" not in d1 and [f["key"] for f in d2["firsts"]] == ["gift_item:cup"]
    assert st2.db.execute("SELECT first_event_id FROM facets WHERE key = 'gift'").fetchone()[0] == e1
    assert by_id[e1]["importance"] == first_imp[e1] and by_id[e2]["importance"] == first_imp[e2]
    assert by_id[e1]["importance"] == event_importance("gift", {"sender": "Ann", "item": "Teapot", "qty": 1},
                                                       d1["firsts"])
    assert "firsts" not in by_id[e3]["data"] and "returns" not in by_id[e3]["data"]
    assert by_id[e1]["importance"] > by_id[e2]["importance"]                      # the first weighs more


# --- error messages and exact results ----------------------------------------------------------------
def test_add_item_refusals_say_what_is_wrong(tmp_path, clock):
    st = mk(tmp_path)
    with pytest.raises(ValueError, match=r"^item needs a name$"):
        st.add_item("   ")
    with pytest.raises(ValueError, match=r"^qty must be at least 1$"):
        st.add_item("rope", 0, "material")
    with pytest.raises(ValueError, match=r"^unknown kind 'bogus'; options: \["):
        st.add_item("rope", 1, "bogus")


def test_partial_matches_resolve_with_no_error_text(tmp_path, clock):
    st = mk(tmp_path)
    st.add_item("needle file", 1, "tool")
    assert st.find_item("needle") == (st.items()[-1], "")
    a = st.add_project("Brass Clock", "g", "c", 1, [], [])
    assert st.find_project("brass") == (a, "")
    k = st.add_creation("Red Kite", "", None, "ok", {}, {})
    assert st.find_creation("red") == (k, "")


def test_exact_names_beat_longer_names_that_contain_them(tmp_path, clock):
    st = mk(tmp_path)
    kite = st.add_project("Kite", "g", "c", 1, [], [])
    st.add_project("Kite Tail", "g", "c", 1, [], [])
    assert st.find_project("KITE") == (kite, "")
    ckite = st.add_creation("Kite", "", None, "ok", {}, {})
    st.add_creation("Kite Tail", "", None, "ok", {}, {})
    assert st.find_creation("kite") == (ckite, "")


def test_find_creation_ignores_a_leading_hash(tmp_path, clock):
    st = mk(tmp_path)
    k = st.add_creation("Red Kite", "", None, "ok", {}, {})
    assert st.find_creation("#Red Kite") == (k, "")
    assert st.find_creation("  #red  ") == (k, "")


def test_garden_ready_flips_only_when_the_time_has_come(tmp_path, clock):
    st = mk(tmp_path)
    st.plant(1, "s", "c", 1, 1, 0.1)
    clock[0] += 59
    assert st.garden()[0]["state"] == "growing" and st.garden()[0]["ready_in_min"] == 1
    clock[0] += 1
    assert st.garden()[0]["state"] == "ready" and st.garden()[0]["ready_in_min"] == 0


def test_matching_wishes_looks_at_the_newest_fifty_wishes_only(tmp_path, clock):
    st = mk(tmp_path)
    st.add_memory("a brass telescope", "wishlist")
    for i in range(50):
        st.add_memory(f"wish number {i}", "wishlist")
    assert st.matching_wishes("telescope") == []
    st.add_memory("another telescope", "wishlist")
    assert [m["text"] for m in st.matching_wishes("telescope")] == ["another telescope"]


def test_capability_context_reads_the_five_hundred_newest_projects(tmp_path, clock):
    st = mk(tmp_path)
    for i in range(501):
        st.add_project(f"P{i}", "", "c", 1, [], [])
    assert len(st.capability_context()[0]) == 500


def test_reflections_by_importance_beats_recency(tmp_path, clock):
    st = mk(tmp_path)
    a = st.add_reflection("day", "a", 3, 0, 1)
    b = st.add_reflection("day", "b", 9, 0, 1)
    c = st.add_reflection("day", "c", 5, 0, 1)
    assert [r["id"] for r in st.reflections(by_importance=True)] == [b, c, a]
    assert [r["id"] for r in st.reflections()] == [c, b, a]


def test_events_after_id_pages_forward_without_a_before_filter(tmp_path, clock):
    st = mk(tmp_path)
    ids = [st.log("noop") for _ in range(5)]
    assert [e["id"] for e in st.events(limit=2, after_id=ids[1])] == ids[2:4]
    assert [e["id"] for e in st.events(after_id=0)] == ids


def test_event_text_for_a_missing_event_is_none(tmp_path, clock):
    st = mk(tmp_path)
    assert st.event_text(99) is None
    e = st.log("say", text="hello there", to_name="")
    assert st.event_text(e) == "You said: hello there"
    assert st.event_text(st.log("noop")) is None


def test_portrait_backfill_only_considers_portraits(tmp_path, clock):
    st = mk(tmp_path)
    st.add_reflection("day", "a day", 5, 0, 1)
    st.set_meta(self_portrait="a tinkerer")
    st._backfill_portraits()
    assert [r["text"] for r in st.reflections("portrait")] == ["a tinkerer"]


def test_recall_ignores_single_letter_words(tmp_path, clock):
    st = mk(tmp_path)
    st.add_memory("xylophone lessons")
    assert st.recall("x") == []
    assert [r["text"] for r in st.recall("xy")] == ["xylophone lessons"]


def test_rebuilt_recall_index_keys_each_kind_of_memory_by_its_own_source_and_ref(tmp_path, clock):
    st = mk(tmp_path)
    note = st.add_memory("alpha note", "todo")
    ev = st.log("say", text="beta event", to_name="")
    refl = st.add_reflection("day", "gamma reflection", 5, 0, 77)
    st.upsert_person("Delta", "delta person", 5.0)
    st.db.execute("DELETE FROM recall_index")
    st.db.commit()
    st._backfill_recall()
    got = {r["text"]: (r["source"], r["ref"], float(r["ts"])) for r in st.recall("alpha beta gamma delta", limit=10)}
    assert got["alpha note"] == ("note:todo", str(note), clock[0])
    assert got["You said: beta event"] == ("event:say", str(ev), clock[0])
    assert got["gamma reflection"] == ("day", str(refl), 77.0)
    assert got["Delta: delta person"] == ("person", "Delta", 5.0)


def test_edit_memory_refusals_explain_themselves(tmp_path, clock):
    st = mk(tmp_path)
    diary = st.add_memory("dear diary")
    err, prev = st.edit_memory(diary, "x")
    assert err == ("note #%d is a diary entry, and those can't be changed - write a new one if something has changed" % diary)
    assert prev == ""
    todo = st.add_memory("fix gate", "todo")
    st.resolve_memory(todo, "done")
    assert st.edit_memory(todo, "x") == (f"note #{todo} is already done", "")
    assert st.edit_memory(999, "x") == ("no note #999", "")
    assert st.resolve_memory(diary) == f"note #{diary} is in diary; only todo/wishlist/ambitions items can be resolved"
