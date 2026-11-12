"""stats.py at its edges: each rule at its threshold, and a state's own world even when another world is the active one."""
import json

import pytest

from app import stats as S
from app import world_pack as W
from app.config import Settings
from app.state import State

from tests.test_world_pack import pack_dir

WASTE = {"radiation": {"label": "rads", "start": 0.1, "low_at": 0.6, "good": "low"},
         "stamina": {"start": 0.8, "restored_by": ["rest"], "tires": True, "tired_below": 0.4}}
CALM = {"calm": {"start": 0.5}}


def pack(tmp_path, name, stats):
    d = pack_dir(tmp_path / name)
    (d / "stats.json").write_text(json.dumps(stats))
    return Settings(world_pack=str(d), db_path=str(tmp_path / f"{name}.db"))


@pytest.fixture
def waste(tmp_path):
    """A wasteland state while Pip's world stays the active one: everything must read the state's own world."""
    W.set_active(W.load(Settings()))
    s = pack(tmp_path, "waste", WASTE)
    return s, State(s)


def test_a_settings_world_and_its_overrides(waste, tmp_path):
    s, _ = waste
    assert set(S.declared(s)) == {"radiation", "stamina"} and set(S.declared()) == {"hunger", "energy"}
    over = S.declared(Settings(stats={"hunger": {"per_hour": 0.5}}))
    assert over["hunger"]["per_hour"] == 0.5 and over["hunger"]["start"] == 0.2 and over["energy"]["per_hour"] == -0.05
    assert S.restored_by("rest", s) == ["stamina"] and S.restored_by("rest") == ["energy"]
    assert S.tiring(s) == "stamina" and S.tiring(pack(tmp_path, "calm", CALM)) is None


def test_low_and_alerts_at_their_thresholds():
    high, low = {"low_at": 0.25}, {"low_at": 0.8, "good": "low"}
    assert S.is_low(high, 0.25) and not S.is_low(high, 0.26) and S.is_low(low, 0.8) and not S.is_low(low, 0.79) and not S.is_low({}, 0.0)
    assert S.alerting({"alert": {"above": 0.8}}, 0.8) and not S.alerting({"alert": {"above": 0.8}}, 0.79)
    assert S.alerting({"alert": {"below": 0.2}}, 0.2) and not S.alerting({"alert": {"below": 0.2}}, 0.21) and not S.alerting({}, 0.0)


def test_rates_for_what_the_agent_is_doing():
    assert S.rate({}, "awake", False) == 0.0 and S.rate({}, "awake", True) == 0.0
    d = {"per_hour": 0.08, "asleep_factor": 0.5}
    assert S.rate(d, "sleeping", False) == 0.04 and S.rate({"per_hour": 0.08}, "sleeping", False) == 0.08
    assert S.rate({"per_hour": -0.05, "asleep_per_hour": 0.25}, "sleeping", False) == 0.25
    r = {"per_hour": -0.05, "resting_per_hour": 0.3, "working_per_hour": -0.05}
    assert S.rate(r, "resting", False) == 0.3 and S.rate({"per_hour": -0.05}, "resting", False) == -0.05
    assert S.rate(r, "awake", True) == pytest.approx(-0.1) and S.rate({"per_hour": 0.1}, "awake", True) == 0.1


def test_bounds():
    assert S.bounded({}, 1.5) == 1.0 and S.bounded({}, -1) == 0.0 and S.bounded({"floor": 0.1, "ceiling": 0.9}, 0.95) == 0.9


def test_a_state_reads_its_own_world(waste):
    s, st = waste
    assert S.values(st) == {"radiation": 0.1, "stamina": 0.8} and S.line(st) == "rads 0.1, stamina 0.8"
    assert S.prompt_line(st) == "rads 0.10, stamina 0.80" and not S.low(st)
    st.update_agent(radiation=0.6)
    assert S.low(st) and S.tiredness(st) == 0.8 and not S.tired(st) and S.tired(st, 0.39) and not S.tired(st, 0.4)


def test_tiredness_in_a_world_with_no_tiring_stat_or_threshold(tmp_path):
    W.set_active(W.load(Settings()))
    st = State(pack(tmp_path, "calm", CALM))
    assert S.tiredness(st) == 1.0 and not S.tired(st) and not S.tired(st, 0.0)
    st2 = State(pack(tmp_path, "plain", {"stamina": {"start": 0.5, "tires": True}}))
    assert S.tiredness(st2) == 0.5 and not S.tired(st2, 0.1)


# --- happenings over stats and tone, at their edges ---------------------------------------------------------------------
def test_happening_effects_read_the_states_own_world(waste):
    from app import happenings as H
    s, st = waste
    assert H.world(st, s, 1000.0)["low"] is False
    st.update_agent(radiation=0.6)
    assert H.world(st, s, 1000.0)["low"] is True
    H.apply_effects(st, [{"kind": "stat", "stat": "stamina", "delta": 0.1}], 1000.0)
    assert st.agent()["stamina"] == pytest.approx(0.9)
    assert H.describe({"kind": "stat", "stat": "gone", "delta": -0.1}) == "Your gone falls by 10%."     # a stat this world doesn't have
    assert H.describe({"kind": "stat", "stat": "energy", "delta": 0.05}) == "Your energy rises by 5%."


def test_effects_stored_as_energy_or_hunger_still_apply(tmp_path):
    from app import happenings as H
    W.set_active(W.load(Settings()))
    st = State(Settings(db_path=str(tmp_path / "p.db")))
    st.update_agent(energy=0.5, hunger=0.5)
    H.apply_effects(st, [{"kind": "energy", "delta": 0.1}, {"kind": "hunger", "delta": -0.2}], 1000.0)
    assert (st.agent()["energy"], st.agent()["hunger"]) == (pytest.approx(0.6), pytest.approx(0.3))


def test_a_world_with_no_stats_says_so(tmp_path):
    import random
    from app import happenings as H
    try:
        W.set_active(W.load(Settings(world_pack=str(pack_dir(tmp_path)))))
        with pytest.raises(ValueError, match=r"^`stat` is one of nothing \(this world has no stats\)$"):
            H._intent({"low": False}, "good", "minor", {"kind": "stat", "stat": "x"}, random.Random(1))
        assert H._kinds() == ("an effect's kind is one of coins, item, food_loss, crop, stat, price, stop, news, memory "
                              "(or a stat's own name: this world has none)")
    finally:
        W.set_active(W.load(Settings()))


def test_tone_checks_at_their_edges():
    from app import happenings as H
    assert H.valid_text("x" * 20, "", [], "minor", "good") == (True, "") and H.valid_text("x" * 19, "", [], "minor", "good")[1] == "length"
    assert H.valid_text("x" * 420, "", [], "minor", "good") == (True, "") and H.valid_text("x" * 421, "", [], "minor", "good")[1] == "length"
    big = "A disaster of a morning in the garden."
    assert H.valid_text(big, "", [], "major", "neutral") == (False, "bigger than the event") and H.valid_text(big, "", [], "major", "bad") == (True, "")
    assert H.DENY.search("the corpse") and H.BIG_WORDS.search("a disaster")
    with pytest.raises(AttributeError, match="NOPE"):
        H.NOPE


def test_a_happening_may_name_its_worlds_agent(waste):
    from app import happenings as H
    try:
        W.set_active(W.load(waste[0]))
        assert H.valid_text("The gate stands open for Wren this morning.", "", [], "minor", "good") == (True, "")
        assert H.valid_text("The gate stands open for Pip this morning.", "", [], "minor", "good") == (False, "a name that was not offered: Pip")
    finally:
        W.set_active(W.load(Settings()))
    assert H.valid_text("The gate stands open for Pip this morning.", "", [], "minor", "good") == (True, "")
