import random
import time
from datetime import datetime

import pytest

from app import capabilities as C
from app import gathering as G
from app import places as P
from app import tools as T
from app.world import KINDS
from tests.test_projects import PLAN, call, make, report

GATHER_TOOLS = ("gather", "where_to", "browse", "go_to", "rest")


def daytime(s):
    h = datetime.now().hour
    s.bedtime_hour, s.wake_hour = (h + 3) % 24, (h + 8) % 24


def night(s):
    h = datetime.now().hour
    s.bedtime_hour, s.wake_hour = h, (h + 8) % 24


def setup(tmp_path, script=None, where="junkyard", **kw):
    s, st, gm, agent = make(tmp_path, script, work_speed=10**6, **kw)
    agent.tools.update({n: T.REGISTRY[n] for n in GATHER_TOOLS})
    daytime(s)
    st.update_agent(location=where)
    return s, st, gm, agent


async def gather_and_wait(agent, minutes=30):
    r = await call(agent, "gather", minutes=minutes)
    time.sleep(0.05)
    await agent.resolve_world()
    return r


def test_the_loot_tables_are_well_formed_and_cover_what_pip_keeps_wishing_for():
    for place, table in G.LOOT.items():
        for name, kind, weight, (lo, hi), desc, attrs in table:
            assert kind in KINDS and weight > 0 and 1 <= lo <= hi and name and desc
            if kind == "seed":
                assert {"crop", "grow_minutes", "yield", "food_value"} <= set(attrs)
            if kind == "food":
                assert "food_value" in attrs
    names = {i[0] for i in G.JUNKYARD}
    assert {"brass wire", "scrap brass", "fine brass gears", "clock parts", "needle file", "tweezers"} <= names
    brass = {i[0]: i[2] for i in G.JUNKYARD}
    assert brass["brass wire"] > brass["fine brass gears"] and brass["needle file"] <= G.RARE_WEIGHT   # common vs rare


def test_stock_refills_with_time_and_shrinks_the_yield(tmp_path):
    s, st, *_ = make(tmp_path)
    now = time.time()
    assert G.stock(st, "woods", now) == G.CAPACITY
    st.set_meta(**{"stock:woods": 10, "stock_at:woods": now})
    assert G.stock(st, "woods", now) == 10 and G.stock(st, "woods", now + 3600) == pytest.approx(10 + G.REGEN_PER_HOUR)
    assert G.stock(st, "woods", now + 10 * 3600) == G.CAPACITY                  # never above capacity
    assert G.yield_factor(G.CAPACITY) == 1.0 and G.yield_factor(0) == G.MIN_YIELD and G.yield_factor(30) == 0.5


def test_a_draw_scales_with_time_and_depletion_and_skill_helps_rare_finds():
    rng = lambda n: random.Random(n)  # noqa: E731
    big = sum(len(G.draw(rng(i), "woods", 60, 1.0, 0)) for i in range(40))
    small = sum(len(G.draw(rng(i), "woods", 15, 1.0, 0)) for i in range(40))
    empty = sum(len(G.draw(rng(i), "woods", 60, G.MIN_YIELD, 0)) for i in range(40))
    assert big > small > 0 and empty < big / 2
    rare = lambda skill: sum(1 for i in range(300) for it in G.draw(rng(i), "junkyard", 60, 1.0, skill)  # noqa: E731
                             if it[0] in ("needle file", "tweezers", "small hammer"))
    assert rare(5) > rare(0)
    assert all(it[2] >= 1 for i in range(50) for it in G.draw(rng(i), "junkyard", 60, 0.3, 0))


@pytest.mark.asyncio
async def test_a_gather_session_finds_things_remembers_where_and_depletes_the_place(tmp_path):
    s, st, gm, agent = setup(tmp_path, [report(text="You turn over rusty heaps and pocket what's useful.")])
    agent.rng = random.Random(3)
    r = await call(agent, "gather", minutes=40)
    assert "you set about scavenging at the junkyard for 40 min" in r.text and st.session()["kind"] == "gather"
    assert "(still busy) you're out scavenging at the junkyard" in (await call(agent, "set_activity", activity="x")).text
    assert "(about" in (await call(agent, "gather")).text                          # busy
    time.sleep(0.05)
    await agent.resolve_world()
    ev = [e for e in st.events(20) if e["kind"] == "gathered"][0]["data"]
    assert ev["place"] == "junkyard" and ev["minutes"] == 40 and ev["items"] and ev["text"].startswith("You turn over rusty heaps")
    for it in ev["items"]:
        assert st.find_item(it["name"])[0]["qty"] >= it["qty"]
        assert any(f["item"] == it["name"] for f in st.finds_at("junkyard"))
    assert G.stock(st, "junkyard") == pytest.approx(G.CAPACITY - 40, abs=1)
    assert st.abilities().get("handiness", 0) > 0 and st.session() is None
    told = gm.calls[0]["messages"][0]["content"]
    assert all(it["name"] in told for it in ev["items"]) and "mention only these" in told
    assert "you found" not in told and st.agent()["activity"] == "idle"
    assert "- You turn over rusty heaps" in agent._perception("timer", [])


@pytest.mark.asyncio
async def test_a_picked_over_place_says_so_and_gives_little(tmp_path):
    s, st, gm, agent = setup(tmp_path)                                               # GM silent: fallback text
    st.set_meta(**{"stock:junkyard": 5, "stock_at:junkyard": time.time()})
    agent.rng = random.Random(1)
    r = await call(agent, "gather", minutes=30)
    assert "well picked over" in r.text
    time.sleep(0.05)
    await agent.resolve_world()
    ev = [e for e in st.events(20) if e["kind"] == "gathered"][0]["data"]
    assert ev["depleted"] and len(ev["items"]) <= 2 and ("picked over" in ev["text"])


@pytest.mark.asyncio
async def test_resting_cuts_a_gather_short_with_a_smaller_haul(tmp_path):
    s, st, gm, agent = setup(tmp_path)
    s.work_speed = 1
    agent.rng = random.Random(5)
    await call(agent, "gather", minutes=60)
    r = await call(agent, "rest")
    assert "you cut your time at the junkyard short" in r.text and st.session() is None
    ev = [e for e in st.events(5) if e["kind"] == "gathered"][0]["data"]
    assert ev["interrupted"] and ev["minutes"] <= 1


@pytest.mark.asyncio
async def test_gathering_needs_the_place_and_daylight(tmp_path):
    s, st, gm, agent = setup(tmp_path, where="workshop")
    assert (await call(agent, "gather")).text == "you're not at the woods; go_to woods first"
    st.update_agent(location="woods")
    night(s)
    assert (await call(agent, "gather")).text == "the woods is closed for now (it's dark); it opens in the morning"
    place = P.here(st, s, None)
    assert [sp.name for sp in T.specs_for(agent.tools, "woods", place, False)].count("gather") == 0
    assert "gather" in [sp.name for sp in T.specs_for(agent.tools, "woods", place, True)]
    assert "You are at: the woods, closed for now" in agent._perception("timer", [])
    daytime(s)
    assert "set about foraging at the woods" in (await call(agent, "gather")).text


@pytest.mark.asyncio
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


@pytest.mark.asyncio
async def test_a_missing_material_comes_with_where_it_was_found(tmp_path):
    s, st, gm, agent = setup(tmp_path, [report(**PLAN)], where="workshop")
    from tests.test_projects import PIP_STEPS
    await call(agent, "start_project", name="gear clock", steps=PIP_STEPS)
    assert "missing 2 brass wire" in agent._perception("timer", []) and "you found brass wire" not in agent._perception("timer", [])
    st.add_find("junkyard", "brass wire", time.time())
    assert "missing 2 brass wire (you have 0) - you found brass wire at the junkyard)" in agent._perception("timer", [])


@pytest.mark.asyncio
async def test_walking_takes_each_places_own_time_and_warns_when_closed(tmp_path):
    s, st, gm, agent = setup(tmp_path, where="workshop")
    s.work_speed = 1
    assert "about 15 min" in (await call(agent, "go_to", place="junkyard")).text
    st.end_session()
    r = await call(agent, "go_to", place="woods")
    assert "about 8 min" in r.text and "closed" not in r.text
    st.end_session()
    night(s)
    assert "It's closed right now (it's dark)" in (await call(agent, "go_to", place="woods")).text


@pytest.mark.asyncio
async def test_arriving_describes_a_new_place_from_its_blurb(tmp_path):
    s, st, gm, agent = setup(tmp_path, [report(text="Heaps of rusted things lean against each other.")], where="workshop")
    await call(agent, "go_to", place="junkyard")
    time.sleep(0.05)
    await agent.finish_work()
    assert st.agent()["location"] == "junkyard" and "scrap metal" in gm.calls[0]["messages"][0]["content"]
    assert "Here you can: gather (scavenge through the heaps), browse (look over the heaps" in agent._perception("timer", [])
    assert "Places you can go (go_to):" in agent._perception("timer", [])


@pytest.mark.asyncio
async def test_browsing_the_junkyard_shows_what_is_worth_digging_for_and_takes_nothing(tmp_path):
    s, st, gm, agent = setup(tmp_path)
    before = [(i["name"], i["qty"]) for i in st.items()]
    r = await call(agent, "browse")
    assert "Looking over the junkyard, you can make out:" in r.text and "gather to dig" in r.text
    assert [(i["name"], i["qty"]) for i in st.items()] == before and st.finds_at("junkyard") == []


@pytest.mark.asyncio
async def test_finds_feed_firsts_recall_and_capabilities(tmp_path):
    s, st, gm, agent = setup(tmp_path, [report(text="You dig out a coil of brass wire.")])
    agent.rng = random.Random(3)
    await gather_and_wait(agent)
    ev = [e for e in st.events(20) if e["kind"] == "gathered"][0]
    first = ev["data"]["items"][0]["name"]
    assert any(f["key"] == f"found:{first}" for f in ev["data"]["firsts"])
    assert st.recall("brass wire")[0]["source"] == "event:gathered" or st.recall(first)
    caps = C.collect(st.events(20))
    assert caps["tool"]["gather"] == {"tries": 1, "good": 1, "neutral": 0, "bad": 0}
    assert C.format_snapshot({"tool": {"gather": {"tries": 3, "good": 2, "neutral": 0, "bad": 1}}, "craft": {}, "ability": {}}) \
        .startswith("Tools:\n- gather: 3 tries, 2 found something, 1 didn't")


def test_wild_places_can_be_switched_off(tmp_path):
    s, st, *_ = make(tmp_path, wild_places=["woods"])
    assert list(P.registry(st, s, None)) == ["workshop", "woods"]
    (tmp_path / "x").mkdir()
    s2, st2, *_ = make(tmp_path / "x", wild_places=[])
    assert list(P.registry(st2, s2, None)) == ["workshop"]
