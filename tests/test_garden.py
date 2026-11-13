"""The garden as a module (docs/DESIGN-world-packs.md, phase 4b): module_library/garden.py, on the engine's generic hooks. Planting and
harvesting are its tools, the plots its store, what the agent sees its status, and the turns others ask of it its answers. Nothing in the
engine knows what a plot is."""
import time

import pytest

from app import modules as M
from app import tools as tools_mod
from app.config import Settings
from app.llm.base import ToolCall
from tests.test_modules import NOW, live, modular, rule


def garden(st, **params):
    """The shipped garden module, put straight in as live."""
    man, src = M.library("garden")
    man.pop("reason", None)
    return live(st, {**man, "params": {**man["params"], **params}}, src, author=M.SHIPPED)


async def use(agent, name, **args):
    return (await agent._run_tool(ToolCall(id="1", name=name, arguments=args), 0))["content"]


def setup(tmp_path, **params):
    s, st, agent = modular(tmp_path)
    return s, st, agent, garden(st, **params)


def plots(st):
    return st.store("garden").get("plots", {})


def ripen(st, now=None):
    """Every planted crop ripe now."""
    now = now or time.time()
    st.merge_store("garden", {"plots": {k: {**p, "ready_at": now - 1} for k, p in plots(st).items()}})


async def step(st, s, agent, now=None):
    m = M.live_named(st, "garden")
    st.update_module(m["id"], due=now or time.time())
    return await M.step(st, s, agent.runner, now or time.time())


# --- planting and harvesting ----------------------------------------------------------------------------------------------------------
async def test_plant_harvest_and_eat(tmp_path):
    s, st, agent, m = setup(tmp_path)
    r = await use(agent, "plant", seed="tomato")
    assert r == "planted tomato seeds in plot 1; tomatoes will be ready in about 24 hours" and st.find_item("tomato seeds")[0]["qty"] == 2
    assert (await use(agent, "plant", seed="carrot seeds", plot=3)).startswith("planted carrot seeds in plot 3")
    assert await use(agent, "plant", seed="tomato", plot=1) == "error: plot 1 is already growing tomatoes"
    assert await use(agent, "plant", seed="tomato", plot=9) == "error: plots are numbered 1-3"
    assert await use(agent, "plant", seed="tomato", plot="two") == "error: `plot` is a integer"
    p = plots(st)["1"]
    assert (p["seed"], p["crop"], p["yield"], p["food_value"], p["notified"]) == ("tomato seeds", "tomatoes", 3, 0.5, False)
    assert p["ready_at"] - p["planted_at"] == pytest.approx(1440 * 60)
    ripen(st)
    assert await use(agent, "harvest") == "harvested 3 tomatoes from plot 1"
    food = st.find_item("tomatoes")[0]
    assert (food["kind"], food["description"], food["attrs"]) == ("food", "fresh tomatoes from your garden", {"food_value": 0.5})
    assert "1" not in plots(st) and await use(agent, "harvest", plot=3) == "harvested 3 carrots from plot 3"
    st.update_agent(hunger=0.9)
    await tools_mod.REGISTRY["eat"][1](agent.ctx, {"item": "tomatoes"})
    assert st.agent()["hunger"] == pytest.approx(0.4)


async def test_every_plot_in_use_and_nothing_ripe(tmp_path):
    s, st, agent, m = setup(tmp_path)
    assert await use(agent, "harvest") == "nothing ripe to harvest; nothing is planted"
    for seed in ("tomato", "carrot", "tomato"):
        await use(agent, "plant", seed=seed)
    assert await use(agent, "plant", seed="carrot") == "error: every plot is in use; harvest one first"
    assert await use(agent, "harvest") == "nothing ripe to harvest; next ready in about 18 hours"
    assert await use(agent, "harvest", plot=0) == "error: plots are numbered 1-3"
    ev = st.events(1)[0]["data"]
    assert ev["tool"] == "harvest" and ev.get("noop") is None
    nothing = [e["data"] for e in st.events(5) if e["kind"] == "tool" and e["data"]["result"].startswith("nothing ripe")][0]
    assert nothing["noop"] and "first" not in nothing                       # nothing changed: not a moment, not a first


async def test_planting_a_seed_you_only_hold_as_food_says_how_to_get_the_seeds(tmp_path):
    s, st, agent, m = setup(tmp_path)
    st.take_item(st.find_item("tomato seeds")[0]["id"], 3)
    assert await use(agent, "plant", seed="tomato seeds") == "error: you don't have 'tomato seeds' (kind: seed)"
    st.add_item("tomatoes", 2, "food")
    assert await use(agent, "plant", seed="tomato seeds") == ("error: you don't have 'tomato seeds' (kind: seed); you could scoop seeds out of "
                                                              "your tomatoes with use_item (say what for)")
    assert "use_item" in await use(agent, "plant", seed="tomato")
    st.add_item("bean seeds", 1, "seed", "", {"crop": "beans", "grow_minutes": 60, "yield": 2, "food_value": 0.3})
    st.add_item("bean sprout seeds", 1, "seed", "", {"crop": "sprouts", "grow_minutes": 60, "yield": 2, "food_value": 0.3})
    assert await use(agent, "plant", seed="bean") == "error: which one? bean seeds, bean sprout seeds"
    assert (await use(agent, "plant", seed="bean seeds")).startswith("planted bean seeds")


async def test_the_garden_only_works_at_home(tmp_path):
    s, st, agent, m = setup(tmp_path)
    st.update_agent(location="woods")
    assert await use(agent, "plant", seed="tomato") == "you're at the woods; go_to home first"
    assert "plant" not in [t.name for t in agent._specs()]


async def test_growing_speed_and_the_weather(tmp_path):
    s, st, agent, m = setup(tmp_path, speed=2.0)
    assert await use(agent, "plant", seed="carrot") == "planted carrot seeds in plot 1; carrots will be ready in about 9 hours"
    assert plots(st)["1"]["ready_at"] - plots(st)["1"]["planted_at"] == pytest.approx(1080 * 30)
    from tests.test_sky import RAIN, sky_says
    sky_says(st, RAIN)                                                               # what the sky publishes
    await use(agent, "plant", seed="tomato")
    assert plots(st)["2"]["ready_at"] - plots(st)["2"]["planted_at"] == pytest.approx(1440 * 0.85 * 30)


# --- what the agent sees, and being told when a crop ripens ----------------------------------------------------------------------------
async def test_the_garden_is_shown_every_time_and_a_ripe_crop_wakes_the_agent(tmp_path):
    s, st, agent, m = setup(tmp_path)
    await use(agent, "plant", seed="tomato")
    lines = M.status_lines(st)
    assert lines[0] == "Your garden:" and lines[1] == "- plot 1: tomatoes growing, ready in about 24 hours" and lines[2] == "- plot 2: empty"
    assert st.module(m["id"])["due"] == pytest.approx(plots(st)["1"]["ready_at"])
    assert M.live_named(st, "garden")["facts"]["names"] == ["tomatoes"]
    ripen(st)
    assert await step(st, s, agent) is True                              # ripe: the agent wakes
    assert M.status_lines(st)[1] == "- plot 1: tomatoes are RIPE - harvest them" and M.standing(st)[0]["ready"]
    ev = next(e["data"] for e in st.events(5) if e["kind"] == "module")
    assert (ev["name"], ev["moment"], ev["text"], ev["feel"]) == ("garden", "ripe", "Your tomatoes in plot 1 ripened", {"joy": 3})
    assert [f["key"] for f in ev["firsts"]] == ["garden:ripe"]
    assert plots(st)["1"]["notified"] is True
    assert await step(st, s, agent) is False                             # told once
    assert agent._free_time(time.time()) == []                           # something waits: no free time


async def test_harvesting_and_planting_are_moments_and_firsts(tmp_path):
    s, st, agent, m = setup(tmp_path)
    await use(agent, "plant", seed="tomato")
    ev = st.events(1)[0]["data"]
    assert ev["first"] == "planted something" and [f["key"] for f in ev["firsts"]] == ["tool:plant"]
    assert agent._moment_text(st.events(1)[0]) == "Planted tomato seeds in plot 1; tomatoes will be ready in about 24 hours"


# --- what others may ask of it -----------------------------------------------------------------------------------------------------------
async def test_a_helper_hurries_the_garden(tmp_path):
    s, st, agent, m = setup(tmp_path)
    await use(agent, "plant", seed="tomato")
    left = plots(st)["1"]["ready_at"] - time.time()
    assert await M.ask_module(st, s, agent.runner, "garden", "hurry", {"share": 0.1}, True) == "helped 1 growing crop along"
    assert plots(st)["1"]["ready_at"] - time.time() == pytest.approx(left * 0.9, rel=0.01)
    with pytest.raises(M.Refused, match=r"`share` is 0.01 to 0.2"):
        await M.ask_module(st, s, agent.runner, "garden", "hurry", {"share": 0.5}, True)


async def test_hurrying_an_empty_garden_is_refused(tmp_path):
    s, st, agent, m = setup(tmp_path)
    with pytest.raises(M.Refused, match="^nothing is growing$"):
        await M.ask_module(st, s, agent.runner, "garden", "hurry", {}, True)


@pytest.mark.parametrize("tone,severity,how,line", [
    ("good", "medium", "time", "Plot 1's tomatoes will be ready about 4 hours sooner."),
    ("bad", "minor", "time", "Plot 1's tomatoes will be ready about 72 min later."),
    ("good", "major", "yield", "Plot 1's tomatoes will give 3 more."),
    ("bad", "major", "yield", "Plot 1's tomatoes will give 2 less."),
    ("bad", "major", "ruin", "Plot 1's tomatoes is lost."),
])
async def test_a_happenings_turn_for_a_crop(tmp_path, tone, severity, how, line):
    s, st, agent, m = setup(tmp_path)
    await use(agent, "plant", seed="tomato")
    before = dict(plots(st)["1"])
    args = {"plot": 1, "how": how}
    assert await M.ask_module(st, s, agent.runner, "garden", "crop", args, False, tone=tone, severity=severity) == line
    assert plots(st)["1"] == before                                        # saying what it would do changes nothing
    assert await M.ask_module(st, s, agent.runner, "garden", "crop", args, True, tone=tone, severity=severity) == line
    after = plots(st).get("1")
    if how == "ruin":
        assert after is None
    elif how == "yield":
        assert after["yield"] == before["yield"] + (3 if tone == "good" else -2)
    else:
        assert (after["ready_at"] < before["ready_at"]) == (tone == "good")


@pytest.mark.parametrize("args,tone,severity,why", [
    ({"plot": 2, "how": "time"}, "good", "minor", "`plot` is the number of a plot with something growing"),
    ({"plot": 1, "how": "ruin"}, "bad", "medium", "only a major bad turn ruins a crop"),
    ({"plot": 1, "how": "ruin"}, "good", "major", "only a major bad turn ruins a crop"),
    ({"plot": 1, "how": "dig"}, "good", "minor", "`how` is time, yield or ruin"),
])
async def test_a_crop_turn_that_cant_be(tmp_path, args, tone, severity, why):
    s, st, agent, m = setup(tmp_path)
    await use(agent, "plant", seed="tomato")
    with pytest.raises(M.Refused, match=__import__("re").escape(why)):
        await M.ask_module(st, s, agent.runner, "garden", "crop", args, False, tone=tone, severity=severity)


async def test_a_ripe_crop_cant_be_shifted_and_a_poor_one_cant_give_less(tmp_path):
    s, st, agent, m = setup(tmp_path)
    await use(agent, "plant", seed="tomato")
    st.merge_store("garden", {"plots": {"1": {**plots(st)["1"], "ready_at": time.time() + 30, "yield": 1}}})
    with pytest.raises(M.Refused, match="as good as ripe"):
        await M.ask_module(st, s, agent.runner, "garden", "crop", {"plot": 1, "how": "time"}, False, tone="good", severity="minor")
    with pytest.raises(M.Refused, match="can't give any less"):
        await M.ask_module(st, s, agent.runner, "garden", "crop", {"plot": 1, "how": "yield"}, False, tone="bad", severity="minor")


async def test_a_new_plot_up_to_the_most(tmp_path):
    s, st, agent, m = setup(tmp_path, plots_max=4)
    assert await M.ask_module(st, s, agent.runner, "garden", "add_plot", {}, True) == \
        "Your garden now has 4 plots: a new bed is ready for planting (plot 4)."
    assert st.store("garden")["meta"] == {"extra_plots": 1} and len(M.standing(st)[0]["lines"]) == 4
    with pytest.raises(M.Refused, match="as big as it can be"):
        await M.ask_module(st, s, agent.runner, "garden", "add_plot", {}, True)
    assert (await use(agent, "plant", seed="tomato", plot=4)).startswith("planted tomato seeds in plot 4")


async def test_finishing_a_bed_adds_a_plot(tmp_path):
    """The pack's world effect `garden_plot` asks the garden for a plot (content.json: request:garden:add_plot)."""
    from app import world_effects as W
    s, st, agent, m = setup(tmp_path)
    spec = {"capabilities": {"world": {"effect": "garden_plot"}}}
    assert await W.apply(st, spec) == "Your garden now has 4 plots: a new bed is ready for planting (plot 4)."


# --- the old garden moves in ---------------------------------------------------------------------------------------------------------------
def test_an_older_install_keeps_its_garden(tmp_path):
    from app.state import State
    s = Settings(db_path=str(tmp_path / "old.db"))
    st = State(s)
    st.db.execute("CREATE TABLE garden (plot INTEGER PRIMARY KEY, seed TEXT NOT NULL, crop TEXT NOT NULL, planted_at REAL NOT NULL, "
                  "ready_at REAL NOT NULL, yield INTEGER NOT NULL, food_value REAL NOT NULL, notified INTEGER NOT NULL DEFAULT 0)")
    st.db.execute("INSERT INTO garden VALUES (2, 'carrot seeds', 'carrots', 100, 200, 3, 0.4, 1)")
    st.set_meta(extra_plots=2)
    st.db.commit()
    st = State(s)
    assert st.store("garden") == {"meta": {"extra_plots": 2}, "plots": {"2": {"seed": "carrot seeds", "crop": "carrots", "planted_at": 100,
                                                                              "ready_at": 200, "yield": 3, "food_value": 0.4, "notified": True}}}
    assert not st.db.execute("SELECT 1 FROM sqlite_master WHERE name = 'garden'").fetchone()
    State(s)                                                                # once
    st.db.execute("CREATE TABLE garden (plot INTEGER PRIMARY KEY, seed TEXT, crop TEXT, planted_at REAL, ready_at REAL, yield INTEGER, "
                  "food_value REAL, notified INTEGER)")
    st.db.commit()
    assert State(s).store("garden")["plots"]["2"]["crop"] == "carrots"     # a store already there is kept


def test_an_empty_old_garden_moves_as_nothing(tmp_path):
    from app.state import State
    s = Settings(db_path=str(tmp_path / "old.db"))
    st = State(s)
    st.db.execute("CREATE TABLE garden (plot INTEGER PRIMARY KEY)")
    st.db.commit()
    assert State(s).store("garden") == {}


async def test_the_module_reads_a_moved_garden(tmp_path):
    s, st, agent, m = setup(tmp_path)
    st.merge_store("garden", {"plots": {"2": {"seed": "carrot seeds", "crop": "carrots", "planted_at": 100, "ready_at": 200, "yield": 3,
                                              "food_value": 0.4, "notified": True}}, "meta": {"extra_plots": 1}})
    assert await use(agent, "harvest") == "harvested 3 carrots from plot 2"
    assert len(M.status_lines(st)) == 5                                    # 4 plots and a title


def test_the_garden_ships_with_the_settings_as_its_params():
    man, _ = M.library("garden")
    s = Settings(garden_plots=5, garden_plots_max=9, garden_speed=3.0)
    assert M.settings_params(s, "garden", man["params"]) == {"plots": 5, "plots_max": 9, "speed": 3.0}
    assert "garden" in M.RULES and M.check_manifest({k: v for k, v in man.items() if k != "reason"}, M.SHIPPED)["tools"][0]["name"] == "plant"


def planted(st, s, plot, crop, minutes):
    """A crop in a plot (the garden module live, its status worked out), for tests of what reads the garden's status."""
    import asyncio
    m = M.live_named(st, "garden") or garden(st)
    now = time.time()
    st.merge_store("garden", {"plots": {str(plot): {"seed": crop + " seeds", "crop": crop, "planted_at": now, "ready_at": now + minutes * 60,
                                                    "yield": 3, "food_value": 0.5, "notified": False}}})
    import threading                                                       # sync or async tests alike: run it on its own loop
    t = threading.Thread(target=lambda: asyncio.run(M.call(st, s, M.LocalRunner(), M.live_named(st, "garden"), "on_install", now)))
    t.start()
    t.join()
    return m


def test_the_weather_scales_growing_time_within_a_cap():
    code = {}
    exec(M.library("garden")[1], code)                                     # the module's own table (the engine's weather has none)
    assert code["WEATHER"]["rainy"] == 0.85 and code["WEATHER"]["snowy"] == 1.15 and "partlycloudy" not in code["WEATHER"]
    assert all(0.85 <= v <= 1.15 for v in code["WEATHER"].values())


async def test_the_public_sees_what_the_garden_did(tmp_path):
    from app import public_view as pv
    s, st, agent, m = setup(tmp_path)
    await use(agent, "plant", seed="tomato")
    e = st.events(1)[0]
    assert e["data"]["module"] == "garden"
    assert pv.public_event(e)["data"] == {"tool": "plant", "result": "planted tomato seeds in plot 1; tomatoes will be ready in about 24 hours"}
    assert pv.public_event({**e, "data": {"tool": "say", "result": "secret"}})["data"] == {"tool": "say"}
