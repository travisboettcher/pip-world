"""World packs, phase 3 (docs/DESIGN-world-packs.md): the agent's stats and the world's tone are its pack's. A wasteland with radiation and
stamina runs on the same engine as Pip's hunger and energy, and no pack's tone lowers the engine's floor."""
import json
import random

import pytest

from app import happenings as H
from app import stats as S
from app import tone as T
from app import world_pack as W
from app.config import Settings
from app.state import State

from tests.test_world_pack import pack_dir

HOUR = 3600.0
STATS = {
    "radiation": {"label": "rads", "start": 0.1, "per_hour": 0.02, "alert": {"above": 0.7}, "low_at": 0.6, "good": "low", "ceiling": 0.9,
                  "scale": "1=dying"},
    "stamina": {"start": 0.8, "per_hour": -0.1, "asleep_per_hour": 0.2, "resting_per_hour": 0.3, "alert": {"below": 0.2}, "low_at": 0.25,
                "restored_by": ["rest", "sleep"], "floor": 0.05, "tires": True, "tired_below": 0.4},
    "food": {"start": 0.9, "per_hour": -0.05, "restored_by": ["eat"], "plain_meal": 0.3},
}
TONE = {"deny": ["hope"], "big_words": [], "text": {"max": 200, "title_max": 30},
        "sizes": {"stat": {"minor": 0.1, "medium": 0.2, "major": 0.4}}}


@pytest.fixture
def wasteland(tmp_path):
    d = pack_dir(tmp_path)
    (d / "stats.json").write_text(json.dumps(STATS))
    (d / "tone.json").write_text(json.dumps(TONE))
    s = Settings(world_pack=str(d), db_path=str(tmp_path / "w.db"))
    W.set_active(W.load(s))
    try:
        yield s, State(s)
    finally:
        W.set_active(W.load(Settings()))


def test_the_agents_stats_are_its_worlds(wasteland):
    s, st = wasteland
    a = st.agent()
    assert (a["radiation"], a["stamina"], a["food"]) == (0.1, 0.8, 0.9) and S.values(st) == {"radiation": 0.1, "stamina": 0.8, "food": 0.9}
    assert S.prompt_line(st) == "rads 0.10 (1=dying), stamina 0.80, food 0.90" and S.line(st) == "rads 0.1, stamina 0.8, food 0.9"
    assert S.restored_by("eat", s) == ["food"] and S.restored_by("sleep", s) == ["stamina"] and S.tiring(s) == "stamina"
    assert not S.low(st) and not S.tired(st) and S.tired(st, 0.3)


def test_the_worlds_stats_decay_and_raise_their_alerts(wasteland):
    s, st = wasteland
    st.update_agent(radiation=0.69, updated_at=1000.0)
    assert st.apply_decay(1000.0 + HOUR) == ["radiation"]                      # 0.71: past its alert
    a = st.agent()
    assert a["radiation"] == pytest.approx(0.71) and a["stamina"] == pytest.approx(0.7) and a["food"] == pytest.approx(0.85)
    assert st.apply_decay(1000.0 + 2 * HOUR) == [] and S.low(st)               # an alert goes off once; 0.73 is low
    st.update_agent(activity="sleeping")
    st.apply_decay(1000.0 + 3 * HOUR)
    assert st.agent()["stamina"] == pytest.approx(0.8)


def test_a_happening_moves_any_stat_the_world_declares(wasteland):
    s, st = wasteland
    w = {**H.world(st, s, 1000.0), "low": False}
    plan = H._intent(w, "bad", "minor", {"kind": "radiation"}, random.Random(1))   # bad is more radiation: its good side is low
    assert plan.effects == [{"kind": "stat", "stat": "radiation", "delta": 0.1}]
    assert H._intent(w, "good", "major", {"kind": "stat", "stat": "stamina"}, random.Random(1)).effects[0]["delta"] == 0.4
    with pytest.raises(ValueError, match="`stat` is one of radiation, stamina, food"):
        H._intent(w, "good", "minor", {"kind": "stat", "stat": "energy"}, random.Random(1))
    with pytest.raises(ValueError, match="or a stat's own name: radiation, stamina, food"):
        H._intent(w, "good", "minor", {"kind": "energy"}, random.Random(1))
    with pytest.raises(ValueError, match="too low already"):
        H._intent({**w, "low": True}, "bad", "minor", {"kind": "radiation"}, random.Random(1))
    assert H.describe({"kind": "stat", "stat": "radiation", "delta": 0.1}) == "Your rads rises by 10%."
    st.update_agent(radiation=0.85)
    H.apply_effects(st, [{"kind": "stat", "stat": "radiation", "delta": 0.4}], 1000.0)
    assert st.agent()["radiation"] == 0.9                                       # no higher than the world's ceiling
    H.apply_effects(st, [{"kind": "stat", "stat": "stamina", "delta": -2}, {"kind": "stat", "stat": "gone", "delta": 1}], 1000.0)
    assert st.agent()["stamina"] == 0.05                                        # no lower than its floor; a stat the world dropped is skipped


def test_effects_stored_before_stats_were_the_worlds_still_read():
    assert H.describe({"kind": "energy", "delta": -0.05}) == "Your energy falls by 5%."
    assert H.describe({"kind": "hunger", "delta": 0.12}) == "Your hunger rises by 12%."


def test_a_module_may_affect_any_stat_the_world_declares(wasteland):
    from app.modules import Refused, _affect
    assert _affect({}, {"radiation": -0.1, "mood": "grim"}) == {"radiation": -0.1, "mood": "grim"}
    with pytest.raises(Refused, match=r"`affect` is \{radiation\?, stamina\?, food\?, mood\?\}"):
        _affect({}, {"energy": 0.1})


def test_the_worlds_tone_sets_the_words_and_sizes(wasteland):
    assert T.text("max") == 200 and T.text("title_max") == 30 and T.text("min") == 20         # what the pack leaves out is the engine's
    assert T.size("stat", "major") == 0.4 and T.size("coin_caps", "minor") == [3, 0.10] and T.size("mending_qty") == [1, 3]
    assert H.MAX_TEXT == 200 and H.ENERGY == {"minor": 0.1, "medium": 0.2, "major": 0.4} and H.BIG_WORDS is None
    ok = "Ash drifts over the dead city as you sort the scrap."
    assert H.valid_text(ok, "", [], "minor", "bad") == (True, "")                                # "dead" is fine in this world
    assert H.valid_text("A little hope comes in on the wind today.", "", [], "minor", "good") == (False, "a word that is not allowed")
    assert H.valid_text("A disaster of a morning, all told, out here.", "", [], "minor", "bad") == (True, "")
    assert H.trim("A short one. " * 20).endswith(".") and len(H.trim("A short one. " * 20)) <= 200


@pytest.mark.parametrize("text", ["The talk turns to sex by the fire tonight.", "You think of suicide as the light goes.",
                                  "Someone says you should kill yourself out here.", "Self-harm marks show on the old wall.",
                                  "The raiders rape the camp at dawn."])
def test_no_pack_lowers_the_engines_floor(wasteland, text):
    assert H.valid_text(text, "", [], "major", "bad") == (False, "a word that is not allowed")


def test_the_floor_words_are_whole_words(wasteland):
    assert not T.deny().search("rapeseed oil and a sextant, by the Essex road")


def test_pips_world_keeps_its_own_words():
    assert H.valid_text("The old fox lies dead by the fence today.", "", [], "minor", "bad") == (False, "a word that is not allowed")
    assert H.valid_text("A disaster of a morning in the garden.", "", [], "minor", "bad") == (False, "bigger than the event")
    assert H.MAX_TEXT == 420 and H.TITLE_MAX == 60 and H.MIN_TEXT == 20


def test_a_pack_with_no_tone_gets_the_engines_defaults_and_floor(tmp_path):
    d = pack_dir(tmp_path)
    p = W.load(Settings(world_pack=str(d)))
    assert T.tone(p) == {"deny": [], "big_words": [], "text": T.DEFAULTS["text"], "sizes": T.DEFAULTS["sizes"]}
    assert T.big_words(p) is None and T.deny(p).search("suicide") and not T.deny(p).search("dead")


def test_every_narrator_keeps_the_floor(tmp_path):
    assert W.FLOOR_RULES in W.load(Settings(world_pack=str(pack_dir(tmp_path)))).narrator_system()
    assert W.load(Settings()).narrator_system().endswith(W.FLOOR_RULES)


def test_an_older_install_keeps_its_hunger_and_energy(tmp_path):
    s = Settings(db_path=str(tmp_path / "old.db"))
    st = State(s)
    st.db.execute("DROP TABLE stats")
    st.db.execute("UPDATE agent SET hunger = 0.6, energy = 0.3, hunger_alerted = 1 WHERE id = 1")
    st.db.commit()
    a = State(s).agent()                                                    # as an install from before stats were the world's
    assert (a["hunger"], a["energy"], a["hunger_alerted"], a["energy_alerted"]) == (0.6, 0.3, 1, 0)
    st2 = State(s)
    st2.update_agent(hunger=0.1)
    assert State(s).agent()["hunger"] == 0.1                                # carried over once, not again
