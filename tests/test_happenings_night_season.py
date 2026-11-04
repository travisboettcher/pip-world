"""Night happenings (rolled when Pip wakes, told as something that happened while it slept) and the seasonal layer (what is likelier when)."""
import asyncio
import random
import time
from datetime import datetime

import pytest

from app import gathering
from app import happenings as H
from app.config import Settings
from tests.test_happenings import (HOUR, NOW, STORY, StubGM, at, fresh, force, plans, run, settings, share, w)


def when(month, day=15, hour=12):
    return time.mktime((2026, month, day, hour, 0, 0, 0, 0, -1))


# --- the seasons ------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("month, season", [(12, "winter"), (1, "winter"), (2, "winter"), (3, "spring"), (4, "spring"), (5, "spring"),
                                           (6, "summer"), (7, "summer"), (8, "summer"), (9, "autumn"), (10, "autumn"), (11, "autumn")])
def test_the_season_follows_the_month_in_the_northern_hemisphere(month, season):
    assert H.season_of(when(month), "north") == season


@pytest.mark.parametrize("month, season", [(12, "summer"), (3, "autumn"), (6, "winter"), (9, "spring"), (1, "summer"), (7, "winter"), (5, "autumn"), (11, "spring")])
def test_and_is_turned_round_in_the_southern_one(month, season):
    assert H.season_of(when(month), "south") == season


def test_the_northern_hemisphere_is_the_default():
    assert H.season_of(when(1)) == "winter" and H.season_of(when(7)) == "summer"


def test_the_edges_of_a_season_are_the_first_and_last_of_the_month():
    assert H.season_of(when(2, 28, 23), "north") == "winter" and H.season_of(when(3, 1, 0), "north") == "spring"
    assert H.season_of(when(11, 30, 23), "north") == "autumn" and H.season_of(when(12, 1, 0), "north") == "winter"


def test_every_season_has_positive_weights_for_known_categories_only():
    assert set(H.SEASON_CATEGORY) == set(H.SEASON_TONE) == {"winter", "spring", "summer", "autumn"}
    for table in H.SEASON_CATEGORY.values():
        assert set(table) <= set(H.CATEGORIES) and all(v > 0 for v in table.values())
    for table in H.SEASON_TONE.values():
        assert all(cat in H.CATEGORIES and tone in H.CATEGORIES[cat].tones and v > 0 for (cat, tone), v in table.items())


def test_the_world_carries_the_season(tmp_path):
    s, st = fresh(tmp_path)
    assert H.world(st, s, when(1))["season"] == "winter"
    assert H.world(st, s, when(7))["season"] == "summer"
    assert H.world(st, settings(hemisphere="south", db_path=s.db_path), when(1))["season"] == "summer"


def test_the_seasons_can_be_turned_off(tmp_path):
    s, st = fresh(tmp_path, happenings_seasons=False)
    assert H.world(st, s, when(1))["season"] is None
    assert H.category_weight(None, "garden") == 1 and H.tone_factor(None, "garden", "bad") == 1


def test_a_season_weighs_what_is_likelier():
    assert H.category_weight("winter", "garden") == 0.5 and H.category_weight("spring", "garden") == 1.5
    assert H.category_weight("winter", "market") == 1 and H.category_weight("nonsense", "garden") == 1
    assert H.tone_factor("winter", "body", "bad") == 1.5 and H.tone_factor("winter", "body", "neutral") == 1
    assert H.tone_factor("summer", "pantry", "bad") == 1.4 and H.tone_factor("nonsense", "body", "bad") == 1


def test_the_season_shapes_which_category_comes_up(tmp_path):
    s, st = fresh(tmp_path)
    def share_of(season, cat):
        draws = [H.build(st, s, w(season=season), NOW, random.Random(i))["category"] for i in range(4000)]
        return draws.count(cat) / len(draws)
    assert share_of("spring", "garden") > share_of("winter", "garden") * 2.2                    # 1.5 against 0.5, a little diluted
    assert share_of("autumn", "memory") > share_of("summer", "memory") * 1.3
    assert share_of("summer", "pantry") > share_of("winter", "pantry") * 0.9


def test_the_season_shapes_the_tone(tmp_path):
    s, st = fresh(tmp_path)
    def bad_body(season):
        pool = [c for c in (H.build(st, s, w(season=season), NOW, random.Random(i)) for i in range(8000)) if c["category"] == "body"]
        return sum(c["tone"] == "bad" for c in pool) / len(pool)
    assert bad_body("winter") > bad_body("summer") * 1.2


def test_pick_tone_takes_factors_and_the_pity_still_applies():
    rng = random.Random(8)
    got = share([H.pick_tone(rng, ("good", "bad", "neutral"), [], {"bad": 2.0}) for _ in range(20000)])
    assert got["bad"] == pytest.approx(50 / (35 + 50 + 40), abs=0.02)
    both = share([H.pick_tone(rng, ("good", "bad", "neutral"), ["bad", "bad"], {"bad": 2.0}) for _ in range(20000)])
    assert both["bad"] == pytest.approx(25 * 2 * 0.3 / (35 + 15 + 40), abs=0.02)
    assert share([H.pick_tone(rng, ("good", "bad"), [], {"neutral": 9}) for _ in range(500)]) .keys() == {"good", "bad"}


@pytest.mark.asyncio
async def test_the_author_is_told_the_season():
    from app.llm.base import LLMResponse, ToolCall, Usage
    from tests.test_gm_prompts import master, task
    gm, b, _ = master(Path_for(), LLMResponse("", [ToolCall("1", "report", {"title": "T", "text": "x"})], Usage(1, 1)))
    await gm.write_happening("garden", "good", "minor", "joy", "", {"period": "morning", "season": "autumn", "names": []}, [])
    assert "It is morning in autumn. Names you may use: none." in task(b)


def Path_for():
    import tempfile
    from pathlib import Path
    return Path(tempfile.mkdtemp())


@pytest.mark.asyncio
async def test_a_prompt_without_a_season_is_as_before():
    from app.llm.base import LLMResponse, ToolCall, Usage
    from tests.test_gm_prompts import master, task
    gm, b, _ = master(Path_for(), LLMResponse("", [ToolCall("1", "report", {"title": "T", "text": "x"})], Usage(1, 1)))
    await gm.write_happening("garden", "good", "minor", "joy", "", {"period": "morning", "names": []}, [])
    assert "It is morning. Names you may use: none." in task(b)


def test_create_gives_the_author_the_season(tmp_path, monkeypatch):
    s, st = fresh(tmp_path)
    force(monkeypatch)
    gm = StubGM(STORY)
    run(H.create(st, s, gm, w(season="winter"), NOW, "x", random.Random(1)))
    assert gm.calls[0][5]["season"] == "winter" and "night" not in gm.calls[0][5]
    gm = StubGM(STORY)
    run(H.create(st, s, gm, w(season=None), NOW, "y", random.Random(1)))
    assert "season" not in gm.calls[0][5] or gm.calls[0][5]["season"] is None


# --- night happenings --------------------------------------------------------------------------------------------
def slept(st, hours=8.0, woke_at=None, early=False):
    """Pip went to bed and woke: the `woke` event the engine logs, and the agent awake again."""
    woke_at = woke_at or at(6, 0)
    st.update_agent(activity="idle")
    eid = st.log("woke", hours=hours, early=early)
    st.db.execute("UPDATE events SET ts = ? WHERE id = ?", (woke_at, eid))
    st.db.commit()
    return eid


def night(tmp_path, **kw):
    kw.setdefault("happenings_chance", 1.0)
    return fresh(tmp_path, **kw)


def stepped(s, st, gm, now):
    return run(H.step(st, s, gm, now))


def test_a_night_of_sleep_rolls_once_per_slot_slept_and_may_make_a_happening(tmp_path):
    s, st = night(tmp_path)
    eid = slept(st, 8.0)
    assert stepped(s, st, StubGM(STORY), at(6, 1)) is True
    (row,) = st.happenings()
    assert row["slot"] == f"night:{eid}#0" and row["status"] == "applied" and row["context"]["night"] is True and row["author"] == "gm"
    assert row["ts"] == at(6, 1)
    assert [st.happening_roll(f"night:{eid}#{k}") is not None for k in range(3)] == [True, True, False]      # 8 hours: two slots of three
    h = H.replay(st, s, row)
    assert h["matches"] is True and h["seed"] == f"{st.meta('happenings_salt')}:night:{eid}#0"


def test_each_sleep_is_rolled_only_once(tmp_path):
    s, st = night(tmp_path, happenings_chance=0.0)
    eid = slept(st, 8.0)
    assert stepped(s, st, StubGM(STORY), at(6, 1)) is False and st.happenings() == []
    assert [st.happening_roll(f"night:{eid}#{k}")["hit"] for k in range(2)] == [0, 0]
    s.happenings_chance = 1.0
    assert stepped(s, st, StubGM(STORY), at(6, 2)) is False and st.happenings() == []               # that sleep has been rolled
    slept(st, 8.0, woke_at=at(6, 3))
    assert stepped(s, st, StubGM(STORY), at(6, 4)) is True                                          # the next one is new


@pytest.mark.parametrize("hours, rolls", [(2.9, 0), (3.0, 1), (5.9, 1), (6.0, 2), (8.0, 2), (9.0, 3), (12.4, 4)])
def test_the_number_of_rolls_is_the_slots_slept(tmp_path, hours, rolls):
    s, st = night(tmp_path, happenings_chance=0.0)
    eid = slept(st, hours)
    stepped(s, st, StubGM(STORY), at(6, 1))
    assert sum(st.happening_roll(f"night:{eid}#{k}") is not None for k in range(6)) == rolls


def test_a_sleep_too_short_for_a_slot_rolls_nothing_but_is_not_rolled_later(tmp_path):
    s, st = night(tmp_path)
    slept(st, 1.5)
    assert stepped(s, st, StubGM(STORY), at(7, 0)) is False and st.happenings() == []
    assert st.meta("happenings_night") is not None


def test_nothing_is_rolled_while_pip_is_still_asleep(tmp_path):
    s, st = night(tmp_path)
    eid = slept(st, 8.0)
    st.update_agent(activity="sleeping")
    assert stepped(s, st, StubGM(STORY), at(6, 1)) is False and st.happening_roll(f"night:{eid}#0") is None
    st.update_agent(activity="idle")
    assert stepped(s, st, StubGM(STORY), at(6, 2)) is True


def test_a_sleep_woken_from_long_ago_is_not_rolled(tmp_path):
    s, st = night(tmp_path)
    eid = slept(st, 8.0, woke_at=at(6, 0))
    assert stepped(s, st, StubGM(STORY), at(8, 1)) is False and st.happening_roll(f"night:{eid}#0") is None    # the service was down: too late
    assert st.happenings() == []
    eid2 = slept(st, 8.0, woke_at=at(9, 0))
    assert stepped(s, st, StubGM(STORY), at(10, 59)) is True                                                 # under two hours is still in time


def test_an_unread_happening_or_a_full_day_holds_the_night_back(tmp_path):
    from tests.test_happenings import waiting
    s, st = night(tmp_path)
    waiting(st, ts=at(5, 0))
    eid = slept(st, 8.0)
    assert stepped(s, st, StubGM(STORY), at(6, 1)) is False and st.happening_roll(f"night:{eid}#0") is None
    assert len(st.happenings()) == 1
    (tmp_path / "b").mkdir()
    s2, st2 = night(tmp_path / "b", happenings_max_per_day=1)
    st2.add_happening(ts=at(0, 5), slot="x", category="body", tone="good", severity="minor", lens="joy", seed="s", status="resolved")
    slept(st2, 8.0)
    assert stepped(s2, st2, StubGM(STORY), at(6, 1)) is False and len(st2.happenings()) == 1


def test_night_mode_off_or_log(tmp_path):
    s, st = night(tmp_path, happenings="off")
    eid = slept(st, 8.0)
    assert stepped(s, st, StubGM(STORY), at(6, 1)) is False and st.happening_roll(f"night:{eid}#0") is None and st.happenings() == []
    (tmp_path / "b").mkdir()
    s2, st2 = night(tmp_path / "b", happenings="log")
    slept(st2, 8.0)
    assert stepped(s2, st2, StubGM(STORY), at(6, 1)) is True and st2.happenings()[0]["status"] == "logged" and st2.coins() == 10


def test_a_night_happening_is_told_as_something_that_happened_while_pip_slept(tmp_path):
    s, st = night(tmp_path)
    slept(st, 8.0)
    gm = StubGM(STORY)
    stepped(s, st, gm, at(6, 1))
    facts = gm.calls[0][5]
    assert facts["night"] is True and facts["period"] == "morning"


@pytest.mark.asyncio
async def test_the_author_is_told_it_happened_in_the_night():
    from app.llm.base import LLMResponse, ToolCall, Usage
    from tests.test_gm_prompts import master, task
    gm, b, _ = master(Path_for(), LLMResponse("", [ToolCall("1", "report", {"title": "T", "text": "x"})], Usage(1, 1)))
    await gm.write_happening("pantry", "bad", "minor", "joy", "", {"period": "morning", "names": [], "night": True}, [])
    p = task(b)
    assert "It happened in the night, while Pip slept, and Pip finds out on waking: tell it in the past tense.\n" in p
    gm2, b2, _ = master(Path_for(), LLMResponse("", [ToolCall("1", "report", {"title": "T", "text": "x"})], Usage(1, 1)))
    await gm2.write_happening("pantry", "bad", "minor", "joy", "", {"period": "morning", "names": []}, [])
    assert "in the night" not in task(b2)


def test_only_what_could_happen_in_the_night_is_chosen(tmp_path):
    s, st = fresh(tmp_path)
    assert {c.name for c in H.CATEGORIES.values() if not c.night} == {"market", "neighbor"}
    seen = {H.build(st, s, w(), NOW, random.Random(i), night=True)["category"] for i in range(800)}
    assert seen == set(H.CATEGORIES) - {"market", "neighbor"}
    by_day = {H.build(st, s, w(), NOW, random.Random(i))["category"] for i in range(800)}
    assert {"market", "neighbor"} <= by_day


def test_a_night_with_nothing_possible_makes_nothing(tmp_path, monkeypatch):
    s, st = night(tmp_path)
    slept(st, 8.0)
    monkeypatch.setattr(H, "build", lambda *a, **k: None)
    assert stepped(s, st, StubGM(STORY), at(6, 1)) is False and st.happenings() == []


def test_night_dice_use_the_salt_and_the_sleep(tmp_path):
    import hashlib
    s, st = night(tmp_path)
    st.set_meta(happenings_salt="fixed")
    eid = slept(st, 8.0)
    seen = {}

    async def spy(state, settings, gm, w_, now, slot, rng, night=False):
        if not seen:                                                                          # the night comes first; the morning slot may follow
            seen.update(slot=slot, night=night, state=rng.getstate())
        return None
    import app.happenings as mod
    orig = mod.create
    mod.create = spy
    try:
        stepped(s, st, None, at(6, 1))
    finally:
        mod.create = orig
    assert seen["night"] is True and seen["slot"] == f"night:{eid}#0"
    assert seen["state"] == random.Random(hashlib.sha256(f"fixed:night:{eid}#0:build".encode()).hexdigest()).getstate()


def test_the_normal_slot_roll_still_works_after_a_night_one(tmp_path):
    s, st = night(tmp_path)
    slept(st, 8.0)
    assert stepped(s, st, StubGM(STORY), at(6, 1)) is True
    for h in H.unresolved(st):
        H.resolve(st, h, "joy")
    assert stepped(s, st, StubGM(STORY), at(9, 5)) is True and st.happenings()[0]["slot"] == "2026-03-05#1"


def test_the_environment_settings(monkeypatch):
    assert Settings().happenings_seasons is True and Settings().hemisphere == "north"
    for k in ("HAPPENINGS_SEASONS", "HEMISPHERE"):
        monkeypatch.delenv(k, raising=False)
    s = Settings.from_env()
    assert s.happenings_seasons is True and s.hemisphere == "north"
    monkeypatch.setenv("HAPPENINGS_SEASONS", "off")
    monkeypatch.setenv("HEMISPHERE", "South")
    s = Settings.from_env()
    assert s.happenings_seasons is False and s.hemisphere == "south"
    monkeypatch.setenv("HAPPENINGS_SEASONS", "maybe")
    monkeypatch.setenv("HEMISPHERE", "sideways")
    s = Settings.from_env()
    assert s.happenings_seasons is True and s.hemisphere == "north"


def test_a_second_look_after_a_night_happening_does_not_make_another(tmp_path):
    s, st = night(tmp_path)
    slept(st, 8.0)
    assert stepped(s, st, StubGM(STORY, STORY), at(6, 1)) is True
    for h in H.unresolved(st):
        H.resolve(st, h, "joy")
    assert stepped(s, st, StubGM(STORY, STORY), at(7, 0)) is False and len(st.happenings()) == 1       # the night was done; the 6 o'clock slot has closed


def test_the_two_hours_after_waking_are_inclusive(tmp_path):
    s, st = night(tmp_path)
    slept(st, 8.0, woke_at=at(6, 0))
    assert stepped(s, st, StubGM(STORY), at(8, 0)) is True                                       # exactly two hours is still in time
    (tmp_path / "b").mkdir()
    s2, st2 = night(tmp_path / "b")
    slept(st2, 8.0, woke_at=at(6, 0))
    assert stepped(s2, st2, StubGM(STORY), at(8, 0) + 0.5) is False                              # half a second over is not


def test_a_night_counts_the_days_happenings_like_the_slots_do(tmp_path):
    s, st = night(tmp_path, happenings_max_per_day=2)
    st.add_happening(ts=at(0, 5), slot="x", category="body", tone="good", severity="minor", lens="joy", seed="s", status="resolved")
    slept(st, 8.0)
    assert stepped(s, st, StubGM(STORY), at(6, 1)) is True                                       # one so far, two allowed
    assert st.happenings()[0]["slot"].startswith("night:")                                       # and it was the night's, not the 6 o'clock slot
    (tmp_path / "b").mkdir()
    s2, st2 = night(tmp_path / "b", happenings_max_per_day=1)
    st2.add_happening(ts=at(0, 0), slot="x", category="body", tone="good", severity="minor", lens="joy", seed="s", status="resolved")
    slept(st2, 8.0)
    assert stepped(s2, st2, StubGM(STORY), at(7, 0)) is False                                    # a happening at midnight sharp is today's


def test_the_night_asks_for_night_categories_and_a_day_happening_is_not_marked_night(tmp_path, monkeypatch):
    s, st = night(tmp_path)
    calls = []
    real = H.build

    def spy(state, settings, w_, now, rng, night=False):
        calls.append(night)
        return real(state, settings, w_, now, rng, night)
    monkeypatch.setattr(H, "build", spy)
    slept(st, 8.0)
    stepped(s, st, StubGM(STORY), at(6, 1))
    assert calls == [True] and st.happenings()[0]["context"]["night"] is True
    (tmp_path / "b").mkdir()
    s2, st2 = night(tmp_path / "b")
    stepped(s2, st2, StubGM(STORY), at(12, 5))
    assert "night" not in st2.happenings()[0]["context"] and calls[-1] is False
