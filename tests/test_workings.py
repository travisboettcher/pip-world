"""Creations' workings as a module (0.25.0): the reads and effects a creation's abilities need, and the shipped `workings` module that runs
a creation's upkeep, clock, periodic lines, sensor and helper instead of the engine's built-in tick."""
import time

import pytest

from app import creations as cr
from app import modules as M
from tests.test_modules import NOW, live, modular, rule
from tests.test_world_view import TIMEKEEPER


def made(st, name="Sandy", caps=None, now=NOW):
    spec = {"capabilities": caps or {}, "quirks": []}
    return st.add_creation(name, "a thing", None, "sound", spec, cr.initial_runtime(spec, now))


PERIODIC = {"periodic": {"lines": ["It hums."], "every_minutes": 60}}
SENSOR = {"sensor": {"condition": "visitor", "alert": "The bell rings: someone is at the door."}}
FINDER = {"helper": {"effect": "find", "line": "It noses about in the hedge.", "every_minutes": 360, "finds": ["acorn", "snail shell"]}}
HURRY = {"helper": {"effect": "hurry_crops", "line": "It waters the beds.", "every_minutes": 60}}
COMFORT = {"helper": {"effect": "comfort", "line": "It purrs on your lap.", "every_minutes": 240}}


# --- reads -------------------------------------------------------------------------------------------------------------------
def test_a_module_can_read_the_garden_the_visitors_and_how_pip_is(tmp_path):
    s, st, agent = modular(tmp_path)
    st.plant(1, "pea seeds", "peas", 600, 3, 0.25)
    st.update_agent(hunger=0.7, energy=0.2, mood="tired")
    m = live(st, rule(reads=["garden", "visitors", "pip"]), "x")
    ctx = M.context(st, s, m, time.time())
    assert ctx["garden"][0] == {"plot": 1, "crop": "peas", "state": "growing", "ready_in_min": ctx["garden"][0]["ready_in_min"]}
    assert ctx["garden"][0]["ready_in_min"] > 0 and all(g["state"] == "empty" for g in ctx["garden"][1:]) and set(ctx["garden"][1]) == {"plot", "state"}
    assert ctx["visitors"] == {"waiting": 0}
    st.add_inbox("hello", "Ada")
    assert M.context(st, s, m, time.time())["visitors"] == {"waiting": 1}
    assert (ctx["pip"]["hunger"], ctx["pip"]["energy"], ctx["pip"]["mood"]) == (0.7, 0.2, "tired")
    assert {"garden", "visitors"} <= set(M.PIP_READS)


# --- effects -----------------------------------------------------------------------------------------------------------------
def test_affect_garden_and_find_are_checked_capped_and_applied(tmp_path):
    s, st, agent = modular(tmp_path)
    st.update_agent(energy=0.5, mood="fine")
    st.plant(1, "pea seeds", "peas", 600, 3, 0.25)
    man = rule(proposes=["affect", "garden", "find"], finds=["Acorn", "snail shell"])
    m = live(st, man, "x")
    assert m["manifest"]["finds"] == ["acorn", "snail shell"]
    now = time.time()
    before = st.garden(now)[0]["ready_at"]
    M.apply(st, m, M.plan(st, m, {"affect": {"energy": 0.05, "mood": "cosy"}, "garden": {"hurry": 0.1}, "find": {"item": "acorn", "qty": 2}}, now, "on_tick"), now)
    a = st.agent()
    assert round(a["energy"], 3) == 0.55 and a["mood"] == "cosy"
    assert st.garden(now)[0]["ready_at"] < before
    item, _ = st.find_item("acorn")
    assert item["qty"] == 2 and item["kind"] == "material"
    m = st.module(m["id"])
    assert (M._budget(m, now)["affect"], M._budget(m, now)["garden"], M._budget(m, now)["find"]) == (1, 1, 1)
    for bad, why in (({"affect": {"energy": 0.2}}, "`affect.energy` is a number from -0.1 to 0.1"),
                     ({"affect": {"mood": "x" * 41}}, "`affect.mood` is a word or two"),
                     ({"affect": {}}, "`affect` is {energy?, mood?}"),
                     ({"affect": 1}, "`affect` is {energy?, mood?}"),
                     ({"garden": {"hurry": 0.5}}, "`garden.hurry` is a number from 0.01 to 0.2"),
                     ({"garden": {}}, "`garden.hurry` is a number from 0.01 to 0.2"),
                     ({"find": {"item": "gold", "qty": 1}}, "it can only find: acorn, snail shell"),
                     ({"find": {"item": "acorn", "qty": 3}}, "`find.qty` is 1 or 2"),
                     ({"find": "acorn"}, "`find` is {item, qty}")):
        with pytest.raises(M.Refused) as e:
            M.plan(st, m, bad, now, "on_tick")
        assert str(e.value) == why
    st.update_module(m["id"], budget={"day": M._day(now), "find": M.PER_DAY["find"], "affect": M.PER_DAY["affect"], "garden": M.PER_DAY["garden"]})
    m = st.module(m["id"])
    for key, val in (("find", {"item": "acorn", "qty": 1}), ("affect", {"energy": 0.01}), ("garden", {"hurry": 0.1})):
        with pytest.raises(M.Refused) as e:
            M.plan(st, m, {key: val}, now, "on_tick")
        assert str(e.value) == f"it has used today's {M.PER_DAY[key]} `{key}`"
    st.update_agent(energy=0.98)
    M.apply(st, m, [("affect", {"energy": 0.1})], now)
    assert st.agent()["energy"] == 1.0


def test_find_needs_its_finds_and_pip_cant_grant_itself_effects():
    with pytest.raises(M.Refused) as e:
        M.check_manifest(rule(proposes=["find"]), "world")
    assert str(e.value) == "`find` and `finds` go together: say what it may find (up to 8 names)"
    with pytest.raises(M.Refused):
        M.check_manifest(rule(finds=["acorn"]), "world")
    for bad in (["x" * 41], ["a"] * 9, "acorn", [3]):
        with pytest.raises(M.Refused):
            M.check_manifest(rule(proposes=["find"], finds=bad), "world")
    for p in ("affect", "garden", "find"):
        assert p in M.PROPOSES and p not in M.PIP_PROPOSES


def test_the_engines_own_modules_have_room_for_a_busy_day():
    assert M.limits({"author": M.SHIPPED})["calls"] >= 1440 + 48 and M.limits({"author": M.SHIPPED})["perceive"] >= 72
    assert M.limits({"author": "world"}) == M.PER_DAY == M.limits({"author": "pip"})


# --- the workings module -----------------------------------------------------------------------------------------------------
async def workings(tmp_path, caps, **kw):
    s, st, agent = modular(tmp_path, **kw)
    c = made(st, caps=caps)
    man, source = M.workings_manifest(c)
    r = await M.propose(st, s, M.LocalRunner(), M.SHIPPED, man, source, "workings", now=NOW)
    assert st.module(r["id"])["status"] == "live", r
    return s, st, agent, c, st.module(r["id"])


@pytest.mark.asyncio
async def test_every_creation_that_does_something_gets_its_workings(tmp_path):
    s, st, agent = modular(tmp_path)
    for name, caps in (("Sandy", PERIODIC), ("Bell", SENSOR), ("Ferret", FINDER), ("Clock", TIMEKEEPER["capabilities"]),
                       ("Sundial", {"timekeeper": {"drift_per_day": 1}}), ("Vase", {}), ("Lamp", {"provides": {"ability": "news"}})):
        made(st, name, caps)
    ids = [i for i in await M.offer_library(st, s, None, now=NOW) if st.module(i)["subject"]]
    mods = {st.module(i)["subject"]: st.module(i) for i in ids}
    assert set(mods) == {"Sandy", "Bell", "Ferret", "Clock"}                                     # nothing to run in a sundial, a vase, a lamp
    assert all(m["status"] == "live" and m["author"] == M.SHIPPED and m["name"].endswith("-workings") for m in mods.values())
    assert mods["Sandy"]["manifest"]["hooks"] == ["on_install", "on_tick"] and mods["Clock"]["manifest"]["hooks"] == ["on_install", "on_time", "on_action"]
    assert mods["Ferret"]["manifest"]["finds"] == ["acorn", "snail shell"] and "finds" not in mods["Sandy"]["manifest"]
    assert mods["Clock"]["manifest"]["tends"] == "tend" and "tends" not in mods["Bell"]["manifest"]
    assert mods["Clock"]["offers"] == [{"name": "tend", "help": "wound: keeps it going about 12 hours"}, {"name": "set", "help": "set it to the right time"}]
    assert mods["Sandy"]["offers"] == [] and all(m["report"]["clean"] for m in mods.values())
    assert await M.offer_library(st, s, None, now=NOW) == []                                     # once


@pytest.mark.asyncio
async def test_periodic_lines_come_on_time_and_only_while_it_runs(tmp_path):
    s, st, agent, c, m = await workings(tmp_path, {**PERIODIC, "upkeep": {"verb": "wound", "hours": 12}})
    assert await M.step(st, s, None, NOW + 59 * 60) is False and M.perception(st) == []
    await M.step(st, s, None, NOW + 61 * 60)
    assert M.perception(st) == ["Things in the world:", "- Your Sandy: It hums."]
    await M.step(st, s, None, NOW + 90 * 60)
    assert M.perception(st) == []
    await M.step(st, s, None, NOW + 13 * 3600)                                                      # run down: it stops, and says so once
    assert M.perception(st) == ["Things in the world:", "- Your Sandy has stopped - it needs tending (wound)."]
    await M.step(st, s, None, NOW + 15 * 3600)
    assert M.perception(st) == []
    assert any(e["kind"] == "module" and e["data"]["text"] == "Your Sandy: It hums." for e in st.events(20))


@pytest.mark.asyncio
async def test_a_sensor_wakes_pip_once_each_time_it_comes_on(tmp_path):
    s, st, agent, c, m = await workings(tmp_path, SENSOR)
    assert await M.step(st, s, None, NOW + 60) is False
    st.add_inbox("hello", "Ada")
    assert await M.step(st, s, None, NOW + 120) is True
    assert M.perception(st) == ["Things in the world:", "- The bell rings: someone is at the door."]
    assert await M.step(st, s, None, NOW + 180) is False                                            # still on: no second alarm
    st.consume_inbox([r["id"] for r in st.pending_inbox()])
    await M.step(st, s, None, NOW + 240)
    assert st.module(m["id"])["state"]["sensor_on"] is False


@pytest.mark.parametrize("cond,setup,hour", [
    ("crop_ripe", lambda st: st.plant(1, "pea seeds", "peas", 1, 3, 0.25), None),
    ("hungry", lambda st: st.update_agent(hunger=0.7), None),
    ("tired", lambda st: st.update_agent(energy=0.2), None),
    ("dawn", lambda st: None, 6),
    ("dusk", lambda st: None, 19),
])
@pytest.mark.asyncio
async def test_each_sensor_condition(tmp_path, cond, setup, hour):
    s, st, agent, c, m = await workings(tmp_path, {"sensor": {"condition": cond, "alert": "Now!"}})
    st.update_agent(hunger=0.1, energy=0.9)
    day = time.strftime("%Y-%m-%d", time.localtime(time.time() + 86400))                     # tomorrow: a crop planted now is ripe by then
    base = time.mktime(time.strptime(f"{day} 12:00", "%Y-%m-%d %H:%M"))
    assert await M.step(st, s, None, base) is False
    setup(st)
    at = time.mktime(time.strptime(f"{day} {hour:02d}:10", "%Y-%m-%d %H:%M")) + 86400 if hour is not None else base + 120
    assert await M.step(st, s, None, at) is True


@pytest.mark.asyncio
async def test_helpers_find_hurry_and_comfort(tmp_path):
    s, st, agent, c, m = await workings(tmp_path, FINDER)
    await M.step(st, s, None, NOW + 361 * 60)
    line = M.perception(st)[1]
    assert line.startswith("- It noses about in the hedge. (found: ")
    found = line.split("found: ")[1].rstrip(")")
    assert st.find_item(found)[0]["qty"] == 1
    await M.step(st, s, None, NOW + 400 * 60)
    assert M.perception(st) == []
    (tmp_path / "h").mkdir()
    s, st, agent, c, m = await workings(tmp_path / "h", HURRY)
    await M.step(st, s, None, NOW + 61 * 60)
    assert M.perception(st) == []                                                                   # nothing growing: nothing to do
    st.plant(1, "pea seeds", "peas", (NOW - time.time()) / 60 + 600, 3, 0.25)               # still growing on the test's clock
    before = st.garden(NOW)[0]["ready_at"]
    await M.step(st, s, None, NOW + 122 * 60)
    assert M.perception(st) == ["Things in the world:", "- It waters the beds."] and st.garden(NOW)[0]["ready_at"] < before
    (tmp_path / "c").mkdir()
    s, st, agent, c, m = await workings(tmp_path / "c", COMFORT)
    st.update_agent(energy=0.5)
    await M.step(st, s, None, NOW + 241 * 60)
    assert round(st.agent()["energy"], 3) == 0.55 and M.perception(st) == ["Things in the world:", "- It purrs on your lap."]


@pytest.mark.asyncio
async def test_the_engine_leaves_a_creation_to_its_workings(tmp_path):
    s, st, agent, c, m = await workings(tmp_path, {**PERIODIC, **FINDER})
    owned = {k for k, b in M.bound(st).items() if b["author"] == M.SHIPPED}
    assert owned == {"sandy"}
    assert cr.tick(st, agent.rng, NOW + 7 * 3600, owned=owned) is False
    assert not [e for e in st.events(10) if e["kind"] == "creation"] and not st.find_item("acorn")[0]
    M.disable(st, m["id"])
    owned = {k for k, b in M.bound(st).items() if b["author"] == M.SHIPPED}
    cr.tick(st, agent.rng, NOW + 7 * 3600, owned=owned)
    assert [e["data"]["what"] for e in st.events(10) if e["kind"] == "creation"] == ["helper", "periodic"]


@pytest.mark.asyncio
async def test_a_live_workings_the_engine_changed_is_upgraded(tmp_path, monkeypatch):
    s, st, agent, c, m = await workings(tmp_path, PERIODIC)
    real = M.library
    monkeypatch.setattr(M, "library", lambda name: (real(name)[0], real(name)[1] + "\n# newer\n") if name == "workings" else real(name))
    st.update_module(m["id"], author="world")                                                       # the first clock was the world's
    ids = await M.offer_library(st, s, None, now=NOW)
    new = st.module(ids[-1])
    assert (new["name"], new["version"], new["author"], new["status"]) == (m["name"], 2, M.SHIPPED, "live") and st.module(m["id"])["status"] == "replaced"
    assert await M.offer_library(st, s, None, now=NOW) == []
    M.disable(st, new["id"])
    monkeypatch.setattr(M, "library", lambda name: (real(name)[0], real(name)[1] + "\n# newest\n") if name == "workings" else real(name))
    assert await M.offer_library(st, s, None, now=NOW) == []                                     # the owner switched it off: left alone


@pytest.mark.asyncio
async def test_effects_at_their_limits_add_up_and_say_where_they_came_from(tmp_path):
    s, st, agent = modular(tmp_path)
    st.update_agent(energy=0.5, mood="fine")
    c = made(st, "Ferret", FINDER)
    man = rule(kind="thing", subject="Ferret", proposes=["affect", "garden", "find"], finds=["acorn"])
    m = live(st, man, "x")
    now = time.time()
    for _ in range(2):
        M.apply(st, m, M.plan(st, m, {"affect": {"energy": 0.1}, "garden": {"hurry": 0.01}, "find": {"item": "Acorn"}}, now, "on_tick"), now)
        m = st.module(m["id"])
    M.apply(st, m, M.plan(st, m, {"affect": {"mood": "x" * 40}, "garden": {"hurry": 0.2}}, now, "on_tick"), now)
    m = st.module(m["id"])
    a = st.agent()
    assert round(a["energy"], 3) == 0.7 and a["mood"] == "x" * 40
    assert {k: M._budget(m, now)[k] for k in ("affect", "garden", "find")} == {"affect": 3, "garden": 3, "find": 2}
    item = st.find_item("acorn")[0]
    assert item["qty"] == 2 and "found by your Ferret" in str(item.get("note") or item.get("source") or item)
    rule_m = live(st, rule(name="hedge", proposes=["find"], finds=["acorn"]), "x")
    M.apply(st, rule_m, M.plan(st, rule_m, {"find": {"item": "acorn", "qty": 1}}, now, "on_tick"), now)
    assert "found by your hedge" in str(st.find_item("acorn")[0])
    with pytest.raises(M.Refused):
        M.plan(st, m, {"affect": {"energy": -0.11}}, now, "on_tick")
    with pytest.raises(M.Refused):
        M.plan(st, m, {"find": {"item": "acorn", "qty": True}}, now, "on_tick")


def test_a_creations_workings_have_only_the_hooks_it_needs():
    hooks = lambda caps: M.workings_manifest({"name": "X", "spec": {"capabilities": caps}})[0]["hooks"]
    assert hooks({"upkeep": {"verb": "w", "hours": 1}}) == ["on_install", "on_time", "on_action"]
    assert hooks({"timekeeper": {"drift_per_day": 1}, **PERIODIC}) == ["on_install", "on_tick", "on_action"]
    assert hooks(SENSOR) == ["on_install", "on_tick"]


@pytest.mark.asyncio
async def test_a_creation_with_nothing_to_run_doesnt_stop_the_next_getting_its_workings(tmp_path):
    s, st, agent = modular(tmp_path)
    made(st, "Vase", {})
    made(st, "Sandy", PERIODIC)
    t0 = time.time()
    ids = [i for i in await M.offer_library(st, s, None) if st.module(i)["subject"]]
    assert [st.module(i)["subject"] for i in ids] == ["Sandy"] and t0 <= st.module(ids[0])["created_at"] <= time.time()
