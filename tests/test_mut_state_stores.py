"""State: garden, projects, sessions, xp, creations, characters, bookmarks, letters and the smaller stores."""
import json
import time
from datetime import date

import pytest

from app.config import Settings
from app.state import State


@pytest.fixture
def clock(monkeypatch):
    now = [2_000_000.0]
    monkeypatch.setattr(time, "time", lambda: now[0])
    return now


def mk(tmp_path, **kw):
    kw.setdefault("sleep", False)
    return State(Settings(db_path=str(tmp_path / "s.db"), **kw))


# --- project slots and garden -----------------------------------------------------------
def test_project_limit_grows_to_the_cap_and_then_refuses(tmp_path, clock):
    st = mk(tmp_path, max_active_projects=3, max_active_projects_cap=5)
    assert st.project_limit() == 3
    assert st.add_project_slot() == 4
    assert st.add_project_slot() == 5
    assert st.add_project_slot() is None
    assert st.project_limit() == 5 and st.meta("extra_project_slots") == "2"


def test_project_limit_is_capped_even_if_meta_is_larger(tmp_path, clock):
    st = mk(tmp_path, max_active_projects=3, max_active_projects_cap=4)
    st.set_meta(extra_project_slots=10)
    assert st.project_limit() == 4


def make_project(st, name="Clock", craft="clockmaking", **kw):
    return st.add_project(name, kw.get("goal", "tell time"), craft, kw.get("difficulty", 3),
                          kw.get("stages", [{"name": "gears"}]), kw.get("tools", ["file"]))


def test_add_project_roundtrips_json_fields_and_defaults(tmp_path, clock):
    st = mk(tmp_path)
    p = make_project(st)
    assert p["name"] == "Clock" and p["goal"] == "tell time" and p["craft"] == "clockmaking" and p["difficulty"] == 3
    assert p["stages"] == [{"name": "gears"}] and p["tools"] == ["file"]
    assert p["history"] == [] and p["questions"] == [] and p["hidden"] == [] and p["findings"] == []
    assert p["status"] == "active" and p["outcome"] == "" and p["finished_at"] is None
    assert p["ts"] == clock[0] and p["dry"] == 0 and p["revised_at"] == 0
    assert st.project(p["id"]) == p and st.project(999) is None


def test_update_project_encodes_json_fields_only(tmp_path, clock):
    st = mk(tmp_path)
    p = make_project(st)
    st.update_project(p["id"], history=[{"x": 1}], findings=["a"], status="done", outcome="ok", dry=2)
    q = st.project(p["id"])
    assert q["history"] == [{"x": 1}] and q["findings"] == ["a"] and q["status"] == "done"
    assert q["outcome"] == "ok" and q["dry"] == 2
    other = make_project(st, "Other")
    assert st.project(other["id"])["status"] == "active"
    st.update_project(other["id"], questions=["why?"], hidden=[{"fact": "f"}], stages=[{"name": "z"}], tools=["t"])
    o = st.project(other["id"])
    assert o["questions"] == ["why?"] and o["hidden"] == [{"fact": "f"}] and o["stages"] == [{"name": "z"}] and o["tools"] == ["t"]


def test_projects_list_filters_limits_and_orders_oldest_first(tmp_path, clock):
    st = mk(tmp_path)
    ids = [make_project(st, f"P{i}")["id"] for i in range(4)]
    st.update_project(ids[1], status="done")
    assert [p["id"] for p in st.projects()] == ids
    assert [p["id"] for p in st.projects("done")] == [ids[1]]
    assert [p["id"] for p in st.projects("active")] == [ids[0], ids[2], ids[3]]
    assert [p["id"] for p in st.projects(limit=2)] == ids[2:]
    assert len(st.projects(limit=50)) == 4


def test_projects_default_limit_is_fifty(tmp_path, clock):
    st = mk(tmp_path)
    for i in range(52):
        make_project(st, f"P{i}")
    got = st.projects()
    assert len(got) == 50 and got[-1]["name"] == "P51"


def test_find_project_by_number_name_and_partial(tmp_path, clock):
    st = mk(tmp_path)
    a = make_project(st, "Brass Clock")
    b = make_project(st, "Wooden Kite")
    c = make_project(st, "Kite Tail")
    done = make_project(st, "Old Boat")
    st.update_project(done["id"], status="done")
    assert st.find_project(f"#{a['id']}") == (a, "")
    assert st.find_project(a["id"])[0]["name"] == "Brass Clock"
    assert st.find_project(" 99 ")[1] == "no active project #99"
    assert st.find_project(done["id"])[1] == f"no active project #{done['id']}"
    assert st.find_project(done["id"], status="done")[0]["name"] == "Old Boat"
    assert st.find_project("brass clock")[0]["id"] == a["id"]
    assert st.find_project("clock")[0]["id"] == a["id"]
    assert st.find_project("the brass clock thing")[0]["id"] == a["id"]
    assert st.find_project("Kite Tail")[0]["id"] == c["id"]                       # exact beats partial
    item, err = st.find_project("kite")
    assert item is None and err == f"which one? #{b['id']} Wooden Kite, #{c['id']} Kite Tail"
    item, err = st.find_project("zeppelin")
    assert item is None and err == f"no active project called 'zeppelin' (yours: #{a['id']} {a['name']}, #{b['id']} Wooden Kite, #{c['id']} Kite Tail)"
    assert st.find_project("")[1].startswith("no active project called ''")


def test_find_project_with_no_projects_says_none(tmp_path, clock):
    st = mk(tmp_path)
    assert st.find_project("anything") == (None, "no active project called 'anything' (yours: none)")


# --- sessions and xp ----------------------------------------------------------------------
def test_session_lifecycle(tmp_path, clock):
    st = mk(tmp_path)
    assert st.session() is None
    st.start_session(4, 2, 30, clock[0] + 1800, kind="walk", target="the pond", expect="frogs")
    s = st.session()
    assert (s["project_id"], s["stage"], s["minutes"], s["started_at"], s["ends_at"]) == (4, 2, 30, clock[0], clock[0] + 1800)
    assert (s["kind"], s["target"], s["expect"]) == ("walk", "the pond", "frogs")
    st.start_session(5, 0, 10, clock[0] + 600)                                    # replaces, with defaults
    s = st.session()
    assert s["project_id"] == 5 and s["kind"] == "work" and s["target"] == "" and s["expect"] == ""
    st.end_session()
    assert st.session() is None


def test_xp_accumulates_per_craft_case_insensitively(tmp_path, clock):
    st = mk(tmp_path)
    st.add_xp("clockmaking", 10)
    st.add_xp("Clockmaking", 5)
    st.add_xp("kites", 2)
    assert st.skills() == {"clockmaking": 15, "kites": 2}
    assert list(st.skills()) == ["clockmaking", "kites"]                          # biggest first


def test_ability_xp_accumulates_and_orders(tmp_path, clock):
    st = mk(tmp_path)
    st.add_ability_xp({"patience": 1, "precision": 5})
    st.add_ability_xp({"patience": 10})
    assert st.abilities() == {"patience": 11, "precision": 5}
    assert list(st.abilities()) == ["patience", "precision"]


def test_old_craft_xp_seeds_abilities_once(tmp_path, clock):
    st = mk(tmp_path)
    st.db.execute("INSERT INTO skills VALUES ('a', 60)")
    st.db.execute("INSERT INTO skills VALUES ('b', 40)")
    st.db.execute("DELETE FROM meta WHERE key = 'abilities_seeded'")
    st.db.commit()
    st._seed_abilities()
    ab = st.abilities()
    assert ab == {"handiness": pytest.approx(40), "precision": pytest.approx(30), "patience": pytest.approx(30)}
    assert st.meta("abilities_seeded") == "1"
    st._seed_abilities()
    assert st.abilities() == ab


def test_fresh_world_seeds_no_abilities_but_marks_seeded(tmp_path, clock):
    st = mk(tmp_path)
    assert st.abilities() == {} and st.meta("abilities_seeded") == "1"


def test_long_craft_names_are_folded_on_start(tmp_path, clock):
    st = mk(tmp_path)
    p = make_project(st, craft="clockmaking")
    st.db.execute("UPDATE projects SET craft = 'Clockmaking (gear train, escapement)' WHERE id = ?", (p["id"],))
    st.db.execute("INSERT INTO skills VALUES ('Clockmaking (gears)', 7)")
    st.db.execute("INSERT INTO skills VALUES ('clockmaking', 3)")
    st.db.execute("INSERT INTO skills VALUES ('kites', 1)")
    st.db.commit()
    st._normalize_crafts()
    assert st.project(p["id"])["craft"] == "clockmaking"
    assert st.skills() == {"clockmaking": 10, "kites": 1}


# --- creations ---------------------------------------------------------------------------
def test_creations_roundtrip_give_and_find(tmp_path, clock):
    st = mk(tmp_path)
    kite = st.add_creation("Red Kite", "flies", 3, "fine", {"a": 1}, {"b": 2})
    assert kite["name"] == "Red Kite" and kite["description"] == "flies" and kite["project_id"] == 3
    assert kite["quality"] == "fine" and kite["spec"] == {"a": 1} and kite["runtime"] == {"b": 2}
    assert kite["ts"] == clock[0] and kite["given_to"] is None
    tail = st.add_creation("Kite Tail", "", None, "ok", {}, {})
    assert st.creation(kite["id"]) == kite and st.creation(99) is None
    st.set_runtime(kite["id"], {"c": 3})
    assert st.creation(kite["id"])["runtime"] == {"c": 3} and st.creation(tail["id"])["runtime"] == {}
    assert st.find_creation("red kite")[0]["id"] == kite["id"]
    assert st.find_creation("#" + str(tail["id"]) + "x")[1] == "you haven't made anything called '#" + str(tail["id"]) + "x'"
    assert st.find_creation("Kite Tail")[0]["id"] == tail["id"]                  # exact beats partial
    assert st.find_creation("red")[0]["id"] == kite["id"]
    assert st.find_creation("a red kite for you")[0]["id"] == kite["id"]
    item, err = st.find_creation("kite")
    assert item is None and err == "which one? Red Kite, Kite Tail"
    assert st.find_creation("boat") == (None, "you haven't made anything called 'boat'")
    assert st.find_creation("")[0] is None
    st.give_creation(kite["id"], "Ada")
    assert [c["id"] for c in st.creations()] == [tail["id"]]
    assert [c["id"] for c in st.creations(include_given=True)] == [kite["id"], tail["id"]]
    assert st.creation(kite["id"])["given_to"] == "Ada" and st.creation(tail["id"])["given_to"] is None
    assert st.find_creation("red kite")[0] is None


# --- characters ---------------------------------------------------------------------------
def test_characters_roundtrip_filter_update_and_find(tmp_path, clock):
    st = mk(tmp_path)
    a = st.add_character("Clockwork Owl", "companion", 7, "wise", 30, clock[0] + 100, about="an owl")
    b = st.add_character("Mabel", "neighbor", None, "kind", 60, clock[0] + 200)
    assert a["name"] == "Clockwork Owl" and a["kind"] == "companion" and a["creation_id"] == 7
    assert a["persona"] == "wise" and a["chatter_minutes"] == 30 and a["next_chatter_at"] == clock[0] + 100
    assert a["about"] == "an owl" and b["about"] == "" and a["ts"] == clock[0]
    assert a["heard"] == [] and a["replies"] == [] and a["life"] == []
    assert [c["id"] for c in st.characters()] == [a["id"], b["id"]]
    assert [c["id"] for c in st.characters("neighbor")] == [b["id"]]
    st.update_character(a["id"], heard=["hi"], replies=["hello"], life=["born"], persona="grumpy")
    got = st.characters("companion")[0]
    assert got["heard"] == ["hi"] and got["replies"] == ["hello"] and got["life"] == ["born"] and got["persona"] == "grumpy"
    assert st.characters("neighbor")[0]["persona"] == "kind"
    assert st.find_character("mabel")["id"] == b["id"]
    assert st.find_character("clock")["id"] == a["id"]
    assert st.find_character("hello Mabel dear")["id"] == b["id"]
    assert st.find_character("") is None and st.find_character("zed") is None
    st.add_character("Mabel Jr", "neighbor", None, "", 1, 0)
    assert st.find_character("mabel")["name"] == "Mabel"                          # exact wins
    assert st.find_character("mab") is None                                       # ambiguous


# --- bookmarks ----------------------------------------------------------------------------
def test_bookmarks(tmp_path, clock):
    st = mk(tmp_path)
    assert st.bookmark(1) is None
    st.set_bookmark(1, "Moby")
    b = st.bookmark(1)
    assert b == {"book_id": 1, "title": "Moby", "section": 0, "offset": 0, "percent": 0, "sessions": 0,
                 "finished": 0, "unreadable": 0, "last_read": None}
    st.set_bookmark(1, "Other title", section=3, percent=40, last_read=10.0)
    b = st.bookmark(1)
    assert b["title"] == "Moby" and b["section"] == 3 and b["percent"] == 40 and b["last_read"] == 10.0
    st.set_bookmark(2, "Emma", finished=1, last_read=20.0)
    st.set_bookmark(3, "Bad", unreadable=1, last_read=5.0)
    st.set_bookmark(4, "Fresh", last_read=30.0)
    assert [x["book_id"] for x in st.bookmarks()] == [4, 2, 1, 3]
    assert [x["book_id"] for x in st.bookmarks(include_finished=False)] == [4, 1]
    assert [x["book_id"] for x in st.bookmarks(False)] == [4, 1]


# --- letters --------------------------------------------------------------------------------
def test_letters_roundtrip_filters_and_counts(tmp_path, clock):
    st = mk(tmp_path)
    one = st.add_letter("Pip", "Mabel", "hello", clock[0] + 60)
    assert one["sender"] == "Pip" and one["recipient"] == "Mabel" and one["text"] == "hello"
    assert one["enclosed"] == "" and one["parcel"] is None and one["reply_to"] is None
    assert one["deliver_at"] == clock[0] + 60 and one["delivered_at"] is None and one["attempts"] == 0
    assert one["ts"] == clock[0]
    clock[0] += 10
    two = st.add_letter("Mabel", "Pip", "hi back", clock[0], enclosed="a seed", parcel={"item": "seed", "qty": 2}, reply_to=one["id"])
    assert two["enclosed"] == "a seed" and two["parcel"] == {"item": "seed", "qty": 2} and two["reply_to"] == one["id"]
    clock[0] += 10
    three = st.add_letter("Bob", "Pip", "yo", clock[0])
    assert [x["id"] for x in st.letters()] == [one["id"], two["id"], three["id"]]
    assert [x["id"] for x in st.letters(limit=2)] == [two["id"], three["id"]]
    assert [x["id"] for x in st.letters(between="Mabel")] == [one["id"], two["id"]]
    assert [x["id"] for x in st.letters(between="Bob")] == [three["id"]]
    st.update_letter(one["id"], delivered_at=5.0, attempts=2)
    assert [x["id"] for x in st.letters(undelivered=True)] == [two["id"], three["id"]]
    assert [x["id"] for x in st.letters(between="Mabel", undelivered=True)] == [two["id"]]
    assert st.letters(between="Mabel")[0]["delivered_at"] == 5.0 and st.letters(between="Mabel")[0]["attempts"] == 2
    assert st.letters_since("Pip", clock[0] - 100) == 1
    assert st.letters_since("Mabel", clock[0] - 100) == 1
    assert st.letters_since("Mabel", one["ts"] + 10) == 0                         # strictly newer
    assert st.letters_since("Mabel", one["ts"] + 9) == 1
    assert st.letters_since_parcel(0) == 1
    assert st.letters_since_parcel(two["ts"]) == 0
    assert st.letters_since_parcel(two["ts"] - 1) == 1


def test_letters_default_limit_is_fifty(tmp_path, clock):
    st = mk(tmp_path)
    for i in range(52):
        st.add_letter("a", "b", str(i), 0)
    got = st.letters()
    assert len(got) == 50 and got[-1]["text"] == "51" and got[0]["text"] == "2"


# --- meta, born_at --------------------------------------------------------------------------
def test_meta_roundtrip_stringifies_and_overwrites(tmp_path, clock):
    st = mk(tmp_path)
    assert st.meta("nope") is None
    st.set_meta(a=1, b="x")
    assert st.meta("a") == "1" and st.meta("b") == "x"
    st.set_meta(a=2)
    assert st.meta("a") == "2"


def test_born_at_is_first_event_then_fixed(tmp_path, clock):
    st = mk(tmp_path)
    st.log("noop")
    clock[0] += 500
    st.log("noop")
    assert st.born_at() == 2_000_000.0
    assert st.meta("born_at") == str(2_000_000.0)
    st.db.execute("DELETE FROM events")
    assert st.born_at() == 2_000_000.0


def test_born_at_of_an_empty_world_is_now(tmp_path, clock):
    st = mk(tmp_path)
    assert st.born_at() == clock[0] and st.meta("born_at") == str(clock[0])


# --- reflections ----------------------------------------------------------------------------
def test_reflections_store_filter_order_and_cites(tmp_path, clock):
    st = mk(tmp_path)
    a = st.add_reflection("day", "slow day", 3, 10, 20)
    b = st.add_reflection("day", "good day", 8, 20, 30, grounded=False, support="none", cites=[("event", 4), ("reflection", a)])
    c = st.add_reflection("week", "busy week", 8, 0, 40, support="supported", cites=[("event", 9)])
    r = st.reflections(limit=10)
    assert [x["id"] for x in r] == [c, b, a]
    assert r[2]["ts"] == clock[0] and r[2]["importance"] == 3 and (r[2]["period_start"], r[2]["period_end"]) == (10, 20)
    assert r[2]["grounded"] == 1 and r[2]["support"] == "legacy" and r[1]["grounded"] == 0 and r[1]["support"] == "none"
    assert [x["id"] for x in st.reflections("day")] == [b, a]
    assert [x["id"] for x in st.reflections(by_importance=True)] == [c, b, a]
    assert [x["id"] for x in st.reflections("day", by_importance=True)] == [b, a]
    assert [x["id"] for x in st.reflections(grounded=False)] == [b]
    assert [x["id"] for x in st.reflections(grounded=True)] == [c, a]
    assert [x["id"] for x in st.reflections("day", grounded=True)] == [a]
    assert [x["id"] for x in st.reflections(limit=1)] == [c]
    assert len(st.reflections()) == 3
    assert st.reflection_cites(b) == [("event", 4), ("reflection", a)] and st.reflection_cites(a) == []
    assert st.reflection_text(a) == "slow day" and st.reflection_text(99) is None
    assert [x["text"] for x in st.recall("busy week")] == ["busy week"]


def test_reflections_default_limit_is_twenty(tmp_path, clock):
    st = mk(tmp_path)
    for i in range(22):
        st.add_reflection("day", f"r{i}", 5, 0, 1)
    assert len(st.reflections()) == 20


def test_reflection_is_indexed_at_its_period_end(tmp_path, clock):
    st = mk(tmp_path)
    st.add_reflection("day", "lanterns glow", 5, 10, 777)
    hit = st.recall("lanterns")[0]
    assert hit["source"] == "day" and float(hit["ts"]) == 777


def test_portrait_backfill_keeps_the_old_single_value_as_first_version(tmp_path, clock):
    st = mk(tmp_path)
    st.set_meta(self_portrait="a tinkerer", last_reflection_ts=555.0)
    st._backfill_portraits()
    p = st.reflections("portrait")
    assert len(p) == 1 and p[0]["text"] == "a tinkerer" and p[0]["importance"] == 5
    assert (p[0]["period_start"], p[0]["period_end"]) == (0, 555.0) and p[0]["support"] == "legacy"
    st._backfill_portraits()
    assert len(st.reflections("portrait")) == 1


def test_portrait_backfill_without_reflection_ts_ends_now(tmp_path, clock):
    st = mk(tmp_path)
    st.set_meta(self_portrait="x")
    st._backfill_portraits()
    assert st.reflections("portrait")[0]["period_end"] == clock[0]


def test_portrait_backfill_skips_when_there_is_none(tmp_path, clock):
    st = mk(tmp_path)
    st._backfill_portraits()
    assert st.reflections("portrait") == []


# --- expectations -----------------------------------------------------------------------------
def test_expectations_store_and_filter(tmp_path, clock):
    st = mk(tmp_path)
    a = st.add_expectation("work", 1, "clockmaking", "x" * 250, {"expected": 3, "actual": 5, "error": 0.4, "surprise": "worse"}, event_id=12)
    clock[0] += 10
    b = st.add_expectation("walk", None, "", "pond", {"expected": "frogs", "actual": "none", "error": 0.0, "surprise": None})
    rows = st.expectations()
    assert [r["id"] for r in rows] == [b, a]
    ra = rows[1]
    assert (ra["kind"], ra["project_id"], ra["craft"], ra["expected"], ra["actual"], ra["error"]) == ("work", 1, "clockmaking", "3", "5", 0.4)
    assert len(ra["subject"]) == 200 and ra["surprising"] == 1 and ra["direction"] == "worse" and ra["event_id"] == 12
    assert rows[0]["surprising"] == 0 and rows[0]["direction"] is None and rows[0]["event_id"] is None and rows[0]["ts"] == clock[0]
    assert [r["id"] for r in st.expectations(limit=1)] == [b]
    assert [r["id"] for r in st.expectations(since=clock[0] - 10)] == [b]            # strictly newer
    assert [r["id"] for r in st.expectations(since=clock[0] - 11)] == [b, a]
    assert [r["id"] for r in st.expectations(surprising=True)] == [a]
    assert [r["id"] for r in st.expectations(surprising=False)] == [b]
    assert [r["id"] for r in st.expectations(since=0.0, surprising=True)] == [a]
    assert [r["id"] for r in st.expectations(since=0.0)] == [b, a]


def test_expectations_default_limit_is_fifty(tmp_path, clock):
    st = mk(tmp_path)
    for _ in range(52):
        st.add_expectation("work", None, "", "s", {"expected": 1, "actual": 1, "error": 0, "surprise": None})
    assert len(st.expectations()) == 50


# --- capabilities ------------------------------------------------------------------------------
def test_capability_context_maps_projects_and_stage_abilities(tmp_path, clock):
    st = mk(tmp_path)
    p = make_project(st, craft="kites", stages=[{"name": "frame", "abilities": ["precision"]}, {"name": "tail"}])
    crafts, stages = st.capability_context()
    assert crafts == {p["id"]: "kites"}
    assert stages == {(p["id"], "frame"): ["precision"], (p["id"], "tail"): []}


def test_capability_context_sees_more_than_fifty_projects(tmp_path, clock):
    st = mk(tmp_path)
    for i in range(60):
        make_project(st, f"P{i}")
    assert len(st.capability_context()[0]) == 60


def test_capability_snapshots_newest_first_with_limit(tmp_path, clock):
    st = mk(tmp_path)
    st.save_capabilities("2026-01-01", {"a": 1})
    st.save_capabilities("2026-01-03", {"a": 3})
    st.save_capabilities("2026-01-02", {"a": 2})
    st.save_capabilities("2026-01-03", {"a": 33})                                   # replaces
    assert st.capability_snapshots() == [("2026-01-03", {"a": 33}), ("2026-01-02", {"a": 2})]
    assert st.capability_snapshots(limit=3)[2] == ("2026-01-01", {"a": 1})
    assert st.capability_snapshots(limit=1) == [("2026-01-03", {"a": 33})]


# --- night pass decisions and focus ----------------------------------------------------------
def test_decisions_roundtrip_filter_and_showings(tmp_path, clock):
    st = mk(tmp_path)
    a = st.add_decision("archive", "memory", 5, {"x": 1}, {"was": "open"}, "stale", [["event", 1]], "archived it", True)
    b = st.add_decision("merge", "", None, {}, {}, "", [], "", False)
    d = st.decision(a)
    assert d["op"] == "archive" and d["target_kind"] == "memory" and d["target_id"] == 5 and d["args"] == {"x": 1}
    assert d["before"] == {"was": "open"} and d["reason"] == "stale" and d["cites"] == [["event", 1]]
    assert d["summary"] == "archived it" and d["applied"] == 1 and d["undone"] == 0 and d["shown"] == 0 and d["ts"] == clock[0]
    assert st.decision(99) is None
    assert st.decision(b)["applied"] == 0 and st.decision(b)["target_id"] is None
    assert [x["id"] for x in st.decisions()] == [b, a]
    assert [x["id"] for x in st.decisions(applied=True)] == [a]
    assert [x["id"] for x in st.decisions(applied=False)] == [b]
    assert [x["id"] for x in st.decisions(limit=1)] == [b]
    assert [x["id"] for x in st.unseen_decisions(24, 2)] == [a]
    st.mark_decisions_shown([a])
    assert [x["id"] for x in st.unseen_decisions(24, 2)] == [a]
    st.mark_decisions_shown([a])
    assert st.unseen_decisions(24, 2) == []                                         # shown < showings
    c = st.add_decision("x", "", None, {}, {}, "", [], "", True)
    st.mark_decision_undone(c)
    assert st.decision(c)["undone"] == 1 and st.decision(a)["undone"] == 0
    assert [x["id"] for x in st.unseen_decisions(24, 2)] == []
    clock[0] += 24 * 3600 - 1
    d2 = st.add_decision("y", "", None, {}, {}, "", [], "", True)
    assert [x["id"] for x in st.unseen_decisions(24, 5)] == [a, d2]
    clock[0] += 2
    assert [x["id"] for x in st.unseen_decisions(24, 5)] == [d2]                    # a is older than 24h


def test_decisions_default_limit_is_twenty(tmp_path, clock):
    st = mk(tmp_path)
    for _ in range(22):
        st.add_decision("x", "", None, {}, {}, "", [], "", True)
    assert len(st.decisions()) == 20


def test_unseen_decisions_age_boundary_is_inclusive(tmp_path, clock):
    st = mk(tmp_path)
    a = st.add_decision("x", "", None, {}, {}, "", [], "", True)
    clock[0] += 3600
    assert [d["id"] for d in st.unseen_decisions(1, 1)] == [a]
    clock[0] += 1
    assert st.unseen_decisions(1, 1) == []


def test_focus_lifecycle(tmp_path, clock):
    st = mk(tmp_path)
    a = st.add_focus("2026-01-01", "finish the clock", "project", 3)
    b = st.add_focus("2026-01-02", "water plants")
    f = st.focus()
    assert [x["id"] for x in f] == [a, b]
    assert (f[0]["day"], f[0]["text"], f[0]["ref_kind"], f[0]["ref_id"], f[0]["status"]) == ("2026-01-01", "finish the clock", "project", 3, "open")
    assert f[0]["decided_at"] == clock[0] and f[0]["reviewed_at"] is None and f[1]["ref_kind"] == "" and f[1]["ref_id"] is None
    st.close_focus(a, "done", "n" * 300)
    assert [x["id"] for x in st.focus()] == [b]
    done = st.focus("done")[0]
    assert done["id"] == a and len(done["note"]) == 200 and done["reviewed_at"] == clock[0]
    assert [x["id"] for x in st.focus(None)] == [a, b]
    assert [x["id"] for x in st.focus(None, limit=1)] == [b]
    st.close_focus(b, "dropped")
    assert st.focus("dropped")[0]["note"] == ""


def test_focus_default_limit_is_twenty(tmp_path, clock):
    st = mk(tmp_path)
    for i in range(22):
        st.add_focus("d", str(i))
    got = st.focus()
    assert len(got) == 20 and got[-1]["text"] == "21"


# --- works --------------------------------------------------------------------------------------
def test_works_store_and_filter(tmp_path, clock):
    st = mk(tmp_path)
    pic = st.add_work("picture", "Sunrise", "<svg>big</svg>", "orange sky", "hill")
    clock[0] += 10
    poem = st.add_work("writing", "Ode", "roses are red", "short", "")
    w = st.work(pic)
    assert w["kind"] == "picture" and w["title"] == "Sunrise" and w["body"] == "<svg>big</svg>" and w["caption"] == "orange sky"
    assert w["location"] == "hill" and w["revisions"] == 0 and w["ts"] == 2_000_000.0
    assert st.work(99) is None
    rows = st.works()
    assert [r["id"] for r in rows] == [poem, pic]
    assert rows[1]["body"] == "" and rows[0]["body"] == "roses are red"
    assert rows[1]["caption"] == "orange sky" and rows[1]["location"] == "hill" and set(rows[0]) == {"id", "ts", "kind", "title", "caption", "location", "body"}
    assert [r["id"] for r in st.works("picture")] == [pic]
    assert [r["id"] for r in st.works(limit=1)] == [poem]
    assert [r["id"] for r in st.works(since=clock[0])] == [poem]                    # inclusive
    assert [r["id"] for r in st.works(since=clock[0] + 1)] == []
    assert [r["id"] for r in st.works("writing", since=0)] == [poem]
    assert [r["id"] for r in st.works("picture", since=clock[0])] == []


def test_works_default_limit_is_fifty(tmp_path, clock):
    st = mk(tmp_path)
    for i in range(52):
        st.add_work("writing", str(i), "b")
    assert len(st.works()) == 50


def test_work_indexing_includes_body_only_for_writing(tmp_path, clock):
    st = mk(tmp_path)
    st.add_work("picture", "Sunrise", "zorkblat", "orange sky")
    st.add_work("writing", "Ode", "quillfeather", "short")
    assert st.recall("zorkblat") == []
    pic = st.recall("sunrise")[0]
    assert pic["text"] == "Sunrise. orange sky" and pic["source"] == "work:picture"
    wr = st.recall("quillfeather")[0]
    assert wr["text"] == "Ode. short quillfeather" and wr["source"] == "work:writing"
    st.add_work("picture", "Bare", "x")
    assert st.recall("bare")[0]["text"] == "Bare."


def test_revise_work_replaces_and_counts(tmp_path, clock):
    st = mk(tmp_path)
    w = st.add_work("picture", "Sunrise", "<svg>1</svg>", "orange")
    assert st.revise_work(w, "<svg>2</svg>") == 1
    got = st.work(w)
    assert got["body"] == "<svg>2</svg>" and got["title"] == "Sunrise" and got["caption"] == "orange" and got["revisions"] == 1
    assert st.revise_work(w, "<svg>3</svg>", title="Dawn", caption="") == 2
    got = st.work(w)
    assert got["title"] == "Dawn" and got["caption"] == "" and got["revisions"] == 2
    assert st.recall("dawn")[0]["text"] == "Dawn." and st.recall("sunrise") == []
    assert st.revise_work(w, "b", caption="new words") == 3
    assert st.work(w)["caption"] == "new words" and st.work(w)["title"] == "Dawn"
    assert st.recall("words")[0]["text"] == "Dawn. new words"


# --- outreach ---------------------------------------------------------------------------------------
def test_outreach_rows_filters(tmp_path, clock):
    st = mk(tmp_path)
    a = st.add_outreach("greeting", "matrix", "!room", "hi", "sent")
    clock[0] += 10
    b = st.add_outreach("news", "matrix", "", "x", "failed", error="e" * 400)
    clock[0] += 10
    c = st.add_outreach("greeting", "web", "", "y", "skipped", ts=5.0)
    rows = st.outreach_rows()
    assert [r["id"] for r in rows] == [c, b, a]
    assert rows[2]["conversation"] == "!room" and rows[2]["text"] == "hi" and rows[2]["error"] == "" and rows[2]["ts"] == 2_000_000.0
    assert len(rows[1]["error"]) == 300 and rows[0]["ts"] == 5.0
    assert [r["id"] for r in st.outreach_rows(limit=1)] == [c]
    assert [r["id"] for r in st.outreach_rows(kind="greeting")] == [c, a]
    assert [r["id"] for r in st.outreach_rows(since=2_000_010.0)] == [b]             # inclusive; c has ts 5
    assert [r["id"] for r in st.outreach_rows(statuses=("sent", "skipped"))] == [c, a]
    assert [r["id"] for r in st.outreach_rows(statuses=("failed",))] == [b]
    assert [r["id"] for r in st.outreach_rows(kind="greeting", statuses=("sent",))] == [a]
    assert [r["id"] for r in st.outreach_rows(kind="greeting", since=0.0, statuses=("sent",))] == [a]
    assert [r["id"] for r in st.outreach_rows(since=0.0)] == [c, b, a]


def test_outreach_default_limit_is_fifty(tmp_path, clock):
    st = mk(tmp_path)
    for _ in range(52):
        st.add_outreach("k", "c", "", "t", "sent")
    assert len(st.outreach_rows()) == 50


# --- place finds ------------------------------------------------------------------------------------
def test_finds_count_and_order(tmp_path, clock):
    st = mk(tmp_path)
    st.add_find("pond", "Smooth Pebble")
    clock[0] += 5
    st.add_find("pond", "smooth pebble")
    st.add_find("pond", "reed")
    st.add_find("hill", "reed", ts=9.0)
    pond = st.finds_at("pond")
    assert [(f["item"], f["times"]) for f in pond] == [("smooth pebble", 2), ("reed", 1)]
    assert pond[0]["last_ts"] == clock[0] and st.finds_at("hill")[0]["last_ts"] == 9.0
    assert st.finds_at("nowhere") == []
    clock[0] += 5
    st.add_find("pond", "stick")
    assert [f["item"] for f in st.finds_at("pond")] == ["smooth pebble", "stick", "reed"]    # ties: newest first
    assert [r["place"] for r in st.found_where("reed bed")] == ["pond", "hill"]
    assert st.found_where("quartz") == []
    assert [r["place"] for r in st.found_where("smooth stone")] == ["pond"]


# --- turning points, day stats ---------------------------------------------------------------------
def test_turning_points(tmp_path, clock):
    st = mk(tmp_path)
    a = st.add_turning(3, ["s1"], 10, 20)
    b = st.add_turning(7, [], 20, 30)
    rows = st.turning_points()
    assert [r["id"] for r in rows] == [b, a]
    assert rows[1]["score"] == 3 and rows[1]["signals"] == ["s1"] and (rows[1]["period_start"], rows[1]["period_end"]) == (10, 20)
    assert rows[1]["ts"] == clock[0]
    assert [r["id"] for r in st.turning_points(limit=1)] == [b]
    for _ in range(22):
        st.add_turning(1, [], 0, 1)
    assert len(st.turning_points()) == 20


def test_day_stats_returns_recent_days_oldest_first(tmp_path, clock):
    st = mk(tmp_path)
    for d in ("2026-01-01", "2026-01-02", "2026-01-03", "2026-01-04"):
        st.save_day_stats(d, {"d": d})
    st.save_day_stats("2026-01-04", {"d": "again"})
    assert st.day_stats() == [("2026-01-02", {"d": "2026-01-02"}), ("2026-01-03", {"d": "2026-01-03"}), ("2026-01-04", {"d": "again"})]
    assert st.day_stats(limit=1) == [("2026-01-04", {"d": "again"})]


# --- people and recall ------------------------------------------------------------------------------
def test_people_upsert_keeps_first_seen_and_latest_last_seen(tmp_path, clock):
    st = mk(tmp_path)
    st.upsert_person("Ada", "likes kites", 100.0)
    st.upsert_person("Bob", "baker", 200.0)
    st.upsert_person("Ada", "likes boats", 50.0)                                   # older sighting: last_seen stays
    people = st.people()
    assert [p["name"] for p in people] == ["Bob", "Ada"]
    ada = people[1]
    assert ada["notes"] == "likes boats" and ada["first_seen"] == 100.0 and ada["last_seen"] == 100.0
    st.upsert_person("Ada", "likes boats", 300.0)
    assert st.people()[0]["name"] == "Ada" and st.people()[0]["last_seen"] == 300.0 and st.people()[0]["first_seen"] == 100.0
    hit = st.recall("boats")[0]
    assert hit["text"] == "Ada: likes boats" and hit["source"] == "person" and hit["ref"] == "Ada" and float(hit["ts"]) == 300.0


def test_index_replaces_the_previous_entry_for_the_same_thing(tmp_path, clock):
    st = mk(tmp_path)
    m = st.add_memory("alpha banana", "todo")
    st.edit_memory(m, "gamma delta")
    assert st.recall("banana") == []
    assert [r["text"] for r in st.recall("gamma")] == ["gamma delta"]
    other = st.add_memory("gamma epsilon", "wishlist")
    assert len(st.recall("gamma")) == 2 and other


def test_recall_query_handling(tmp_path, clock):
    st = mk(tmp_path)
    for i, t in enumerate(["red kite flying", "blue kite string", "green boat sailing", "the quick fox"]):
        clock[0] += 1
        st.add_memory(t)
    assert st.recall("") == [] and st.recall("a the of") == [] and st.recall("!!!") == []
    got = st.recall("kite")
    assert [r["text"] for r in got] == ["red kite flying", "blue kite string"]          # oldest first
    assert set(got[0]) == {"text", "source", "ref", "ts"}
    assert [r["text"] for r in st.recall("kit")] == ["red kite flying", "blue kite string"]   # prefix match
    assert len(st.recall("kite boat")) == 3
    assert len(st.recall("kite", limit=1)) == 1
    assert len(st.recall("kite boat fox", limit=2)) == 2
    assert [r["text"] for r in st.recall("KITE KITE")] == ["red kite flying", "blue kite string"]
    assert st.recall("x") == []                                                          # one-letter words are ignored
    words = " ".join(f"zz{i}" for i in range(12))
    st.add_memory("late word qqq")
    assert st.recall(words + " qqq") == []                                               # only the first twelve terms count
    assert st.recall(words.replace("zz0", "qqq")) != []
    st.add_memory("tw tw")
    assert st.recall("tw") != []                                                         # two letters is enough
    assert len(st.recall("kite")) == 2


def test_recall_default_limit_is_five(tmp_path, clock):
    st = mk(tmp_path)
    for i in range(7):
        st.add_memory(f"lantern {i}")
    assert len(st.recall("lantern")) == 5


def test_recall_backfill_rebuilds_from_everything(tmp_path, clock):
    st = mk(tmp_path)
    m = st.add_memory("brass gears", "wishlist")
    st.resolve_memory(m, "found some")
    n = st.add_memory("copper pipes", "todo")
    st.resolve_memory(n)
    st.log("say", text="hello wanderer", to_name="")
    st.add_reflection("day", "quiet reflection", 5, 0, 99)
    st.upsert_person("Ada", "gardener", 10.0)
    st.db.execute("DELETE FROM recall_index")
    st.db.execute("DELETE FROM meta WHERE key = 'recall_indexed'")
    st.db.commit()
    st._backfill_recall()
    assert st.meta("recall_indexed") == "2"
    texts = {r["text"] for r in st.recall("brass gears copper pipes hello wanderer quiet reflection ada gardener", limit=20)}
    assert "brass gears (done: found some)" in texts and "copper pipes" in texts
    assert "quiet reflection" in texts and "Ada: gardener" in texts
    ev = [r for r in st.recall("wanderer")]
    assert len(ev) == 1 and ev[0]["source"] == "event:say"
    assert st.recall("brass")[0]["source"] == "note:wishlist" and st.recall("quiet")[0]["source"] == "day"
    assert float(st.recall("quiet")[0]["ts"]) == 99


def test_open_notes_are_not_marked_done_in_the_rebuilt_index(tmp_path, clock):
    st = mk(tmp_path)
    st.add_memory("brass gears", "wishlist")
    st.db.execute("UPDATE memories SET outcome = 'leftover'")
    st.db.commit()
    st._backfill_recall()
    assert st.recall("brass")[0]["text"] == "brass gears"


def test_reopening_a_world_rebuilds_the_recall_index_when_version_is_stale(tmp_path, clock):
    st = mk(tmp_path)
    st.add_memory("brass gears")
    st.db.execute("DELETE FROM recall_index")
    st.set_meta(recall_indexed="1")
    st.db.close()
    st2 = mk(tmp_path)
    assert [r["text"] for r in st2.recall("brass")] == ["brass gears"]
    assert st2.meta("recall_indexed") == "2"


def test_reopening_a_current_world_leaves_the_recall_index_alone(tmp_path, clock):
    st = mk(tmp_path)
    st.add_memory("brass gears")
    st.db.execute("DELETE FROM recall_index")
    st.db.commit()
    st.db.close()
    assert mk(tmp_path).recall("brass") == []


def test_reopening_keeps_state_and_does_not_reset_the_agent(tmp_path, clock):
    st = mk(tmp_path)
    st.update_agent(mood="grumpy", location="garden")
    st.db.close()
    a = mk(tmp_path).agent()
    assert a["mood"] == "grumpy" and a["location"] == "garden"


def test_explicit_path_overrides_settings(tmp_path, clock):
    other = tmp_path / "other.db"
    st = State(Settings(db_path=str(tmp_path / "s.db"), sleep=False), path=str(other))
    st.add_memory("here")
    assert other.exists() and not (tmp_path / "s.db").exists()


# --- usage ---------------------------------------------------------------------------------------------
def test_usage_accumulates_per_day_and_budget(tmp_path, clock):
    st = mk(tmp_path, daily_token_budget=100)
    day = date.today().isoformat()
    assert st.usage_today() == {"day": day, "input_tokens": 0, "output_tokens": 0, "calls": 0, "total_tokens": 0, "budget": 100}
    assert st.budget_exceeded() is False
    st.add_usage(30, 20)
    st.add_usage(10, 5)
    u = st.usage_today()
    assert (u["input_tokens"], u["output_tokens"], u["calls"], u["total_tokens"], u["day"]) == (40, 25, 2, 65, day)
    assert st.budget_exceeded() is False
    st.add_usage(20, 15)
    assert st.usage_today()["total_tokens"] == 100 and st.budget_exceeded() is True     # at the budget counts as exceeded
