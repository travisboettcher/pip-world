"""The shipped `happenings` rule's own logic (module_library/happenings.py), tested directly: the slots, the choosing and what each kind of
happening changes. It is plain Python (the sandbox's rules), so it can be imported and its functions called with a context like the one the
engine builds. (Through the engine, with the real context: test_happenings_module.py.)"""
import importlib.util
import random
import time
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parent.parent / "app" / "module_library" / "happenings.py"


def rule_module():
    spec = importlib.util.spec_from_file_location("happenings_rule", SRC)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


R = rule_module()
NOW = time.mktime((2026, 3, 5, 12, 0, 0, 0, 0, -1))
PARAMS = {"chance": 1.0, "slot_hours": 3, "severity": [50, 45, 5], "seasons": True, "wake_hour": 6, "bedtime_hour": 22}


def ctx(**kw):
    """A context like the engine builds: a busy world with something for every category."""
    base = {"now": NOW, "params": dict(PARAMS), "state": {"salt": 7, "rolled": []},
            "time": {"hour": 12, "minute": 0, "weekday": "Thursday", "season": "spring"},
            "agent": {"asleep": False, "walking": False, "hunger": 0.2, "energy": 0.8, "coins": 78, "mood": "calm"},
            "garden": [{"plot": 1, "crop": "tomatoes", "state": "growing", "ready_in_min": 600}, {"plot": 2, "state": "empty"}],
            "items": [{"name": "tomatoes", "qty": 91, "kind": "food"}, {"name": "needle file", "qty": 1, "kind": "tool"}],
            "places": [{"key": "Saltholm", "label": "Saltholm", "kind": "shop"}, {"key": "woods", "label": "the woods", "kind": "wild"}],
            "people": [{"name": "Oriel Vantosh", "kind": "neighbor"}],
            "creations": [{"name": "Gear Clock", "running": True, "tended": True}],
            "happenings": {"recent": [], "today": 0, "room": "", "can_remember": True}}
    for k, v in kw.items():
        base[k] = {**base[k], **v} if isinstance(v, dict) and isinstance(base.get(k), dict) and k not in ("state",) else v
    return base


def plans(cat, tone, severity, c=None, seeds=range(80)):
    return [p for p in (R._plan(c or ctx(), cat, tone, severity, random.Random(i)) for i in seeds) if p is not None]


# --- the slots ---------------------------------------------------------------------------------------------------------------
def at(h, m=0, d=5):
    return time.mktime((2026, 3, d, h, m, 0, 0, 0, -1))


def slot_at(h, m=5, **params):
    t = at(h, m)
    return R._slots(ctx(now=t, time={"hour": h, "minute": m}, params={**PARAMS, **params}))


def test_the_awake_day_is_cut_into_slots_from_the_wake_hour():
    midnight = at(0)
    assert slot_at(6) == (f"{int(midnight)}#0", at(6)) and slot_at(8, 59) == (f"{int(midnight)}#0", at(6))
    assert slot_at(9) == (f"{int(midnight)}#1", at(9)) and slot_at(21, 30) == (f"{int(midnight)}#5", at(21))
    assert slot_at(9, slot_hours=2) == (f"{int(midnight)}#1", at(8))
    yesterday = at(0) - 86400                                                                   # before waking: yesterday's last slot
    assert slot_at(3) == (f"{int(yesterday)}#5", yesterday + 21 * 3600)
    late = slot_at(1, wake_hour=8, bedtime_hour=2)                                              # a day that runs past midnight
    assert late == (f"{int(yesterday)}#5", yesterday + (8 + 15) * 3600) and slot_at(3, wake_hour=8, bedtime_hour=2) == late


# --- choosing ----------------------------------------------------------------------------------------------------------------
def test_a_category_rests_twelve_hours_and_a_skipped_one_doesnt_count():
    recent = [{"category": c, "tone": "good", "severity": "minor", "ts": NOW - 3600, "status": "resolved"} for c in R.CATEGORIES if c != "found"]
    chosen = {R._choose(ctx(happenings={"recent": recent}), random.Random(i), False)["category"] for i in range(30)}
    assert chosen == {"found"}
    recent = [{**r, "ts": NOW - 13 * 3600} for r in recent]
    assert len({R._choose(ctx(happenings={"recent": recent}), random.Random(i), False)["category"] for i in range(200)}) > 5
    skipped = [{"category": c, "tone": "good", "severity": "minor", "ts": NOW, "status": "skipped"} for c in R.CATEGORIES]
    assert R._choose(ctx(happenings={"recent": skipped}), random.Random(1), False) is not None
    every = [{"category": c, "tone": "good", "severity": "minor", "ts": NOW, "status": "resolved"} for c in R.CATEGORIES]
    assert R._choose(ctx(happenings={"recent": every}), random.Random(1), False) is None


def test_two_bad_ones_in_a_row_make_a_third_less_likely():
    def bad_share(recent):
        picks = [R._choose(ctx(happenings={"recent": recent}), random.Random(i), False) for i in range(600)]
        return sum(p["tone"] == "bad" for p in picks if p) / len(picks)
    old = NOW - 13 * 3600
    two_bad = [{"category": "x", "tone": "bad", "severity": "minor", "ts": old, "status": "resolved"}] * 2
    one_bad = [two_bad[0], {**two_bad[0], "tone": "good"}]
    assert bad_share(two_bad) < bad_share(one_bad) * 0.6


def test_the_world_must_allow_a_category():
    bare = ctx(garden=[], places=[], people=[], creations=[], items=[], happenings={"can_remember": False})
    chosen = {R._choose(bare, random.Random(i), False)["category"] for i in range(300)}
    assert chosen <= {"creature", "pantry", "found", "body", "atmosphere"} and "garden" not in chosen
    assert not R._possible(bare, "garden") and not R._possible(bare, "market") and not R._possible(bare, "mishap")
    assert not R._possible(bare, "neighbor") and not R._possible(bare, "kindness") and not R._possible(bare, "memory")
    assert R._possible(ctx(), "mishap") and R._possible(ctx(creations=[], items=[{"name": "awl", "qty": 1, "kind": "tool"}]), "mishap")


def test_the_night_has_no_market_and_no_neighbors_news():
    night = {R._choose(ctx(), random.Random(i), True)["category"] for i in range(300)}
    assert not {"market", "neighbor"} & night and all(R._choose(ctx(), random.Random(i), True)["night"] for i in range(5))


def test_a_neutral_turn_is_minor_and_severity_follows_the_weights():
    picks = [R._choose(ctx(), random.Random(i), False) for i in range(400)]
    assert all(p["severity"] == "minor" for p in picks if p["tone"] == "neutral")
    assert all(p["severity"] == "major" for p in (R._choose(ctx(params={**PARAMS, "severity": [0, 0, 1]}), random.Random(i), False)
                                                   for i in range(50)) if p["tone"] != "neutral")


def test_every_category_and_tone_it_can_take_has_fallback_words():
    for cat, (tones, _) in R.CATEGORIES.items():
        for tone in tones:
            assert (cat, tone) in R.FALLBACK, (cat, tone)
    picks = [R._choose(ctx(), random.Random(i), False) for i in range(100)]
    assert all(p["fallback"] == {"title": R.FALLBACK[(p["category"], p["tone"])][0], "text": R.FALLBACK[(p["category"], p["tone"])][1]} for p in picks)


def test_the_seasons_lean_the_dice():
    def share(season, cat, seasons=True):
        c = ctx(time={"season": season}, params={**PARAMS, "seasons": seasons})
        return sum(R._choose(c, random.Random(i), False)["category"] == cat for i in range(800)) / 800
    assert share("spring", "garden") > share("winter", "garden") * 2
    assert abs(share("spring", "garden", False) - share("winter", "garden", False)) < 0.03


# --- what each kind of happening changes ---------------------------------------------------------------------------------------
def test_the_garden_shifts_a_crop_ruins_one_only_when_major_and_bad_and_spares_a_ripe_one():
    good = plans("garden", "good", "medium")
    assert {p["effects"][0]["how"] for p in good} == {"time", "yield"} and all(p["effects"][0]["plot"] == 1 for p in good)
    bad = plans("garden", "bad", "major")
    assert {p["effects"][0]["how"] for p in bad} == {"time", "ruin"}
    assert all(p["effects"][0]["how"] == "time" for p in plans("garden", "bad", "medium"))
    assert plans("garden", "neutral", "minor")[0] == {"names": ["tomatoes"]}
    ripe = ctx(garden=[{"plot": 1, "crop": "peas", "state": "growing", "ready_in_min": 10}])
    assert all(p["effects"][0]["how"] == "yield" for p in plans("garden", "good", "minor", ripe))      # 5% of 10 minutes: not worth it


def test_creatures_pantry_and_finds():
    assert {p["effects"][0]["kind"] for p in plans("creature", "good", "minor")} == {"item"}
    assert plans("creature", "bad", "minor")[0] == {"effects": [{"kind": "food_loss"}]}
    assert plans("creature", "bad", "minor", ctx(agent={"hunger": 0.85})) == []                              # a low Pip is spared
    assert plans("pantry", "bad", "minor", ctx(items=[{"name": "beans", "qty": 4, "kind": "food"}])) == []  # too small a stack
    assert plans("pantry", "neutral", "minor")[0] == {}
    assert {p["effects"][0]["kind"] for p in plans("found", "good", "minor")} == {"item", "coins"}
    assert plans("found", "bad", "minor")[0] == {"effects": [{"kind": "coins"}]}
    assert plans("found", "bad", "minor", ctx(agent={"coins": 9})) == []


def test_the_body_a_market_and_a_mishap():
    assert {p["effects"][0]["kind"] for p in plans("body", "good", "minor")} == {"energy", "hunger"}
    assert plans("body", "bad", "minor", ctx(agent={"energy": 0.2})) == []
    assert plans("market", "good", "minor")[0] == {"effects": [{"kind": "price", "place": "Saltholm", "item": "tomatoes"}]}
    assert plans("market", "neutral", "minor")[0] == {"names": ["Saltholm"]}
    assert plans("mishap", "neutral", "minor")[0] == {"names": ["needle file"]}
    assert plans("mishap", "bad", "minor")[0] == {"effects": [{"kind": "energy"}], "names": ["needle file"]}
    assert plans("mishap", "bad", "major")[0] == {"effects": [{"kind": "stop", "creation": "Gear Clock", "mend": True}]}
    assert plans("mishap", "bad", "medium")[0]["effects"][0]["mend"] is False
    assert plans("mishap", "bad", "major", ctx(creations=[{"name": "Gear Clock", "running": False, "tended": True}])) == []


def test_neighbors_memories_kindness_and_the_air():
    assert plans("neighbor", "good", "minor")[0] == {"effects": [{"kind": "news", "name": "Oriel Vantosh"}]}
    assert plans("neighbor", "neutral", "minor")[0] == {"names": ["Oriel Vantosh"]}
    assert plans("memory", "bad", "minor")[0] == {"effects": [{"kind": "memory"}]}
    kind = plans("kindness", "good", "medium")
    assert {p["effects"][0]["kind"] for p in kind} == {"item", "coins"} and all(p["effects"][0]["gift"] and p["names"] == ["Oriel Vantosh"] for p in kind)
    assert plans("atmosphere", "neutral", "minor")[0] == {}


# --- the tick ----------------------------------------------------------------------------------------------------------------
def test_the_tick_rolls_a_slot_once_in_its_first_half_hour_and_never_while_busy():
    c = ctx(now=at(12, 10), time={"hour": 12, "minute": 10})
    out = R.on_tick(c)
    assert out["happen"]["category"] in R.CATEGORIES and out["state"]["rolled"] == [f"{int(at(0))}#2"]
    assert "happen" not in R.on_tick({**c, "state": out["state"]})                                  # rolled
    late = ctx(now=at(12, 40), time={"hour": 12, "minute": 40})
    assert "happen" not in R.on_tick(late) and R.on_tick(late).get("state", {}).get("rolled", []) == []
    assert R.on_tick(ctx(now=at(12, 10), time={"hour": 12, "minute": 10}, agent={"walking": True})).get("happen") is None
    held = R.on_tick(ctx(now=at(12, 10), time={"hour": 12, "minute": 10}, happenings={"room": "Pip hasn't taken in the last one yet"}))
    assert "happen" not in held and held.get("state", {}).get("rolled", []) == []                    # the slot waits
    missed = R.on_tick(ctx(now=at(12, 10), time={"hour": 12, "minute": 10}, params={**PARAMS, "chance": 0.0}))
    assert "happen" not in missed and missed["state"]["rolled"] == [f"{int(at(0))}#2"]               # a miss is rolled too


def test_the_dice_follow_the_salt():
    def pick(salt):
        return R.on_tick(ctx(now=at(12, 10), time={"hour": 12, "minute": 10}, params={**PARAMS, "chance": 0.5}, state={"salt": salt, "rolled": []}))
    assert pick(3) == pick(3)
    assert len({str(pick(s).get("happen")) for s in range(20)}) > 3


def test_sleep_is_noted_and_the_night_is_rolled_on_waking():
    asleep = ctx(agent={"asleep": True})
    out = R.on_tick(asleep)
    assert out["state"]["slept_at"] == NOW and R.on_tick({**asleep, "state": out["state"]}) == {}
    woke = R.on_tick(ctx(now=NOW + 8 * 3600, time={"hour": 20, "minute": 0}, state={"salt": 1, "rolled": [], "slept_at": NOW}))
    assert woke["happen"]["night"] is True and "slept_at" not in woke["state"]
    nap = R.on_tick(ctx(now=NOW + 2 * 3600, time={"hour": 14, "minute": 40}, state={"salt": 1, "rolled": [], "slept_at": NOW}))
    assert "happen" not in nap
    assert R.on_install({"seed": 5})["state"]["rolled"] == [] and R.on_install({"seed": 5}) == R.on_install({"seed": 5})
