"""Tools: the remaining edges of busy-handling, note checks, tool offers and the tool list."""

from app import tools as T
from test_mut_tools_core import make, clock  # noqa: F401
from test_mut_tools_registry import settings


async def test_an_experiment_whose_project_is_gone_leaves_no_note(tmp_path, clock):
    ctx, st = make(tmp_path)
    st.start_session(404, -1, 30, clock[0] + 1800, kind="experiment", target="x")
    assert await T.stop_working(ctx) == ""
    st.start_session(404, 0, 30, clock[0] + 1800, kind="work")
    assert await T.stop_working(ctx) == ""


def test_a_closed_place_hides_its_own_tools_even_when_they_come_first():
    tools = {n: T.REGISTRY[n] for n in ("browse", "say")}

    class P:
        scope = "junkyard"
        verbs = {}
    assert [s.name for s in T.specs_for(tools, "junkyard", place=P(), open_=False)] == ["say"]
    assert [s.name for s in T.specs_for(tools, "junkyard", place=P(), open_=True)] == ["browse", "say"]


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
    assert list(T.enabled_tools(s)) == ["say", "eat", "rest", "note_to_self", "set_activity", "browse", "recall", "where_to"]
