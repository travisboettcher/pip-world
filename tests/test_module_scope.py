"""Whose a module's working data is (docs/DESIGN-multi-agent.md, "Modules' working data"): a module's definition is the world's; an
agent-scoped module's working data (its state, status, offers, facts, due time...) and store are each agent's own, kept in that agent's
file and stepped as that agent; a world-scoped module has one of each, stepped once."""
import os

import pytest

from app import loop, modules as M, world_pack as W
from app.config import Settings
from app.llm.fake import FakeBackend
from tests.test_agents import two
from tests.test_modules import NOW, live, rule

COUNT = ("def on_install(ctx):\n    return {'state': {'n': 0, 'installed': True}}\n\n"
         "def on_tick(ctx):\n    n = ctx['state'].get('n', 0) + 1\n    return {'state': {**ctx['state'], 'n': n}, 'status': {'title': 'Count', 'lines': [str(n)]}}\n")


@pytest.fixture
def world(tmp_path):
    os.makedirs(tmp_path / "data")
    s = Settings(world_pack=str(two(tmp_path)), db_path=str(tmp_path / "data" / "agent.db"), persona_path="/x", pacing="manual",
                 modules="on", module_library="off", module_runner="local")
    w = loop.build(s, FakeBackend())
    w.runner = M.LocalRunner()                                                # the world's modules run in the local sandbox
    yield w
    W.set_active(W.load(Settings()))


def test_a_manifest_says_whose_its_working_data_is():
    assert M.check_manifest(rule(), "world")["scope"] == "agent" and M.check_manifest(rule(scope="world"), "world")["scope"] == "world"
    assert M.check_manifest({**rule(name="clockwork", scope="agent"), "kind": "thing", "subject": "Clock"}, "world")["scope"] == "agent"
    with pytest.raises(M.Refused, match=r"^`scope` is agent \(each agent has its own working data\) or world \(one, the world's\)$"):
        M.check_manifest(rule(scope="everyone"), "world")
    with pytest.raises(M.Refused, match="^only a rule's working data can be the world's"):
        M.check_manifest({**rule(name="clockwork", scope="world"), "kind": "thing", "subject": "Clock"}, "world")
    place = M.check_manifest({"name": "mill", "kind": "place", "api": 2, "hooks": ["on_build"], "place": "mill"}, "world")
    assert place["scope"] == "world"
    for name in ("sky", "neighborhood"):
        assert M.library(name)[0]["scope"] == "world", name
    assert W.load(Settings(world_pack=str(W.DEFAULT.parent / "ashfall"))).module("village")[0]["scope"] == "world"
    assert M.library("crafting")[0].get("scope", "agent") == "agent"


def test_each_agent_has_its_own_working_data_and_store(world):
    wren, ivo = world.agents
    m = live(wren.state, rule(name="counter", hooks=["on_tick"], proposes=["state", "status", "store"]), COUNT)
    wren.state.update_module(m["id"], state={"n": 3}, standing={"title": "Count", "lines": ["3"]}, due=NOW + 60, status="live")
    wren.state.merge_store("counter", {"tally": {"a": 1}})
    mine, his = wren.state.module(m["id"]), ivo.state.module(m["id"])
    assert (mine["state"], mine["due"], mine["standing"]["lines"], mine.get("fresh")) == ({"n": 3}, NOW + 60, ["3"], False)
    assert (his["state"], his["due"], his["standing"], his["fresh"]) == ({}, None, {}, True) and his["status"] == "live"   # the definition is shared
    assert wren.state.store("counter") == {"tally": {"a": 1}} and ivo.state.store("counter") == {}
    ivo.state.update_module(m["id"], state={"n": 9})
    assert wren.state.module(m["id"])["state"] == {"n": 3} and ivo.state.module(m["id"])["state"] == {"n": 9}
    assert [x["state"] for x in ivo.state.modules("live")] == [{"n": 9}]


def test_a_world_module_has_one_set_of_working_data(world):
    wren, ivo = world.agents
    m = live(wren.state, rule(name="weather", scope="world", proposes=["state", "publish", "store"]), "x")
    wren.state.update_module(m["id"], state={"rain": True}, facts={"weather": "rain"})
    wren.state.merge_store("weather", {"days": {"mon": "rain"}})
    assert ivo.state.module(m["id"])["state"] == {"rain": True} and ivo.state.module(m["id"])["facts"] == {"weather": "rain"}
    assert ivo.state.store("weather") == {"days": {"mon": "rain"}} and "fresh" not in ivo.state.module(m["id"])


@pytest.mark.asyncio
async def test_agent_modules_step_for_each_agent_and_world_modules_once(world):
    wren, ivo = world.agents
    mine = live(wren.state, rule(name="counter", hooks=["on_install", "on_tick"], proposes=["state", "status"]), COUNT)
    ours = live(wren.state, rule(name="clock-tower", hooks=["on_tick"], proposes=["state", "status"], scope="world"), COUNT.split("\n\n")[1])
    ivo.state.log("arrived", place="lockup")
    await world.step()                                                       # the world's modules, once
    await wren.step()
    await ivo.step()
    await ivo.step()
    assert wren.state.module(ours["id"])["state"] == {"n": 1} == ivo.state.module(ours["id"])["state"]
    assert wren.state.module(mine["id"])["state"] == {"n": 1}                # Wren's had its tick (no install: it was live already)
    his = ivo.state.module(mine["id"])
    assert his["state"] == {"n": 2, "installed": True} and his["standing"]["lines"] == ["2"] and not his["fresh"]   # installed, then two ticks
    assert his["cursor"] == ivo.state.events(1)[0]["id"] or his["cursor"] >= 1                                    # no replay of what went before


@pytest.mark.asyncio
async def test_a_things_workings_run_only_for_the_one_whose_thing_it_is(world):
    from tests.test_world_view import clock
    wren, ivo = world.agents
    clock(wren.state)
    m = live(wren.state, {**rule(name="gear-clock-workings", hooks=["on_tick"], proposes=["state", "status"]), "kind": "thing", "subject": "Gear Clock"},
             COUNT.split("\n\n")[1])
    await wren.step()
    await ivo.step()
    assert wren.state.module(m["id"])["state"] == {"n": 1} and ivo.state.module(m["id"])["state"] == {}


def test_an_install_from_before_gives_its_first_agent_the_working_data(tmp_path):
    from app.state import State
    s = Settings(db_path=str(tmp_path / "agent.db"), persona_path="/x")
    st = State(s)
    m = live(st, rule(name="counter", proposes=["state", "store"]), "x")
    st.db.execute("DELETE FROM module_runtime")                               # as an install from before kept it: on the module's row
    st.db.execute("UPDATE world.modules SET state = ?, due = ? WHERE id = ?", ('{"n": 7}', NOW, m["id"]))
    st.db.execute("INSERT INTO world.module_store VALUES ('counter', 'tally', 'a', '1')")
    st.set_meta(module_runtime_moved="")
    st.db.commit()
    st.db.close()
    again = State(s)
    assert again.module(m["id"])["state"] == {"n": 7} and again.module(m["id"])["due"] == NOW and again.store("counter") == {"tally": {"a": 1}}
    assert again.db.execute("SELECT COUNT(*) FROM world.module_store").fetchone()[0] == 0


def test_whose_a_stored_module_is_even_from_before_scope_was_said():
    from app.state import State
    for kind, man, scope in (("part", {}, "world"), ("place", {}, "world"), ("place", {"scope": "agent"}, "world"), ("rule", {}, "agent"),
                             ("thing", {}, "agent"), ("rule", {"scope": "world"}, "world")):
        assert State.scope_of(kind, man) == scope, (kind, man)


def test_working_data_at_its_edges(world):
    wren, ivo = world.agents
    m = live(wren.state, rule(name="counter", proposes=["state"]), "x")
    assert wren.state.module(m["id"])["fresh"] is False and wren.state.module(999) is None   # its maker has it from the start
    wren.state.db.execute("UPDATE world.modules SET state = ?, due = ? WHERE id = ?", ('{"stale": 1}', NOW, m["id"]))
    assert (ivo.state.module(m["id"])["state"], ivo.state.module(m["id"])["due"]) == ({}, None)         # never the row's leftovers
    wren.state.update_module(m["id"], due=NOW + 5)
    wren.state.update_module(m["id"], due=None, cursor=4)
    got = wren.state.module(m["id"])
    assert got["due"] is None and got["cursor"] == 4


def test_only_the_worlds_first_agent_gets_what_its_modules_had_and_only_once(tmp_path, world):
    wren, ivo = world.agents
    first = live(wren.state, rule(name="spare", proposes=["state"]), "x")
    a = live(wren.state, rule(name="counter", proposes=["state", "store"]), "x")
    b = live(wren.state, rule(name="tally", proposes=["state"]), "x")
    for st in (wren.state, ivo.state):
        st.db.execute("DELETE FROM module_runtime")
        st.set_meta(module_runtime_moved="")
    wren.state.db.execute("UPDATE world.modules SET state = ? WHERE id = ?", ('{"n": 7}', a["id"]))
    wren.state.db.execute("UPDATE world.modules SET state = ? WHERE id = ?", ('{"t": 2}', b["id"]))
    wren.state.db.commit()
    from app.state import State
    w2, i2 = State(wren.s), State(ivo.s)
    assert (w2.module(a["id"])["state"], w2.module(b["id"])["state"], w2.module(first["id"])["state"]) == ({"n": 7}, {"t": 2}, {})
    assert i2.module(a["id"])["fresh"] and i2.meta("module_runtime_moved") == "1" == w2.meta("module_runtime_moved")
    w2.update_module(a["id"], state={"n": 8})
    assert State(wren.s).module(a["id"])["state"] == {"n": 8}                                  # a second start moves nothing again


def test_a_new_version_may_speak_as_its_old_versions_voices(world):
    wren, _ = world.agents
    old = live(wren.state, rule(name="radio-hut", proposes=["voices"], scope="world"), "x")
    wren.state.update_module(old["id"], voices=[{"name": "the radio", "at": "home", "about": "a receiver"}])
    new = live(wren.state, rule(name="radio-hut", proposes=["voices"], scope="world"), "x")
    assert M._voices(wren.state, new, [{"name": "the radio", "at": "home"}])[0]["name"] == "the radio"
    other = live(wren.state, rule(name="other-hut", proposes=["voices"], scope="world"), "x")
    with pytest.raises(M.Refused, match="^someone called the radio is already in the world$"):
        M._voices(wren.state, other, [{"name": "the radio", "at": "home"}])
