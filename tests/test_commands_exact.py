"""The exact replies: they are what the owner reads on a phone, so the wording and layout are the behaviour."""
from datetime import datetime

from app import commands
from tests.test_projects import given, make


def at(hour):
    return datetime(2026, 11, 2, hour, 30).timestamp()


def clear_items(st):
    with st.lock:
        st.db.execute("DELETE FROM items")
        st.db.commit()


def test_help_text(tmp_path):
    s, st, *_ = make(tmp_path)
    assert commands.answer(st, s, "/help") == (
        "Commands (answered by the engine, not by Pip):\n"
        "/help: this list\n"
        "/status: what Pip is doing and how it is\n"
        "/items: what Pip owns\n"
        "/projects: projects in progress\n"
        "/creations: what Pip has made\n"
        "/notes: open to-dos, wishes and ambitions (or /notes diary|learned|todo|wishlist|ambitions)\n"
        "/emotions: Pip's emotion state\n"
        "/usage: today's token use against the budget")


def test_unknown_command_text(tmp_path):
    s, st, *_ = make(tmp_path)
    assert commands.answer(st, s, "/Frobnicate now") == "I don't know /frobnicate. Try /help."


def test_status_text_with_and_without_the_day_rhythm(tmp_path):
    s, st, *_ = make(tmp_path, sleep=True)
    s.bedtime_hour, s.wake_hour = 22, 6
    st.set_meta(born_at=at(0))
    st.update_agent(activity="working", description="Gear clock: fit the escapement", mood="hopeful",
                    hunger=0.17, energy=0.95, location="workshop")
    assert commands.answer(st, s, "/status", at(14)) == (
        "Status\nPip is working: Gear clock: fit the escapement\n"
        "Mood hopeful; hunger 17%, energy 95%; at the workshop.\nDay 1, afternoon.")
    st.update_agent(activity="idle", description="")
    s.sleep = False
    assert commands.answer(st, s, "/status", at(14) + 86400) == (
        "Status\nPip is idle\nMood hopeful; hunger 17%, energy 95%; at the workshop.\nDay 2.")


def test_items_text(tmp_path):
    s, st, *_ = make(tmp_path)
    clear_items(st)
    assert commands.answer(st, s, "/items") == "Items\nPip has nothing."
    st.add_item("brass wire", 3, "material")
    st.add_item("needle file", 1, "tool")
    assert commands.answer(st, s, "/items") == "Items\nbrass wire x3 (material)\nneedle file x1 (tool)"


async def test_projects_text(tmp_path):
    s, st, *_ = make(tmp_path)
    assert commands.answer(st, s, "/projects") == "Projects\nNo projects right now."
    old = {"name": "old clock", "status": "done", "stages": [{"name": "a", "minutes": 30, "progress": 30}]}   # finished ones aren't listed
    await given(st, old, {"name": "gear clock", "stages": [{"name": "cut", "minutes": 60, "progress": 60}, {"name": "fit it", "minutes": 60}]})
    assert commands.answer(st, s, "/projects") == "Projects\ngear clock: 50%, next: fit it"
    await given(st, old, {"name": "gear clock", "stages": [{"name": "cut", "minutes": 60, "progress": 60}, {"name": "fit it", "minutes": 60, "progress": 60}]})
    assert commands.answer(st, s, "/projects") == "Projects\ngear clock: 100%, next: all the planned steps are done"


def test_creations_text(tmp_path):
    s, st, *_ = make(tmp_path)
    assert commands.answer(st, s, "/creations") == "Creations\nNothing made yet."
    st.add_creation("Gear Clock", "keeps even time", None, "sound", {}, {})
    given = st.add_creation("Music Box", "plays one tune", None, "fine", {}, {})
    st.give_creation(given["id"], "Briar")                                     # given away: no longer Pip's
    assert commands.answer(st, s, "/creations") == "Creations\nGear Clock (sound): keeps even time"


def test_notes_text(tmp_path):
    s, st, *_ = make(tmp_path)
    assert commands.answer(st, s, "/notes") == "Notes\nTodo:\n(none)\nWishlist:\n(none)\nAmbitions:\n(none)"
    a = st.add_memory("wind the clock", "todo")
    b = st.add_memory("buy brass", "wishlist")
    st.add_memory("a diary line", "diary")
    assert commands.answer(st, s, "/notes") == (
        f"Notes\nTodo:\n#{a} wind the clock\nWishlist:\n#{b} buy brass\nAmbitions:\n(none)")
    assert commands.answer(st, s, "/notes   DIARY ") == "Notes\nDiary:\n#3 a diary line"
    assert commands.answer(st, s, "/notes bogus") == "No section 'bogus'. Options: diary, todo, wishlist, ambitions, learned."


def test_notes_shows_only_the_ten_newest(tmp_path):
    s, st, *_ = make(tmp_path)
    for i in range(12):
        st.add_memory(f"task {i}", "todo")
    lines = commands.answer(st, s, "/notes todo").splitlines()
    assert lines[1:3] == ["Todo:", "#3 task 2"] and lines[-1] == "#12 task 11" and len(lines) == 12


def test_usage_text(tmp_path):
    s, st, *_ = make(tmp_path, daily_token_budget=5000)
    assert commands.answer(st, s, "/usage") == "Usage\n0 of 5,000 tokens today (0%). Calls: 0."
    st.add_usage(1200, 300)
    assert commands.answer(st, s, "/usage") == "Usage\n1,500 of 5,000 tokens today (30%). Calls: 1."
    s.daily_token_budget = 0
    assert commands.answer(st, s, "/usage") == "Usage\n1,500 of 0 tokens today (0%). Calls: 1."


def test_arguments_are_ignored_by_commands_that_take_none(tmp_path):
    s, st, *_ = make(tmp_path)
    assert commands.answer(st, s, "/help please") == commands.answer(st, s, "/help")
    assert commands.answer(st, s, "/items\nand more") == commands.answer(st, s, "/items")


async def test_lists_put_each_entry_on_its_own_line(tmp_path):
    s, st, *_ = make(tmp_path, daily_token_budget=5000)
    await given(st, {"name": "clock", "stages": [{"name": "cut", "minutes": 60}]}, {"name": "walker", "stages": [{"name": "bend", "minutes": 60, "progress": 30}]})
    assert commands.answer(st, s, "/projects") == "Projects\nclock: 0%, next: cut\nwalker: 50%, next: bend"
    st.add_creation("Gear Clock", "keeps even time", None, "sound", {}, {})
    st.add_creation("Lamp", "glows at dusk", None, "fine", {}, {})
    assert commands.answer(st, s, "/creations") == "Creations\nGear Clock (sound): keeps even time\nLamp (fine): glows at dusk"


def test_percentages_are_exact(tmp_path):
    s, st, *_ = make(tmp_path, daily_token_budget=5000)
    st.update_agent(hunger=0.99, energy=0.5)
    assert "hunger 99%, energy 50%" in commands.answer(st, s, "/status")
    st.add_usage(3000, 1000)
    assert "(80%)" in commands.answer(st, s, "/usage")
