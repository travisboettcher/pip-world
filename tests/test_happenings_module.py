"""The shipped `happenings` rule (0.28.0): the dice, the slots, the nights and the choosing, as a module on the generic reads and `happen`."""
import random
import time

import pytest

from app import happenings as H
from app import modules as M
from tests.test_happenings_rule import rule_module
from tests.test_modules import modular

DAY0 = time.mktime((2026, 6, 1, 0, 0, 0, 0, 0, -1))          # a summer day, so the season is fixed


def at(day, hour, minute=5):
    return DAY0 + day * 86400 + hour * 3600 + minute * 60


async def rule_live(tmp_path, chance=1.0, **kw):
    s, st, agent = modular(tmp_path, happenings="on", happenings_chance=chance, **kw)
    man, src = M.library("happenings")
    man = {**man, "params": M.settings_params(s, "happenings", man["params"])}
    r = await M.propose(st, s, M.LocalRunner(), M.SHIPPED, man, src, man["reason"], now=at(0, 5))
    m = st.module(r["id"])
    assert m["status"] == "live" and m["report"]["clean"], m["report"]
    st.update_agent(activity="idle", hunger=0.2, energy=0.8)
    return s, st, agent, m


def proposed(st, m):
    return st.module(m["id"])["happen"]


@pytest.mark.asyncio
async def test_its_params_are_the_engines_happenings_settings(tmp_path):
    s, st, agent = modular(tmp_path, happenings_chance=0.25, happenings_slot_hours=2, happenings_severity=(1, 2, 3), happenings_seasons=False,
                           wake_hour=8, bedtime_hour=21)
    man, _ = M.library("happenings")
    assert M.settings_params(s, "happenings", man["params"]) == {"chance": 0.25, "slot_hours": 2, "severity": [1, 2, 3], "seasons": False,
                                                                  "wake_hour": 8, "bedtime_hour": 21}
    assert M.settings_params(s, "stall", {"a": 1}) == {"a": 1}
    made = await M.offer_library(st, s, None, now=at(0, 5))
    h = next(st.module(i) for i in made if st.module(i)["name"] == "happenings")
    assert h["manifest"]["params"]["chance"] == 0.25
    s.happenings_chance = 0.5                                                                    # the owner retunes: a new version
    again = await M.offer_library(st, s, None, now=at(0, 6))
    assert [st.module(i)["name"] for i in again] == ["happenings"] and st.module(again[0])["manifest"]["params"]["chance"] == 0.5


@pytest.mark.asyncio
async def test_one_roll_for_each_slot_in_its_first_half_hour(tmp_path):
    s, st, agent, m = await rule_live(tmp_path)
    await M.step(st, s, None, at(0, 6, 40))                                                      # the 6:00 slot's half hour is over
    assert proposed(st, m) == []
    await M.step(st, s, None, at(0, 9, 5))
    h = proposed(st, m)[0]
    assert h["category"] in rule_module().CATEGORIES and h["tone"] in ("good", "bad", "neutral") and "night" not in h
    st.update_module(m["id"], happen=[])
    await M.step(st, s, None, at(0, 9, 10))
    assert proposed(st, m) == []                                                                 # rolled once
    assert len(st.module(m["id"])["state"]["rolled"]) == 1


@pytest.mark.asyncio
async def test_about_one_slot_in_ten_at_the_usual_chance(tmp_path):
    s, st, agent, m = await rule_live(tmp_path, chance=0.1)
    hits = 0
    for day in range(40):
        for hour in (6, 9, 12, 15, 18, 21):
            await M.step(st, s, None, at(day, hour, 1))
            if proposed(st, m):
                hits += 1
                st.update_module(m["id"], happen=[])
    assert 8 <= hits <= 40                                                                       # 240 slots at 10%


@pytest.mark.asyncio
async def test_nothing_is_rolled_while_pip_cant_take_one_in(tmp_path):
    s, st, agent, m = await rule_live(tmp_path)
    st.start_session(0, 0, 10, at(0, 23), kind="walk", target="woods")
    await M.step(st, s, None, at(0, 9, 5))
    assert proposed(st, m) == []
    st.end_session()
    await M.step(st, s, None, at(0, 9, 10))                                                       # still in the slot's half hour: now it rolls
    assert proposed(st, m)
    st.update_module(m["id"], happen=[])
    s.happenings = "off"
    await M.step(st, s, None, at(0, 12, 5))
    assert proposed(st, m) == [] and st.module(m["id"])["state"]["rolled"][-1].endswith("#1")      # off: the 12:00 slot isn't rolled


@pytest.mark.asyncio
async def test_a_night_slept_through_is_rolled_on_waking(tmp_path):
    s, st, agent, m = await rule_live(tmp_path)
    st.update_agent(activity="sleeping")
    await M.step(st, s, None, at(0, 22, 30))
    assert st.module(m["id"])["state"]["slept_at"] == at(0, 22, 30)
    st.update_agent(activity="idle")
    await M.step(st, s, None, at(1, 6, 50))                                                      # eight hours: slots to roll
    h = proposed(st, m)[0]
    assert h["night"] is True and h["category"] not in ("market", "neighbor") and "slept_at" not in st.module(m["id"])["state"]
    (tmp_path / "b").mkdir()
    s, st, agent, m = await rule_live(tmp_path / "b")
    st.update_agent(activity="sleeping")
    await M.step(st, s, None, at(0, 13, 0))
    st.update_agent(activity="idle")
    await M.step(st, s, None, at(0, 14, 50))                                                     # a nap shorter than a slot: nothing
    assert proposed(st, m) == []


@pytest.mark.asyncio
async def test_a_category_rests_twelve_hours_and_needs_the_world_to_allow_it(tmp_path):
    s, st, agent, m = await rule_live(tmp_path)
    seen = []
    for k in range(18):
        st.update_module(m["id"], happen=[])
        await M.step(st, s, None, at(k // 6, 6 + 3 * (k % 6), 5))
        if proposed(st, m):
            h = proposed(st, m)[0]
            seen.append((h["category"], at(k // 6, 6 + 3 * (k % 6), 5)))
            row = st.add_happening(ts=at(k // 6, 6 + 3 * (k % 6), 5), slot=f"t{k}", category=h["category"], tone=h["tone"], severity=h["severity"],
                                   lens="joy", seed="x", context={}, effects=[], effects_line="", meaning={"emotion": "joy", "amount": 1, "jolt": 0,
                                   "shown_at": None}, text="t", title="t", author="test", status="resolved")
    assert len(seen) == 9                                                                         # three a day
    for i, (cat, t) in enumerate(seen):
        assert all(t - t0 >= 12 * 3600 for c0, t0 in seen[:i] if c0 == cat), seen               # nothing twice in twelve hours
    assert not {"garden", "market", "neighbor", "kindness", "memory"} & {c for c, _ in seen}     # nothing growing, no shops, no neighbors


@pytest.mark.asyncio
async def test_a_proposed_happening_becomes_real(tmp_path):
    s, st, agent, m = await rule_live(tmp_path)
    await M.step(st, s, None, at(0, 9, 5))
    assert proposed(st, m)
    class Writer:
        async def write_happening(self, category, tone, severity, lens, line, facts, recent):
            return None
    t = at(0, 9, 6)
    assert await H.from_modules(st, s, Writer(), t) in (True, False)
    assert st.happenings(1) or any(e["kind"] == "happening_dropped" for e in st.events(5))


