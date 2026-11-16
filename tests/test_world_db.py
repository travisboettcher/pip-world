"""The world's database and the agent's (docs/DESIGN-multi-agent.md, release 1): the world's tables live in a file of their own, attached
to each agent's, so agents can share a world and keep their minds apart; an install from before moves its world's tables out once."""
import sqlite3

from app.config import Settings
from app.state import SCHEMA, State, WORLD_TABLES, world_path


def tables(path):
    c = sqlite3.connect(path)
    try:
        return {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    finally:
        c.close()


def settings(tmp_path, name="agent.db", **kw):
    return Settings(db_path=str(tmp_path / name), persona_path="/x", **kw)


def test_the_world_keeps_its_own_file_next_to_the_agents(tmp_path):
    s = settings(tmp_path)
    assert world_path(s) == str(tmp_path / "agent-world.db")
    assert world_path(settings(tmp_path, world_db_path=str(tmp_path / "shared.db"))) == str(tmp_path / "shared.db")
    st = State(s)
    st.add_place("Hollin", "hollin", kind="wild", status="real", created_at=1, heard_at=1, hours=None, daylight_only=0, walk_minutes=5.0,
                 loot=[], verbs={})
    st.add_item("acorn", 2, "material", "")
    assert set(WORLD_TABLES) <= tables(world_path(s)) and not set(WORLD_TABLES) & tables(s.db_path)
    assert {"items", "memories", "agent", "events"} <= tables(s.db_path) and not {"items", "agent"} & tables(world_path(s))
    assert st.place_row("hollin")["kind"] == "wild" and st.find_item("acorn")[0]["qty"] == 2
    assert set(WORLD_TABLES) == {"places", "map_places", "modules", "module_store", "module_calls", "characters", "purses", "agent_post"}


def test_two_agents_share_a_world_and_keep_their_own_things(tmp_path):
    shared = str(tmp_path / "world.db")
    wren = State(settings(tmp_path, "wren.db", world_db_path=shared))
    tomas = State(settings(tmp_path, "tomas.db", world_db_path=shared))
    wren.add_character("Marta", "villager", None, "keeps the gate", 60, 0, place="village")
    wren.add_item("crowbar", 1, "tool", "")
    wren.add_memory("the gate opens at dawn", "diary")
    assert [c["name"] for c in tomas.characters()] == ["Marta"]                     # the world's people are everyone's
    assert tomas.find_item("crowbar")[0] is None and tomas.memories("diary") == []    # a mind is its own
    tomas.add_coins("tomas", 5)
    assert wren.coins("tomas") == 5


def test_an_install_from_before_moves_its_worlds_tables_out_once(tmp_path):
    s = settings(tmp_path)
    old = sqlite3.connect(s.db_path)                                                  # one file, as every install was
    old.executescript(SCHEMA)
    old.executescript("""
        INSERT INTO modules (id, name, kind, author, api, manifest, source, status, created_at) VALUES (7, 'bells', 'rule', 'world', 2, '{}', 'x', 'live', 1);
        INSERT INTO purses VALUES ('agent', 42);
        INSERT INTO items (name, qty, kind, description, attrs, ts) VALUES ('acorn', 3, 'material', '', '{}', 1);
    """)
    old.commit()
    old.close()
    st = State(s)
    assert st.module(7)["name"] == "bells" and st.coins() == 42 and st.find_item("acorn")[0]["qty"] == 3
    assert {"modules", "purses"} <= tables(world_path(s)) and not {"modules", "purses"} & tables(s.db_path)
    later = st.add_module(name="gong", kind="rule", author="world", api=2, subject="", manifest={}, source="x", status="live", created_at=2)
    assert later == 8                                                                 # the ids carry on where they were
    st.db.close()
    again = State(s)                                                                  # once: a second start moves nothing
    assert [m["name"] for m in again.modules()] == ["bells", "gong"] and again.coins() == 42


def test_the_worlds_file_is_named_from_the_agents_wherever_it_is():
    for agent, world in (("/a.b/agent.db", "/a.b/agent-world.db"), ("/a.b/agent", "/a.b/agent-world"), ("/data/agent", "/data/agent-world"),
                         ("wren.sqlite", "wren-world.sqlite")):
        assert world_path(Settings(db_path=agent)) == world, agent


def test_moving_the_worlds_tables_is_said(tmp_path, caplog):
    s = settings(tmp_path)
    old = sqlite3.connect(s.db_path)
    old.executescript(SCHEMA)
    old.close()
    with caplog.at_level("INFO", logger="state"):
        State(s)
    assert "moved the world's tables into their own file: places, map_places, modules, module_store, module_calls, characters, purses, agent_post" in caplog.messages
