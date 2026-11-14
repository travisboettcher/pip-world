"""Stakes (docs/DESIGN-world-packs.md, phase 6): a stat that can run out (`at_zero`: knocked out, or weak until it recovers), and the
`harm` a happening can do to it. Pip's world has none, so these tests give the agent health (or radiation) through `Settings.stats`."""
import json
import random
import time

import pytest

from app import happenings as H
from app import memory as mem
from app import places
from app import stakes as S
from app import stats as stats_mod
from app.llm.base import ToolCall
from tests.test_projects import make

HEALTH = {"label": "health", "start": 0.8, "good": "high", "low_at": 0.25, "at_zero": "knocked_out", "out_hours": 3, "scale": "0=dying"}
RADIATION = {"label": "radiation", "start": 0.1, "good": "low", "low_at": 0.7, "at_zero": "weak"}


def world(tmp_path, **health):
    return make(tmp_path, stats={"health": {**HEALTH, **health}, "radiation": RADIATION})


def test_a_stat_settings_name_is_added_to_the_worlds(tmp_path):
    s, st, gm, agent = world(tmp_path)
    assert set(stats_mod.declared(s)) == {"hunger", "energy", "health", "radiation"} and stats_mod.declared(s)["energy"]["tires"]
    assert st.agent()["health"] == 0.8 and st.agent()["radiation"] == 0.1


def test_the_bad_end_recovery_and_where_a_knockout_leaves_a_stat():
    assert (S.bad_end(HEALTH), S.bad_end(RADIATION)) == (0.0, 1.0)
    assert S.at_end(HEALTH, 0.0) and S.at_end(HEALTH, 0.001) and not S.at_end(HEALTH, 0.0011) and not S.at_end(HEALTH, 1.0)
    assert S.at_end(RADIATION, 1.0) and S.at_end(RADIATION, 0.999) and not S.at_end(RADIATION, 0.998) and not S.at_end(RADIATION, 0.0)
    assert S.recovers_to(HEALTH) == pytest.approx(0.35) and S.recovers_to(RADIATION) == pytest.approx(0.6)
    assert S.recovers_to({**HEALTH, "recovers_to": 0.5}) == 0.5
    bare_high, bare_low = {"good": "high"}, {"good": "low"}
    assert S.recovers_to(bare_high) == pytest.approx(0.3) and S.recovers_to(bare_low) == pytest.approx(0.7)
    assert not S.recovered(HEALTH, 0.25) and S.recovered(HEALTH, 0.26) and not S.recovered(RADIATION, 0.7) and S.recovered(RADIATION, 0.69)
    assert not S.recovered(bare_high, 0.19) and S.recovered(bare_high, 0.2) and not S.recovered(bare_low, 0.81) and S.recovered(bare_low, 0.8)


async def test_knocked_out_the_agent_comes_to_at_home_hours_later(tmp_path):
    s, st, gm, agent = world(tmp_path)
    st.update_agent(location="woods", health=0.0005)
    st.start_session(0, 0, 10, time.time() + 600, kind="walk", target="library")
    now = time.time()
    assert await S.step(st, s, now)
    a = st.agent()
    assert (a["location"], a["activity"], a["description"], a["health"]) == (places.HOME, "sleeping", "out cold", pytest.approx(0.35))
    assert st.session() is None and S.out(st, now) and S.out(st, now + 3 * 3600 - 1) and not S.out(st, now + 3 * 3600) and not S.weak(st)
    c = S.condition(st)
    assert c == {"outcome": "knocked_out", "stat": "health", "label": "health", "since": now, "until": now + 3 * 3600}
    assert float(st.meta("sleep_until")) == now + 3 * 3600 and float(st.meta("sleep_started")) == now
    (ev,) = [e for e in st.events(5) if e["kind"] == "stakes"]
    assert ev["data"] == {"outcome": "knocked_out", "stat": "health", "label": "health", "place": "woods", "hours": 3, **({"firsts": ev["data"]["firsts"]} if "firsts" in ev["data"] else {})}
    assert S.moment(ev["data"]) == "Your health ran out and you were knocked out; you came to at home"
    assert agent._moment_text(ev) == S.moment(ev["data"]) and mem.recall_text("stakes", ev["data"]) == S.moment(ev["data"])
    assert mem.event_importance("stakes", ev["data"]) >= 6
    assert not await S.step(st, s, now + 3600)                                       # still out
    assert await S.step(st, s, now + 3 * 3600)
    assert S.condition(st) is None and [e["data"] for e in st.events(5) if e["kind"] == "recovered"] == [
        {"outcome": "knocked_out", "stat": "health", "label": "health"}]


async def test_weak_the_agent_can_only_recover_talk_and_think(tmp_path):
    s, st, gm, agent = world(tmp_path)
    st.start_session(0, 0, 30, time.time() + 1800, kind="module", target="gone", expect="digging")
    st.update_agent(radiation=0.9995)
    assert await S.step(st, s)
    assert S.weak(st) and not S.out(st) and st.session() is None and st.agent()["activity"] == "resting"
    assert st.agent()["radiation"] == pytest.approx(0.9995)                          # weak leaves the stat as it is
    assert S.perception(st) == ["Your radiation ran out: you are too weak to do anything but eat, rest, sleep, talk and think until it recovers."]
    assert S.moment(S.condition(st)) == "Your radiation ran out and you grew too weak to do much"
    assert all(S.allowed(st, t) for t in ("eat", "rest", "sleep", "say", "note_to_self", "recall", "feel"))
    assert not any(S.allowed(st, t) for t in ("go_to", "work_on", "use_item", "draw"))
    names = {t.name for t in agent._specs()}
    assert {"eat", "rest", "note_to_self"} <= names and "use_item" not in names and "set_activity" not in names
    out = await agent._run_tool(ToolCall(id="1", name="use_item", arguments={"item": "x"}), 0)
    assert out["content"] == "you're too weak for that; eat, rest or sleep until you recover" and out["is_error"] and out["followup"]
    assert "Your radiation ran out" in agent._perception("timer", [])
    st.update_agent(radiation=0.75)
    assert not await S.step(st, s) and S.weak(st)                                    # still on its low side
    st.update_agent(radiation=0.6)
    assert await S.step(st, s) and not S.weak(st) and S.allowed(st, "go_to") and S.perception(st) == []


async def test_a_world_with_nothing_that_can_run_out_has_no_stakes(tmp_path):
    s, st, gm, agent = make(tmp_path)
    st.update_agent(energy=0.0, hunger=1.0)
    assert not await S.step(st, s) and S.condition(st) is None and S.allowed(st, "go_to") and S.perception(st) == []
    (tmp_path / "b").mkdir()
    s, st, gm, agent = world(tmp_path / "b")
    st.update_agent(health=0.5, radiation=0.5)
    assert not await S.step(st, s)


async def test_a_stat_the_world_no_longer_has_lets_the_agent_go(tmp_path):
    s, st, gm, agent = world(tmp_path)
    st.set_meta(stakes=json.dumps({"outcome": "weak", "stat": "gone", "label": "gone", "since": 1.0}))
    assert await S.step(st, s) and S.condition(st) is None


async def test_while_out_cold_a_tick_does_nothing_and_a_visitor_waits(tmp_path):
    s, st, gm, agent = world(tmp_path)
    st.update_agent(health=0.0)
    agent.receive("hello?", "Travis")
    await agent._tick("event")
    assert S.out(st) and st.agent()["activity"] == "sleeping" and st.pending_inbox() and agent.backend.calls == []


# --- harm --------------------------------------------------------------------------------------------------------------------------
def harm(st, s, stat="health", tone="bad", severity="medium"):
    return H.decide(st, s, {"category": "raid", "tone": tone, "severity": severity, "effects": [{"kind": "harm", "stat": stat}]},
                    time.time(), random.Random(1))


def test_harm_is_a_hurt_to_a_stat_that_can_run_out_sized_by_the_tone(tmp_path):
    s, st, gm, agent = world(tmp_path)
    for severity, size in (("minor", 0.1), ("medium", 0.25), ("major", 0.5)):
        assert harm(st, s, severity=severity)["effects"] == [{"kind": "stat", "stat": "health", "delta": -size}]
    assert harm(st, s, "radiation")["effects"] == [{"kind": "stat", "stat": "radiation", "delta": 0.25}]
    st.update_agent(health=0.2)                                                         # low: the world spares a low agent its bad turns,
    assert harm(st, s)["effects"][0]["delta"] == -0.25                                  # but harm is the world's stakes
    with pytest.raises(ValueError, match="`stat` is one of the stats that can run out: health, radiation"):
        harm(st, s, "energy")
    with pytest.raises(ValueError, match="a good turn can't bring harm"):
        harm(st, s, tone="good")
    st.set_meta(stakes=json.dumps({"outcome": "weak", "stat": "radiation", "label": "radiation", "since": 1.0}))
    with pytest.raises(ValueError, match="Pip is down already"):
        harm(st, s)
    H.apply_effects(st, [{"kind": "stat", "stat": "health", "delta": -0.5}], time.time())
    assert st.agent()["health"] == pytest.approx(0.0)


def test_without_a_stat_that_can_run_out_there_is_nothing_to_harm(tmp_path):
    s, st, gm, agent = make(tmp_path)
    with pytest.raises(ValueError, match="none in this world"):
        harm(st, s, "energy")
    assert "harm" in H.INTENTS and "harm" in H.LOSSES and "harm" not in H.GAINS


async def test_status_says_when_the_agent_is_out_or_weak(tmp_path):
    from datetime import datetime
    from fastapi.testclient import TestClient
    from app import commands
    s, st, gm, agent = world(tmp_path)
    assert "ran out" not in commands.answer(st, s, "/status")
    st.update_agent(health=0.0)
    await S.step(st, s)
    until = datetime.fromtimestamp(S.condition(st)["until"]).strftime("%-I:%M %p")
    assert f"\nKnocked out (health ran out) until {until}.\n" in commands.answer(st, s, "/status")
    st.set_meta(stakes=json.dumps({"outcome": "weak", "stat": "radiation", "label": "radiation", "since": 1.0}))
    assert "\nToo weak to do much (radiation ran out) until it recovers.\n" in commands.answer(st, s, "/status")
    from app.config import Settings
    from app.llm.fake import FakeBackend
    from app.main import create_app
    s2 = Settings(db_path=str(tmp_path / "t.db"), persona_path="/x", pacing="manual", stats=s.stats)
    with TestClient(create_app(s2, FakeBackend())) as c:
        assert c.get("/state").json()["condition"]["outcome"] == "weak"


async def test_work_cut_short_by_a_knockout_is_heard_by_its_module(tmp_path):
    from tests.test_crafting import events, world as crafting_world
    from tests.test_projects import call, report
    review = {"craft": "kitemaking", "difficulty": 2, "tools": [], "steps": [{"abilities": ["handiness"]}]}
    s, st, gm, agent = crafting_world(tmp_path, [report(**review)], stats={"health": {"good": "high", "at_zero": "knocked_out"}})
    await call(agent, "start_project", name="Kite", steps=[{"name": "cut", "minutes": 30}])
    await call(agent, "work_on", project="Kite", minutes=30)
    st.update_agent(health=0.0)
    now = time.time()
    assert await S.step(st, s, now) and st.session() is None
    assert events(st, "work")[0]["interrupted"] is True                              # the module heard it was cut short
    c = S.condition(st)
    assert (c["label"], c["until"]) == ("health", now + S.OUT_HOURS * 3600)        # no label: its name; no out_hours: four
    assert [e["data"]["hours"] for e in st.events(10) if e["kind"] == "stakes"] == [4]


async def test_weak_says_so_and_still_lets_the_agent_eat(tmp_path):
    s, st, gm, agent = world(tmp_path)
    st.add_item("bread", 1, "food")
    st.update_agent(radiation=1.0)
    await agent.resolve_world()                                                     # the world's turn notices
    assert S.weak(st) and st.agent()["description"] == "too weak to do much"
    (ev,) = [e["data"] for e in st.events(10) if e["kind"] == "stakes"]
    assert {k: v for k, v in ev.items() if k != "firsts"} == {"outcome": "weak", "stat": "radiation", "label": "radiation", "place": "workshop"}
    out = await agent._run_tool(ToolCall(id="1", name="eat", arguments={"food": "bread"}), 0)
    assert not out["is_error"] and "too weak" not in out["content"]


def test_harm_names_what_can_run_out_or_says_there_is_none(tmp_path):
    s, st, gm, agent = make(tmp_path)
    with pytest.raises(ValueError) as e:
        harm(st, s, "energy")
    assert str(e.value) == "`stat` is one of the stats that can run out: none in this world"
    assert mem.event_importance("world_changed", {}) == mem.event_importance("stakes", {}) == 6


def test_the_public_view_shows_the_condition(tmp_path):
    from fastapi.testclient import TestClient
    from app.config import Settings
    from app.llm.fake import FakeBackend
    from app.main import create_app
    s = Settings(db_path=str(tmp_path / "t.db"), persona_path="/x", pacing="manual", public_hosts=["pip.example.org"])
    with TestClient(create_app(s, FakeBackend())) as c:
        c.app.state.agent.state.set_meta(stakes=json.dumps({"outcome": "weak", "stat": "x", "label": "x", "since": 1.0}))
        assert c.get("/state", headers={"Host": "pip.example.org"}).json()["condition"]["outcome"] == "weak"


async def test_the_condition_names_the_stat_by_its_label(tmp_path):
    s, st, gm, agent = world(tmp_path, label="wellbeing")
    st.update_agent(health=0.0)
    await S.step(st, s)
    assert S.condition(st)["label"] == "wellbeing" and S.moment(S.condition(st)).startswith("Your wellbeing ran out")
