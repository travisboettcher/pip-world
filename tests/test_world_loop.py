"""The world and its agents (docs/DESIGN-multi-agent.md, release 1): a World owns what agents share (the pack, the narrator, the library,
the module runner) and runs the world's steps once; each Agent runs its own loop. The World is their supervisor: an agent whose loop dies
is started again without stopping the world or the others."""
import asyncio

import pytest

from app import loop, sources
from app.config import Settings
from app.llm.fake import FakeBackend
from app.loop import Agent, World
from app.pacing import get_policy
from app.state import State


def settings(tmp_path, name="agent.db", **kw):
    return Settings(**{"db_path": str(tmp_path / name), "world_db_path": str(tmp_path / "world.db"), "persona_path": "/x",
                       "pacing": "manual", "monitor_seconds": 0.01, **kw})


def agent(tmp_path, name="agent.db", world=None, **kw):
    s = settings(tmp_path, name, **kw)
    return Agent(s, State(s), FakeBackend(), get_policy(s), world=world)


def test_an_agent_alone_has_a_world_of_its_own(tmp_path):
    a = agent(tmp_path)
    w = a.world
    assert isinstance(w, World) and w.agents == [a] and (a.gm, a.runner, a.library, a.pack) == (w.gm, w.runner, w.library, w.pack)
    other = object()
    a.gm = other                                                   # a narrator swapped on the agent is the world's, and the sources'
    assert w.gm is other and sources._wired["agent"] is w


def test_agents_in_one_world_share_it(tmp_path):
    a = agent(tmp_path, "wren.db")
    b = agent(tmp_path, "tomas.db", world=a.world)
    assert a.world.agents == [a, b] and b.gm is a.gm and b.runner is a.runner and b.library is a.library and b.world is a.world


@pytest.mark.asyncio
async def test_the_worlds_steps_run_once_and_wake_every_agent(tmp_path, monkeypatch):
    a = agent(tmp_path, "wren.db")
    b = agent(tmp_path, "tomas.db", world=a.world)
    ran = []

    async def step(state, settings, runner, now=None, scope=None):
        ran.append((state, scope))
        return True                                                # something happened
    monkeypatch.setattr(loop.modules, "step", step)
    woke = []
    for x in (a, b):
        monkeypatch.setattr(x, "request_wake", lambda force=False, urgent=False, x=x: woke.append(x))
    await a.world.step()
    assert ran == [(a.state, "world")] and woke == [a, b]                           # the world's modules, once


@pytest.mark.asyncio
async def test_an_agent_whose_loop_dies_is_started_again_and_the_others_go_on(tmp_path, monkeypatch):
    a = agent(tmp_path, "wren.db")
    b = agent(tmp_path, "tomas.db", world=a.world)
    runs = {"a": 0, "b": 0}

    async def dies():
        runs["a"] += 1
        if runs["a"] == 1:
            raise RuntimeError("the wire snapped")
        await asyncio.sleep(3600)

    async def lives():
        runs["b"] += 1
        await asyncio.sleep(3600)
    monkeypatch.setattr(a, "run", dies)
    monkeypatch.setattr(b, "run", lives)
    monkeypatch.setattr(World, "step", lambda self: asyncio.sleep(0))
    task = asyncio.create_task(a.world.run())
    for _ in range(200):
        await asyncio.sleep(0.01)
        if runs["a"] >= 2:
            break
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert runs == {"a": 2, "b": 1}
    err = next(e["data"] for e in a.state.events(10) if e["kind"] == "error")
    assert err["error"] == "the agent's loop stopped (RuntimeError: the wire snapped); started again"


def test_the_app_runs_the_world(tmp_path):
    from fastapi.testclient import TestClient
    from app.main import create_app
    with TestClient(create_app(settings(tmp_path), FakeBackend())) as c:
        world = c.app.state.world
        assert world is c.app.state.agent.world and world.agents[0].state is c.app.state.agent.state                # the first, by default
        assert [a.identity.key for a in world.agents] == ["pip", "oriel", "abel", "tansy", "lio"]                  # Pip's neighbours run too


def test_the_world_has_the_packs_narrator_and_its_own_runner_and_library(tmp_path):
    w = agent(tmp_path).world
    assert w.gm.system == w.pack.narrator_system() and w.gm.agent is w.pack.agent and w.gm.state is w.state
    assert w.runner is None and w.library is None                                  # no runner set, no library mounted: none, as before


@pytest.mark.asyncio
async def test_the_worlds_step_does_the_worlds_work_with_its_own_pieces(tmp_path, monkeypatch):
    a = agent(tmp_path, "wren.db", module_library="on", modules="on", module_runner="local")
    b = agent(tmp_path, "tomas.db", world=a.world)
    w, seen = a.world, {}

    def spy(name, real):
        async def f(*args, **kw):
            seen[name] = (args, kw)
            return await real(*args, **kw)
        return f
    for name, mod in (("step", loop.modules), ("answer", loop.modules), ("notify_owner", loop.modules), ("offer_library", loop.modules)):
        monkeypatch.setattr(mod, name, spy(name, getattr(mod, name)))
    monkeypatch.setattr(loop.happenings, "from_modules", spy("from_modules", loop.happenings.from_modules))
    monkeypatch.setattr(loop.layouts, "step", spy("layouts", loop.layouts.step))
    await w.step()
    assert seen["offer_library"][0] == (w.state, w.s, w.runner) and seen["step"][0] == (w.state, w.s, w.runner)
    assert seen["answer"][0] == (w.state, w.s, w.gm, w.runner) and seen["from_modules"][0] == (w.state, w.s, w.gm)
    assert seen["notify_owner"][0] == (w.state, w.s, a.outreach)                    # the first agent's channel
    assert seen["layouts"] == ((b.state, w.s, w.runner), {"library": w.library})                   # each agent's places, the last's here
    assert w.state.modules("live")                                                  # the library was offered for real
    w.check()
    assert w.state.map_positions()                                                  # and the map has its places


@pytest.mark.asyncio
async def test_the_worlds_night_is_the_builders_turn_and_a_failure_is_said(tmp_path, monkeypatch, caplog):
    w = agent(tmp_path).world
    seen = []

    async def night(*args, agents=None):
        seen.append((*args, agents))
        if len(seen) == 2:
            raise RuntimeError("no ideas")
    monkeypatch.setattr(loop.builder, "night", night)
    await w.night()
    with caplog.at_level("ERROR", logger="agent"):
        await w.night()
    one = w.agents[0]
    assert seen == [(w.state, w.s, w.gm, w.runner, [(one.identity, one.state)])] * 2 and "builder failed" in caplog.messages
    assert next(e["data"] for e in w.state.events(5) if e["kind"] == "error")["error"] == "builder: RuntimeError: no ideas"


@pytest.mark.asyncio
async def test_a_loop_that_just_ends_is_started_again_and_a_failing_step_is_logged(tmp_path, monkeypatch, caplog):
    a = agent(tmp_path)
    runs = []

    async def ends():
        runs.append(1)
        if len(runs) > 1:
            await asyncio.sleep(3600)

    async def fails(self):
        raise RuntimeError("the map tore")
    monkeypatch.setattr(a, "run", ends)
    monkeypatch.setattr(World, "step", fails)
    with caplog.at_level("ERROR", logger="agent"):
        task = asyncio.create_task(a.world.run())
        for _ in range(200):
            await asyncio.sleep(0.01)
            if len(runs) >= 2:
                break
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    assert next(e["data"] for e in a.state.events(10) if e["kind"] == "error")["error"] == "the agent's loop stopped; started again"
    assert "world step failed" in caplog.messages
