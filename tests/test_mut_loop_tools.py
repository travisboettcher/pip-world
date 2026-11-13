"""The loop and the tools where phase 4 touched them, at their edges: tool dispatch, diary moments, free time, the world check, what a
finished or interrupted session is handed, module tools at a closed place, and the small registries around them."""
import time
from types import SimpleNamespace

import pytest

from app import modules as M
from app import tools as T
from app.config import Settings
from app.llm.base import ToolCall
from tests.test_modules import live, modular, rule
from tests.test_projects import make


async def run(agent, name, index=0, **args):
    return await agent._run_tool(ToolCall(id="7", name=name, arguments=args), index)


# --- dispatching a tool call ------------------------------------------------------------------------------------------------------------
async def test_too_many_calls_unknown_tools_and_failures(tmp_path, monkeypatch):
    s, st, gm, agent = make(tmp_path)
    assert await run(agent, "rest", index=4) == {"id": "7", "name": "rest", "followup": False, "is_error": True,
                                                  "content": "skipped: too many tool calls this turn"}
    assert (await run(agent, "rest", index=3))["is_error"] is False
    out = await run(agent, "teleport")
    assert out == {"id": "7", "name": "teleport", "followup": True, "is_error": True, "content": "error: unknown or disabled tool 'teleport'"}
    assert st.events(1)[0]["kind"] == "tool_error" and st.events(1)[0]["data"] == {"tool": "teleport", "error": "unknown or disabled tool"}

    async def boom(ctx, args):
        raise KeyError("x")
    agent.tools["rest"] = (agent.tools["rest"][0], boom)
    out = await run(agent, "rest", how="quietly")
    assert out == {"id": "7", "name": "rest", "followup": True, "is_error": True, "content": "error: KeyError: 'x'"}
    assert st.events(1)[0]["data"] == {"tool": "rest", "args": {"how": "quietly"}, "error": "KeyError: 'x'"}


async def test_a_tools_pictures_go_to_the_model_only_if_it_can_see(tmp_path):
    s, st, gm, agent = make(tmp_path)

    async def pic(ctx, args):
        return T.ToolResult("a picture", images=[("image/png", b"x")])
    agent.tools["rest"] = (agent.tools["rest"][0], pic)
    agent.backend.vision = False
    assert "images" not in await run(agent, "rest")
    agent.backend.vision = True
    assert (await run(agent, "rest"))["images"] == [("image/png", b"x")]

    async def plain(ctx, args):
        return T.ToolResult("nothing to see")
    agent.tools["rest"] = (agent.tools["rest"][0], plain)
    assert "images" not in await run(agent, "rest")


async def test_a_modules_tool_call_is_logged_with_its_arguments(tmp_path):
    from tests.test_garden import garden
    s, st, gm, agent = make(tmp_path, modules="on", module_runner="local")
    garden(st)
    out = await run(agent, "plant", seed="tomato", plot=2)
    assert out["followup"] is False and out["content"].startswith("planted tomato seeds in plot 2")
    assert st.events(1)[0]["data"]["args"] == {"seed": "tomato", "plot": 2} and st.events(1)[0]["data"]["first"] == "planted something"


# --- diary moments -------------------------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("kind,data,text", [
    ("module", {"text": "Your peas ripened", "moment": "ripe"}, "Your peas ripened"),
    ("module", {"text": "It hums."}, None),
    ("reading", {"title": "Dune", "finished": True}, "You finished reading Dune"),
    ("reading", {"title": "Dune", "finished": False}, None),
    ("arrived", {"place": "woods", "first_time": True}, "You went to the woods for the first time"),
    ("arrived", {"place": "woods", "first_time": False}, None),
    ("arrived", {"place": "workshop", "first_time": True}, None),
    ("work", {"project": "Clock", "text": "Gears.", "result": "steady", "finished_stage": False, "project_done": False, "interrupted": True}, None),
    ("work", {"project": "Clock", "text": "Gears.", "result": "steady", "finished_stage": False, "project_done": False}, None),
    ("work", {"project": "Clock", "text": "Gears.", "result": "breakthrough", "finished_stage": False, "project_done": False},
     "Working on Clock: Gears."),
    ("work", {"project": "Clock", "text": "Gears.", "result": "blowup", "finished_stage": True, "project_done": False, "step_note": "fit",
              "expectation": "as hoped", "lost": ["brass", "glue"], "learned": "go slow"},
     "Working on Clock: Gears. (that stage is done) (fit) (as hoped) You lost some brass, glue. You learned: go slow"),
    ("work", {"project": "Clock", "text": "Gears.", "result": "steady", "finished_stage": False, "project_done": False, "learned": "x"},
     "Working on Clock: Gears. You learned: x"),
    ("work", {"project": "Clock", "text": "Gears.", "result": "steady", "finished_stage": False, "project_done": False, "expectation": "e"},
     "Working on Clock: Gears. (e)"),
    ("experiment", {"project": "Clock", "hypothesis": "oil helps", "text": "It did.", "finding": "oil helps", "added": ["oil it", "test it"],
                    "expectation": "right"}, "Experiment on Clock (oil helps): It did. You now know: oil helps New steps opened up: oil it, test it. (right)"),
    ("experiment", {"project": "Clock", "hypothesis": "h", "text": "Nothing."}, "Experiment on Clock (h): Nothing."),
    ("experiment", {"project": "Clock", "hypothesis": "h", "text": "Nothing.", "interrupted": True}, None),
    ("tool", {"tool": "harvest", "args": {}, "result": "harvested 3 peas", "first": "harvested something"}, "Harvested 3 peas"),
    ("tool", {"tool": "harvest", "args": {}, "result": "error: no", "first": "harvested something"}, None),
    ("tool", {"tool": "harvest", "args": {}}, None),
    ("tool", {"tool": "say", "args": {}, "result": "started project"}, None),
    ("tool", {"tool": "start_project", "args": {"name": "Kite"}, "result": "error"}, None),
    ("tool", {"tool": "resolve_note", "args": {"id": 4}, "result": "nope"}, None),
    ("tool", {"tool": "resolve_note", "args": {"id": 4}, "result": "crossed off #4"}, "You crossed off #4"),
    ("tool", {"tool": "resolve_note", "args": {"id": 4, "outcome": "y" * 120}, "result": "crossed off #4"}, "You crossed off #4: " + "y" * 100),
])
def test_what_is_worth_a_diary_line(kind, data, text):
    from app.loop import Agent
    assert Agent._moment_text({"kind": kind, "data": data}) == text


# --- free time -----------------------------------------------------------------------------------------------------------------------------
def test_free_time_at_its_edges(tmp_path):
    s, st, gm, agent = make(tmp_path)
    now = time.time()
    m = live(st, rule(name="pots"), "x")
    st.update_module(m["id"], standing={"title": "Pots", "lines": [], "ready": False, "next_at": now})
    assert agent._free_time(now)[0] == "Nothing needs you for now."                     # due now is not "for a while"
    st.update_module(m["id"], standing={"title": "Pots", "lines": [], "ready": False})
    assert agent._free_time(now)[0] == "Nothing needs you for now."
    st.add_memory("A" * 150, "ambitions")
    for i in range(25):
        st.add_memory(f"wish {i}", "wishlist", "thing")
    st.add_memory("To fly a kite.", "wishlist", "activity")
    got = agent._free_time(now)
    assert got[1].endswith("A" * 97 + "...") or len(got[1].split(" ", 3)[-1]) <= 101
    assert len(got) >= 3 and "To fly a kite." in got[2]


# --- the world check -------------------------------------------------------------------------------------------------------------------------
def test_the_world_check_alerts_drifts_and_maps(tmp_path, monkeypatch):
    from app import emotions, worldmap
    s, st, gm, agent = make(tmp_path)
    seen = []
    monkeypatch.setattr(emotions, "drift", lambda state, settings: seen.append(("drift", state, settings)))
    monkeypatch.setattr(worldmap, "sync", lambda state, settings, library: seen.append(("sync", state, settings, library)))
    agent.library = "lib"
    st.update_agent(hunger=0.79, updated_at=time.time() - 3600)
    agent.check_world()
    assert st.events(1)[0]["kind"] == "alert" and st.events(1)[0]["data"]["stat"] == "hunger" and agent._wake.is_set()
    assert seen == [("drift", st, s), ("sync", st, s, "lib")]


# --- what a finished or interrupted session is handed ------------------------------------------------------------------------------------------


@pytest.mark.parametrize("kind,where,fn,result,note", [
    ("module", "modules", "end_session", {"label": "tidying"}, " (you stopped tidying early)"),
])
async def test_stopping_early_hands_on_everything_and_says_so(tmp_path, monkeypatch, kind, where, fn, result, note):
    s, st, gm, agent = make(tmp_path)
    got = []

    async def fake(*args, **kw):
        got.append((args, kw))
        return result

    async def none(*args, **kw):
        return None
    monkeypatch.setattr(getattr(T, where), fn, fake)
    st.start_session(0, 0, 30, time.time() + 1800, kind=kind, target="x")
    assert await T.stop_working(agent.ctx) == note
    args, kw = got[0]
    assert args[0] is st and kw == {"interrupted": True} and args[1] is s
    if kind in ("experiment", "work"):
        assert agent.ctx.gm in args
    if kind in ("experiment", "work"):
        assert args[-1] is agent.ctx.rng
    monkeypatch.setattr(getattr(T, where), fn, none)
    st.start_session(0, 0, 30, time.time() + 1800, kind=kind, target="x")
    assert await T.stop_working(agent.ctx) == ""


# --- module tools where they apply -------------------------------------------------------------------------------------------------------------
def test_a_modules_tools_at_a_closed_place(tmp_path):
    s, st, agent = modular(tmp_path)
    tools = [{"name": "fish", "help": "Fish.", "where": "harbour", "params": {"type": "object", "properties": {"n": {"type": "integer"}}}},
             {"name": "hum", "help": "Hum.", "where": "anywhere"}]
    live(st, rule(name="sea", hooks=["on_action"], tools=tools), "x")
    harbour = SimpleNamespace(scope="harbour")
    open_ = T.module_specs(st, "harbour", harbour, open_=True)
    assert [(t.name, t.description, t.parameters["properties"]) for t in open_] == [("fish", "Fish.", {"n": {"type": "integer"}}), ("hum", "Hum.", {})]
    assert [t.name for t in T.module_specs(st, "harbour", harbour, open_=False)] == ["hum"]
    assert [t.name for t in T.module_specs(st, "woods", SimpleNamespace(scope="woods"), open_=False)] == ["hum"]
    assert [t.name for t in T.module_specs(st, "")] == ["hum"]                    # on the way somewhere: what works anywhere


async def test_the_agent_is_offered_module_tools_where_it_is(tmp_path, monkeypatch):
    from app import places
    s, st, gm, agent = make(tmp_path)
    live(st, rule(name="sea", hooks=["on_action"], tools=[{"name": "fish", "help": "Fish.", "where": "woods"}, {"name": "hum", "help": "Hum."}]), "x")
    st.update_agent(location="woods")
    monkeypatch.setattr(places, "open_now", lambda place, settings: False)
    assert "fish" not in [t.name for t in agent._specs()] and "hum" in [t.name for t in agent._specs()]
    monkeypatch.setattr(places, "open_now", lambda place, settings: True)
    assert "fish" in [t.name for t in agent._specs()]
    monkeypatch.setattr(places, "present_at", lambda state: None)
    assert "fish" not in [t.name for t in agent._specs()] and "hum" in [t.name for t in agent._specs()]


async def test_a_module_tools_result_and_what_it_carries(tmp_path):
    s, st, agent = modular(tmp_path)
    t = [{"name": "hum", "help": "Hum.", "first": "hummed"}]
    live(st, rule(name="tune", hooks=["on_action"], proposes=["state"], tools=t), "def on_action(ctx):\n    return {'state': {'a': 1}, 'reply': 'hm'}\n")
    r = await T.module_tool(agent.ctx, "hum", {})
    assert (r.text, r.followup, r.noop, r.first, r.module) == ("hm", False, False, "hummed", "tune")
    live(st, rule(name="tune2", hooks=["on_action"], tools=[{"name": "sing", "help": "Sing."}]), "def on_action(ctx):\n    return {}\n")
    r = await T.module_tool(agent.ctx, "sing", {"x": 1})
    assert (r.text, r.followup, r.noop, r.first) == ("error: it takes: nothing", True, False, "")
    r = await T.module_tool(agent.ctx, "sing", {})
    assert (r.text, r.noop, r.first) == ("you sing.", True, "")
    assert await T.module_tool(agent.ctx, "dance", {}) is None


# --- enabled tools, decay, and the small registries ------------------------------------------------------------------------------------------
def test_each_unavailable_tool_is_skipped_not_the_rest(tmp_path):
    base = dict(db_path=str(tmp_path / "t.db"), modules="off", emotions="off", outreach="off", sleep=False, library_path="")
    got = T.enabled_tools(Settings(tools=["program", "settle", "send_postcard", "read", "sleep", "say", "browse"], **base))
    assert list(got) == ["say", "browse"]                                    # browse looks over the junkyard, library or not
    assert list(T.enabled_tools(Settings(tools=["say", "say", "rest"], **base))) == ["say", "rest"]


def test_a_module_session_tires_only_if_it_is_work(tmp_path):
    s, st, gm, agent = make(tmp_path)
    for stage, kind in ((0, "module"), (1, "read")):
        st.update_agent(energy=0.8, updated_at=time.time() - 3600, activity="idle")
        st.start_session(0, stage, 60, time.time() + 3600, kind=kind, target="x")
        st.apply_decay()
        assert st.agent()["energy"] == pytest.approx(0.75, abs=0.001), (stage, kind)
        assert st.agent()["updated_at"] == pytest.approx(time.time(), abs=5)


def test_world_effects_details(tmp_path, monkeypatch):
    from app import world_effects as W
    from app import world_pack
    with pytest.raises(AttributeError, match="^NOPE$"):
        W.NOPE
    assert "garden_plot (clearing and preparing new ground so the garden has another plot); workbench (" in W.gm_lines()
    bench = {"name": "Make a thing", "goal": "a new workbench", "difficulty": 2, "stages": [{"name": "saw"}]}
    assert W.allowed("workbench", bench) and not W.allowed("workbench", {**bench, "goal": None})
    raw = {"wall": {"help": "a wall", "does": "add_project_slot"}}                   # nothing the engine does itself any more: a module's
    monkeypatch.setattr(world_pack.Pack, "data", lambda self, name: {"world_effects": raw} if name == "content" else {})
    assert W.registry()["wall"].apply(SimpleNamespace()) is None and W.DOES == {}


async def test_a_world_effect_asks_the_module_with_no_arguments(tmp_path, monkeypatch):
    from app import world_effects as W
    s, st, agent = modular(tmp_path)
    seen = {}

    async def ask(state, settings, runner, name, what, args, apply, **kw):
        seen.update(name=name, what=what, args=args, apply=apply)
        return ""
    monkeypatch.setattr(M, "ask_module", ask)
    spec = {"capabilities": {"world": {"effect": "garden_plot"}}}
    assert await W.apply(st, spec) is None and "world" not in spec["capabilities"]
    assert seen == {"name": "garden", "what": "add_plot", "args": {}, "apply": True}


def test_a_pack_with_no_module_firsts(tmp_path):
    from app import firsts, world_pack
    from tests.test_world_pack import pack_dir
    world_pack.set_active(world_pack.load(Settings(world_pack=str(pack_dir(tmp_path)))))
    assert firsts.module_firsts() == {}


def test_status_names_the_worlds_stats(tmp_path):
    from app import commands
    from tests.test_mut_stats import WASTE, pack
    from app.state import State
    s = pack(tmp_path, "waste", WASTE)
    st = State(s)
    assert "rads 10%, stamina 80%" in commands.answer(st, s, "/status")


def test_a_working_module_session_tires_by_the_work_rate(tmp_path):
    s, st, gm, agent = make(tmp_path)
    st.update_agent(energy=0.8, updated_at=time.time() - 3600, activity="idle")
    st.start_session(0, 1, 60, time.time() + 3600, kind="module", target="x")
    st.apply_decay()
    assert st.agent()["energy"] == pytest.approx(0.7, abs=0.001)


async def test_a_session_of_a_kind_nothing_finishes_just_ends(tmp_path):
    s, st, gm, agent = make(tmp_path)
    assert await agent.finish_work() is False                                       # nothing to finish
    st.start_session(0, 0, 1, time.time() + 600, kind="gather", target="woods")
    assert await agent.finish_work() is False and st.session()                      # not yet
    st.start_session(0, 0, 1, time.time() - 1, kind="gather", target="woods")       # from before gathering was a module
    assert await agent.finish_work() is False and st.session() is None
