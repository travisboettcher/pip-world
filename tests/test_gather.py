"""Gathering (docs/DESIGN-world-packs.md, phase 5a): the shipped `gathering` module (module_library/gathering.py) on the engine's place data
(app/finds.py): the find tables, how picked over a place is, and the session, haul, practice and words."""
import random
import time
from datetime import datetime

import pytest

from app import capabilities as C
from app import finds as F
from app import modules as M
from app import places as P
from app import tools as T
from app.llm.base import ToolCall
from app.world import KINDS
from tests.test_projects import PLAN, call, make, report

GATHER_TOOLS = ("where_to", "browse", "go_to", "rest", "set_activity")


def daytime(s):
    h = datetime.now().hour
    s.bedtime_hour, s.wake_hour = (h + 3) % 24, (h + 8) % 24


def night(s):
    h = datetime.now().hour
    s.bedtime_hour, s.wake_hour = h, (h + 8) % 24


def module(st, **params):
    from tests.test_modules import live                                      # (test_modules reaches back here through its own imports)
    man, src = M.library("gathering")
    man.pop("reason", None)
    return live(st, {**man, "params": {**man["params"], **params}}, src, author=M.SHIPPED)


def setup(tmp_path, script=None, where="junkyard", speed=10**6, **kw):
    s, st, gm, agent = make(tmp_path, script, work_speed=speed, modules="on", module_runner="local", **kw)
    agent.tools.update({n: T.REGISTRY[n] for n in GATHER_TOOLS})
    module(st, speed=speed)
    daytime(s)
    st.update_agent(location=where)
    return s, st, gm, agent


async def gather(agent, **args):
    return (await agent._run_tool(ToolCall(id="1", name="gather", arguments=args), 0))["content"]


async def finish(agent, s):
    """The session's time is up: the haul, then the model's words for it."""
    agent.state.db.execute("UPDATE work_session SET ends_at = ?", (time.time() - 1,))
    agent.state.db.commit()
    await agent.finish_work()
    await M.answer(agent.state, s, agent.gm, agent.runner)


async def gather_and_wait(agent, minutes=30):
    """Gather, and let the time pass: the haul and its words."""
    r = await call_gather(agent, minutes=minutes)
    await finish(agent, agent.s)
    return r


async def call_gather(agent, **args):
    return T.ToolResult(await gather(agent, **args))


def haul(st):
    return next(e["data"] for e in st.events(20) if e["kind"] == "module" and e["data"].get("moment") == "gathered")


def code():
    out = {}
    exec(M.library("gathering")[1], out)
    return out


# --- the place data ------------------------------------------------------------------------------------------------------------------------
def test_the_find_tables_are_well_formed_and_cover_what_pip_keeps_wishing_for():
    for place, table in F.loot().items():
        for name, kind, weight, (lo, hi), desc, attrs in table:
            assert kind in KINDS and weight > 0 and 1 <= lo <= hi and name and desc
            if kind == "seed":
                assert {"crop", "grow_minutes", "yield", "food_value"} <= set(attrs)
            if kind == "food":
                assert "food_value" in attrs
    junk = F.loot()["junkyard"]
    assert {"brass wire", "scrap brass", "fine brass gears", "clock parts", "needle file", "tweezers"} <= {i[0] for i in junk}
    brass = {i[0]: i[2] for i in junk}
    assert brass["brass wire"] > brass["fine brass gears"] and brass["needle file"] <= code()["RARE_WEIGHT"]   # common vs rare


def test_stock_refills_with_time_is_drawn_down_and_shrinks_the_yield(tmp_path):
    s, st, *_ = make(tmp_path)
    now = time.time()
    assert F.stock(st, "woods", now) == F.CAPACITY
    st.set_meta(**{"stock:woods": 10, "stock_at:woods": now})
    assert F.stock(st, "woods", now) == 10 and F.stock(st, "woods", now + 3600) == pytest.approx(10 + F.REGEN_PER_HOUR)
    assert F.stock(st, "woods", now + 10 * 3600) == F.CAPACITY                  # never above capacity
    assert F.deplete(st, "woods", 4, now) == 6 and F.deplete(st, "woods", 40, now) == 0 and F.stock(st, "woods", now) == 0
    assert F.yield_factor(F.CAPACITY) == 1.0 and F.yield_factor(0) == F.MIN_YIELD and F.yield_factor(30) == 0.5


def test_a_heard_of_shop_has_the_default_session_and_verb(tmp_path):
    from tests.test_invented_places import known_shop
    s, st, *_ = make(tmp_path)
    known_shop(st, now=time.time())
    assert F.session_for(st, "Saltholm") == F.SESSION_MINUTES and F.verb_for(st, "Saltholm") == "gathering"


# --- the module's draw ----------------------------------------------------------------------------------------------------------------------
class ScriptRng:
    """A random source whose draws the test decides: `uniform` returns u, `choices` the next picked index, `randint` hi."""
    def __init__(self, u=0.0, picks=()):
        self.u, self.picks, self.calls = u, list(picks), []

    def uniform(self, a, b):
        self.calls.append(("uniform", a, b))
        return self.u

    def choices(self, table, weights):
        self.calls.append(("choices", list(weights)))
        return [table[self.picks.pop(0)]]

    def randint(self, lo, hi):
        self.calls.append(("randint", lo, hi))
        return hi


TABLE = [["odd tool", "tool", 6, [1, 1], "an odd tool", {}], ["stuff", "material", 7, [1, 4], "common stuff", {}]]


def test_a_draw_counts_finds_from_minutes_and_stock_and_practice_weights_rare_ones():
    draw = code()["draw"]
    rng = ScriptRng(0.4, [1])
    assert draw(rng, TABLE, 6, 1.0, 2.0) == [["stuff", "material", 4, "common stuff", {}]]
    assert rng.calls == [("uniform", -0.5, 0.5), ("choices", [pytest.approx(7.8), 7]), ("randint", 1, 4)]
    assert draw(ScriptRng(0.0, [1]), TABLE, 0, 1.0, 0) == []                         # no time, no finds
    assert draw(ScriptRng(0.0, [1, 1, 0]), TABLE, 60, 0.5, 0) == [["stuff", "material", 6, "common stuff", {}], ["odd tool", "tool", 1, "an odd tool", {}]]


def test_a_draw_scales_with_time_and_depletion_and_practice_helps_rare_finds():
    draw, table = code()["draw"], [list(e[:3]) + [list(e[3]), e[4], e[5]] for e in F.loot()["junkyard"]]
    big = sum(len(draw(random.Random(i), table, 60, 1.0, 0)) for i in range(40))
    small = sum(len(draw(random.Random(i), table, 15, 1.0, 0)) for i in range(40))
    poor = sum(len(draw(random.Random(i), table, 60, F.MIN_YIELD, 0)) for i in range(40))
    assert big > small > 0 and poor < big / 2
    rare = lambda skill: sum(1 for i in range(300) for it in draw(random.Random(i), table, 60, 1.0, skill)  # noqa: E731
                             if it[0] in ("needle file", "tweezers", "small hammer"))
    assert rare(5) > rare(0) and all(it[2] >= 1 for i in range(50) for it in draw(random.Random(i), table, 60, 0.3, 0))


# --- a gathering session -----------------------------------------------------------------------------------------------------------------------
async def test_a_gather_finds_things_remembers_where_and_depletes_the_place(tmp_path):
    s, st, gm, agent = setup(tmp_path, [report(text="You turn over rusty heaps and pocket what's useful.")])
    r = await gather(agent, minutes=40)
    assert r == "you set about scavenging at the junkyard for 40 min. You'll see what you found in about 1 min." and st.session()["kind"] == "module"
    assert (st.agent()["activity"], st.agent()["description"]) == ("gathering", "scavenging at the junkyard")
    assert "(still busy) you're out scavenging at the junkyard" in (await call(agent, "set_activity", activity="x")).text
    assert (await gather(agent)) == "error: Pip is busy with something else"
    await finish(agent, s)
    ev = haul(st)
    assert ev["text"] == "You turn over rusty heaps and pocket what's useful." and ev["items"] and ev["tool"] == "gather"
    for it in ev["items"]:
        assert st.find_item(it["name"])[0]["qty"] >= it["qty"] and any(f["item"] == it["name"] for f in st.finds_at("junkyard"))
    assert F.stock(st, "junkyard") == pytest.approx(F.CAPACITY - 40, abs=1)
    assert st.abilities() == {"handiness": 20, "patience": 20} and st.session() is None
    told = gm.calls[0]["messages"][0]["content"]
    assert all(it["name"] in told for it in ev["items"]) and "mention only these" in told and "Pip spent about 40 minutes scavenging" in told
    assert (st.agent()["activity"], st.agent()["description"]) == ("idle", "just back from scavenging at the junkyard")
    assert "- You turn over rusty heaps" in agent._perception("timer", [])


async def test_with_no_words_from_the_model_the_haul_is_told_plainly(tmp_path):
    s, st, gm, agent = setup(tmp_path)                                               # the model says nothing
    st.set_meta(**{"stock:junkyard": 5, "stock_at:junkyard": time.time()})
    r = await gather(agent, minutes=30)
    assert "The ground looks well picked over." in r
    await finish(agent, s)
    ev = haul(st)
    assert ev["text"].startswith("You spend about 30 minutes at the junkyard and ") and "picked over" in ev["text"] and len(ev["items"]) <= 2


async def test_resting_cuts_a_gather_short_with_a_smaller_haul(tmp_path):
    s, st, gm, agent = setup(tmp_path, speed=1)
    await gather(agent, minutes=60)
    r = await call(agent, "rest")
    assert "(you stopped out scavenging at the junkyard early)" in r.text and st.session() is None
    ev = haul(st)
    assert ev["text"].startswith("You spend about 0 minutes at the junkyard and come away with nothing") and ev["text"].endswith("(You cut it short.)")
    assert gm.calls == []                                                            # cut short: not narrated


async def test_gathering_needs_a_place_that_offers_it_and_daylight(tmp_path):
    s, st, gm, agent = setup(tmp_path, where="workshop")
    assert await gather(agent) == "there's nothing to gather at home"
    assert "gather" not in [sp.name for sp in agent._specs()]
    st.update_agent(location="woods")
    night(s)
    assert await gather(agent) == "the woods is closed for now (it's dark); it opens in the morning"
    assert "gather" not in [sp.name for sp in agent._specs()]
    daytime(s)
    spec = next(sp for sp in agent._specs() if sp.name == "gather")
    assert spec.description == P.registry(st, s, None)["woods"].verbs["gather"][1]   # worded the woods' way
    assert (await gather(agent)).startswith("you set about foraging at the woods")


async def test_a_shop_haul_goes_on_account(tmp_path):
    from tests.test_invented_places import real_shop
    s, st, gm, agent = setup(tmp_path, [report(text="You pick through the drawers.")], where="Saltholm")
    real_shop(st)
    st.update_place("Saltholm", on_account={"brass wire": 2})
    st.update_agent(location="Saltholm")
    assert (await gather(agent, minutes=15)).startswith("you set about rummaging in the ironmonger's drawer at Saltholm for 15 min.")
    await finish(agent, s)
    ev = haul(st)
    owed = st.place_row("Saltholm")["on_account"]
    assert sum(owed.values()) == 2 + sum(i["qty"] for i in ev["items"])
    assert ev["text"] == "You pick through the drawers. It's on account at Saltholm: they're happy for you to settle up later."
    assert st.agent()["description"] == "just back from rummaging in the ironmonger's drawer at Saltholm"


async def test_practice_makes_rare_finds_likelier(tmp_path, monkeypatch):
    s, st, gm, agent = setup(tmp_path)
    st.add_ability_xp({"handiness": 540, "patience": 60})                            # levels 3 and 1: practice 2
    m = M.live_named(st, "gathering")
    assert M.context(st, s, m, time.time())["abilities"]["handiness"] == 3


async def test_finds_feed_firsts_recall_and_capabilities(tmp_path):
    s, st, gm, agent = setup(tmp_path, [report(text="You dig out a coil of brass wire.")])
    await gather(agent)
    await finish(agent, s)
    ev = next(e for e in st.events(20) if e["kind"] == "module" and e["data"].get("moment") == "gathered")
    first = ev["data"]["items"][0]["name"]
    assert any(f["key"] == f"found:{first}" for f in ev["data"]["firsts"])
    assert st.recall("brass wire") or st.recall(first)
    caps = C.collect(st.events(20))
    assert caps["tool"]["gather"] == {"tries": 1, "good": 1, "neutral": 0, "bad": 0}
    assert C.format_snapshot({"tool": {"gather": {"tries": 3, "good": 2, "neutral": 0, "bad": 1}}, "craft": {}, "ability": {}}) \
        .startswith("Tools:\n- gather: 3 tries, 2 found something, 1 didn't")


# --- places, walking, where_to (the engine's) -----------------------------------------------------------------------------------------------------
async def test_where_to_uses_the_directory_and_what_pip_has_found(tmp_path):
    s, st, gm, agent = setup(tmp_path, where="workshop")
    r = await call(agent, "where_to", what="some wire")
    assert "the junkyard: a scrapyard over the hill" in r.text and "you haven't found any yet" in r.text
    st.add_find("junkyard", "brass wire", time.time() - 3 * 86400)
    st.add_find("junkyard", "brass wire", time.time())
    r = await call(agent, "where_to", what="brass")
    assert "the junkyard" in r.text and "you've found brass wire there 2 times (last just now)" in r.text
    assert "woods" not in (await call(agent, "where_to", what="brass")).text
    assert "the woods" in (await call(agent, "where_to", what="berries and nuts")).text
    assert "can't think of anywhere" in (await call(agent, "where_to", what="a unicorn")).text
    assert "error" in (await call(agent, "where_to", what="  ")).text


async def test_a_missing_material_comes_with_where_it_was_found(tmp_path):
    s, st, gm, agent = setup(tmp_path, [report(**PLAN)], where="workshop")
    from tests.test_projects import PIP_STEPS
    agent.tools["start_project"] = T.REGISTRY["start_project"]
    await call(agent, "start_project", name="gear clock", steps=PIP_STEPS)
    assert "missing 2 brass wire" in agent._perception("timer", []) and "you found brass wire" not in agent._perception("timer", [])
    st.add_find("junkyard", "brass wire", time.time())
    assert "missing 2 brass wire (you have 0) - you found brass wire at the junkyard)" in agent._perception("timer", [])


async def test_walking_takes_each_places_own_time_and_warns_when_closed(tmp_path):
    s, st, gm, agent = setup(tmp_path, where="workshop", speed=1)
    assert "about 15 min" in (await call(agent, "go_to", place="junkyard")).text
    st.end_session()
    r = await call(agent, "go_to", place="woods")
    assert "about 8 min" in r.text and "closed" not in r.text
    st.end_session()
    night(s)
    assert "It's closed right now (it's dark)" in (await call(agent, "go_to", place="woods")).text


async def test_arriving_describes_a_new_place_from_its_blurb(tmp_path):
    s, st, gm, agent = setup(tmp_path, [report(text="Heaps of rusted things lean against each other.")], where="workshop")
    await call(agent, "go_to", place="junkyard")
    time.sleep(0.05)
    await agent.finish_work()
    assert st.agent()["location"] == "junkyard" and "scrap metal" in gm.calls[0]["messages"][0]["content"]
    assert "Here you can: gather (scavenge through the heaps), browse (look over the heaps" in agent._perception("timer", [])
    assert "Places you can go (go_to):" in agent._perception("timer", [])


async def test_browsing_the_junkyard_shows_what_is_worth_digging_for_and_takes_nothing(tmp_path):
    s, st, gm, agent = setup(tmp_path)
    before = [(i["name"], i["qty"]) for i in st.items()]
    r = await call(agent, "browse")
    assert "Looking over the junkyard, you can make out:" in r.text and "gather to dig" in r.text
    assert [(i["name"], i["qty"]) for i in st.items()] == before and st.finds_at("junkyard") == []


def test_wild_places_can_be_switched_off(tmp_path):
    s, st, *_ = make(tmp_path, wild_places=["woods"])
    assert list(P.registry(st, s, None)) == ["workshop", "woods"]
    (tmp_path / "x").mkdir()
    s2, st2, *_ = make(tmp_path / "x", wild_places=[])
    assert list(P.registry(st2, s2, None)) == ["workshop"]


async def test_getting_home_is_never_a_first_visit(tmp_path):
    s, st, gm, agent = setup(tmp_path, [report(text="Heaps of rusted things.")], where="junkyard")
    await call(agent, "go_to", place="home")
    time.sleep(0.05)
    await agent.finish_work()
    (arrived,) = st.events(1)
    assert arrived["data"] == {"place": "workshop", "label": "home", "first_time": False, "description": ""}
    assert gm.calls == []
