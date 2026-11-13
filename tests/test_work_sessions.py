"""A module's session that is work, and about something (5f's hooks): it shows as work in the scene, and reminders and the memory's
context name what it's about, as they do for the engine's own work."""
import time

import pytest

from app import modules as M
from app import reminders as R
from app import world_view as WV
from tests.test_modules import NOW, live, modular, rule


def refused(fn, *args):
    with pytest.raises(M.Refused) as e:
        fn(*args)
    return str(e.value)


def test_a_session_may_say_what_it_is_about(tmp_path):
    s, st, agent = modular(tmp_path)
    assert M._session(st, {"minutes": 30, "label": "working on the kite", "working": True, "about": " Kite "}) == \
        {"minutes": 30.0, "label": "working on the kite", "working": True, "about": "Kite"}
    assert M._session(st, {"minutes": 30, "label": "x"})["about"] == "" and M._session(st, {"minutes": 1, "label": "x", "about": "k" * 60})["about"] == "k" * 60
    why = ("`session` is {minutes (1 to 240), label, working?, about?}: about is what it's about (a project's name), at most 60 characters")
    for bad in ({"minutes": 30, "label": "x", "about": "k" * 61}, {"minutes": 30, "label": "x", "about": 3}, {"minutes": 30, "label": "x", "y": 1}):
        assert refused(M._session, st, bad) == why


async def test_work_in_a_modules_session_shows_and_is_remembered_as_work(tmp_path):
    s, st, agent = modular(tmp_path)
    src = "def on_action(ctx):\n    return {'session': {'minutes': 30, 'label': 'working on the kite', 'working': True, 'about': 'Kite'}}\ndef on_time(ctx):\n    return {}\n"
    m = live(st, rule(name="crafting", hooks=["on_action", "on_time"], proposes=["session"], tools=[{"name": "work_at", "help": "work",
             "params": {"type": "object", "properties": {}, "required": []}}]), src)
    await M.use_tool(st, s, M.LocalRunner(), m, m["manifest"]["tools"][0], {}, NOW)
    assert st.session()["about"] == "Kite" and st.session()["kind"] == "module"
    sess = WV.scene_view(st, s, None)["pip"]["session"]
    assert (sess["label"], sess["working"], sess["project"]) == ("working on the kite", True, "Kite")
    c = R.cue(st, [], time.time())
    assert c.project == "Kite" and "working on the kite" in c.words
    mem = st.add_memory("the kite needs a longer tail", "diary")
    row = st.db.execute("SELECT project FROM memory_context WHERE ref = ?", (str(mem),)).fetchone()
    assert row["project"] == "Kite" and [m["text"] for m in st.memories_about([], None, "Kite", 5)] == ["the kite needs a longer tail"]


async def test_a_session_that_isnt_work_or_about_anything(tmp_path):
    s, st, agent = modular(tmp_path)
    st.start_session(0, 0, 10, time.time() + 600, kind="module", target="reading", expect="reading Tides")
    sess = WV.scene_view(st, s, None)["pip"]["session"]
    assert sess["working"] is False and "project" not in sess and R.cue(st, [], time.time()).project is None
