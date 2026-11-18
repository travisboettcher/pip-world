"""An agent's temperament (world.json, an agent's `temperament`): where each of its feelings rests (its emotions' baselines), so a
grumpy agent's anger settles higher and its trust lower than another's, in the same world and the same engine."""
import os
import re

import pytest

from app import emotions as emo, loop, world_pack as W
from app.config import Settings
from app.llm.fake import FakeBackend
from tests.test_agents import IVO, WREN
from tests.test_world_pack import pack_dir

GRUMPY = {"baseline": {"anger": 25, "trust": 30, "joy": 30}}


@pytest.fixture
def world(tmp_path):
    d = pack_dir(tmp_path, agents=[WREN, {**IVO, "persona": "", "temperament": GRUMPY}])
    os.makedirs(tmp_path / "data")
    w = loop.build(Settings(world_pack=str(d), db_path=str(tmp_path / "data" / "agent.db"), persona_path="/x", pacing="manual"),
                   FakeBackend())
    yield w
    W.set_active(W.load(Settings()))


def test_a_temperament_is_where_an_agents_feelings_rest(world):
    wren, ivo = world.agents
    assert dict(ivo.identity.temperament) == {"anger": 25, "trust": 30, "joy": 30} and wren.identity.temperament == ()
    with ivo.acting():
        assert emo.baseline() == {**emo.BASELINE, "anger": 25, "trust": 30, "joy": 30}
        assert emo.levels(ivo.state)["anger"] == 25.0
        snap = {e["name"]: e["baseline"] for e in emo.snapshot(ivo.state)["emotions"]}
        assert (snap["anger"], snap["trust"], snap["fear"]) == (25, 30, 10)
        assert emo.readout(ivo.state)[0].startswith("Emotion state: close to your usual self")     # grumpy is his usual
    with wren.acting():
        assert emo.baseline() == emo.BASELINE and emo.levels(wren.state)["anger"] == 8.0


def test_feelings_ease_back_to_the_agents_own_rest(world):
    _, ivo = world.agents
    with ivo.acting():
        emo.nudge(ivo.state, {"anger": 40}, "a quarrel", now=1000.0)
        assert round(emo.levels(ivo.state, now=1000.0 + 365 * 86400)["anger"]) == 25          # decays to his rest, not the engine's
        emo.ease(ivo.state, 1.0, "a night's sleep", now=2000.0)
        assert round(emo.levels(ivo.state, now=2000.0)["anger"]) == 25
        ok, why = emo.settle(ivo.state, ivo.s, "anger", now=3000.0)
        assert not ok and why == "you're already settled: anger is near its usual level"
        emo.nudge(ivo.state, {"anger": 50}, "another quarrel", now=4000.0)
        ok, _ = emo.settle(ivo.state, ivo.s, "anger", now=4000.0)
        assert ok and round(emo.levels(ivo.state, now=4000.0)["anger"]) == 40                  # 75 eased by 35, never below 25
        emo.nudge(ivo.state, {"trust": 20, "joy": 20}, "a kindness", now=5000.0)
        assert emo.blend(emo.levels(ivo.state, now=5000.0)) == "warmth"                      # above his own rest, not the engine's


def test_a_temperament_is_checked(tmp_path):
    why = ("an agent's `temperament` is {\"baseline\": {emotion: 0-100}}, emotions among joy, sadness, anger, fear, trust, disgust, "
           "surprise, anticipation")
    for bad in ({"baseline": {"spite": 50}}, {"baseline": {"anger": 101}}, {"mood": "bad"}, {"baseline": {"anger": True}}, "grumpy"):
        d = pack_dir(tmp_path / str(abs(hash(str(bad)))), agent={**WREN, "temperament": bad})
        with pytest.raises(ValueError, match=f"^world pack [^:]+: {re.escape(why)}$"):
            W.load(Settings(world_pack=str(d)))
    d = pack_dir(tmp_path / "ok", agent={**WREN, "temperament": {"baseline": {"fear": 0, "joy": 100}}})
    assert dict(W.load(Settings(world_pack=str(d))).agent.temperament) == {"fear": 0, "joy": 100}


def test_neighbours_know_each_other_from_the_start(tmp_path):
    """An agent's `knows`: the agents it already knows when the world starts (villagers living side by side), both ways, without a
    first meeting staged; everyone else is met by chance."""
    tobin = {"key": "tobin", "name": "Tobin", "pronoun": "he", "kind": "a water-runner", "knows": ["ivo"]}
    d = pack_dir(tmp_path, agents=[WREN, {**IVO, "persona": ""}, tobin])
    os.makedirs(tmp_path / "data")
    s = Settings(world_pack=str(d), db_path=str(tmp_path / "data" / "agent.db"), persona_path="/x", pacing="manual")
    w = loop.build(s, FakeBackend())
    try:
        wren, ivo, tob = w.agents
        assert tob.identity.knows == ("ivo",)
        assert ivo.state.meta("met:tobin") and tob.state.meta("met:ivo") and wren.state.meta("met:tobin") is None
        assert not [e for a in w.agents for e in a.state.events(20) if e["kind"] == "met"]
        first = ivo.state.meta("met:tobin")
        loop.build(s, FakeBackend())                                                     # a second start changes nothing
        assert ivo.state.meta("met:tobin") == first
        alone = loop.build(Settings(**{**s.__dict__, "agents": ["tobin"]}), FakeBackend())   # one it knows that isn't running: nothing
        assert alone.agents[0].state.meta("met:ivo") == tob.state.meta("met:ivo")
    finally:
        W.set_active(W.load(Settings()))
    for bad in (["nobody"], "ivo", [3], ["tobin"], {"ivo": 1}):
        d2 = pack_dir(tmp_path / f"bad{abs(hash(str(bad)))}", agents=[WREN, {**IVO, "persona": ""}, {**tobin, "knows": bad}])
        with pytest.raises(ValueError, match="^world pack [^:]+: " + re.escape("an agent's `knows` lists other agents of this world by key") + "$"):
            W.load(Settings(world_pack=str(d2)))


def test_knowing_skips_whoever_isnt_running_and_dates_it(tmp_path):
    import time
    tobin = {"key": "tobin", "name": "Tobin", "pronoun": "he", "kind": "a water-runner", "knows": ["wren", "ivo"]}
    d = pack_dir(tmp_path, agents=[WREN, {**IVO, "persona": ""}, tobin])
    os.makedirs(tmp_path / "data")
    s = Settings(world_pack=str(d), db_path=str(tmp_path / "data" / "agent.db"), persona_path="/x", pacing="manual", agents=["ivo", "tobin"])
    try:
        w = loop.build(s, FakeBackend())
        ivo, tob = w.agents
        assert time.time() - 60 < float(tob.state.meta("met:ivo")) <= time.time() and tob.state.meta("met:wren") is None
        from app import others
        others.acquainted(w.agents, now=5.0)                                              # known already: left as it was
        assert float(ivo.state.meta("met:tobin")) > 5.0
    finally:
        W.set_active(W.load(Settings()))


def test_an_agents_role_chooses_its_guide_pages(tmp_path):
    """The owner (2026-11-18): the guide can tell an agent its role (a villager's work is inside the walls), as the persona tells who it
    is. An agent's `role` in world.json; a guide page's `when: role villager|trader`. A page that names no role is everyone's."""
    from app import guide
    tobin = {"key": "tobin", "name": "Tobin", "pronoun": "he", "kind": "a water-runner", "role": "villager"}
    d = pack_dir(tmp_path, agents=[{**WREN, "role": "survivor"}, {**IVO, "persona": "", "role": "trader"}, tobin])
    (d / "guide" / "village.md").write_text("---\norder: 5\nwhen: role villager|trader\n---\nThe village is yours.\n")
    (d / "guide" / "shelter.md").write_text("---\norder: 6\nwhen: role survivor and always\n---\nHome is your shelter.\n")
    s = Settings(world_pack=str(d))
    pack = W.load(s)
    assert [a.role for a in pack.agents] == ["survivor", "trader", "villager"]
    W.set_active(pack)
    try:
        seen = {}
        for a in pack.agents:
            with W.acting(a, None):
                seen[a.key] = guide.render([], s, False)
        assert "The village is yours." in seen["tobin"] and "The village is yours." in seen["ivo"] and "village" not in seen["wren"]
        assert "Home is your shelter." in seen["wren"] and "shelter" not in seen["tobin"]
        assert all("You act on your own." in v for v in seen.values())                              # a page for everyone
    finally:
        W.set_active(W.load(Settings()))
    assert guide._condition("role villager|trader") == ("role", "villager|trader")
    for bad in ("role", "role Villager", "role a b"):
        with pytest.raises(ValueError, match="role a|b"):
            guide._condition(bad)
    for bad in ("Villager", 3, "two words"):
        d2 = pack_dir(tmp_path / f"r{abs(hash(str(bad)))}", agent={**WREN, "role": bad})
        with pytest.raises(ValueError, match=re.escape("an agent's `role` is a word in lower case")):
            W.load(Settings(world_pack=str(d2)))
    assert W.load(Settings(world_pack=str(pack_dir(tmp_path / "none", agent=WREN)))).agent.role == ""
