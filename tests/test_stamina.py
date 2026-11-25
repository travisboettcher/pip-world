"""Stamina (docs/DESIGN-stamina.md): energy is what an agent can spend. The owner (2026-11-24): thinking and talking tire an agent, time
awake still does, rest and sleep restore it, and the day's token budget stays a hard ceiling behind it. Oriel, who is old, tires sooner."""
import json
import os

import pytest

from app import loop, stats as S, world_pack as W
from app.config import Settings
from app.llm.fake import FakeBackend
from tests.test_agents import two
from tests.test_projects import make


@pytest.fixture
def restore():
    yield
    W.set_active(W.load(Settings()))


def p_stamina(key):
    return W.load(Settings()).agent_named(key).stamina


def energy(state):
    return state.agent()["energy"]


# --- what a call costs ------------------------------------------------------------------------------------------------------------
def test_a_calls_tokens_spend_energy_by_the_agents_stamina(tmp_path):
    s, st, gm, agent = make(tmp_path)
    st.update_agent(energy=0.9)
    assert S.stamina(st) == S.DEFAULT_STAMINA == 2_500_000 and S.stamina(st) == p_stamina("pip")
    st.add_usage(200_000, 50_000)                                                              # an hour's talk, about
    assert energy(st) == pytest.approx(0.9 - 250_000 / 2_500_000)
    st.add_usage(0, 0)
    assert energy(st) == pytest.approx(0.8)
    st.add_usage(2_500_000, 0)                                                                 # never below the stat's floor
    assert energy(st) == pytest.approx(S.declared(s)["energy"]["floor"])
    assert st.usage_today()["total_tokens"] == 2_750_000                                       # the budget counts it all as before


def test_stamina_is_the_agents_then_the_worlds_then_the_default(tmp_path, restore):
    d = two(tmp_path)
    w = json.loads((d / "world.json").read_text())
    w["agents"][1]["stamina"] = 300_000
    (d / "world.json").write_text(json.dumps(w))
    (d / "stats.json").write_text(json.dumps({"energy": {"label": "energy", "start": 0.9, "tires": True, "floor": 0.1, "good": "high",
                                                         "stamina": 450_000}}))
    os.makedirs(tmp_path / "data")
    s = Settings(world_pack=str(d), db_path=str(tmp_path / "data" / "agent.db"), persona_path="/x", pacing="manual")
    wren, ivo = loop.build(s, FakeBackend()).agents
    with wren.acting():
        assert S.stamina(wren.state) == 450_000                                               # the world's
    with ivo.acting():
        assert S.stamina(ivo.state) == 300_000                                                 # his own
        ivo.state.add_usage(30_000, 0)
    assert energy(ivo.state) == pytest.approx(0.9 - 0.1) and energy(wren.state) == pytest.approx(0.9)   # each spends its own
    for bad in (0, -5, "lots", True, 1.5):
        w["agents"][1]["stamina"] = bad
        (d / "world.json").write_text(json.dumps(w))
        with pytest.raises(W.PackError, match="an agent's `stamina` is how many tokens a full bar of energy holds: a whole number above 0$"):
            W.load(Settings(world_pack=str(d)))


def test_a_world_without_a_tiring_stat_spends_nothing(tmp_path, restore):
    d = two(tmp_path)
    (d / "stats.json").write_text(json.dumps({"hunger": {"label": "hunger", "start": 0.2, "good": "low"}}))
    os.makedirs(tmp_path / "data")
    s = Settings(world_pack=str(d), db_path=str(tmp_path / "data" / "agent.db"), persona_path="/x", pacing="manual")
    wren, _ = loop.build(s, FakeBackend()).agents
    with wren.acting():
        before = wren.state.agent()
        wren.state.add_usage(100_000, 0)
        assert S.stamina(wren.state) == S.DEFAULT_STAMINA and wren.state.agent()["hunger"] == before["hunger"]


# --- how tired it feels -----------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("value,words", [(1.0, "wide awake"), (0.55, "wide awake"), (0.54, "a little tired"), (0.3, "a little tired"),
                                         (0.29, "tired"), (0.13, "tired"), (0.12, "exhausted"), (0.1, "exhausted")])
def test_the_agent_sees_how_tired_it_is_in_words(tmp_path, value, words):
    s, st, gm, agent = make(tmp_path)
    st.update_agent(energy=value)
    assert S.how_tired(st) == words
    assert f"energy {value:.2f} (0=exhausted; you feel {words})" in S.prompt_line(st)
    assert S.exhausted(st) is (words == "exhausted")


# --- exhausted ----------------------------------------------------------------------------------------------------------------------
def test_an_exhausted_agent_can_only_do_small_things(tmp_path):
    from app import stakes
    s, st, gm, agent = make(tmp_path)
    st.update_agent(energy=0.5)
    assert all(stakes.allowed(st, t) for t in ("go_to", "gather", "write_letter", "eat", "sleep"))
    st.update_agent(energy=0.1)
    assert [t for t in ("go_to", "gather", "write_letter", "eat", "rest", "sleep", "say", "feel", "note_to_self", "recall") if stakes.allowed(st, t)] \
        == ["eat", "rest", "sleep", "say", "feel", "note_to_self", "recall"]


@pytest.mark.asyncio
async def test_a_talk_ends_when_the_next_to_speak_is_exhausted(tmp_path, restore):
    from app import talk
    from tests.test_agent_talk import opens, says
    d = two(tmp_path)
    (d / "stats.json").write_text(json.dumps({"energy": {"label": "energy", "start": 0.9, "tires": True, "floor": 0.1, "good": "high"}}))
    os.makedirs(tmp_path / "data")
    s = Settings(world_pack=str(d), db_path=str(tmp_path / "data" / "agent.db"), persona_path="/x", pacing="manual", talk_scenes="on",
                 tools=["say", "go_to"], reflect_hour=99, min_tick_interval=0)
    w = loop.build(s, FakeBackend())
    wren, ivo = w.agents
    for a in w.agents:
        a.state.update_agent(location="ruins")
    assert talk.cut_short(wren.state, ivo.state) is None
    ivo.state.update_agent(energy=0.1)
    assert talk.cut_short(ivo.state, wren.state) == "too tired" and talk.cut_short(wren.state, ivo.state) is None   # the one to speak


# --- naps ---------------------------------------------------------------------------------------------------------------------------
def at(hour, minute=30, day=24):
    from datetime import datetime
    return datetime(2026, 11, day, hour, minute).timestamp()


def test_bed_before_the_evening_is_a_nap_until_rested(tmp_path):
    """Tansy went to bed at 12:23 (2026-11-24) and slept until 6 the next morning, about 18 hours, rested in three."""
    from app import sleep as sl
    s, st, gm, agent = make(tmp_path, sleep=True)
    assert sl.nap_before(s) == 20                                                             # two hours before the usual 10 pm
    st.update_agent(energy=0.5)
    r = sl.fall_asleep(st, s, at(12, 23))
    assert r == {"until": at(12, 23) + 2 * 3600, "nap": True} and st.meta("sleep_kind") == "nap"   # rested in two hours: the most
    st.update_agent(energy=0.8)
    assert sl.fall_asleep(st, s, at(15))["until"] == pytest.approx(at(15) + 0.2 / 0.25 * 3600)       # 48 minutes
    st.update_agent(energy=0.97)
    assert sl.fall_asleep(st, s, at(19, 59))["until"] == at(19, 59) + 20 * 60                      # 20 minutes at the least
    r = sl.fall_asleep(st, s, at(20, 0))
    assert r == {"until": sl.next_wake(s, at(20, 0)), "nap": False} and st.meta("sleep_kind") == "night"   # an early night
    assert sl.fall_asleep(st, s, at(23))["nap"] is False and sl.fall_asleep(st, s, at(3))["nap"] is False
    s.nap_before_hour = 18
    assert sl.nap_before(s) == 18 and sl.fall_asleep(st, s, at(18, 30))["nap"] is False and sl.fall_asleep(st, s, at(17, 59))["nap"] is True


def test_a_nap_brings_no_reflection_the_night_does(tmp_path):
    from app import memory as mem, sleep as sl
    s, st, gm, agent = make(tmp_path, sleep=True)
    st.set_meta(last_reflection_ts=at(10), last_reflection_day="2026-11-24")
    sl.fall_asleep(st, s, at(13))
    assert not mem.due(st, s, at(13, 40))
    sl.fall_asleep(st, s, at(22))
    assert mem.due(st, s, at(22, 10))


@pytest.mark.asyncio
async def test_the_sleep_tool_says_whether_it_is_a_nap(tmp_path, monkeypatch):
    from app import sleep as sl
    from tests.test_projects import call
    s, st, gm, agent = make(tmp_path, sleep=True)
    st.update_agent(energy=0.6)
    monkeypatch.setattr(sl, "is_nap", lambda settings, now: True)
    r = await call(agent, "sleep")
    assert r.text.startswith("you lie down for a nap; you'll wake rested in about") and r.text.endswith("min.")
    st.update_agent(activity="idle")
    monkeypatch.setattr(sl, "is_nap", lambda settings, now: False)
    assert (await call(agent, "sleep")).text.startswith("you go to bed and fall asleep; you'll sleep until about")


# --- the day's budget, and messages that wait ---------------------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_an_agent_at_its_days_budget_sleeps_until_morning(tmp_path, monkeypatch):
    """Oriel hit her budget at 14:21 (2026-11-24) and stood silent for the rest of the day; now she sleeps it off."""
    from app import sleep as sl
    s, st, gm, agent = make(tmp_path, sleep=True)
    monkeypatch.setattr(s, "daily_token_budget", 100)
    st.add_usage(80, 30)
    agent.backend.script = []
    await agent.tick("timer")
    assert st.agent()["activity"] == "sleeping" and st.meta("sleep_kind") == "night"
    assert float(st.meta("sleep_until")) == sl.next_wake(s, float(st.meta("sleep_started")))
    assert [e["kind"] for e in st.events(5)][:2] == ["fell_asleep", "budget_exceeded"] and agent.backend.calls == []
    from app import memory as mem
    assert not mem.due(st, s, float(st.meta("sleep_started")) + 60)                         # no reflection it can't pay for
    monkeypatch.setattr(s, "daily_token_budget", 10_000)
    assert mem.due(st, s, float(st.meta("sleep_started")) + 60)                             # once the budget is back, it reflects


@pytest.mark.asyncio
async def test_a_message_waits_for_a_sleeper_to_wake(tmp_path):
    """The owner (2026-11-24): a message, the owner's too, waits in the inbox until the agent wakes. A forced tick still wakes it."""
    import asyncio
    from app import sleep as sl
    s, st, gm, agent = make(tmp_path, sleep=True)
    sl.fall_asleep(st, s, at(23))
    agent.pacing.next_delay = lambda now, last: 0.05
    agent.receive("Are you awake?", "Travis")                                                  # a visitor's message
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(agent._sleep(), timeout=0.3)
    assert [m["text"] for m in st.pending_inbox()] == ["Are you awake?"]                       # waiting, unread
    agent.request_wake(force=True)
    assert await asyncio.wait_for(agent._sleep(), timeout=2) == "forced"


def test_where_a_nap_ends_and_the_night_begins(tmp_path):
    from app import sleep as sl
    s, st, gm, agent = make(tmp_path, sleep=True)
    naps = lambda: [h for h in range(24) if sl.is_nap(s, at(h, 0))]
    assert naps() == list(range(6, 20))                                                      # 6 am to 8 pm; 8 to 10 an early night
    s.bedtime_hour, s.wake_hour = 1, 9                                                       # a late world: the cut-off is 11 pm
    assert sl.nap_before(s) == 23 and naps() == list(range(9, 23))
    s.bedtime_hour, s.wake_hour, s.nap_before_hour = 22, 6, 22                               # no early night at all
    assert naps() == list(range(6, 22))
    s.nap_before_hour = None
    sl.fall_asleep(st, s, at(13))
    assert st.agent()["description"] == "napping"
    sl.fall_asleep(st, s, at(21))
    assert st.agent()["description"] == "asleep"
    assert sl.perception(st, s, at(21))[0].endswith("you can go to bed now for the night (you'd wake in the morning).")
    assert sl.perception(st, s, at(13))[0].endswith("lying down now is a nap until you're rested.")


def test_a_nap_in_a_world_whose_tiredness_counts_up_or_has_no_sleep_rate(tmp_path, restore):
    from app import sleep as sl
    d = two(tmp_path)
    (d / "stats.json").write_text(json.dumps({"fatigue": {"label": "fatigue", "start": 0.1, "tires": True, "good": "low", "ceiling": 0.9,
                                                          "asleep_per_hour": -0.5}}))
    os.makedirs(tmp_path / "data")
    s = Settings(world_pack=str(d), db_path=str(tmp_path / "data" / "agent.db"), persona_path="/x", pacing="manual", sleep=True)
    wren, _ = loop.build(s, FakeBackend()).agents
    with wren.acting():
        wren.state.update_agent(fatigue=0.5)
        assert sl.nap_until(wren.state, s, 1000.0) == 1000.0 + 0.5 / 0.5 * 3600                # an hour to rest it off
        assert S.how_tired(wren.state) == "a little tired" and not S.exhausted(wren.state)
        wren.state.update_agent(fatigue=0.9)
        assert S.exhausted(wren.state) and S.how_tired(wren.state) == "exhausted"             # at its ceiling: spent
        wren.state.add_usage(10, 0)
        assert wren.state.agent()["fatigue"] == pytest.approx(0.9)                            # no further than the ceiling
    (d / "stats.json").write_text(json.dumps({"fatigue": {"label": "fatigue", "start": 0.1, "tires": True, "good": "low"}}))
    W._data.cache_clear()
    W.set_active(W.load(s))
    with wren.acting():
        assert sl.nap_until(wren.state, s, 1000.0) == 1000.0 + 120 * 60                        # no sleep rate: the longest nap
