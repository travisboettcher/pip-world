"""Tools: where a tool works, being busy, journal checks and the simple everyday tools."""
import time
from datetime import datetime

import pytest

from app import tools as T
from app.config import Settings
from app.state import State
from test_mut_projects_flow import OneRoll, StubGM, add as add_project, begin  # noqa: F401


NOON = datetime(2026, 3, 4, 12, 0).timestamp()
THREE_AM = datetime(2026, 3, 4, 3, 0).timestamp()


@pytest.fixture
def clock(monkeypatch):
    now = [NOON]
    monkeypatch.setattr(time, "time", lambda: now[0])
    return now


def make(tmp_path, **kw):
    kw.setdefault("sleep", False)
    s = Settings(db_path=str(tmp_path / "t.db"), **kw)
    st = State(s)
    return T.ToolContext(st, s, rng=OneRoll(0.5)), st


async def run(ctx, name, **args):
    return await T.REGISTRY[name][1](ctx, args)


# --- scopes -----------------------------------------------------------------------------------
def test_tools_declare_where_they_work():
    assert T.SCOPES["say"] == ("anywhere",) and T.SCOPES["eat"] == ("anywhere",)
    assert T.SCOPES["sleep"] == ("home",) and "plant" not in T.SCOPES                          # planting is the garden module's
    assert T.SCOPES["work_on"] == ("home",) and T.SCOPES["experiment"] == ("home",) and T.SCOPES["tend"] == ("home",)
    assert T.SCOPES["browse"] == ("library", "junkyard", "neighbor") and T.SCOPES["buy"] == T.SCOPES["sell"] == ("market", "neighbor") and T.SCOPES["read"] == ("library",)
    assert "gather" not in T.SCOPES                                                 # gathering is a module's (0.36.0)


def test_is_here():
    assert T.is_here(("anywhere",), "library") and T.is_here(("home",), "workshop")
    assert not T.is_here(("home",), "library") and T.is_here(("library", "junkyard"), "junkyard")
    assert T.is_here(("neighbor",), "Ada's home") and not T.is_here(("home",), "Ada's home")


async def test_a_tool_used_from_the_wrong_place_says_where_to_go(tmp_path, clock):
    ctx, st = make(tmp_path)
    st.update_agent(location="library")
    r = await run(ctx, "tend", creation="x")
    assert r.text == "you're at the library; go_to home first" and r.followup is True
    st.update_agent(location="workshop")
    r = await run(ctx, "read", book="x")
    assert r.text == "you're not at the library; go_to library first" and r.followup is True


def test_out_of_place_for_unscoped_names_is_always_fine(tmp_path, clock):
    ctx, st = make(tmp_path)
    st.update_agent(location="library")
    assert T.out_of_place(ctx, "no_such_tool") == ""
    assert T.out_of_place(ctx, "say") == ""


async def test_a_wild_place_is_closed_in_the_dark(tmp_path, clock):
    ctx, st = make(tmp_path)
    st.update_agent(location="junkyard")
    clock[0] = THREE_AM
    assert T.out_of_place(ctx, "browse") == "the junkyard is closed for now (it's dark); it opens in the morning"
    r = await run(ctx, "browse")
    assert r.followup is True and "closed for now" in r.text
    clock[0] = NOON
    assert T.out_of_place(ctx, "browse") == ""
    clock[0] = THREE_AM
    assert T.out_of_place(ctx, "say") == ""                          # a tool that works anywhere is not shut out


def test_specs_for_offers_what_belongs_to_the_place(tmp_path, clock):
    ctx, st = make(tmp_path)
    tools = {n: T.REGISTRY[n] for n in ("say", "tend", "read", "browse")}
    names = lambda loc, **kw: sorted(s.name for s in T.specs_for(tools, loc, **kw))
    assert names("workshop") == ["say", "tend"]
    assert names("woods") == ["say"]
    assert names("junkyard") == ["browse", "say"]

    class P:
        scope = "junkyard"
        verbs = {"browse": ("short", "Look over the heaps.")}
    out = {s.name: s for s in T.specs_for(tools, "junkyard", place=P())}
    assert out["browse"].description == "Look over the heaps." and out["say"].description == T.REGISTRY["say"][0].description
    assert out["browse"].parameters == T.REGISTRY["browse"][0].parameters
    assert sorted(s.name for s in T.specs_for(tools, "junkyard", place=P(), open_=False)) == ["say"]     # closed: nothing of its own

    class Q:
        scope = "junkyard"
        verbs = {}
    assert {s.name: s for s in T.specs_for(tools, "junkyard", place=Q())}["browse"].description == T.REGISTRY["browse"][0].description
    assert sorted(s.name for s in T.specs_for(tools, "workshop", place=P(), open_=False)) == ["say", "tend"]


# --- busy --------------------------------------------------------------------------------------
def test_busy_says_what_pip_is_in_the_middle_of(tmp_path, clock):
    ctx, st = make(tmp_path)
    assert T.busy(ctx) == ""
    st.start_session(0, 0, 10, clock[0] + 600, kind="walk", target="library")
    assert T.busy(ctx) == "you're on your way to the library (about 10 min to go)"
    clock[0] += 570
    assert T.busy(ctx) == "you're on your way to the library (about 1 min to go)"      # never less than a minute
    clock[0] += 29
    assert T.busy(ctx) == "you're on your way to the library (about 1 min to go)"
    st.start_session(0, 0, 10, clock[0] + 90, kind="walk", target="library")
    assert "about 2 min to go" in T.busy(ctx)
    st.start_session(5, 0, 30, clock[0] + 1800, kind="read", target="Moby Dick")
    assert T.busy(ctx) == "you're reading Moby Dick (about 30 min left); rest stops early"
    st.start_session(0, 0, 30, clock[0] + 1800, kind="module", target="gathering", expect="out foraging at the woods")
    assert T.busy(ctx) == "you're out foraging at the woods (about 30 min left); rest stops early"
    p = add_project(st)
    st.start_session(p["id"], 0, 30, clock[0] + 1800, kind="experiment", target="h")
    assert T.busy(ctx) == "you're in the middle of an experiment on Clock (about 30 min left); rest stops early"
    st.start_session(999, 0, 30, clock[0] + 1800, kind="experiment", target="h")
    assert "an experiment on something (about" in T.busy(ctx)
    st.start_session(p["id"], 0, 30, clock[0] + 1800, kind="work")
    assert T.busy(ctx) == "you're in the middle of working on Clock (about 30 min left); rest stops early"
    st.start_session(999, 0, 30, clock[0] + 1800, kind="work")
    assert "working on something (about" in T.busy(ctx)


async def test_stop_working_reports_what_was_cut_short(tmp_path, clock):
    ctx, st = make(tmp_path)
    assert await T.stop_working(ctx) == ""
    p = add_project(st)
    begin(st, p, minutes=30, started_at=clock[0])
    assert await T.stop_working(ctx) == " (you stopped working on Clock early)"
    assert st.session() is None
    begin(st, p, kind="experiment", target="soak it", minutes=30, started_at=clock[0])
    assert await T.stop_working(ctx) == " (you cut the experiment on Clock short)"
    st.start_session(0, 0, 30, clock[0] + 1800, kind="module", target="gone", expect="out foraging at the woods")
    assert await T.stop_working(ctx) == " (you stopped out foraging at the woods early)"
    st.start_session(0, 0, 30, clock[0] + 1800, kind="walk", target="library")
    assert await T.stop_working(ctx) == ""
    st.start_session(77, 0, 30, clock[0] + 1800, kind="read", target="Moby")
    assert await T.stop_working(ctx) == " (you put Moby down early)"


# --- the journal checks ----------------------------------------------------------------------------
def test_content_words_are_meaningful_distinct_stems():
    assert T.content_words("Fix the Gates, fix gates!") == {"gate"}
    assert T.content_words("find a tiny needle files and the kites") == {"find", "tiny", "needle", "file", "kite"}
    assert T.content_words("a an the cat") == set()
    assert T.content_words("their about with") == set()                     # filler words


def test_overlapping_needs_three_shared_words_and_sixty_percent_of_the_shorter():
    a = "repair the brass clock pendulum soon"
    assert T.overlapping(a, "fix brass clock pendulum soon") is True               # shares brass, clock, pendulum, soon
    assert T.overlapping(a, "brass clock soon") is True                             # 3 shared, all of the shorter's words
    assert T.overlapping("brass clock gears wheel spring", "brass clock gears tower window bell") is True    # 3 of 5 = exactly 0.6
    assert T.overlapping("brass clock gears wheel", "brass clock gears tower window bell") is True            # 3 of 4
    assert T.overlapping("brass clock", "brass clock gears") is False                # only two shared
    assert T.overlapping("", "") is False
    assert T.overlapping("brass clock gears wheel spring tower", "brass clock gears window bell door") is False


def test_overlap_threshold_is_exactly_sixty_percent():
    # 3 shared of a shorter note with 5 content words is exactly 0.6: counts
    assert T.overlapping("alpha bravo charlie delta echoes", "alpha bravo charlie foxtrot golfing hotel india") is True
    assert T.overlapping("alpha bravo charlie delta echoes foxtrot", "alpha bravo charlie golfing hotel india") is False


def test_stat_numbers_pattern():
    assert T.STAT_NUMBERS.search("hunger is 0.4 today") and T.STAT_NUMBERS.search("Energy: 0.8")
    assert T.STAT_NUMBERS.search("my energy was low at 0.2")
    assert not T.STAT_NUMBERS.search("hunger is high") and not T.STAT_NUMBERS.search("version 1.5 shipped")
    assert not T.STAT_NUMBERS.search("energy " + "x" * 20 + " 0.5")                  # too far apart


def test_check_note_refuses_numbers_near_copies_and_restatements(tmp_path, clock):
    ctx, st = make(tmp_path)
    assert T.check_note(ctx, "diary", "energy at 0.5 now") == "don't write hunger/energy numbers in notes - your stats are already tracked for you"
    n = st.add_memory("fix the garden gate before winter", "todo")
    assert T.check_note(ctx, "todo", "fix the garden gate before winter!") == \
        f"too close to your note #{n}; only write something new (edit_note #{n} to update it)"
    again = T.check_note(ctx, "todo", "before winter: the gate and garden need attention please")
    assert again == (f"this is about the same thing as your open todo #{n} (\"fix the garden gate before winter\"): "
                     f"edit_note #{n} to update it, or resolve_note it first if it's done")
    assert T.check_note(ctx, "todo", "buy flour") == ""
    st.resolve_memory(n)
    assert T.check_note(ctx, "todo", "fix the garden gate before winter") == ""      # resolved ones no longer count
    d = st.add_memory("saw a heron by the pond today", "diary")
    assert T.check_note(ctx, "diary", "saw a heron by the pond today!") == f"too close to your note #{d}; only write something new"
    assert T.check_note(ctx, "diary", "pond heron today saw quiet morning mist wind everything") == ""                     # no overlap rule for the diary
    l = st.add_memory("wire bends when heated", "learned")
    assert T.check_note(ctx, "learned", "wire bends when heated.") == \
        f"too close to your note #{l}; only write something new (edit_note #{l} to update it)"


def test_check_note_looks_at_a_bounded_number_of_notes(tmp_path, clock):
    ctx, st = make(tmp_path)
    st.add_memory("paint the old fence green", "todo")
    for i in range(40):
        st.add_memory(f"unrelated chore number {i} entirely different words {'abcdefghij'[i % 10]}{i}", "todo")
    assert T.check_note(ctx, "todo", "paint the old fence green") == ""              # the oldest is beyond the 40 checked
    for i in range(10):
        st.add_memory(f"diary line {i} zzz{i}", "diary")
    st.add_memory("a rare diary entry about moths", "diary")
    assert T.check_note(ctx, "diary", "a rare diary entry about moths") != ""        # within the latest ten


def test_check_note_is_below_the_similarity_limit_at_a_clear_difference(tmp_path, clock):
    ctx, st = make(tmp_path)
    st.add_memory("abcdefghij", "diary")
    assert T.check_note(ctx, "diary", "abcdefgxyz") != ""                            # ratio 0.7: too close
    assert T.check_note(ctx, "diary", "abcdexxxxx") == ""                            # ratio 0.5: different enough
    assert T.check_note(ctx, "diary", "abcdefxxxx") != ""                            # ratio 0.6 exactly: still too close
