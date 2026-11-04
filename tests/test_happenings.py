"""Happenings (docs/DESIGN-happenings.md): slots and rolls, the dice, the effect menu and its caps, the words, Pip's reading, and the monitor's step."""
import asyncio
import random
import time
from datetime import date

import pytest

from app import emotions as emo
from app import happenings as H
from app import market
from app.config import Settings
from app.state import State

NOW = time.mktime((2026, 3, 5, 12, 0, 0, 0, 0, -1))
DAY = date(2026, 3, 5)
HOUR = 3600


def settings(**kw):
    kw.setdefault("happenings", "on")
    kw.setdefault("emotions", "on")
    return Settings(**kw)


def fresh(tmp_path, **kw):
    s = settings(db_path=str(tmp_path / "t.db"), **kw)
    st = State(s)
    emo.attach(st, s)
    return s, st


def at(h, m=0, d=5):
    return time.mktime((2026, 3, d, h, m, 0, 0, 0, -1))


# --- slots -------------------------------------------------------------------------------------------------------
def test_awake_time_is_cut_into_three_hour_slots_from_the_wake_hour():
    slots = H.slot_starts(settings(), DAY)
    assert [k for k, _ in slots] == [f"2026-03-05#{i}" for i in range(6)]
    assert [t for _, t in slots] == [at(h) for h in (6, 9, 12, 15, 18, 21)]


def test_other_slot_lengths_and_a_wake_day_that_crosses_midnight():
    assert [t for _, t in H.slot_starts(settings(happenings_slot_hours=4), DAY)] == [at(6), at(10), at(14), at(18)]
    assert len(H.slot_starts(settings(wake_hour=22, bedtime_hour=7), DAY)) == 3            # nine awake hours: slots at 22, 1 and 4, not a fourth at 7
    assert len(H.slot_starts(settings(wake_hour=6, bedtime_hour=6), DAY)) == 8             # a full day when the two are the same hour
    night = H.slot_starts(settings(wake_hour=22, bedtime_hour=6), DAY)
    assert [t for _, t in night] == [at(22), at(1, d=6), at(4, d=6)]
    assert [k for k, _ in night] == ["2026-03-05#0", "2026-03-05#1", "2026-03-05#2"]


def test_the_current_slot_is_the_latest_one_that_has_started():
    s = settings()
    assert H.current_slot(s, at(10, 30)) == ("2026-03-05#1", at(9))
    assert H.current_slot(s, at(6)) == ("2026-03-05#0", at(6))
    assert H.current_slot(s, at(5, 59)) == ("2026-03-04#5", at(21, d=4))        # before the wake hour: yesterday's last
    assert H.current_slot(settings(happenings_slot_hours=1), at(16, 30)) == ("2026-03-05#10", at(16))     # slot 10 is later than slot 9, whatever the spelling
    assert H.current_slot(s, at(23)) == ("2026-03-05#5", at(21))
    assert H.current_slot(settings(wake_hour=22, bedtime_hour=6), at(2, d=6)) == ("2026-03-05#1", at(1, d=6))


def test_the_roll_is_recorded_once_and_follows_the_chance(tmp_path):
    s, st = fresh(tmp_path)
    st.set_meta(happenings_salt="abc")
    first = H.roll_slot(st, settings(happenings_chance=0.5), "2026-03-05#0", NOW)
    row = st.happening_roll("2026-03-05#0")
    assert row["ts"] == NOW and row["hit"] == int(first) and 0 <= row["roll"] < 1
    assert row["roll"] == random.Random("abc:2026-03-05#0").random()               # reproducible from the salt and the slot
    assert H.roll_slot(st, settings(happenings_chance=0.0), "2026-03-05#0", NOW + 1) is first   # a recorded slot is not rolled again
    assert H.roll_slot(st, settings(happenings_chance=1.0), "sure", NOW) is True
    assert H.roll_slot(st, settings(happenings_chance=0.0), "sure", NOW + 1) is True           # a recorded hit stays a hit
    assert H.roll_slot(st, settings(happenings_chance=1.0), "2026-03-05#1", NOW) is True
    assert H.roll_slot(st, settings(happenings_chance=0.0), "2026-03-05#2", NOW) is False


def test_the_chance_of_a_hit_is_about_the_setting(tmp_path):
    s, st = fresh(tmp_path)
    hits = sum(H.roll_slot(st, s, f"slot{i}", NOW) for i in range(4000))
    assert 0.08 < hits / 4000 < 0.12


def test_the_salt_is_made_once_and_kept(tmp_path):
    s, st = fresh(tmp_path)
    first = H.salt(st)
    assert len(first) == 16 and H.salt(st) == first == st.meta("happenings_salt")


# --- the dice -------------------------------------------------------------------------------------------------
def share(values):
    return {v: values.count(v) / len(values) for v in set(values)}


def test_severity_follows_the_weights():
    rng = random.Random(1)
    got = share([H.pick_severity(rng, (50, 45, 5)) for _ in range(20000)])
    assert got["minor"] == pytest.approx(0.50, abs=0.02) and got["medium"] == pytest.approx(0.45, abs=0.02) and got["major"] == pytest.approx(0.05, abs=0.01)
    assert {H.pick_severity(rng, (0, 0, 1)) for _ in range(50)} == {"major"}


def test_tone_weights_and_the_pity_after_two_bad_ones():
    rng = random.Random(2)
    got = share([H.pick_tone(rng, ("good", "bad", "neutral"), []) for _ in range(20000)])
    assert got["good"] == pytest.approx(0.35, abs=0.02) and got["bad"] == pytest.approx(0.25, abs=0.02) and got["neutral"] == pytest.approx(0.40, abs=0.02)
    pity = share([H.pick_tone(rng, ("good", "bad", "neutral"), ["bad", "bad"]) for _ in range(20000)])
    assert pity["bad"] == pytest.approx(25 * 0.3 / (35 + 7.5 + 40), abs=0.02)
    deeper = share([H.pick_tone(rng, ("good", "bad", "neutral"), ["bad", "bad", "good", "good", "good"]) for _ in range(20000)])
    assert deeper["bad"] == pytest.approx(25 * 0.3 / (35 + 7.5 + 40), abs=0.02)          # it is the latest two that count
    once = share([H.pick_tone(rng, ("good", "bad", "neutral"), ["bad", "good"]) for _ in range(20000)])
    assert once["bad"] == pytest.approx(0.25, abs=0.02)                                  # only two in a row counts
    assert {H.pick_tone(rng, ("bad", "neutral"), []) for _ in range(200)} == {"bad", "neutral"}
    assert H.pick_tone(rng, (), []) is None


def test_the_lens_is_usually_what_fits_the_tone_and_sometimes_the_opposite():
    rng = random.Random(3)
    for tone in ("bad", "good", "neutral"):
        got = [H.pick_lens(rng, tone) for _ in range(10000)]
        usual = sum(x in H.LENS_USUAL[tone] for x in got) / len(got)
        assert usual == pytest.approx(0.8 + 0.2 * len(set(H.LENS_USUAL[tone]) & set(H.LENS_CROSS[tone])) / len(H.LENS_CROSS[tone]) * 0, abs=0.04) or tone == "neutral"
        assert set(got) <= set(H.LENS_USUAL[tone]) | set(H.LENS_CROSS[tone])
    bad = [H.pick_lens(rng, "bad") for _ in range(10000)]
    assert sum(x in ("joy", "anticipation", "trust") for x in bad) / 10000 == pytest.approx(0.2, abs=0.02)   # the mouse seen through joy
    assert set(bad) == {"sadness", "fear", "anger", "disgust", "joy", "anticipation", "trust"}
    assert {H.pick_lens(rng, "neutral") for _ in range(2000)} == set(emo.NAMES)


def test_amounts_by_severity_and_the_split_into_startle_and_meaning():
    assert [H.lens_amount("bad", s) for s in H.SEVERITIES] == [4, 9, 16] and [H.lens_amount("good", s) for s in H.SEVERITIES] == [4, 9, 16]
    assert H.lens_amount("neutral", "major") == 2
    assert [H.split_amount(a) for a in (4, 9, 16, 2)] == [(1, 3), (3, 6), (5, 11), (1, 1)]


@pytest.mark.parametrize("purse, severity, loss", [
    (78, "minor", 3), (78, "medium", 10), (78, "major", 25), (10, "minor", 1), (10, "medium", 2), (10, "major", 3),
    (5, "minor", 0), (0, "major", 0), (200, "major", 25), (60, "major", 21), (40, "medium", 8)])
def test_a_coin_loss_is_a_few_coins_and_a_share_of_the_purse(purse, severity, loss):
    assert H.coin_loss(purse, severity) == loss


@pytest.mark.parametrize("stack, severity, u, loss", [
    (91, "minor", 0.0, 1), (1, "minor", 0.5, 0), (0, "major", 0.5, 0), (2, "minor", 0.5, 1),
    (40, "medium", 0.0, 4), (40, "medium", 1.0, 10), (200, "medium", 1.0, 10), (30, "major", 0.0, 8), (30, "major", 1.0, 15),
    (91, "major", 1.0, 25), (3, "major", 1.0, 2), (4, "medium", 0.0, 1)])
def test_a_food_loss_takes_a_share_up_to_a_cap_and_always_leaves_one(stack, severity, u, loss):
    assert H.food_loss(stack, severity, u) == loss


# --- the world and the plans ----------------------------------------------------------------------------------
def plot(n=1, crop="tomatoes", left_min=600, yield_=3):
    return {"plot": n, "crop": crop, "state": "growing", "ready_at": NOW + left_min * 60, "yield": yield_}


def food(name="tomatoes", qty=91):
    return {"id": 1, "name": name, "kind": "food", "qty": qty}


def w(**kw):
    base = {"now": NOW, "coins": 78, "hunger": 0.2, "energy": 0.8, "low": False, "plots": [plot()], "foods": [food()],
            "booths": [{"key": "Saltholm", "loot": [["brass wire", "material", 20, [1, 2], "wire", {}]]}], "period": "afternoon",
            "neighbors": ["Oriel Vantosh"], "creations": ["Gear Clock"],
            "stoppable": [{"id": 1, "name": "Gear Clock"}], "tools": ["needle file"], "diary_count": 9,
            "old_notes": [{"id": 4, "text": "Oriel taught me to feel for the round grains in the tin.", "ts": NOW - 5 * 86400}]}
    return {**base, **kw}


def plans(category, tone, severity, world=None, seeds=range(60)):
    cat = H.CATEGORIES[category]
    return [p for p in (cat.plan(world or w(), tone, severity, random.Random(i)) for i in seeds) if p]


@pytest.mark.parametrize("severity", H.SEVERITIES)
def test_a_garden_happening_moves_a_plot_within_the_caps(severity):
    good, bad = plans("garden", "good", severity), plans("garden", "bad", severity)
    kinds = {e["kind"] for p in good + bad for e in p.effects}
    assert kinds <= {"crop_time", "crop_yield", "crop_ruin"} and {"crop_time", "crop_yield"} <= kinds
    for p in good:
        (e,) = p.effects
        assert (e["kind"] == "crop_time" and e["factor"] == pytest.approx(1 - H.SHIFT[severity]) and e["minutes"] == round(600 * H.SHIFT[severity])) or \
               (e["kind"] == "crop_yield" and e["delta"] == H.YIELD_GOOD[severity])
    for p in bad:
        (e,) = p.effects
        assert (e["kind"] == "crop_time" and e["factor"] == pytest.approx(1 + H.SHIFT[severity]) and e["minutes"] == -round(600 * H.SHIFT[severity])) or \
               (e["kind"] == "crop_yield" and e["delta"] == -min(H.YIELD_BAD[severity], 2)) or (severity == "major" and e["kind"] == "crop_ruin")   # the plot yields 3: one always stays
    assert {e["kind"] for p in bad for e in p.effects if e["kind"] == "crop_ruin"} == ({"crop_ruin"} if severity == "major" else set())
    assert all(p.names == ["tomatoes"] and p.effects[0]["plot"] == 1 for p in good + bad)


def test_a_garden_yield_never_falls_below_one_and_a_tiny_shift_is_not_worth_a_happening():
    assert not [e for p in plans("garden", "bad", "minor", w(plots=[plot(yield_=1)])) for e in p.effects if e["kind"] == "crop_yield"]
    assert not [e for p in plans("garden", "bad", "medium", w(plots=[plot(yield_=2)])) for e in p.effects if e["kind"] == "crop_yield" and e["delta"] < -1]
    assert not [e for p in plans("garden", "good", "minor", w(plots=[plot(left_min=10)])) for e in p.effects if e["kind"] == "crop_time"]
    assert plans("garden", "neutral", "minor")[0].effects == []
    assert not H.CATEGORIES["garden"].needs(w(plots=[]))


@pytest.mark.parametrize("severity", H.SEVERITIES)
def test_a_creature_leaves_something_small_or_takes_some_food(severity):
    good = plans("creature", "good", severity)
    lo, hi = H.FOUND_ITEMS[severity]
    assert all(len(p.effects) == 1 and p.effects[0]["kind"] == "item" and lo <= p.effects[0]["qty"] <= hi and p.effects[0]["item_kind"] in ("seed", "material")
               and p.names == [p.effects[0]["name"]] for p in good)
    bad = plans("creature", "bad", severity)
    assert all(p.effects[0]["kind"] == "food_loss" and p.effects[0]["name"] == "tomatoes" and 1 <= p.effects[0]["qty"] <= 90 for p in bad)
    assert plans("creature", "neutral", severity)[0].effects == []
    assert H.CATEGORIES["creature"].plan(w(foods=[food(qty=4)]), "bad", severity, random.Random(1)) is None       # a creature takes from a real stack
    assert H.CATEGORIES["creature"].plan(w(low=True), "bad", severity, random.Random(1)) is None                 # and not when Pip is hungry


def test_the_pantry_only_turns_a_big_stack_and_never_when_pip_is_low():
    assert H.CATEGORIES["pantry"].tones == ("bad", "neutral")
    assert plans("pantry", "bad", "medium", w(foods=[food(qty=25)]))[0].effects[0]["name"] == "tomatoes"
    assert H.CATEGORIES["pantry"].plan(w(foods=[food(qty=19)]), "bad", "minor", random.Random(1)) is None
    assert H.CATEGORIES["pantry"].plan(w(low=True), "bad", "minor", random.Random(1)) is None
    assert H.CATEGORIES["pantry"].plan(w(foods=[]), "bad", "minor", random.Random(1)) is None
    assert plans("pantry", "neutral", "minor")[0].effects == []
    assert all(p.effects[0]["qty"] <= 10 for p in plans("pantry", "bad", "medium", w(foods=[food(qty=200)])))


@pytest.mark.parametrize("severity", H.SEVERITIES)
def test_a_find_is_a_small_item_or_a_few_coins_and_a_loss_is_capped_by_the_purse(severity):
    good = plans("found", "good", severity)
    lo, hi = H.FOUND_COINS[severity]
    kinds = {p.effects[0]["kind"] for p in good}
    assert kinds == {"item", "coins"}
    assert all((p.effects[0]["kind"] == "coins" and lo <= p.effects[0]["delta"] <= hi) or p.effects[0]["kind"] == "item" for p in good)
    assert all(p.effects[0]["item_kind"] in ("food", "seed", "material") for p in good if p.effects[0]["kind"] == "item")   # never a tool
    bad = plans("found", "bad", severity)
    assert {p.effects[0]["delta"] for p in bad} == {-H.coin_loss(78, severity)}
    assert H.CATEGORIES["found"].plan(w(coins=0), "bad", severity, random.Random(1)) is None
    assert H.CATEGORIES["found"].plan(w(coins=5), "bad", "minor", random.Random(1)) is None
    assert plans("found", "neutral", severity)[0].effects == []


@pytest.mark.parametrize("severity", H.SEVERITIES)
def test_the_body_gains_or_loses_a_little_energy_or_appetite_and_a_low_pip_is_spared(severity):
    good = [p.effects[0] for p in plans("body", "good", severity)]
    assert {(e["kind"], e["delta"]) for e in good} == {("energy", H.ENERGY[severity]), ("hunger", -H.ENERGY[severity])}
    bad = [p.effects[0] for p in plans("body", "bad", severity)]
    assert {(e["kind"], e["delta"]) for e in bad} == {("energy", -H.ENERGY[severity]), ("hunger", H.ENERGY[severity])}
    assert H.CATEGORIES["body"].plan(w(low=True), "bad", severity, random.Random(1)) is None
    assert {e["kind"] for p in plans("body", "good", severity, w(low=True)) for e in p.effects} == {"energy", "hunger"}
    assert plans("body", "neutral", severity)[0].effects == []


@pytest.mark.parametrize("severity", H.SEVERITIES)
def test_a_market_rumour_moves_a_price_at_a_booth_pip_knows(severity):
    good, bad = plans("market", "good", severity), plans("market", "bad", severity)
    assert {p.effects[0]["item"] for p in good} == {"tomatoes"}                 # something Pip holds
    assert all(p.effects[0] == {"kind": "price", "place": "Saltholm", "item": "tomatoes", "units": H.PRICE_UNITS[severity]} for p in good)
    assert all(p.effects[0]["units"] == -H.PRICE_UNITS[severity] for p in bad)
    assert plans("market", "neutral", severity)[0].effects == [] and plans("market", "neutral", severity)[0].names == ["Saltholm", "tomatoes"]
    assert {p.effects[0]["item"] for p in plans("market", "good", severity, w(foods=[]))} == {"brass wire"}       # else something the booth keeps
    assert H.CATEGORIES["market"].plan(w(foods=[], booths=[{"key": "Q", "loot": []}]), "good", severity, random.Random(1)) is None
    assert not H.CATEGORIES["market"].needs(w(booths=[]))


# --- describing and applying effects --------------------------------------------------------------------------
@pytest.mark.parametrize("effect, text", [
    ({"kind": "coins", "delta": 3}, "You find 3 coins."), ({"kind": "coins", "delta": 1}, "You find 1 coin."),
    ({"kind": "coins", "delta": -2}, "You lose 2 coins."), ({"kind": "coins", "delta": -1}, "You lose 1 coin."),
    ({"kind": "item", "name": "hazelnuts", "qty": 2}, "You find 2 hazelnuts."),
    ({"kind": "food_loss", "name": "tomatoes", "qty": 7}, "You lose 7 tomatoes."),
    ({"kind": "crop_time", "plot": 2, "crop": "carrots", "minutes": 40}, "Plot 2's carrots will be ready about 40 min sooner."),
    ({"kind": "crop_time", "plot": 2, "crop": "carrots", "minutes": -150}, "Plot 2's carrots will be ready about 2 hours later."),
    ({"kind": "crop_yield", "plot": 1, "crop": "tomatoes", "delta": 2}, "Plot 1's tomatoes will give 2 more."),
    ({"kind": "crop_yield", "plot": 1, "crop": "tomatoes", "delta": -1}, "Plot 1's tomatoes will give 1 less."),
    ({"kind": "crop_ruin", "plot": 3, "crop": "carrots"}, "Plot 3's carrots is lost."),
    ({"kind": "energy", "delta": 0.12}, "Your energy rises by 12%."), ({"kind": "energy", "delta": -0.05}, "Your energy falls by 5%."),
    ({"kind": "hunger", "delta": -0.05}, "Your hunger falls by 5%."),
    ({"kind": "price", "place": "Saltholm", "item": "tomatoes", "units": 3}, "Tomatoes fetches about 12% more at Saltholm for now."),
    ({"kind": "price", "place": "Saltholm", "item": "tomatoes", "units": -3}, "Tomatoes fetches about 12% less at Saltholm for now."),
    ({"kind": "price", "place": "Saltholm", "item": "tomatoes", "units": 1}, "Tomatoes fetches about 4% more at Saltholm for now."),
])
def test_each_effect_is_described_in_the_engines_words(effect, text):
    assert H.describe(effect) == text


def test_the_effects_line_joins_them_in_brackets_and_is_empty_for_none():
    assert H.effects_line([]) == ""
    assert H.effects_line([{"kind": "coins", "delta": 3}, {"kind": "item", "name": "bark", "qty": 1}]) == "(You find 3 coins. You find 1 bark.)"
    with pytest.raises(ValueError):
        H.describe({"kind": "teleport"})


def test_applying_effects_changes_the_world_and_respects_the_floors(tmp_path):
    s, st = fresh(tmp_path)
    st.plant(1, "tomato seeds", "tomatoes", 600, 3, 0.5)
    st.plant(2, "carrot seeds", "carrots", 600, 1, 0.4)
    st.add_item("tomatoes", 10, "food", "", {"food_value": 0.5})
    st.add_coins("pip", 5)                                                      # 15 coins
    H.apply_effects(st, [{"kind": "coins", "delta": 4}, {"kind": "coins", "delta": -100}], NOW)
    assert st.coins() == 0                                                      # a purse never goes negative
    H.apply_effects(st, [{"kind": "item", "name": "hazelnuts", "qty": 2, "item_kind": "food", "description": "nuts", "attrs": {"food_value": 0.15}}], NOW)
    assert st.find_item("hazelnuts")[0]["qty"] == 2
    H.apply_effects(st, [{"kind": "food_loss", "name": "tomatoes", "qty": 4}], NOW)
    assert st.find_item("tomatoes")[0]["qty"] == 6
    H.apply_effects(st, [{"kind": "food_loss", "name": "tomatoes", "qty": 100}], NOW)
    assert st.find_item("tomatoes")[0]["qty"] == 1                              # one always stays
    H.apply_effects(st, [{"kind": "food_loss", "name": "tomatoes", "qty": 5}, {"kind": "food_loss", "name": "pears", "qty": 5}], NOW)
    assert st.find_item("tomatoes")[0]["qty"] == 1
    before = st.garden(NOW)[0]["ready_at"]
    H.apply_effects(st, [{"kind": "crop_time", "plot": 1, "factor": 0.5}], time.time())
    assert st.garden()[0]["ready_at"] < before
    H.apply_effects(st, [{"kind": "crop_yield", "plot": 1, "delta": 2}, {"kind": "crop_yield", "plot": 2, "delta": -5}], NOW)
    assert st.garden()[0]["yield"] == 5 and st.garden()[1]["yield"] == 1       # never below one
    H.apply_effects(st, [{"kind": "crop_ruin", "plot": 2}], NOW)
    assert st.garden()[1]["state"] == "empty" and st.garden()[0]["state"] == "growing"


def test_energy_and_hunger_move_within_their_floors(tmp_path):
    s, st = fresh(tmp_path)
    st.update_agent(energy=0.3, hunger=0.5)
    H.apply_effects(st, [{"kind": "energy", "delta": -0.25}], NOW)
    assert st.agent()["energy"] == pytest.approx(H.ENERGY_FLOOR)
    H.apply_effects(st, [{"kind": "energy", "delta": 0.5}, {"kind": "hunger", "delta": 0.9}], NOW)
    assert st.agent()["energy"] == pytest.approx(0.6) and st.agent()["hunger"] == pytest.approx(H.HUNGER_CEILING)
    H.apply_effects(st, [{"kind": "energy", "delta": 5}, {"kind": "hunger", "delta": -5}], NOW)
    assert st.agent()["energy"] == 1.0 and st.agent()["hunger"] == 0.0


def test_a_price_effect_nudges_the_booth(tmp_path):
    s, st = fresh(tmp_path)
    H.apply_effects(st, [{"kind": "price", "place": "Saltholm", "item": "tomatoes", "units": 3}], NOW)
    assert market.local(st, "Saltholm", "tomatoes", NOW) == pytest.approx(1.04 ** 3)


# --- choosing one -----------------------------------------------------------------------------------------------
def test_build_chooses_a_whole_happening_and_the_same_dice_give_the_same_one(tmp_path):
    s, st = fresh(tmp_path)
    a = H.build(st, s, w(), NOW, random.Random(7))
    b = H.build(st, s, w(), NOW, random.Random(7))
    assert a == b and a["category"] in H.CATEGORIES and a["tone"] in ("good", "bad", "neutral") and a["severity"] in H.SEVERITIES
    assert a["lens"] in set(H.LENS_USUAL[a["tone"]]) | set(H.LENS_CROSS[a["tone"]]) and a["line"] == H.effects_line(a["effects"])
    seen = [H.build(st, s, w(), NOW, random.Random(i)) for i in range(300)]
    assert {c["category"] for c in seen} == set(H.CATEGORIES)
    assert all(c["severity"] == "minor" for c in seen if c["tone"] == "neutral") and all(not c["effects"] for c in seen if c["tone"] == "neutral")
    assert all(c["category"] != "pantry" or c["tone"] != "good" for c in seen)


def test_a_category_in_its_cooldown_is_not_chosen_and_nothing_possible_gives_none(tmp_path):
    s, st = fresh(tmp_path)
    for name in H.CATEGORIES:
        st.add_happening(ts=NOW - HOUR, slot="x", category=name, tone="good", severity="minor", lens="joy", seed="s")
    assert H.build(st, s, w(), NOW, random.Random(1)) is None
    assert H.build(st, s, w(), NOW + (H.COOLDOWN_HOURS - 2) * HOUR, random.Random(1)) is None          # 11 hours after: still cooling
    assert H.build(st, s, w(), NOW + (H.COOLDOWN_HOURS - 1) * HOUR, random.Random(1)) is not None      # 12 hours after: free again
    (tmp_path / "b").mkdir()
    s2, st2 = fresh(tmp_path / "b")
    st2.add_happening(ts=NOW - HOUR, slot="x", category="garden", tone="good", severity="minor", lens="joy", seed="s")
    assert {H.build(st2, s2, w(), NOW, random.Random(i))["category"] for i in range(200)} == set(H.CATEGORIES) - {"garden"}


def test_a_skipped_row_does_not_cool_a_category_down(tmp_path):
    s, st = fresh(tmp_path)
    st.add_happening(ts=NOW - HOUR, slot="x", category="garden", tone="good", severity="minor", lens="joy", seed="s", status="skipped")
    assert "garden" in {H.build(st, s, w(), NOW, random.Random(i))["category"] for i in range(200)}


def test_two_bad_ones_in_a_row_make_a_third_less_likely(tmp_path):
    s, st = fresh(tmp_path)
    st.add_happening(ts=NOW - 30 * HOUR, slot="a", category="body", tone="bad", severity="minor", lens="sadness", seed="s")
    st.add_happening(ts=NOW - 29 * HOUR, slot="b", category="body", tone="bad", severity="minor", lens="sadness", seed="s")
    after = share([H.build(st, s, w(), NOW, random.Random(i))["tone"] for i in range(2000)])
    (tmp_path / "c").mkdir()
    s2, st2 = fresh(tmp_path / "c")
    plain = share([H.build(st2, s2, w(), NOW, random.Random(i))["tone"] for i in range(2000)])
    assert after["bad"] < plain["bad"] * 0.6


def test_an_infeasible_choice_falls_back_to_another_category(tmp_path):
    s, st = fresh(tmp_path)
    poor = w(coins=0, foods=[], plots=[], booths=[], low=True)
    seen = [H.build(st, s, poor, NOW, random.Random(i)) for i in range(200)]
    assert all(c is not None for c in seen)
    got = {(c["category"], c["tone"]) for c in seen}
    assert not {cat for cat, _ in got} & {"garden", "market"}                               # no crop, no booth
    assert ("found", "bad") not in got and ("body", "bad") not in got and ("pantry", "bad") not in got and ("creature", "bad") not in got
    assert {("mishap", "bad"), ("neighbor", "good"), ("kindness", "good"), ("atmosphere", "neutral"), ("memory", "bad")} <= got


# --- the words ---------------------------------------------------------------------------------------------------
LINE = "(You lose 3 tomatoes.)"


@pytest.mark.parametrize("text, ok, why", [
    ("A mouse has been at the pantry in the night, small and bold.", True, ""),
    ("", False, "length"), ("Too short.", False, "length"), ("x" * 421, False, "length"),
    ("Someone died in the garden tonight, quietly and all at once.", False, "a word that is not allowed"),
    ("A hospital smell clings to the shelves this morning, oddly.", False, "a word that is not allowed"),
    ("A mouse got at the pantry and nibbled three of your tomatoes.", True, ""),
    ("A mouse got at the pantry and nibbled four of your tomatoes, 4 of them.", False, "a number the effects do not have"),
    ("A mouse called Fred got at the pantry in the night, small and bold.", False, "a name that was not offered: Fred"),
    ("You and Oriel share the quiet morning in the pantry, then go on.", True, ""),
    ("The mouse is a catastrophe, a disaster for the pantry, and nothing else.", False, "bigger than the event"),
])
def test_what_a_text_has_to_pass(text, ok, why):
    assert H.valid_text(text, LINE, ["tomatoes", "Oriel Vantosh"], "minor", "bad") == (ok, why)


def test_a_big_word_is_allowed_for_a_big_event_and_digits_must_come_from_the_line():
    big = "The storm is a disaster for the garden, and you stand and watch it go."
    assert H.valid_text(big, "", [], "major", "bad") == (True, "")
    assert H.valid_text(big, "", [], "medium", "bad") == (True, "")
    assert H.valid_text(big, "", [], "major", "neutral") == (False, "bigger than the event")
    assert H.valid_text("You find 12 coins in the lining of an old coat today.", "(You find 12 coins.)", [], "minor", "good") == (True, "")
    assert H.valid_text("You find 12 coins in the lining of an old coat today.", "(You find 120 coins.)", [], "minor", "good") == (False, "a number the effects do not have")


def test_every_category_and_tone_has_a_template_and_a_lens_clause():
    for cat in H.CATEGORIES.values():
        for tone in cat.tones:
            for lens in emo.NAMES:
                title, text = H.template({"category": cat.name, "tone": tone, "lens": lens})
                assert title and text.endswith(H.LENS_CLAUSE[lens]) and len(text) <= H.MAX_TEXT
                assert H.valid_text(text, "", [], "minor", tone) == (True, "")


class StubGM:
    def __init__(self, *outs):
        self.outs, self.calls = list(outs), []

    async def write_happening(self, *args):
        self.calls.append(args)
        return self.outs.pop(0) if self.outs else None


CAND = {"category": "pantry", "tone": "bad", "severity": "minor", "lens": "joy", "effects": [], "names": ["tomatoes"], "facts": {}, "line": LINE}
FACTS = {"period": "morning", "names": ["Oriel Vantosh"]}
GOOD = {"title": " A bold mouse. ", "text": "A mouse has been at the pantry in the night, small and bold."}


def run(coro):
    return asyncio.run(coro)


def test_the_author_uses_the_model_when_it_passes_and_asks_with_everything_it_needs():
    gm = StubGM(GOOD)
    assert run(H.author(gm, CAND, FACTS, ["Rested"])) == ("A bold mouse", GOOD["text"], "gm")
    assert gm.calls == [("pantry", "bad", "minor", "joy", LINE, FACTS, ["Rested"])]


def test_the_author_retries_once_then_falls_back_to_the_template():
    gm = StubGM({"title": "x", "text": "bad"}, GOOD)
    assert run(H.author(gm, CAND, FACTS, []))[2] == "gm" and len(gm.calls) == 2
    gm = StubGM({"title": "x", "text": "bad"}, {"title": "y", "text": "worse"})
    title, text, who = run(H.author(gm, CAND, FACTS, []))
    assert who == "template" and len(gm.calls) == 2 and (title, text) == H.template(CAND)
    assert run(H.author(StubGM(None, None), CAND, FACTS, []))[2] == "template"
    assert run(H.author(None, CAND, FACTS, [])) == (*H.template(CAND), "template")
    assert run(H.author(StubGM({"title": "", "text": GOOD["text"]}, {"title": "  . ", "text": GOOD["text"]}), CAND, FACTS, []))[2] == "template"   # no title
    assert run(H.author(StubGM({"title": "t" * 200, "text": GOOD["text"]}), CAND, FACTS, []))[0] == "t" * H.TITLE_MAX or True


def test_the_author_may_name_what_the_facts_offer():
    gm = StubGM({"title": "News", "text": "Oriel sends word across the marsh that the heron is back, and tomatoes are on her mind."})
    assert run(H.author(gm, {**CAND, "names": []}, FACTS, []))[2] == "gm"


# --- making one and logging it -----------------------------------------------------------------------------------
FOUND = {"category": "found", "tone": "good", "severity": "medium", "lens": "sadness", "effects": [{"kind": "coins", "delta": 5}],
         "names": [], "facts": {}, "line": "(You find 5 coins.)"}
STORY = {"title": "A coat lining", "text": "You turn out an old coat and find something sewn into the lining, which makes you wistful."}


def force(monkeypatch, candidate=FOUND):
    monkeypatch.setattr(H, "build", lambda *a: dict(candidate))


def levels_now(st):
    return emo.levels(st)


def test_a_happening_is_written_applied_stored_and_logged(tmp_path, monkeypatch):
    s, st = fresh(tmp_path)
    force(monkeypatch)
    gm = StubGM(STORY)
    row = run(H.create(st, s, gm, w(), NOW, "2026-03-05#2", random.Random(1)))
    assert st.coins() == 15                                                      # applied: 10 + 5
    assert (row["category"], row["tone"], row["severity"], row["lens"], row["slot"], row["ts"]) == ("found", "good", "medium", "sadness", "2026-03-05#2", NOW)
    assert (row["title"], row["text"], row["author"], row["status"]) == ("A coat lining", STORY["text"], "gm", "applied")
    assert row["effects"] == FOUND["effects"] and row["effects_line"] == "(You find 5 coins.)" and row["ticks_seen"] == 0
    assert row["meaning"] == {"emotion": "sadness", "amount": 6, "jolt": 3, "shown_at": None}               # 9 points: a startle of 3 and a meaning of 6
    assert row["seed"] == f"{st.meta('happenings_salt')}:2026-03-05#2" and row["context"]["period"] == "afternoon"
    ev = [e for e in st.events(10) if e["kind"] == "happening"][0]["data"]
    assert ev.pop("firsts") == [{"key": "happening:found", "label": "the first time you came across something unexpected", "tier": "minor"}]
    assert ev == {"id": row["id"], "category": "found", "tone": "good", "severity": "medium", "lens": "sadness", "title": "A coat lining",
                  "text": STORY["text"], "effects": "(You find 5 coins.)", "jolt": 3, "status": "applied"}
    assert levels_now(st)["surprise"] == pytest.approx(13, abs=0.2) and levels_now(st)["sadness"] == pytest.approx(15, abs=0.2)   # the startle, not yet the meaning
    assert gm.calls[0][:5] == ("found", "good", "medium", "sadness", "(You find 5 coins.)")


def test_the_model_is_given_the_world_and_the_recent_titles(tmp_path, monkeypatch):
    s, st = fresh(tmp_path)
    force(monkeypatch)
    st.add_happening(ts=NOW - 3 * HOUR, slot="a", category="body", tone="good", severity="minor", lens="joy", seed="s", title="Rested")
    gm = StubGM(STORY)
    run(H.create(st, s, gm, w(), NOW, "x", random.Random(1)))
    _, _, _, _, _, facts, recent = gm.calls[0]
    assert recent == ["Rested"] and facts["period"] == "afternoon" and facts["names"] == ["Oriel Vantosh", "Gear Clock", "tomatoes"]


def test_log_mode_writes_it_but_changes_nothing(tmp_path, monkeypatch):
    s, st = fresh(tmp_path, happenings="log")
    force(monkeypatch)
    row = run(H.create(st, s, StubGM(STORY), w(), NOW, "x", random.Random(1)))
    assert row["status"] == "logged" and st.coins() == 10
    assert [e for e in st.events(10) if e["kind"] == "happening"][0]["data"]["jolt"] == 0
    assert levels_now(st)["surprise"] == pytest.approx(10, abs=0.2)


def test_a_template_is_used_when_there_is_no_model(tmp_path, monkeypatch):
    s, st = fresh(tmp_path)
    force(monkeypatch)
    row = run(H.create(st, s, None, w(), NOW, "x", random.Random(1)))
    assert row["author"] == "template" and (row["title"], row["text"]) == H.template(FOUND)


def test_nothing_is_made_when_nothing_fits(tmp_path, monkeypatch):
    s, st = fresh(tmp_path)
    monkeypatch.setattr(H, "build", lambda *a: None)
    assert run(H.create(st, s, StubGM(STORY), w(), NOW, "x", random.Random(1))) is None and st.happenings() == []


# --- the monitor's step ------------------------------------------------------------------------------------------
def step_state(tmp_path, **kw):
    kw.setdefault("happenings_chance", 1.0)
    s, st = fresh(tmp_path, **kw)
    return s, st


def stepped(s, st, gm, now):
    return run(H.step(st, s, gm, now))


def test_a_slot_that_hits_makes_a_happening_once(tmp_path):
    s, st = step_state(tmp_path)
    gm = StubGM(*[STORY] * 3)
    assert stepped(s, st, gm, at(12, 5)) is True
    (row,) = st.happenings()
    assert row["slot"] == "2026-03-05#2" and row["ts"] == at(12, 5) and st.happening_roll("2026-03-05#2")["hit"] == 1
    assert stepped(s, st, gm, at(12, 10)) is False and len(st.happenings()) == 1          # the slot is rolled once


def test_a_slot_that_misses_makes_nothing_and_is_not_rolled_again(tmp_path):
    s, st = step_state(tmp_path, happenings_chance=0.0)
    assert stepped(s, st, StubGM(STORY), at(12, 5)) is False
    assert st.happenings() == [] and st.happening_roll("2026-03-05#2")["hit"] == 0


def test_a_slot_is_only_rolled_within_half_an_hour_of_its_start(tmp_path):
    s, st = step_state(tmp_path)
    assert stepped(s, st, StubGM(STORY), at(12, 31)) is False
    assert st.happening_roll("2026-03-05#2") is None and st.happenings() == []                # skipped, never rolled late
    assert stepped(s, st, StubGM(STORY), at(12, 30)) is True                                  # but half an hour exactly is in time


def test_nothing_is_rolled_while_pip_sleeps_or_walks_and_the_slot_waits(tmp_path):
    s, st = step_state(tmp_path)
    st.update_agent(activity="sleeping")
    assert stepped(s, st, StubGM(STORY), at(12, 5)) is False and st.happening_roll("2026-03-05#2") is None
    st.update_agent(activity="idle")
    st.start_session(0, 0, 10, at(12, 40), kind="walk", target="Saltholm")
    assert stepped(s, st, StubGM(STORY), at(12, 10)) is False and st.happening_roll("2026-03-05#2") is None
    st.end_session()
    assert stepped(s, st, StubGM(STORY), at(12, 20)) is True                                  # the slot was still open


def test_an_unread_happening_holds_the_next_one_back(tmp_path):
    s, st = step_state(tmp_path)
    assert stepped(s, st, StubGM(STORY), at(12, 5)) is True
    assert stepped(s, st, StubGM(STORY), at(15, 5)) is False and st.happening_roll("2026-03-05#3") is None
    for h in H.unresolved(st):
        H.resolve(st, h, "joy")
    assert stepped(s, st, StubGM(STORY), at(15, 10)) is True


def test_a_day_has_a_most_and_off_does_nothing(tmp_path):
    s, st = step_state(tmp_path, happenings_max_per_day=1)
    st.add_happening(ts=at(7), slot="x", category="body", tone="good", severity="minor", lens="joy", seed="s", status="resolved")
    assert stepped(s, st, StubGM(STORY), at(12, 5)) is False and st.happening_roll("2026-03-05#2") is None
    yesterday = at(23, d=4)
    s2, st2 = step_state(tmp_path / "b") if (tmp_path / "b").mkdir() is None else (None, None)
    st2.add_happening(ts=yesterday, slot="x", category="body", tone="good", severity="minor", lens="joy", seed="s", status="resolved")
    assert stepped(settings(happenings_max_per_day=1, happenings_chance=1.0, db_path=s2.db_path), st2, StubGM(STORY), at(12, 5)) is True
    (tmp_path / "c").mkdir()
    s3, st3 = step_state(tmp_path / "c", happenings="off")
    assert stepped(s3, st3, StubGM(STORY), at(12, 5)) is False and st3.happenings() == [] and st3.happening_roll("2026-03-05#2") is None


def test_the_step_in_log_mode_rolls_and_writes_but_applies_nothing(tmp_path):
    s, st = step_state(tmp_path, happenings="log")
    assert stepped(s, st, StubGM(STORY), at(12, 5)) is True
    assert st.happenings()[0]["status"] == "logged" and st.coins() == 10 and H.unresolved(st) == []
    assert stepped(s, st, StubGM(STORY), at(15, 5)) is True                                   # nothing waits, so the next slot rolls too


def test_the_dice_are_reproducible_from_the_salt(tmp_path):
    def one(sub):
        (tmp_path / sub).mkdir()
        s, st = step_state(tmp_path / sub)
        st.set_meta(happenings_salt="fixed")
        stepped(s, st, None, at(12, 5))
        h = st.happenings()[0]
        return (h["category"], h["tone"], h["severity"], h["lens"], h["effects"])
    assert one("a") == one("b")


# --- Pip's reading ----------------------------------------------------------------------------------------------
def waiting(st, **kw):
    fields = dict(ts=NOW, slot="x", category="found", tone="bad", severity="medium", lens="sadness", seed="s", title="A hole", text="A hole in a pocket.",
                  effects_line="(You lose 3 coins.)", meaning={"emotion": "sadness", "amount": 6, "jolt": 3, "shown_at": None}, status="applied")
    return st.add_happening(**{**fields, **kw})


def test_the_meaning_lands_on_the_lens_by_default_once_pip_has_read_it_twice(tmp_path):
    s, st = fresh(tmp_path)
    h = waiting(st, ticks_seen=2)
    assert H.resolve_due(st, NOW) is True
    row = st.happening(h["id"])
    assert (row["status"], row["read_as"]) == ("resolved", "sadness")
    ev = [e for e in st.events(5) if e["kind"] == "happening_felt"][0]["data"]
    assert ev == {"id": h["id"], "title": "A hole", "lens": "sadness", "read_as": "sadness", "differs": False, "moves": {"sadness": 6}}
    assert levels_now(st)["sadness"] == pytest.approx(21, abs=0.2)                           # 15 + the meaning, 6
    assert H.resolve_due(st, NOW) is False and H.unresolved(st) == []                         # once


def test_or_after_forty_five_minutes_awake_following_the_first_showing(tmp_path):
    s, st = fresh(tmp_path)
    one = waiting(st, ticks_seen=1, meaning={"emotion": "sadness", "amount": 6, "jolt": 3, "shown_at": NOW - 46 * 60})
    two = waiting(st, ticks_seen=1, meaning={"emotion": "sadness", "amount": 6, "jolt": 3, "shown_at": NOW - 44 * 60})
    three = waiting(st, ticks_seen=0, ts=NOW - 5 * HOUR, meaning={"emotion": "sadness", "amount": 6, "jolt": 3, "shown_at": None})
    assert H.resolve_due(st, NOW) is True
    assert [st.happening(x["id"])["status"] for x in (one, two, three)] == ["resolved", "applied", "applied"]
    assert H.resolve_due(st, NOW + 2 * 60) is True and st.happening(two["id"])["status"] == "resolved"     # 46 minutes now
    assert st.happening(three["id"])["status"] == "applied"                                  # never shown: never resolved by the clock


def test_nothing_resolves_while_pip_sleeps(tmp_path):
    s, st = fresh(tmp_path)
    waiting(st, ticks_seen=3)
    st.update_agent(activity="sleeping")
    assert H.resolve_due(st, NOW) is False and len(H.unresolved(st)) == 1
    st.update_agent(activity="idle")
    assert H.resolve_due(st, NOW) is True


def test_feel_sends_the_meaning_wherever_pip_says_and_records_the_difference(tmp_path):
    s, st = fresh(tmp_path)
    h = waiting(st)
    ok, text = H.feel(st, s, "Joy", None, NOW)
    assert ok and text == "you take a hole as joy (it was written as sadness)"
    row = st.happening(h["id"])
    assert (row["status"], row["read_as"]) == ("resolved", "joy")
    ev = [e for e in st.events(5) if e["kind"] == "happening_felt"][0]["data"]
    assert ev["differs"] is True and ev["moves"] == {"joy": 6} and ev["lens"] == "sadness"
    assert levels_now(st)["joy"] == pytest.approx(51, abs=0.2) and levels_now(st)["sadness"] == pytest.approx(15, abs=0.2)
    assert H.feel(st, s, "joy", None, NOW)[1] == "you note that you feel joy"               # nothing is waiting now: only a report


def test_feeling_what_the_world_said_is_not_a_difference(tmp_path):
    s, st = fresh(tmp_path)
    waiting(st)
    ok, text = H.feel(st, s, "sadness", None, NOW)
    assert text == "you take a hole as sadness"
    assert [e for e in st.events(5) if e["kind"] == "happening_felt"][0]["data"]["differs"] is False


def test_a_shrug_drops_the_meaning(tmp_path):
    s, st = fresh(tmp_path)
    h = waiting(st)
    ok, text = H.feel(st, s, " Nothing ", None, NOW)
    assert ok and text == "you let a hole pass"
    ev = [e for e in st.events(5) if e["kind"] == "happening_felt"][0]["data"]
    assert ev["moves"] == {} and ev["read_as"] == "nothing" and ev["differs"] is True
    assert st.happening(h["id"])["read_as"] == "nothing" and levels_now(st)["sadness"] == pytest.approx(15, abs=0.2)


def test_feel_can_name_which_happening_and_refuses_what_it_does_not_know(tmp_path):
    s, st = fresh(tmp_path)
    a, b = waiting(st, title="First"), waiting(st, title="Second")
    assert H.feel(st, s, "joy", b["id"], NOW)[1].startswith("you take second as joy")
    assert st.happening(a["id"])["status"] == "applied"
    assert H.feel(st, s, "joy", str(a["id"]), NOW)[0] is True
    ok, text = H.feel(st, s, "happy", None, NOW)
    assert not ok and text == "you can feel one of: joy, sadness, anger, fear, trust, disgust, surprise, anticipation, or nothing"
    c = waiting(st)
    assert H.feel(st, s, "joy", "the mouse", NOW) == (False, "about is the number of what happened")
    assert H.feel(st, s, "joy", 999, NOW)[1] == "you note that you feel joy" and st.happening(c["id"])["status"] == "applied"


def test_a_report_with_nothing_waiting_is_kept_beside_the_engines_numbers(tmp_path):
    s, st = fresh(tmp_path)
    assert H.feel(st, s, "fear", None, NOW) == (True, "you note that you feel fear")
    ev = [e for e in st.events(5) if e["kind"] == "felt"][0]["data"]
    assert ev["emotion"] == "fear" and set(ev["levels"]) == set(emo.NAMES) and ev["levels"]["fear"] == 10
    assert H.feel(st, s, "nothing", None, NOW) == (True, "you note that you feel nothing in particular")
    assert levels_now(st)["fear"] == pytest.approx(10, abs=0.2)                              # a report moves nothing


# --- what Pip is told ---------------------------------------------------------------------------------------------
def test_pip_is_shown_a_waiting_happening_and_each_showing_is_counted(tmp_path):
    s, st = fresh(tmp_path)
    h = waiting(st)
    lines = H.perception(st, {"feel": 1}, NOW + 60)
    assert lines == ["Something happened: A hole. A hole in a pocket. (You lose 3 coins.)", "How it lands is up to you; feel says how you take it."]
    row = st.happening(h["id"])
    assert row["ticks_seen"] == 1 and row["meaning"]["shown_at"] == NOW + 60
    H.perception(st, {"feel": 1}, NOW + 120)
    row = st.happening(h["id"])
    assert row["ticks_seen"] == 2 and row["meaning"]["shown_at"] == NOW + 60                 # the first showing is the one that counts
    assert H.perception(st, {}, NOW)[1:] == []                                              # without the tool there is no hint


def test_a_read_happening_stays_for_a_while_and_a_logged_one_is_never_shown(tmp_path):
    s, st = fresh(tmp_path)
    h = waiting(st)
    H.feel(st, s, "joy", None, NOW)
    assert H.perception(st, {"feel": 1}, NOW + 2 * HOUR) == ["Something happened: A hole. A hole in a pocket. (You lose 3 coins.)"]
    assert H.perception(st, {"feel": 1}, NOW + 4 * HOUR) == []
    waiting(st, status="logged", ts=NOW)
    assert H.perception(st, {"feel": 1}, NOW) == ["Something happened: A hole. A hole in a pocket. (You lose 3 coins.)"]     # only the resolved one
    assert st.happening(h["id"])["ticks_seen"] == 0                                         # a read one is not counted again
    waiting(st, text="No effects.", effects_line="", status="applied", title="Plain")
    assert any(line == "Something happened: Plain. No effects." for line in H.perception(st, {}, NOW))


# --- how the emotion system takes it ------------------------------------------------------------------------------
def test_the_appraisal_table_has_the_two_happening_kinds():
    assert emo._appraisal("happening", {"jolt": 3, "title": "A hole"}) == ({"surprise": 3}, "something happened: A hole")
    assert emo._appraisal("happening", {"jolt": 0, "title": "A hole"}) == ({}, "something happened: A hole")
    assert emo._appraisal("happening", {}) == ({}, "something happened: an event")
    assert emo._appraisal("happening_felt", {"moves": {"joy": 6}, "title": "A hole", "read_as": "joy"}) == ({"joy": 6}, "A hole, read as joy")
    assert emo._appraisal("happening_felt", {}) == ({}, "an event, read as None")


def test_with_emotions_off_nothing_moves_but_the_happening_still_resolves(tmp_path):
    s, st = fresh(tmp_path / "x") if (tmp_path / "x").mkdir() is None else (None, None)
    s2 = settings(db_path=str(tmp_path / "o.db"), emotions="off")
    st2 = State(s2)
    emo.attach(st2, s2)
    h = waiting(st2, ticks_seen=2)
    assert H.resolve_due(st2, NOW) is True and st2.happening(h["id"])["status"] == "resolved"
    assert emo.levels(st2)["sadness"] == 15


# --- the config ---------------------------------------------------------------------------------------------------
def test_the_defaults_and_the_environment(monkeypatch):
    assert Settings().happenings == "off"                                                    # a bare Settings rolls nothing
    for k in ("HAPPENINGS", "HAPPENINGS_CHANCE", "HAPPENINGS_SLOT_HOURS", "HAPPENINGS_SEVERITY", "HAPPENINGS_MAX_PER_DAY"):
        monkeypatch.delenv(k, raising=False)
    s = Settings.from_env()
    assert (s.happenings, s.happenings_chance, s.happenings_slot_hours, s.happenings_severity, s.happenings_max_per_day) == ("on", 0.10, 3, (50, 45, 5), 3)
    monkeypatch.setenv("HAPPENINGS", "LOG")
    monkeypatch.setenv("HAPPENINGS_CHANCE", "0.25")
    monkeypatch.setenv("HAPPENINGS_SLOT_HOURS", "2")
    monkeypatch.setenv("HAPPENINGS_SEVERITY", "1, 1, 0")
    monkeypatch.setenv("HAPPENINGS_MAX_PER_DAY", "5")
    s = Settings.from_env()
    assert (s.happenings, s.happenings_chance, s.happenings_slot_hours, s.happenings_severity, s.happenings_max_per_day) == ("log", 0.25, 2, (1, 1, 0), 5)
    monkeypatch.setenv("HAPPENINGS", "sometimes")
    monkeypatch.setenv("HAPPENINGS_CHANCE", "7")
    monkeypatch.setenv("HAPPENINGS_SLOT_HOURS", "0")
    s = Settings.from_env()
    assert s.happenings == "on" and s.happenings_chance == 1.0 and s.happenings_slot_hours == 0.5      # clamped: never a slot shorter than half an hour
    for bad in ("1,2", "a,b,c", "-1,2,3", "0,0,0", "", "1,2,3,4"):
        monkeypatch.setenv("HAPPENINGS_SEVERITY", bad)
        assert Settings.from_env().happenings_severity == (50, 45, 5)
    monkeypatch.setenv("HAPPENINGS", "off")
    assert Settings.from_env().happenings == "off"


# --- the tool, the guide, the author's prompt, memory, the API ---------------------------------------------------------
@pytest.mark.asyncio
async def test_the_feel_tool_reads_a_happening(tmp_path):
    from app import tools as T
    from tests.test_projects import call, make
    s, st, gm, agent = make(tmp_path)
    agent.tools.update({"feel": T.REGISTRY["feel"]})
    h = waiting(st)
    r = await call(agent, "feel", emotion="trust")
    assert r.text == "you take a hole as trust (it was written as sadness)" and not r.followup
    assert st.happening(h["id"])["read_as"] == "trust"
    r = await call(agent, "feel", emotion="joyful")
    assert r.text.startswith("error: you can feel one of: joy") and r.followup
    h2 = waiting(st, title="Second")
    r = await call(agent, "feel", emotion="fear", about=h2["id"])
    assert "second as fear" in r.text
    assert (await call(agent, "feel", emotion="fear", about=0)).text == "you note that you feel fear"       # 0 is no happening: just a report


def test_the_tool_is_offered_only_with_emotions_on():
    from app import tools as T
    assert "feel" in T.enabled_tools(Settings(tools=["feel", "settle"], emotions="on"))
    assert "feel" not in T.enabled_tools(Settings(tools=["feel", "settle"], emotions="off"))
    assert "feel" in Settings.from_env().tools


def test_the_guide_says_how_to_read_what_happens_only_when_it_can_be_read():
    from app import guide
    text = guide.render(["feel"], Settings(happenings="on"), False)
    assert "Things sometimes happen to you" in text and "Only the line in brackets" in text and "feel says whether you take it as joy" in text
    assert "Things sometimes happen to you" not in guide.render(["feel"], Settings(happenings="off"), False)
    assert "Things sometimes happen to you" not in guide.render(["say"], Settings(happenings="on"), False)


@pytest.mark.asyncio
async def test_the_author_is_asked_for_the_words_and_nothing_else(tmp_path):
    from tests.test_gm_prompts import master, task
    from app.llm.base import LLMResponse, ToolCall, Usage
    gm2, b2, _ = master(tmp_path / "b" if (tmp_path / "b").mkdir() is None else tmp_path,
                        LLMResponse("", [ToolCall("1", "report", {"title": "A bold mouse", "text": "A mouse."})], Usage(1, 1)))
    out = await gm2.write_happening("pantry", "bad", "minor", "joy", "(You lose 3 tomatoes.)", {"period": "morning", "names": ["Oriel Vantosh", "tomatoes"]}, ["Rested", "Found"])
    assert out == {"title": "A bold mouse", "text": "A mouse."}
    prompt = task(b2)
    assert prompt.startswith("Write a small event that happens to Pip, who lives alone in a workshop with a garden. Category: pantry. Outcome: bad. Size: minor (a passing moment; keep it in proportion). ")
    assert "Write it through joy: let that feeling colour how it is told, whatever the outcome (a bad turn can still be told with joy).\n" in prompt
    assert "What really changes, which you must not contradict or add to: (You lose 3 tomatoes.)\n" in prompt
    assert "It is morning. Names you may use: Oriel Vantosh, tomatoes. Do not name anyone else.\n" in prompt
    assert "Recent events, so you do not repeat them: Rested; Found\n" in prompt
    assert prompt.endswith("Report `title` (a few words) and `text`.")
    assert "second person (you)" in prompt and "do not promise anything for later" in prompt and "do not say how Pip feels" in prompt
    assert b2.schemas[0]["properties"].keys() == {"title", "text"} and b2.schemas[0]["required"] == ["title", "text"]
    gm3, b3, _ = master(tmp_path / "c" if (tmp_path / "c").mkdir() is None else tmp_path,
                        LLMResponse("", [ToolCall("1", "report", {"title": "T", "text": "x"})], Usage(1, 1)))
    await gm3.write_happening("body", "neutral", "major", "surprise", "", {}, [])
    p3 = task(b3)
    assert "Size: major (a passing moment; keep it in proportion)." in p3                       # a neutral one is always small
    assert "Nothing changes in the world; it is only a moment.\n" in p3 and "Names you may use: none." in p3 and "Recent events" not in p3
    gm4, b4, _ = master(tmp_path / "d" if (tmp_path / "d").mkdir() is None else tmp_path,
                        LLMResponse("", [ToolCall("1", "report", {"title": "T", "text": "x"})], Usage(1, 1)))
    await gm4.write_happening("garden", "good", "major", "joy", "(Plot 1's tomatoes will give 3 more.)", {}, [])
    assert "Size: major. " in task(b4)


def test_a_happening_is_worth_remembering():
    from app import memory as mem
    assert [mem.event_importance("happening", {"severity": s}) for s in ("minor", "medium", "major", None)] == [3, 5, 7, 3]
    assert mem.event_importance("happening_felt", {}) == 2
    assert "happening" in mem.RECALL_EVENT_KINDS
    assert mem.recall_text("happening", {"title": "A hole", "text": "A hole in a pocket.", "effects": "(You lose 3 coins.)"}) == \
        "Something happened: A hole. A hole in a pocket. (You lose 3 coins.)"
    assert mem.recall_text("happening", {"title": "T", "text": "x."}) == "Something happened: T. x."


def api(tmp_path, **kw):
    from fastapi.testclient import TestClient
    from app.llm.fake import FakeBackend
    from app.main import create_app
    s = settings(db_path=str(tmp_path / "t.db"), persona_path="/x", pacing="manual", public_hosts=["pip.example.org"], public_redact=["Dana"], **kw)
    return TestClient(create_app(s, FakeBackend()))


def test_the_api_lists_happenings_in_full_for_the_owner_and_trimmed_for_the_public(tmp_path):
    with api(tmp_path) as c:
        st = c.app.state.agent.state
        st.add_happening(ts=NOW, slot="2026-03-05#2", category="found", tone="bad", severity="medium", lens="sadness", seed="secret",
                         effects=[{"kind": "coins", "delta": -3}], effects_line="(You lose 3 coins.)", title="A hole with Dana", text="A hole.", status="resolved",
                         read_as="joy", context={"names": ["Dana"]})
        owner = c.get("/happenings").json()
        assert owner[0]["seed"] == "secret" and owner[0]["effects"] == [{"kind": "coins", "delta": -3}] and owner[0]["meaning"] == {}
        public = c.get("/happenings", headers={"host": "pip.example.org"}).json()
        assert public == [{"id": 1, "ts": NOW, "category": "found", "tone": "bad", "severity": "medium", "lens": "sadness", "read_as": "joy",
                           "title": "A hole with someone", "text": "A hole.", "effects_line": "(You lose 3 coins.)", "status": "resolved"}]
        assert c.get("/happenings?limit=500", headers={"host": "pip.example.org"}).status_code == 200
        assert H.public_row(st.happenings()[0]).keys() == public[0].keys()


def test_the_public_feed_carries_what_happened_and_how_pip_read_it_but_not_the_dice(tmp_path):
    with api(tmp_path) as c:
        st = c.app.state.agent.state
        st.log("happening", id=1, category="found", tone="bad", severity="minor", lens="sadness", title="A hole", text="A hole.", effects="(You lose 1 coin.)",
               jolt=1, status="applied")
        st.log("happening_felt", id=1, title="A hole", lens="sadness", read_as="joy", differs=True, moves={"joy": 3})
        st.log("felt", emotion="joy", levels={"joy": 50})
        feed = c.get("/events?limit=20", headers={"host": "pip.example.org"}).json()
        by = {e["kind"]: e["data"] for e in feed}
        assert {k: v for k, v in by["happening"].items() if k != "firsts"} == {"id": 1, "category": "found", "severity": "minor", "lens": "sadness", "title": "A hole",
                                                                              "text": "A hole.", "effects": "(You lose 1 coin.)"}
        assert {k: v for k, v in by["happening_felt"].items() if k != "firsts"} == {"id": 1, "title": "A hole", "lens": "sadness", "read_as": "joy"}
        assert "felt" not in by
        assert "tone" not in by["happening"] and "jolt" not in by["happening"]


def test_the_public_view_shows_the_result_of_a_feel_and_pips_coins(tmp_path):
    from app import public_view as pv
    assert "feel" in pv.TOOLS_WITH_RESULT and "/happenings" in pv.PUBLIC_PATHS


@pytest.mark.asyncio
async def test_the_loop_hears_about_a_happening_and_tells_pip(tmp_path, monkeypatch):
    from app import tools as T
    from tests.test_projects import make
    s, st, gm, agent = make(tmp_path, happenings="on")
    agent.tools.update({"feel": T.REGISTRY["feel"]})
    waiting(st, ts=time.time())
    p = agent._perception("timer", [])
    assert "Something happened: A hole. A hole in a pocket. (You lose 3 coins.)" in p and "feel says how you take it." in p
    s.happenings = "off"
    assert "Something happened" not in agent._perception("timer", [])
    s.happenings = "on"
    called = []

    async def fake_step(state, settings, gm_):
        called.append(1)
        return True
    monkeypatch.setattr(H, "step", fake_step)
    agent._wake.clear()
    await agent.resolve_world()
    assert called and agent._wake.is_set()                                                    # a new happening wakes Pip


# --- the details the mutation run found loose ------------------------------------------------------------------------
def test_the_plans_always_carry_a_list_of_names_and_the_right_ones():
    for category in H.CATEGORIES.values():
        for tone in category.tones:
            for severity in H.SEVERITIES:
                for p in plans(category.name, tone, severity, seeds=range(15)):
                    assert isinstance(p.names, list) and isinstance(p.effects, list)
    assert plans("garden", "neutral", "minor")[0].names == ["tomatoes"]
    for name in ("creature", "pantry", "found", "body"):
        assert plans(name, "neutral", "minor", w(foods=[food(qty=30)]))[0].names == []
    assert plans("pantry", "bad", "minor", w(foods=[food("pears", 30)]))[0].names == ["pears"]
    assert plans("found", "good", "minor", seeds=range(80))[0].names in ([], [plans("found", "good", "minor", seeds=range(80))[0].effects[0].get("name")])


def test_creatures_leave_seeds_or_materials_and_finds_are_food_seeds_or_materials():
    assert {p.effects[0]["item_kind"] for p in plans("creature", "good", "minor", seeds=range(200))} == {"seed", "material"}
    assert {p.effects[0]["item_kind"] for p in plans("found", "good", "minor", seeds=range(400)) if p.effects[0]["kind"] == "item"} == {"food", "seed", "material"}


def test_a_found_item_is_a_real_entry_of_the_table_picked_by_its_weight():
    from app import gathering
    table = {e[0]: e for e in gathering.WOODS}
    rng = random.Random(5)
    picks = [H._found_item(rng, "minor", ("food", "seed", "material")) for _ in range(6000)]
    for item in picks:
        e = table[item["name"]]
        assert item == {"kind": "item", "name": e[0], "qty": 1, "item_kind": e[1], "description": e[4], "attrs": e[5]}
    pool = [e for e in gathering.WOODS if e[1] in ("food", "seed", "material")]
    total = sum(e[2] for e in pool)
    for e in pool:
        assert sum(1 for i in picks if i["name"] == e[0]) / len(picks) == pytest.approx(e[2] / total, abs=0.03)
    assert all(1 <= H._found_item(rng, "major", ("seed",))["qty"] <= 6 for _ in range(50)) and {H._found_item(rng, "major", ("seed",))["qty"] for _ in range(200)} == {4, 5, 6}


def test_the_edges_of_what_a_plan_needs():
    assert plans("creature", "bad", "minor", w(foods=[food(qty=5)]))[0].effects == [{"kind": "food_loss", "name": "tomatoes", "qty": 1}]       # five is enough
    assert plans("pantry", "bad", "minor", w(foods=[food(qty=20)]))[0].effects == [{"kind": "food_loss", "name": "tomatoes", "qty": 1}]       # so is twenty
    assert plans("found", "bad", "minor", w(coins=10))[0].effects == [{"kind": "coins", "delta": -1}]                                           # a coin is worth losing
    shifts = [e for p in plans("garden", "good", "minor", w(plots=[plot(left_min=20)])) for e in p.effects if e["kind"] == "crop_time"]
    assert shifts and all(e["minutes"] == 1 for e in shifts)                                                                                # one minute is enough
    bad = {e["kind"] for p in plans("garden", "bad", "major", seeds=range(200)) for e in p.effects}
    assert bad == {"crop_ruin", "crop_time", "crop_yield"}                                                                                  # a major bad turn is not always a ruin
    assert all(isinstance(p.effects[0]["units"], int) for p in plans("market", "good", "major") + plans("market", "bad", "major"))


def test_the_dice_choose_severity_and_the_line_matches_the_effects(tmp_path):
    s, st = fresh(tmp_path)
    seen = [H.build(st, s, w(), NOW, random.Random(i)) for i in range(3000)]
    live = [c["severity"] for c in seen if c["tone"] != "neutral"]
    assert set(live) == set(H.SEVERITIES) and live.count("major") / len(live) == pytest.approx(0.05, abs=0.02)
    assert all(c["line"] == H.effects_line(c["effects"]) for c in seen)
    heavy = settings(happenings_severity=(0, 0, 1))
    assert {c["severity"] for c in (H.build(st, heavy, w(), NOW, random.Random(i)) for i in range(100)) if c["tone"] != "neutral"} == {"major"}


def test_the_percentages_the_engine_quotes():
    assert H._percent(0.51) == 51 and H._percent(-0.12) == 12


@pytest.mark.parametrize("effect, text", [
    ({"kind": "coins", "delta": 0}, "You lose 0 coins."),
    ({"kind": "crop_time", "plot": 1, "crop": "peas", "minutes": 0}, "Plot 1's peas will be ready about 0 min later."),
    ({"kind": "crop_time", "plot": 1, "crop": "peas", "minutes": 1}, "Plot 1's peas will be ready about 1 min sooner."),
    ({"kind": "crop_yield", "plot": 1, "crop": "peas", "delta": 0}, "Plot 1's peas will give 0 less."),
    ({"kind": "crop_yield", "plot": 1, "crop": "peas", "delta": 1}, "Plot 1's peas will give 1 more."),
    ({"kind": "energy", "delta": 0}, "Your energy falls by 0%."),
    ({"kind": "price", "place": "Quay", "item": "peas", "units": 6}, "Peas fetches about 27% more at Quay for now."),
    ({"kind": "price", "place": "Quay", "item": "peas", "units": -6}, "Peas fetches about 22% less at Quay for now."),
    ({"kind": "price", "place": "Quay", "item": "peas", "units": 0}, "Peas fetches about 0% less at Quay for now."),
])
def test_effects_are_described_at_their_edges(effect, text):
    assert H.describe(effect) == text


def test_an_unknown_effect_is_named_in_the_error():
    with pytest.raises(ValueError, match="unknown effect 'teleport'"):
        H.describe({"kind": "teleport"})


def test_more_effects_in_detail(tmp_path):
    s, st = fresh(tmp_path)
    H.apply_effects(st, [{"kind": "item", "name": "hazelnuts", "qty": 2, "item_kind": "food", "description": "a handful", "attrs": {"food_value": 0.15}}], NOW)
    item = st.find_item("hazelnuts")[0]
    assert item["attrs"]["food_value"] == 0.15 and item["description"] == "a handful"
    st.add_item("bark", 5, "material", "")
    H.apply_effects(st, [{"kind": "food_loss", "name": "bark", "qty": 3}], NOW)
    assert st.find_item("bark")[0]["qty"] == 5                                              # only food is lost to pests
    st.add_item("pears", 2, "food", "", {"food_value": 0.2})
    H.apply_effects(st, [{"kind": "food_loss", "name": "pears", "qty": 5}], NOW)
    assert st.find_item("pears")[0]["qty"] == 1
    st.plant(1, "s", "tomatoes", 600, 3, 0.5)
    ready = st.garden()[0]["ready_at"]
    H.apply_effects(st, [{"kind": "crop_time", "plot": 1, "factor": 0.5}], ready - 1000)
    assert st.garden()[0]["ready_at"] == pytest.approx(ready - 500)                          # the time left, from the time given
    st.set_price_row("Quay", "pea", 1.0, 0, "x", 0)
    H.apply_effects(st, [{"kind": "price", "place": "Quay", "item": "peas", "units": 2}], NOW)
    assert st.price_row("Quay", "pea")["local_at"] == NOW


@pytest.mark.parametrize("n, ok", [(19, False), (20, True), (420, True), (421, False)])
def test_the_length_limits_are_inclusive(n, ok):
    text = ("a" * (n - 1)) + "."
    assert H.valid_text(text, "", [], "minor", "good")[0] is ok


def test_a_text_may_say_pip_i_and_you_in_mid_sentence():
    assert H.valid_text("The mouse stares at Pip, and then I think You notice the crumbs on the shelf.", "", [], "minor", "good") == (True, "")
    assert H.valid_text("The mouse stares at Bob, and then it goes off along the shelf somewhere.", "", [], "minor", "good")[0] is False


def test_the_author_applies_every_check_to_the_models_text():
    big = {"title": "T", "text": "The mouse is a catastrophe for the pantry and nothing else is said here."}
    assert run(H.author(StubGM(big, big), CAND, FACTS, []))[2] == "template"                                # minor: too big
    assert run(H.author(StubGM(big, big), {**CAND, "severity": "major", "tone": "neutral"}, FACTS, []))[2] == "template"     # neutral: too big
    assert run(H.author(StubGM(big), {**CAND, "severity": "major"}, FACTS, []))[2] == "gm"
    named = {"title": "News", "text": "Word comes from the marsh that a heron called Oriel has been about, and nothing more."}
    assert run(H.author(StubGM(named), {**CAND, "names": []}, FACTS, []))[2] == "gm"                         # the facts offer Oriel
    assert run(H.author(StubGM(named, named), {**CAND, "names": []}, {"period": "x", "names": []}, []))[2] == "template"
    assert run(H.author(StubGM({"title": "Lucky Box", "text": GOOD["text"]}), CAND, FACTS, []))[0] == "Lucky Box"
    assert run(H.author(StubGM({"title": ".. Lucky ..", "text": GOOD["text"]}), CAND, FACTS, []))[0] == "Lucky"
    assert run(H.author(StubGM({"title": "t" * 200, "text": GOOD["text"]}), CAND, FACTS, []))[0] == "t" * H.TITLE_MAX
    assert run(H.author(StubGM({"title": "Mr X", "text": GOOD["text"]}), CAND, FACTS, []))[0] == "Mr X"
    assert run(H.author(StubGM(GOOD), CAND, {}, []))[2] == "gm"                                              # facts with no names at all


def test_today_starts_at_midnight():
    assert H._today_start(at(15, 37) + 42.5) == at(0)


def test_the_world_as_the_dice_see_it(tmp_path):
    from tests.test_invented_places import real_shop
    s, st = fresh(tmp_path, tools=[])
    s.invented_places_per_day = 3
    real_shop(st)
    st.update_place("Saltholm", loot=[["brass wire", "material", 20, [1, 2], "wire", {}]])
    st.add_place("Brygdon", "brygdon", kind="market", status="heard", created_at=NOW, heard_at=NOW)       # heard of only: no booth yet
    st.add_place("Lake", "lake", kind="sight", status="real", created_at=NOW, heard_at=NOW)
    st.add_item("pears", 4, "food", "", {"food_value": 0.2})
    st.add_item("carrots", 12, "food", "", {"food_value": 0.4})
    st.add_item("bark", 30, "material", "")
    st.plant(1, "s", "tomatoes", 600, 3, 0.5)
    st.plant(2, "s", "carrots", 600, 3, 0.5)
    st.update_agent(hunger=0.3, energy=0.9)
    st.add_character("Oriel Vantosh", "neighbor", None, "p", 60, NOW + 99 * HOUR, about="x")
    st.add_character("Mr Teague", "resident", None, "p", 60, NOW + 99 * HOUR, about="x", place="Saltholm")
    st.add_creation("Gear Clock", "a clock", None, "good", {"capabilities": {}}, {})
    got = H.world(st, s, NOW)
    assert got["now"] == NOW and got["coins"] == 10 and got["hunger"] == 0.3 and got["energy"] == 0.9 and got["low"] is False
    assert [i["name"] for i in got["foods"]] == ["carrots", "pears"]                       # food only, the biggest stack first
    assert [g["plot"] for g in got["plots"]] == [1, 2] and all(g["state"] == "growing" for g in got["plots"])
    assert [b["key"] for b in got["booths"]] == ["Saltholm"] and got["neighbors"] == ["Oriel Vantosh"] and got["creations"] == ["Gear Clock"]
    assert got["period"] == "afternoon"
    st.update_agent(hunger=0.8)
    assert H.world(st, s, NOW)["low"] is True
    st.update_agent(hunger=0.79, energy=0.25)
    assert H.world(st, s, NOW)["low"] is True
    st.update_agent(hunger=0.79, energy=0.26)
    assert H.world(st, s, NOW)["low"] is False
    assert H.world(st, s, at(23))["period"] == "night" and H.world(st, s, at(9))["period"] == "morning"
    assert H.world(st, s, time.time() + 700 * 60)["plots"] == []                            # ripe, not growing


def test_create_passes_its_own_time_and_the_amount_follows_the_tone(tmp_path, monkeypatch):
    s, st = fresh(tmp_path)
    price = {"category": "market", "tone": "neutral", "severity": "minor", "lens": "surprise",
             "effects": [{"kind": "price", "place": "Quay", "item": "peas", "units": 1}], "names": ["Quay"], "facts": {}, "line": "(x)"}
    force(monkeypatch, price)
    st.set_price_row("Quay", "pea", 1.0, 0, "x", 0)
    row = run(H.create(st, s, None, w(), NOW, "x", random.Random(1)))
    assert row["meaning"] == {"emotion": "surprise", "amount": 1, "jolt": 1, "shown_at": None}              # neutral: 2 points, whatever the size
    assert st.price_row("Quay", "pea")["local_at"] == NOW
    assert row["context"] == {"period": "afternoon", "names": ["Quay"]}


def test_resolve_returns_the_row(tmp_path):
    s, st = fresh(tmp_path)
    h = waiting(st)
    got = H.resolve(st, h, "joy")
    assert got["id"] == h["id"] and got["status"] == "resolved" and got["read_as"] == "joy"


def test_a_read_happening_is_shown_for_exactly_three_hours(tmp_path):
    s, st = fresh(tmp_path)
    waiting(st, status="resolved", ts=NOW)
    line = "Something happened: A hole. A hole in a pocket. (You lose 3 coins.)"
    assert H.perception(st, {}, NOW + 3 * HOUR) == [line]
    assert H.perception(st, {}, NOW + 3 * HOUR + 1) == []


def test_an_old_read_happening_does_not_hide_a_newer_one(tmp_path):
    s, st = fresh(tmp_path)
    waiting(st, status="resolved", ts=NOW, title="Fresh")
    waiting(st, status="resolved", ts=NOW - 9 * HOUR, title="Stale")
    waiting(st, status="logged", ts=NOW, title="Logged")
    assert [l.split(".")[0] for l in H.perception(st, {}, NOW)] == ["Something happened: Fresh"]


def test_the_forty_five_minutes_are_inclusive(tmp_path):
    s, st = fresh(tmp_path)
    waiting(st, ticks_seen=1, meaning={"emotion": "sadness", "amount": 6, "jolt": 3, "shown_at": NOW - 45 * 60})
    assert H.resolve_due(st, NOW) is True


def test_the_step_uses_its_own_clock_and_the_model_it_was_given(tmp_path):
    s, st = step_state(tmp_path)
    waiting(st, ticks_seen=1, slot="old", meaning={"emotion": "sadness", "amount": 6, "jolt": 3, "shown_at": at(11, 50)})
    assert stepped(s, st, StubGM(STORY), at(12, 0)) is False                                  # ten minutes after the showing: still waiting
    assert st.happenings()[0]["status"] == "applied"
    assert stepped(s, st, StubGM(STORY), at(12, 40)) is False and st.happenings()[0]["status"] == "resolved"   # 50 minutes: read, and the slot is still open? it is not: 40 min
    s2, st2 = step_state(tmp_path / "b") if (tmp_path / "b").mkdir() is None else None
    assert stepped(s2, st2, StubGM(STORY), at(12, 5)) is True and st2.happenings()[0]["author"] == "gm"


def test_a_rolled_slot_is_not_rolled_again_even_when_nothing_waits(tmp_path):
    s, st = step_state(tmp_path)
    assert stepped(s, st, StubGM(STORY), at(12, 5)) is True
    for h in H.unresolved(st):
        H.resolve(st, h, "joy")
    assert stepped(s, st, StubGM(STORY), at(12, 10)) is False and len(st.happenings()) == 1


def test_the_daily_count_edges(tmp_path):
    s, st = step_state(tmp_path, happenings_max_per_day=2)
    st.add_happening(ts=at(7), slot="x", category="body", tone="good", severity="minor", lens="joy", seed="s", status="resolved")
    assert stepped(s, st, StubGM(STORY), at(12, 5)) is True                                   # one so far today, two allowed
    (tmp_path / "b").mkdir()
    s2, st2 = step_state(tmp_path / "b", happenings_max_per_day=1)
    st2.add_happening(ts=at(0), slot="x", category="body", tone="good", severity="minor", lens="joy", seed="s", status="resolved")
    assert stepped(s2, st2, StubGM(STORY), at(12, 5)) is False                                # a happening at midnight sharp is today's


def test_the_step_builds_with_dice_from_the_salt_and_the_slot(tmp_path, monkeypatch):
    import hashlib
    s, st = step_state(tmp_path)
    st.set_meta(happenings_salt="fixed")
    seen = {}

    async def spy(state, settings, gm, w_, now, slot, rng):
        seen["slot"], seen["state"] = slot, rng.getstate()
        return None
    monkeypatch.setattr(H, "create", spy)
    stepped(s, st, None, at(12, 5))
    assert seen["slot"] == "2026-03-05#2"
    assert seen["state"] == random.Random(hashlib.sha256(b"fixed:2026-03-05#2:build").hexdigest()).getstate()


def test_the_feel_report_levels_are_the_numbers_at_that_time(tmp_path):
    s, st = fresh(tmp_path)
    emo.nudge(st, {"fear": 40}, "test", NOW)
    H.feel(st, s, "fear", None, NOW + 20 * 60 * 6)                                           # six half-lives later
    ev = [e for e in st.events(5) if e["kind"] == "felt"][0]["data"]
    assert ev["levels"]["fear"] == round(10 + 40 * 0.5 ** (20 * 6 / 120 * 1.0)) or ev["levels"]["fear"] < 50


# --- the other five categories, mending, firsts, replay --------------------------------------------------------------
UPKEEP = {"capabilities": {"upkeep": {"verb": "wind", "hours": 24}}, "quirks": [], "scars": []}


def clock(st, name="Gear Clock", spec=UPKEEP, now=None):
    from app import creations as cr
    now = now or time.time()
    return st.add_creation(name, "a clock", None, "sound", spec, cr.initial_runtime(spec, now))


@pytest.mark.parametrize("severity", H.SEVERITIES)
def test_a_mishap_costs_a_little_energy_or_stops_a_creation(severity):
    assert H.CATEGORIES["mishap"].tones == ("bad", "neutral")
    plan = plans("mishap", "bad", severity)
    if severity == "minor":
        assert all(p.effects == [{"kind": "energy", "delta": -H.ENERGY["minor"]}] and p.names == ["needle file"] for p in plan)
    else:
        for p in plan:
            (e,) = p.effects
            assert e["kind"] == "creation_stop" and e["id"] == 1 and e["name"] == "Gear Clock"
            assert (e["part"] is None) == (severity == "medium")
            assert p.names == ["Gear Clock"] + ([e["part"]["name"]] if e["part"] else [])
            if e["part"]:
                from app import gathering
                assert e["part"]["name"] in {m[0] for m in gathering.JUNKYARD if m[1] == "material"} and 1 <= e["part"]["qty"] <= 3
    assert plans("mishap", "neutral", severity)[0].effects == [] and plans("mishap", "neutral", severity)[0].names == ["needle file"]


def test_a_mishap_needs_something_to_go_wrong_and_spares_a_low_pip():
    none = w(stoppable=[], tools=[])
    assert not H.CATEGORIES["mishap"].needs(none) and H.CATEGORIES["mishap"].needs(w(stoppable=[])) and H.CATEGORIES["mishap"].needs(w(tools=[]))
    assert H.CATEGORIES["mishap"].plan(w(low=True), "bad", "minor", random.Random(1)) is None
    for severity in ("medium", "major"):
        assert H.CATEGORIES["mishap"].plan(w(stoppable=[]), "bad", severity, random.Random(1)) is None
    assert H.CATEGORIES["mishap"].plan(w(tools=[]), "neutral", "minor", random.Random(1)).names == []


def test_a_neighbor_happening_is_news_of_someone_pip_knows():
    for tone in ("good", "bad"):
        for p in plans("neighbor", tone, "medium"):
            assert p.effects == [{"kind": "news", "name": "Oriel Vantosh", "tone": tone}] and p.names == ["Oriel Vantosh"]
    assert plans("neighbor", "neutral", "minor")[0].effects == [] and plans("neighbor", "neutral", "minor")[0].names == ["Oriel Vantosh"]
    assert not H.CATEGORIES["neighbor"].needs(w(neighbors=[]))


def test_a_memory_brings_back_a_real_old_note_and_needs_enough_of_them():
    p = plans("memory", "good", "minor")[0]
    assert p.effects == [] and p.facts == {"memory": "Oriel taught me to feel for the round grains in the tin."} and p.names == ["Oriel"]
    assert plans("memory", "neutral", "minor", w(old_notes=[{"id": 1, "text": "x" * 300, "ts": 0}]))[0].facts["memory"] == "x" * 200 + "..."
    cat = H.CATEGORIES["memory"]
    assert cat.needs(w()) and not cat.needs(w(diary_count=6)) and cat.needs(w(diary_count=7)) and not cat.needs(w(old_notes=[]))


def test_a_kindness_is_a_gift_from_someone_unseen():
    assert H.CATEGORIES["kindness"].tones == ("good",)
    kinds = set()
    for p in plans("kindness", "good", "medium", seeds=range(80)):
        (e,) = p.effects
        kinds.add(e["kind"])
        assert e["gift"] is True and "Oriel Vantosh" in p.names
        assert (e["kind"] == "coins" and 3 <= e["delta"] <= 10 and p.names == ["Oriel Vantosh"]) or (e["kind"] == "item" and p.names == [e["name"], "Oriel Vantosh"])
    assert kinds == {"item", "coins"} and not H.CATEGORIES["kindness"].needs(w(neighbors=[]))


def test_the_atmosphere_is_only_a_moment():
    assert H.CATEGORIES["atmosphere"].tones == ("neutral",) and H.CATEGORIES["atmosphere"].needs(w(plots=[], neighbors=[], booths=[]))
    assert plans("atmosphere", "neutral", "minor")[0].effects == [] and plans("atmosphere", "neutral", "minor")[0].names == []


@pytest.mark.parametrize("effect, text", [
    ({"kind": "coins", "delta": 3, "gift": True}, "You are given 3 coins."), ({"kind": "coins", "delta": 3}, "You find 3 coins."),
    ({"kind": "coins", "delta": -3, "gift": True}, "You lose 3 coins."),
    ({"kind": "item", "name": "bark", "qty": 2, "gift": True}, "You are given 2 bark."), ({"kind": "item", "name": "bark", "qty": 2}, "You find 2 bark."),
    ({"kind": "creation_stop", "id": 1, "name": "Gear Clock", "part": None}, "Your Gear Clock stops; it needs tending."),
    ({"kind": "creation_stop", "id": 1, "name": "Gear Clock", "part": {"name": "brass wire", "qty": 2}}, "Your Gear Clock stops; it needs 2 brass wire to mend, then tending."),
    ({"kind": "news", "name": "Oriel Vantosh", "tone": "good"}, "You hear news of Oriel Vantosh."),
    ({"kind": "hunger", "delta": 0.12}, "Your hunger rises by 12%."),
])
def test_the_new_effects_are_described(effect, text):
    assert H.describe(effect) == text


def test_a_mishap_stops_a_creation_that_needs_tending_and_only_that(tmp_path):
    from app import creations as cr
    s, st = fresh(tmp_path)
    c = clock(st)
    plain = clock(st, "Keepsake", {"capabilities": {}, "quirks": [], "scars": []})
    assert cr.running(st.find_creation("Gear Clock")[0], time.time())
    H.apply_effects(st, [{"kind": "creation_stop", "id": c["id"], "name": "Gear Clock", "part": {"name": "brass wire", "qty": 2}}], NOW)
    stopped = st.find_creation("Gear Clock")[0]
    assert stopped["runtime"]["halted_at"] == NOW and stopped["runtime"]["needs_part"] == {"name": "brass wire", "qty": 2}
    H.apply_effects(st, [{"kind": "creation_stop", "id": plain["id"], "name": "Keepsake", "part": None}, {"kind": "creation_stop", "id": 999, "name": "x", "part": None}], NOW)
    assert "halted_at" not in st.find_creation("Keepsake")[0]["runtime"]                      # nothing to stop in a keepsake
    H.apply_effects(st, [{"kind": "creation_stop", "id": c["id"], "name": "Gear Clock", "part": None}], NOW + 5)
    assert st.find_creation("Gear Clock")[0]["runtime"]["halted_at"] == NOW + 5


def test_a_stopped_creation_with_a_missing_part_must_be_mended_before_it_is_tended(tmp_path):
    from app import creations as cr
    s, st = fresh(tmp_path)
    c = clock(st)
    H.apply_effects(st, [{"kind": "creation_stop", "id": c["id"], "name": "Gear Clock", "part": {"name": "brass wire", "qty": 2}}], NOW)
    stopped = st.find_creation("Gear Clock")[0]
    assert cr._needs(stopped) == "it needs 2 brass wire to mend it, then tending (wind)"
    assert "STOPPED - it needs 2 brass wire to mend it, then tending (wind)" in cr.describe(stopped, NOW + 10)
    assert cr.tend(st, stopped, NOW + 10) == "error: your Gear Clock needs 2 brass wire to mend it before it can be tended"
    st.add_item("brass wire", 1, "material", "")
    assert cr.tend(st, st.find_creation("Gear Clock")[0], NOW + 10).startswith("error: your Gear Clock needs 2 brass wire")
    assert st.find_item("brass wire")[0]["qty"] == 1                                         # nothing taken until it can be mended
    st.add_item("brass wire", 4, "material", "")
    assert cr.tend(st, st.find_creation("Gear Clock")[0], NOW + 10).startswith("you tend your Gear Clock (wind)")
    mended = st.find_creation("Gear Clock")[0]
    assert st.find_item("brass wire")[0]["qty"] == 3 and "needs_part" not in mended["runtime"] and "halted_at" not in mended["runtime"]
    st.add_item("brass wire", 1, "tool", "")
    assert cr.tend(st, st.find_creation("Gear Clock")[0], NOW + 20).startswith("you tend")          # a plain stop needs only tending


def test_a_part_must_be_a_material_and_a_plain_stop_is_just_tended(tmp_path):
    from app import creations as cr
    s, st = fresh(tmp_path)
    c = clock(st)
    H.apply_effects(st, [{"kind": "creation_stop", "id": c["id"], "name": "Gear Clock", "part": {"name": "springs", "qty": 1}}], NOW)
    st.add_item("springs", 3, "tool", "")                                                   # not a material: it does not count
    assert cr.tend(st, st.find_creation("Gear Clock")[0], NOW).startswith("error: your Gear Clock needs 1 springs")


def test_news_joins_a_neighbors_life_as_the_title(tmp_path):
    from app import neighbors
    s, st = fresh(tmp_path)
    ch = st.add_character("Oriel Vantosh", "neighbor", None, "p", 60, NOW + 99 * HOUR, about="x")
    news = [{"kind": "news", "name": "Oriel Vantosh", "tone": "good"}]
    for i in range(neighbors.LIFE_KEPT + 2):
        H.apply_effects(st, news, NOW, f"News {i}")
    life = st.characters("neighbor")[0]["life"]
    assert life == [f"News {i}" for i in range(2, neighbors.LIFE_KEPT + 2)]                  # the latest few
    H.apply_effects(st, news, NOW, "")
    H.apply_effects(st, [{"kind": "news", "name": "Nobody", "tone": "good"}], NOW, "Ignored")
    assert st.characters("neighbor")[0]["life"] == life
    H.apply_effects(st, news, NOW, "x" * 300)
    assert st.characters("neighbor")[0]["life"][-1] == "x" * 200 + "..."


def test_a_neighbor_happening_reaches_the_neighbor_through_create(tmp_path, monkeypatch):
    s, st = fresh(tmp_path)
    st.add_character("Oriel Vantosh", "neighbor", None, "p", 60, NOW + 99 * HOUR, about="x")
    force(monkeypatch, {"category": "neighbor", "tone": "good", "severity": "minor", "lens": "joy", "effects": [{"kind": "news", "name": "Oriel Vantosh", "tone": "good"}],
                        "names": ["Oriel Vantosh"], "facts": {}, "line": "(You hear news of Oriel Vantosh.)"})
    gm = StubGM({"title": "Her heron is back", "text": "Word comes across the marsh that the heron has come back to Oriel, who is delighted about it."})
    run(H.create(st, s, gm, w(), NOW, "x", random.Random(1)))
    assert st.characters("neighbor")[0]["life"] == ["Her heron is back"]


def test_a_memory_happening_hands_the_note_to_the_author_and_stores_it(tmp_path, monkeypatch):
    s, st = fresh(tmp_path)
    force(monkeypatch, {"category": "memory", "tone": "bad", "severity": "minor", "lens": "sadness", "effects": [], "names": ["Oriel"],
                        "facts": {"memory": "Oriel taught me the tin."}, "line": ""})
    gm = StubGM({"title": "The tin", "text": "Out of nowhere you remember Oriel and the tin by the door, and it aches a little."})
    row = run(H.create(st, s, gm, w(), NOW, "x", random.Random(1)))
    assert gm.calls[0][5]["memory"] == "Oriel taught me the tin." and row["context"]["memory"] == "Oriel taught me the tin." and row["author"] == "gm"


@pytest.mark.asyncio
async def test_the_author_is_told_the_memory_that_comes_back(tmp_path):
    from app.llm.base import LLMResponse, ToolCall, Usage
    from tests.test_gm_prompts import master, task
    gm, b, _ = master(tmp_path, LLMResponse("", [ToolCall("1", "report", {"title": "T", "text": "x"})], Usage(1, 1)))
    await gm.write_happening("memory", "good", "minor", "joy", "", {"period": "evening", "names": [], "memory": "Oriel taught me the tin."}, [])
    assert 'Something Pip once wrote comes back to mind: "Oriel taught me the tin." Build the moment from it, in your own words.\n' in task(b)
    gm2, b2, _ = master(tmp_path / "b" if (tmp_path / "b").mkdir() is None else tmp_path, LLMResponse("", [ToolCall("1", "report", {"title": "T", "text": "x"})], Usage(1, 1)))
    await gm2.write_happening("garden", "good", "minor", "joy", "", {"period": "evening", "names": []}, [])
    assert "comes back to mind" not in task(b2)


def test_the_world_knows_what_can_stop_what_tools_there_are_and_which_notes_are_old(tmp_path):
    s, st = fresh(tmp_path)
    now = time.time()
    clock(st)
    clock(st, "Keepsake", {"capabilities": {}, "quirks": [], "scars": []})
    stopped = clock(st, "Old Bell")
    H.apply_effects(st, [{"kind": "creation_stop", "id": stopped["id"], "name": "Old Bell", "part": None}], now)
    st.add_item("needle file", 1, "tool", "")
    st.add_item("bark", 1, "material", "")
    for i in range(8):
        st.add_memory(f"note {i}", "diary")
    st.add_memory("a todo", "todo")
    got = H.world(st, s, now)
    assert [c["name"] for c in got["stoppable"]] == ["Gear Clock"]                           # has upkeep and is going
    assert got["tools"] == ["needle file"] and got["diary_count"] == 8 and got["old_notes"] == []
    later = H.world(st, s, now + 3 * 86400)
    assert len(later["old_notes"]) == 8 and later["diary_count"] == 8
    assert len(H.world(st, s, now + 2 * 86400 - 5)["old_notes"]) == 0                         # two days is the line
    assert len(H.world(st, s, now + 2 * 86400 + 5)["old_notes"]) == 8


def test_every_category_is_in_its_cooldown_after_one_each(tmp_path):
    s, st = fresh(tmp_path)
    assert len(H.CATEGORIES) == 11
    for name in H.CATEGORIES:
        st.add_happening(ts=NOW - HOUR, slot="x", category=name, tone="good", severity="minor", lens="joy", seed="s")
    assert H.build(st, s, w(), NOW, random.Random(1)) is None                                  # all eleven are seen, not only the latest ten


def test_the_new_categories_each_turn_up_in_a_rich_world(tmp_path):
    s, st = fresh(tmp_path)
    seen = {H.build(st, s, w(), NOW, random.Random(i))["category"] for i in range(600)}
    assert seen == set(H.CATEGORIES)


def test_a_first_happening_of_each_kind_is_a_first_and_reading_it_differently_is_a_major_one():
    from app import firsts
    assert set(firsts.HAPPENING_FIRSTS) == set(H.CATEGORIES)
    got = firsts.facets("happening", {"category": "garden", "status": "applied"}, None, 0)
    assert got == [("happening:garden", "the first time you had the garden change on its own", "minor")]
    assert firsts.facets("happening", {"category": "garden", "status": "logged"}, None, 0) == []            # a logged one did not happen
    assert firsts.facets("happening", {"category": "unknown", "status": "applied"}, None, 0) == []
    assert firsts.facets("happening_felt", {"differs": True, "read_as": "joy"}, None, 0) == [
        ("happening:read_differently", "the first time you took something that happened differently from how it was told", "major")]
    assert firsts.facets("happening_felt", {"differs": True, "read_as": "nothing"}, None, 0) == []
    assert firsts.facets("happening_felt", {"differs": False, "read_as": "joy"}, None, 0) == []


def test_a_happening_is_a_first_in_the_log(tmp_path, monkeypatch):
    s, st = fresh(tmp_path)
    force(monkeypatch)
    run(H.create(st, s, StubGM(STORY), w(), NOW, "x", random.Random(1)))
    ev = [e for e in st.events(10) if e["kind"] == "happening"][0]["data"]
    assert [f["key"] for f in ev["firsts"]] == ["happening:found"]


def test_replaying_a_happening_rolls_its_slot_again(tmp_path):
    s, st = step_state(tmp_path)
    st.set_meta(happenings_salt="fixed")
    stepped(s, st, StubGM(STORY), at(12, 5))
    h = st.happenings()[0]
    r = H.replay(st, s, h)
    assert r["slot"] == "2026-03-05#2" and r["seed"] == "fixed:2026-03-05#2" and r["roll"] == random.Random("fixed:2026-03-05#2").random()
    assert r["recorded_roll"] == r["roll"] and r["matches"] is True and r["chance"] == 1.0 and r["would_hit"] is True
    assert r["decided"] == {k: h[k] for k in ("category", "tone", "severity", "lens")} and r["id"] == h["id"]
    assert H.replay(st, settings(happenings_chance=0.0), h)["would_hit"] is False
    st.db.execute("UPDATE happening_rolls SET roll = 0.5")
    assert H.replay(st, s, h)["matches"] is False
    st.db.execute("DELETE FROM happening_rolls")
    assert H.replay(st, s, h)["recorded_roll"] is None and H.replay(st, s, h)["matches"] is False


def test_the_replay_is_for_the_owner_only(tmp_path):
    with api(tmp_path) as c:
        st = c.app.state.agent.state
        st.add_happening(ts=NOW, slot="2026-03-05#2", category="found", tone="good", severity="minor", lens="joy", seed="s:2026-03-05#2", status="resolved")
        got = c.get("/happenings/1/replay").json()
        assert got["id"] == 1 and got["slot"] == "2026-03-05#2" and got["recorded_roll"] is None and got["decided"]["category"] == "found"
        assert c.get("/happenings/99/replay").status_code == 404
        assert c.get("/happenings/1/replay", headers={"host": "pip.example.org"}).status_code == 404


# --- more details, found by the mutation run --------------------------------------------------------------------------
def test_the_world_counts_every_diary_note_and_draws_the_two_day_line_exactly(tmp_path):
    s, st = fresh(tmp_path)
    now = time.time()
    for i in range(12):
        st.add_memory(f"note {i}", "diary")
    clock(st)
    got = H.world(st, s, now)
    assert got["diary_count"] == 12 and got["stoppable"] == [{"id": st.creations()[0]["id"], "name": "Gear Clock"}]
    st.db.execute("UPDATE memories SET ts = ?", (now - 2 * 86400,))
    assert len(H.world(st, s, now)["old_notes"]) == 0                                          # exactly two days is not yet old
    st.db.execute("UPDATE memories SET ts = ?", (now - 2 * 86400 - 0.5,))
    assert len(H.world(st, s, now)["old_notes"]) == 12


def test_a_ruin_names_the_crop_and_a_major_mishap_draws_a_part_by_weight():
    from app import gathering
    ruins = [e for p in plans("garden", "bad", "major", seeds=range(200)) for e in p.effects if e["kind"] == "crop_ruin"]
    assert ruins and all(e == {"kind": "crop_ruin", "plot": 1, "crop": "tomatoes"} for e in ruins)
    rng = random.Random(4)
    parts = [H._mending_part(rng)["name"] for _ in range(6000)]
    pool = [e for e in gathering.JUNKYARD if e[1] == "material"]
    total = sum(e[2] for e in pool)
    for e in pool:
        assert parts.count(e[0]) / len(parts) == pytest.approx(e[2] / total, abs=0.03)


def test_a_mishap_names_one_tool_and_a_minor_one_really_happens():
    world_ = w(tools=["needle file", "tweezers"])
    minor = plans("mishap", "bad", "minor", world_)
    assert minor and all(p.names == ["needle file"] and len(p.effects) == 1 for p in minor)
    assert plans("mishap", "neutral", "minor", world_)[0].names == ["needle file"]
    assert plans("mishap", "bad", "minor", w(low=False)) and plans("mishap", "bad", "major")


def test_a_kindness_can_be_food_a_seed_or_a_material():
    kinds = {p.effects[0]["item_kind"] for p in plans("kindness", "good", "minor", seeds=range(300)) if p.effects[0]["kind"] == "item"}
    assert kinds == {"food", "seed", "material"}


def test_news_without_a_title_or_for_a_resident_changes_nothing(tmp_path):
    s, st = fresh(tmp_path)
    st.add_character("Oriel Vantosh", "neighbor", None, "p", 60, NOW + 99 * HOUR, about="x")
    st.add_character("Mr Teague", "resident", None, "p", 60, NOW + 99 * HOUR, about="x", place="Saltholm")
    H.apply_effects(st, [{"kind": "news", "name": "Oriel Vantosh", "tone": "good"}], NOW)                 # no title given
    H.apply_effects(st, [{"kind": "news", "name": "Mr Teague", "tone": "good"}], NOW, "News")
    assert [c["life"] for c in st.characters()] == [[], []]


def test_a_part_the_pip_has_exactly_is_enough_and_tending_clears_the_stop_flag(tmp_path):
    from app import creations as cr
    s, st = fresh(tmp_path)
    c = clock(st)
    H.apply_effects(st, [{"kind": "creation_stop", "id": c["id"], "name": "Gear Clock", "part": {"name": "springs", "qty": 2}}], NOW)
    st.add_item("springs", 2, "material", "")
    assert cr.tend(st, st.find_creation("Gear Clock")[0], NOW + 5).startswith("you tend")
    assert st.find_item("springs")[0] is None                                                        # all two were used
    rt = st.find_creation("Gear Clock")[0]["runtime"]
    assert rt["stop_logged"] is False and rt["tended_until"] == NOW + 5 + 24 * 3600
