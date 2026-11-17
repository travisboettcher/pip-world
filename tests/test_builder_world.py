"""The builder sees the whole world (2026-11-17): every agent by name, what each has wanted and for how long, what each keeps coming back
to, and what the world can produce, so it can tell a gap (something wanted for days that nothing can give) from a wish the world will
answer in time."""
import json
import os
import time

import pytest

from app import builder as B, loop, modules as M, world_pack as W
from app.config import Settings
from app.llm.fake import FakeBackend
from tests.test_agents import two

DAY = 86400


@pytest.fixture
def world(tmp_path):
    os.makedirs(tmp_path / "data")
    s = Settings(world_pack=str(two(tmp_path)), db_path=str(tmp_path / "data" / "agent.db"), persona_path="/x", pacing="manual",
                 module_builder="on")
    w = loop.build(s, FakeBackend())
    w.runner = M.LocalRunner()
    yield w
    W.set_active(W.load(Settings()))


def aged(st, text, section, days):
    mid = st.add_memory(text, section)
    st.db.execute("UPDATE memories SET ts = ? WHERE id = ?", (time.time() - days * DAY - 60, mid))
    st.db.commit()
    return mid


def test_the_builder_sees_each_agent_and_how_long_they_have_wanted_things(world):
    wren, ivo = world.agents
    aged(wren.state, "a working lamp", "wishlist", 3)
    aged(wren.state, "find the source of the vent smell", "todo", 2)
    aged(wren.state, "sweep the stairs", "todo", 0)
    wren.state.add_focus("2026-11-17", "Find the source of the vent smell before using the stove again.")
    aged(ivo.state, "to know what the gate pays for wire", "wishlist", 1)
    with W.acting(ivo.identity, ivo.state):                                          # whoever happened to reflect: the builder sees everyone
        text = B.minds([(a.identity, a.state) for a in world.agents], time.time())
    assert "Wren's open wishes: a working lamp (open 3 days)" in text
    assert "Wren's oldest open to-dos: find the source of the vent smell (open 2 days); sweep the stairs (open 0 days)" in text
    assert "What Wren's sleeping self chose to focus on: Find the source of the vent smell before using the stove again." in text
    assert "Ivo's open wishes: to know what the gate pays for wire (open 1 day)" in text and "Ivo's oldest open to-dos: none" in text


def test_the_builder_sees_what_the_world_can_produce(world, tmp_path):
    wren, _ = world.agents
    items = {"kinds": ["tool", "material", "food"],
             "finds": {"ruins": [["scrap", "material", 30, [2, 5], "offcuts", {}], ["copper wire", "material", 15, [1, 3], "wire", {}]]}}
    (W.active().dir / "items.json").write_text(json.dumps(items))
    places = json.loads((W.active().dir / "places.json").read_text())
    (W.active().dir / "places.json").write_text(json.dumps({**places, "kinds": {"yard": {"help": "somewhere to dig"}}}))
    W._data.cache_clear()
    now = time.time()
    wren.state.add_place("Mill", "mill", kind="yard", status="real", created_at=now, heard_at=now, hours=None, daylight_only=0,
                         walk_minutes=20.0, loot=[["flour", "food", 5, [1, 2], "a sack", {}]], verbs={})
    with wren.acting():
        text = B.produce(wren.state, wren.s)
    assert text.startswith("What can be had in this world (where, and what turns up or is sold there):")
    assert "- the ruins: scrap, copper wire" in text and "- Mill: flour" in text


@pytest.mark.asyncio
async def test_the_builder_runs_once_a_world_night_as_the_world(world, monkeypatch):
    wren, ivo = world.agents
    aged(ivo.state, "to know what the gate pays for wire", "wishlist", 1)
    seen = []

    async def ask(task, props, required, purpose, **kw):
        seen.append(task)
        return {"action": "nothing", "reason": "fine"}
    monkeypatch.setattr(world.gm, "ask", ask)
    with ivo.acting():                                                              # Ivo's reflection comes first tonight
        await world.night()
    with wren.acting():
        await world.night()                                                         # once a world night
    assert len(seen) == 1
    task = seen[0]
    assert "Ivo's open wishes: to know what the gate pays for wire" in task and "Wren's open wishes: none" in task
    assert "Lately for Wren:" in task and "Lately for Ivo:" in task
    assert ("that is a gap worth filling" in task and "When there is no such gap, nothing is a fine answer." in task
            and "Most nights, nothing is a fine answer." not in task)
    assert [json.loads(e["data"])["outcome"] if isinstance(e["data"], str) else e["data"]["outcome"]
            for e in wren.state.events(5) if e["kind"] == "builder"] == ["nothing"]


def test_how_long_and_how_much_the_builder_is_shown(world):
    wren, ivo = world.agents
    now = time.time()
    assert (B._open(now - DAY, now), B._open(now - DAY + 1, now), B._open(now + 5, now)) == (" (open 1 day)", " (open 0 days)", " (open 0 days)")
    for i in range(10):
        aged(wren.state, f"wish {i}", "wishlist", 0)
    done = aged(wren.state, "a met wish", "wishlist", 9)
    wren.state.set_memory_status(done, "done")
    for i in range(6):
        aged(wren.state, f"todo {i}", "todo", 6 - i)
    gone = aged(wren.state, "an old done todo", "todo", 30)
    wren.state.set_memory_status(gone, "done")
    for i in range(7):
        wren.state.add_focus("2026-11-17", f"focus {i}")
    text = B.minds([(wren.identity, wren.state), (ivo.identity, ivo.state)], now).split("\n")
    assert text[0] == "Wren's open wishes: " + "; ".join(f"wish {i} (open 0 days)" for i in range(2, 10))     # the newest eight
    assert text[1] == "Wren's oldest open to-dos: " + "; ".join(f"todo {i} (open {6 - i} days)" for i in range(4))
    assert text[2] == "What Wren's sleeping self chose to focus on: " + " / ".join(f["text"] for f in wren.state.focus("open", limit=5))
    assert len(text[2].split(" / ")) == 5
    assert text[3:] == ["Ivo's open wishes: none", "Ivo's oldest open to-dos: none", "What Ivo's sleeping self chose to focus on: nothing yet"]


def test_what_can_be_had_at_its_edges(world):
    wren, _ = world.agents
    with wren.acting():
        assert B.produce(wren.state, wren.s) == "What can be had in this world (where, and what turns up or is sold there):\n- (nothing yet)"
    places = json.loads((W.active().dir / "places.json").read_text())
    (W.active().dir / "places.json").write_text(json.dumps({**places, "kinds": {"yard": {"help": "somewhere to dig"}}}))
    W._data.cache_clear()
    now = time.time()
    wren.state.add_place("Depot", "depot", kind="yard", status="real", created_at=now, heard_at=now, hours=None, daylight_only=0, walk_minutes=20.0,
                         loot=[[f"thing {i}", "material", 1, [1, 1], "x", {}] for i in range(14)], verbs={})
    with wren.acting():
        shown = B.produce(wren.state, wren.s).split("\n")[1]
    assert shown == "- Depot: " + ", ".join(f"thing {i}" for i in range(12))                        # a dozen at most


@pytest.mark.asyncio
async def test_the_world_alone_says_lately_plainly_and_many_say_whose(world, monkeypatch, tmp_path):
    wren, ivo = world.agents
    seen = []

    async def ask(task, props, required, purpose, **kw):
        seen.append(task)
        return {"action": "nothing", "reason": "fine"}
    monkeypatch.setattr(world.gm, "ask", ask)
    names = []
    real = B.night

    async def night(*a, **k):
        names.append(W.active().agent.name)
        return await real(*a, **k)
    monkeypatch.setattr(loop.builder, "night", night)
    with ivo.acting():
        await world.night()
    assert names == ["Wren"]                                                         # as the world: its first agent, whoever reflected
    assert "\n\nLately for Wren:\n" in seen[0] and "\n\nLately for Ivo:\n" in seen[0] and "What can be had in this world" in seen[0]
    alone = loop.build(Settings(**{**wren.s.__dict__, "agents": ["wren"], "agent_key": ""}), FakeBackend())
    alone.runner = M.LocalRunner()
    alone.agents[0].state.set_meta(builder_day="")
    monkeypatch.setattr(alone.gm, "ask", ask)
    await alone.night()
    assert "\n\nLately:\n" in seen[-1] and "Lately for" not in seen[-1]
