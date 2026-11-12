"""Tools: the remaining edges of busy-handling, note checks, tool offers and the tool list."""
import pytest

from app import library as lib
from app import tools as T
from test_library import calibre
from test_mut_projects_flow import StubGM, add as add_project, begin
from test_mut_tools_core import make, clock  # noqa: F401
from test_mut_tools_registry import settings


class ReadGM(StubGM):
    async def read_summary(self, title, authors, text, percent):
        return {"summary": "A summary from the narrator.", "quotes": []}


async def test_putting_a_book_down_early_still_records_what_was_read(tmp_path, clock):
    path = calibre(tmp_path / "calibre")
    ctx, st = make(tmp_path, library_path=path, work_speed=60.0, read_chars_per_minute=10)
    ctx.library = lib.open_library(ctx.settings)
    ctx.gm = ReadGM()
    lib.start_reading(st, ctx.settings, ctx.library.book(1), 60)
    clock[0] += 3600                                                     # an hour at work_speed 60: the full hour
    note = await T.stop_working(ctx)
    assert note == " (you put The Beekeeper's Year down early)"
    ev = [e for e in st.events(limit=5) if e["kind"] == "reading"][0]["data"]
    assert ev["interrupted"] is True and ev["summary"] == "A summary from the narrator."
    assert ev["percent"] > 0 and st.bookmark(1)["sessions"] == 1


async def test_an_experiment_whose_project_is_gone_leaves_no_note(tmp_path, clock):
    ctx, st = make(tmp_path)
    st.start_session(404, -1, 30, clock[0] + 1800, kind="experiment", target="x")
    assert await T.stop_working(ctx) == ""
    st.start_session(404, 0, 30, clock[0] + 1800, kind="work")
    assert await T.stop_working(ctx) == ""


def test_a_closed_place_hides_its_own_tools_even_when_they_come_first():
    tools = {n: T.REGISTRY[n] for n in ("read", "say")}

    class P:
        scope = "library"
        verbs = {}
    assert [s.name for s in T.specs_for(tools, "library", place=P(), open_=False)] == ["say"]
    assert [s.name for s in T.specs_for(tools, "library", place=P(), open_=True)] == ["read", "say"]


def test_a_tool_nobody_scoped_works_anywhere():
    from app.llm.base import ToolSpec
    spec = ToolSpec("unlisted_thing", "d", {})
    assert [s.name for s in T.specs_for({"unlisted_thing": (spec, None)}, "library")] == ["unlisted_thing"]


def test_a_finished_diary_entry_still_counts_for_the_near_copy_check(tmp_path, clock):
    ctx, st = make(tmp_path)
    d = st.add_memory("watched the heron fish at dawn", "diary")
    st.set_memory_status(d, "done")
    assert T.check_note(ctx, "diary", "watched the heron fish at dawn!") == f"too close to your note #{d}; only write something new"


def test_the_near_copy_check_reads_ten_diary_entries_and_forty_open_notes(tmp_path, clock):
    ctx, st = make(tmp_path)
    first = st.add_memory("an entry about moths at the lamp", "diary")
    for i in range(9):
        st.add_memory(f"filler {i} qxz{i}wv plain different", "diary")
    assert T.check_note(ctx, "diary", "an entry about moths at the lamp") != ""          # tenth newest: checked
    st.add_memory("another filler zzz", "diary")
    assert T.check_note(ctx, "diary", "an entry about moths at the lamp") == ""          # eleventh: out of sight
    assert first
    (tmp_path / "second").mkdir()
    ctx2, st2 = make(tmp_path / "second")
    st2.add_memory("sweep out the quiet workshop", "todo")
    for i in range(10):
        st2.add_memory(f"unrelated task {i} qxz{i}wv something else entirely", "todo")
    assert T.check_note(ctx2, "todo", "sweep out the quiet workshop") != ""             # beyond ten, within forty
    for i in range(30):
        st2.add_memory(f"another unrelated task {i} rrv{i}ww something else entirely", "todo")
    assert T.check_note(ctx2, "todo", "sweep out the quiet workshop") == ""             # forty-first: out of sight


def test_the_restatement_message_quotes_ninety_characters(tmp_path, clock):
    ctx, st = make(tmp_path)
    long = "alpha bravo charlie delta " * 5
    n = st.add_memory(long.strip(), "todo")
    msg = T.check_note(ctx, "todo", "bravo alpha delta charlie please do this soon, it matters a lot, really")
    assert msg == (f"this is about the same thing as your open todo #{n} (\"{long.strip()[:90]}\"): "
                   f"edit_note #{n} to update it, or resolve_note it first if it's done")


def test_enabled_tools_skips_unavailable_ones_without_stopping(tmp_path):
    s = settings(tmp_path, tools=["say", "say", "eat", "web_search", "rest", "sleep", "note_to_self", "send_postcard",
                                  "set_activity", "browse", "recall", "read", "where_to"],
                 sleep=False, tavily_api_key="", outreach="off", outreach_channels=[])
    assert list(T.enabled_tools(s)) == ["say", "eat", "rest", "note_to_self", "set_activity", "recall", "where_to"]
