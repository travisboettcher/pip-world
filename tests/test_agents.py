"""More than one agent in a world (docs/DESIGN-multi-agent.md, release 2): a pack may name several agents, each with a home and a persona
of its own; the engine runs a loop, a database and a token budget for each, and whatever names "the agent" names the one acting."""
import json
import os

import pytest

from app import loop, places, world_pack as W
from app.config import Settings
from app.llm.fake import FakeBackend
from tests.test_world_pack import pack_dir

IVO = {"key": "ivo", "name": "Ivo", "pronoun": "he", "kind": "a scavenger", "lives": "lives in a lock-up off the east blocks",
       "persona": "personas/ivo.md",
       "home": {"key": "lockup", "description": "your home: a lock-up garage off the east blocks", "called": "lock-up",
                "aliases": ["home", "lock-up", "garage"], "about": "a steel-shuttered lock-up crammed with salvage", "offers": ["sleep"]}}
WREN = {"key": "wren", "name": "Wren", "pronoun": "she", "kind": "a survivor"}


def two(tmp_path, **world):
    d = pack_dir(tmp_path, agents=[WREN, IVO], **world)
    (d / "personas").mkdir()
    (d / "personas" / "ivo.md").write_text("You are Ivo, who trades salvage at the gate.\n")
    (d / "items.json").write_text(json.dumps({"kinds": ["tool", "material", "food"]}))
    (d / "places.json").write_text(json.dumps({"home": {"key": "shelter", "description": "your home: a shelter", "called": "shelter"},
                                              "start": [{"key": "ruins", "kind": "yard", "about": "broken blocks", "description": "the broken blocks"}]}))
    return d


@pytest.fixture
def restore():
    yield
    W.set_active(W.load(Settings()))


def test_a_pack_names_its_agents_and_the_first_is_the_agent(tmp_path):
    p = W.load(Settings(world_pack=str(two(tmp_path))))
    assert [a.key for a in p.agents] == ["wren", "ivo"] and p.agent is p.agents[0] and p.agent_named("ivo").pronoun == "he"
    assert p.agent_named("") is p.agent and p.agent_named("nobody") is None
    assert p.persona(p.agent_named("ivo")) == "You are Ivo, who trades salvage at the gate." and p.persona() == "You are Wren, who keeps the shelter."
    assert p.agent_named("ivo").home_place["key"] == "lockup" and p.agent.home_place == {}
    one = W.load(Settings(world_pack=str(pack_dir(tmp_path / "one"))))
    assert one.agents == (one.agent,) and one.agent.key == "wren"                        # a key from the name


@pytest.mark.parametrize("agents,why", [
    ([WREN, {**IVO, "key": "wren"}], "two agents can't share the key 'wren'"),
    ([WREN, {**IVO, "key": "Ivo!"}], "an agent's `key` is a word in lower case"),
    ([WREN, {**IVO, "home": {"key": "lockup"}}], "an agent's `home` is {key, description, called?, aliases?, about?, offers?}"),
    ([WREN, {**IVO, "persona": "personas/nobody.md"}], "the agent ivo's persona personas/nobody.md isn't in the pack"),
])
def test_what_an_agents_entry_cant_be_is_named(tmp_path, agents, why):
    d = two(tmp_path)
    w = json.loads((d / "world.json").read_text())
    (d / "world.json").write_text(json.dumps({**w, "agents": agents}))
    with pytest.raises(W.PackError) as e:
        W.load(Settings(world_pack=str(d)))
    assert str(e.value) == f"world pack {d}: {why}"


def test_whatever_names_the_agent_names_the_one_acting(tmp_path, restore):
    p = W.load(Settings(world_pack=str(two(tmp_path))))
    W.set_active(p)
    assert W.active().agent.name == "Wren" and places.home_key() == "shelter" and W.acting_state() is None
    marker = object()
    with W.acting(p.agent_named("ivo"), marker):
        assert W.active().agent.name == "Ivo" and places.home_key() == "lockup" and places.home()["called"] == "lock-up"
        assert W.acting_state() is marker and W.active().dir == p.dir
    assert W.active().agent.name == "Wren" and places.home()["key"] == "shelter"


def test_the_settings_say_which_agents_run_and_each_ones_budget(monkeypatch):
    monkeypatch.setenv("AGENTS", "wren, ivo")
    monkeypatch.setenv("DAILY_TOKEN_BUDGET", "1000")
    monkeypatch.setenv("DAILY_TOKEN_BUDGET_IVO", "300")
    s = Settings.from_env()
    assert s.agents == ["wren", "ivo"] and s.agent_budgets == {"ivo": 300} and s.daily_token_budget == 1000 and s.agent_key == ""
    monkeypatch.delenv("AGENTS")
    assert Settings.from_env().agents is None                                                 # all of the pack's


def test_the_engine_runs_a_loop_a_file_and_a_budget_for_each_agent(tmp_path, restore):
    d = two(tmp_path)
    s = Settings(world_pack=str(d), db_path=str(tmp_path / "data" / "agent.db"), persona_path="/x", pacing="manual",
                 daily_token_budget=1000, agent_budgets={"ivo": 300})
    os.makedirs(tmp_path / "data")
    world = loop.build(s, FakeBackend())
    wren, ivo = world.agents
    assert (wren.identity.key, ivo.identity.key) == ("wren", "ivo") and ivo.world is world and ivo.gm is wren.gm
    assert wren.s.db_path == str(tmp_path / "data" / "agent.db") and ivo.s.db_path == str(tmp_path / "data" / "agents" / "ivo.db")
    assert wren.s.world_db_path == ivo.s.world_db_path == str(tmp_path / "data" / "agent-world.db")
    assert (wren.s.daily_token_budget, ivo.s.daily_token_budget) == (1000, 300) and (wren.s.agent_key, ivo.s.agent_key) == ("wren", "ivo")
    assert wren.state.agent()["location"] == "shelter" and ivo.state.agent()["location"] == "lockup"     # each starts at home
    assert wren._persona() == "You are Wren, who keeps the shelter." and ivo._persona() == "You are Ivo, who trades salvage at the gate."
    wren.state.add_memory("the gate opens at dawn", "diary")
    assert ivo.state.memories("diary") == []                                                     # a mind is its own
    only = loop.build(Settings(**{**s.__dict__, "agents": ["ivo"]}), FakeBackend())
    assert [a.identity.key for a in only.agents] == ["ivo"]


@pytest.mark.asyncio
async def test_the_narrator_spends_the_acting_agents_budget(tmp_path, restore):
    d = two(tmp_path)
    os.makedirs(tmp_path / "data")
    s = Settings(world_pack=str(d), db_path=str(tmp_path / "data" / "agent.db"), persona_path="/x", pacing="manual")
    world = loop.build(s, FakeBackend())
    wren, ivo = world.agents
    with W.acting(ivo.identity, ivo.state):
        assert world.gm.state is ivo.state and world.gm.agent.name == "Ivo"
    assert world.gm.state is wren.state and world.gm.agent.name == "Wren"                        # the world's own steps: its first agent


def test_the_app_shows_any_agent_and_lists_them(tmp_path, restore):
    from fastapi.testclient import TestClient
    from app.main import create_app
    d = two(tmp_path)
    os.makedirs(tmp_path / "data")
    s = Settings(world_pack=str(d), db_path=str(tmp_path / "data" / "agent.db"), persona_path="/x", pacing="manual")
    with TestClient(create_app(s, FakeBackend())) as c:
        assert c.get("/agents").json() == {"agents": [{"key": "wren", "name": "Wren"}, {"key": "ivo", "name": "Ivo"}]}
        assert c.get("/state").json()["agent"]["location"] == "shelter"
        assert c.get("/state?agent=ivo").json()["agent"]["location"] == "lockup"
        assert c.get("/state?agent=nobody").status_code == 404


def test_the_dashboard_lets_you_choose_whose_page_it_is(tmp_path, restore):
    from fastapi.testclient import TestClient
    from app.main import create_app
    d = two(tmp_path)
    os.makedirs(tmp_path / "data")
    s = Settings(world_pack=str(d), db_path=str(tmp_path / "data" / "agent.db"), persona_path="/x", pacing="manual")
    with TestClient(create_app(s, FakeBackend())) as c:
        js = c.get("/ui/dashboard.js").text + c.get("/ui/core.js").text
    assert "api('/agents')" in js and "withAgent(`/stream?after_id=" in js and "fetch(withAgent(path), opts)" in js


def test_an_agents_entry_at_its_edges(tmp_path):
    d = pack_dir(tmp_path, agents=[WREN, {"name": "Old Tom", "lives": "lives under the bridge"}])
    p = W.load(Settings(world_pack=str(d)))
    tom = p.agents[1]
    assert tom.key == "oldtom" and tom.lives == "lives under the bridge" and p.persona(tom) == "You are Old Tom."   # persona.md is the first's
    assert p.agent.lives == ""                                                                                # none given: none
    for home, ok in (({"key": "lockup", "description": "x", "colour": 1}, False), ({"key": 3, "description": "x"}, False),
                     ({"key": "lockup", "description": "x", "called": "lock-up"}, True)):
        e = tmp_path / f"h{len(str(home))}"
        try:
            W.load(Settings(world_pack=str(pack_dir(e, agents=[WREN, {**IVO, "persona": "", "home": home}]))))
            assert ok, home
        except W.PackError as err:
            assert not ok and str(err).endswith("an agent's `home` is {key, description, called?, aliases?, about?, offers?}"), home


def test_home_asked_of_a_given_agent_and_a_world_that_names_none(tmp_path, restore):
    from app.state import State
    p = W.load(Settings(world_pack=str(two(tmp_path))))
    W.set_active(p)
    assert places.home_key(p.agent_named("ivo")) == "lockup" and places.home_key() == "shelter"
    bare = pack_dir(tmp_path / "bare")
    s = Settings(world_pack=str(bare), db_path=str(tmp_path / "bare.db"), persona_path="/x")
    assert State(s).home_key() == "home"


def test_building_a_world_at_its_edges(tmp_path, restore):
    d = two(tmp_path)
    os.makedirs(tmp_path / "data")
    s = Settings(world_pack=str(d), db_path=str(tmp_path / "data" / "agent.db"), persona_path=str(tmp_path / "persona.md"), pacing="manual",
                 outreach="log")
    with pytest.raises(ValueError, match=r"^AGENTS names tomas, kit, which this world doesn't have \(it has wren, ivo\)$"):
        loop.build(Settings(**{**s.__dict__, "agents": ["tomas", "ivo", "kit"]}), FakeBackend())
    narrator = FakeBackend()
    world = loop.build(s, FakeBackend(), gm_backend=narrator)
    wren, ivo = world.agents
    assert world.gm.backend is narrator and wren.backend is not narrator
    assert (wren.s.outreach, ivo.s.outreach) == ("log", "off") and (wren.s.persona_path, ivo.s.persona_path) == (s.persona_path, "")
    with ivo.acting():
        assert W.active().agent.name == "Ivo" and W.acting_state() is ivo.state


def test_a_narrator_given_an_agent_keeps_to_it(tmp_path, restore):
    from app.gm import GameMaster
    p = W.load(Settings(world_pack=str(two(tmp_path))))
    gm = GameMaster(FakeBackend(), None, agent=p.agent_named("ivo"))
    assert gm.agent.name == "Ivo"


def test_an_agent_may_start_with_belongings_of_its_own(tmp_path, restore):
    """Found on Ashfall (2026-11-18): the villagers started with Wren's kit and acted like scavengers; for Pip's world (0.67.0) Oriel
    starts with her tin of brass and wire, not Pip's seed packets. An agent's `items` replace the world's starting belongings."""
    tin = {"name": "brass and wire tin", "qty": 1, "kind": "material", "description": "a tin of found brass and wire"}
    d = two(tmp_path)
    w = json.loads((d / "world.json").read_text())
    w["agents"][1]["items"] = [tin, {"name": "rope", "qty": 2, "kind": "material"}]
    (d / "world.json").write_text(json.dumps(w))
    (d / "items.json").write_text(json.dumps({"kinds": ["tool", "material", "food"], "start": [{"name": "bandage", "qty": 1, "kind": "tool"}]}))
    os.makedirs(tmp_path / "data")
    s = Settings(world_pack=str(d), db_path=str(tmp_path / "data" / "agent.db"), persona_path="/x", pacing="manual")
    wren, ivo = loop.build(s, FakeBackend()).agents
    assert [(i["name"], i["qty"]) for i in wren.state.items()] == [("bandage", 1)]               # the world's
    assert sorted((i["name"], i["qty"], i["description"]) for i in ivo.state.items()) == [("brass and wire tin", 1, tin["description"]), ("rope", 2, "")]
    for bad in ([{"name": "rope"}], [{"name": "", "qty": 1, "kind": "material"}], [{"name": "rope", "qty": 0, "kind": "material"}], "rope"):
        w["agents"][1]["items"] = bad
        (d / "world.json").write_text(json.dumps(w))
        with pytest.raises(W.PackError, match="an agent's `items` are its starting belongings: \\[\\{name, qty, kind, description\\?, attrs\\?\\}\\]$"):
            W.load(Settings(world_pack=str(d)))
