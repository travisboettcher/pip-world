"""The agent is `agent` everywhere (DESIGN-engine-audit.md, A4, 0.47.0): what was stored under the old name moves once, an old setting
naming it is refused rather than ignored, and what a thing shows may name the agent of whatever world it is in."""
import json
import os
import time

import pytest

from app.config import Settings
from app.state import State


def old_rows(st):
    """A database from before 0.47.0: the agent's purse, its program, a world-made layout and a shipped one, and events, under `pip`."""
    st.db.execute("INSERT OR REPLACE INTO purses VALUES ('pip', 37)")
    st.db.execute("DELETE FROM purses WHERE party = 'agent'")
    add = lambda name, kind, author, man, source, built="{}": st.db.execute(  # noqa: E731
        "INSERT INTO modules (name, kind, author, api, manifest, source, status, built, created_at) VALUES (?, ?, ?, 1, ?, ?, 'live', ?, 0)",
        (name, kind, author, json.dumps(man), source, built)).lastrowid
    ids = {"program": add("bell-by-pip", "thing", "pip", {"name": "bell-by-pip", "reads": ["pip", "time", "agent"]}, "x"),
           "other": add("bell", "thing", "pip", {"name": "something else", "reads": ["time"]}, "x"),
           "layout": add("glade", "place", "world", {"name": "glade", "reads": []},
                         'A = [{"id": "pip", "tags": ["pip"]}, {"id": "pip-stall"}]\nW = ["no-pip-stall"]\n# a pipe, pipped\n',
                         '{"version": 3}'),
           "shipped": add("home", "place", "library", {"name": "home"}, '{"id": "pip"}', '{"version": 1}'),
           "still": add("still", "part", "world", {"name": "still"}, "nothing to rename", '{"version": 2}'),
           "part": add("post", "part", "world", {"name": "post"}, '{"tags": ["pip"]}', '{"version": 4}')}
    talk = st.log("talk", name="Marigold", turns=3, ended="pip")
    her = st.log("talk", name="Marigold", turns=3, ended="Marigold")
    live = st.log("module_live", name="bell-by-pip", author="pip")
    st.set_meta(agent_named="")
    st.db.commit()
    return ids, talk, her, live


def test_what_was_stored_as_pip_is_the_agents_once(tmp_path):
    st = State(Settings(db_path=str(tmp_path / "a.db"), persona_path="/x"))
    ids, talk, her, live = old_rows(st)
    st = State(st.s)
    assert st.coins() == 37 and st.coins("pip") == 0
    m = {k: st.module(i) for k, i in ids.items()}
    assert (m["program"]["author"], m["program"]["name"], m["program"]["manifest"]["name"]) == ("agent", "bell-by-agent", "bell-by-agent")
    assert m["program"]["manifest"]["reads"] == ["agent", "time"]                              # the old read is the agent's, once
    assert (m["other"]["author"], m["other"]["name"], m["other"]["manifest"]["name"]) == ("agent", "bell", "something else")
    assert m["layout"]["source"] == 'A = [{"id": "agent", "tags": ["agent"]}, {"id": "agent-stall"}]\nW = ["no-agent-stall"]\n# a pipe, pipped\n'
    assert m["layout"]["built"] == {} and m["layout"]["author"] == "world"                     # built again with the new names
    assert m["shipped"]["source"] == '{"id": "pip"}' and m["shipped"]["built"] == {"version": 1}  # the engine's own change with the engine
    assert m["still"]["source"] == "nothing to rename" and m["still"]["built"] == {"version": 2}
    assert m["part"]["source"] == '{"tags": ["agent"]}' and m["part"]["built"] == {}
    ev = {e["id"]: e["data"] for e in st.events(10)}
    assert ev[talk]["ended"] == "agent" and ev[her]["ended"] == "Marigold" and ev[live]["author"] == "agent"
    assert st.meta("agent_named") == "1"
    later = st.db.execute("INSERT INTO modules (name, kind, author, api, manifest, source, status, created_at) "
                          "VALUES ('late-by-pip', 'thing', 'pip', 1, '{\"reads\": [\"pip\"]}', 'x', 'live', 0)").lastrowid
    st.db.commit()
    st = State(st.s)
    assert (st.module(later)["author"], st.module(later)["name"]) == ("pip", "late-by-pip")                    # once, not every start


def test_a_purse_the_agent_already_has_is_kept(tmp_path):
    st = State(Settings(db_path=str(tmp_path / "a.db"), persona_path="/x"))
    old_rows(st)
    st.db.execute("INSERT INTO purses VALUES ('agent', 3)")
    st.db.commit()
    st = State(st.s)
    assert st.coins() == 3 and st.coins("pip") == 37 and st.coins("Marigold") == 0


def test_a_world_starts_its_stats_where_it_says_or_halfway(tmp_path):
    st = State(Settings(db_path=str(tmp_path / "a.db"), persona_path="/x", stats={"luck": {"good": "high"}, "grit": {"start": 0.25}}))
    assert (st.agent()["luck"], st.agent()["grit"], st.agent()["luck_alerted"]) == (0.5, 0.25, 0)


@pytest.mark.parametrize("raw, got", [(None, "world,agent"), (" world , agent ,library ", "world,agent,library"), ("", ""), ("agent", "agent")])
def test_whose_modules_wait_for_approval(monkeypatch, raw, got):
    if raw is None:
        monkeypatch.delenv("MODULES_APPROVAL", raising=False)
    else:
        monkeypatch.setenv("MODULES_APPROVAL", raw)
    assert Settings.from_env().modules_approval == got


def test_an_author_the_engine_doesnt_have_is_refused_not_ignored(monkeypatch):
    for raw, named in (("world,pip", "pip"), ("world,pip,someone", "pip, someone")):
        monkeypatch.setenv("MODULES_APPROVAL", raw)
        with pytest.raises(ValueError) as e:
            Settings.from_env()
        assert str(e.value) == (f"MODULES_APPROVAL names {named}: the authors are world, agent (the agent's own programs; `pip` before 0.47.0) "
                                "and library")
    assert os.environ["MODULES_APPROVAL"] == "world,pip,someone"


async def test_a_shown_things_tip_names_the_agent_of_its_world(tmp_path):
    from app import modules as M
    from tests.test_modules import live, modular, rule, shipped_layouts
    s, st, agent = modular(tmp_path)
    await shipped_layouts(st, s, "home")
    m = live(st, rule(name="pins", proposes=["show"]), "x")
    sprite = {"rows": ["kk", "kk", "kk", "kk"], "palette": {"k": "#123456"}}
    st.update_module(m["id"], show=[{"id": "a", "sprite": sprite, "size": 0.5, "frame": False, "motion": "bob",
                                     "at": {"type": "floor", "place": "workshop"}, "tip": {"title": "$name's", "text": "for $name and $name"}},
                                    {"id": "b", "sprite": sprite, "size": 0.5, "frame": False, "at": {"type": "floor", "place": "workshop"}}])
    objs = {o["key"]: o for o in M.scene_objects(st, "workshop", "home")}
    assert objs["pins:a"]["tip"] == {"title": "Pip's", "text": "for Pip and Pip"} and objs["pins:a"]["motion"] == "bob"
    assert "tip" not in objs["pins:b"] and "motion" not in objs["pins:b"] and set(objs["pins:b"]) >= {"pos", "normal", "upright"}


def test_the_map_says_whose_it_is_and_calls_home_what_the_world_does(tmp_path):
    from app import worldmap
    from app import world_pack as W
    from tests.test_world_pack import pack_dir
    st = State(Settings(db_path=str(tmp_path / "a.db"), persona_path="/x"))
    snap = worldmap.snapshot(st, st.s, None, time.time())
    assert (snap["agent"]["name"], snap["home_called"]) == ("Pip", "workshop")
    d = pack_dir(tmp_path)
    try:
        W.set_active(W.load(Settings(world_pack=str(d))))
        s2 = Settings(world_pack=str(d), db_path=str(tmp_path / "b.db"), persona_path="/x")
        snap = worldmap.snapshot(State(s2), s2, None, time.time())
        assert (snap["agent"]["name"], snap["home_called"]) == ("Wren", "home")               # a world that names no home's word
    finally:
        W.set_active(W.load(Settings()))
