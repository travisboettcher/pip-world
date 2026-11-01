"""Boundaries, exact wording and time plumbing of the emotion rules (what the owner reads in the log and UI)."""
from datetime import datetime, timedelta

import pytest

from app import emotions as emo
from tests.test_projects import make

H = 3600.0
T = datetime(2026, 11, 3, 15, 0).timestamp()


def fresh(tmp_path, **kw):
    s, st, gm, agent = make(tmp_path, emotions="on", **kw)
    return s, st


def causes(st):
    return {(r["emotion"], r["cause"]) for r in st.emotion_log()}


def test_decay_starts_at_once():
    assert emo.decayed(80, 20, 60, 1) == pytest.approx(20 + 60 * 0.5 ** (1 / 60))
    assert emo.decayed(80, 20, 60, 1) < 80


def test_the_high_band_is_entered_at_exactly_60_and_not_left_and_reentered(tmp_path):
    s, st = fresh(tmp_path)
    emo.nudge(st, {"fear": 50}, "build up", T)                           # fear 60 exactly: that is entering the band
    assert [e["data"]["value"] for e in st.events(10) if e["kind"] == "emotion"] == [60]
    emo.nudge(st, {"fear": 5}, "more", T)                                # 60 -> 65: already high
    assert len([e for e in st.events(10) if e["kind"] == "emotion"]) == 1
    emo.nudge(st, {"anger": 51}, "just under", T)                        # anger 59: not yet
    assert len([e for e in st.events(10) if e["kind"] == "emotion"]) == 1


def test_causes_read_naturally(tmp_path):
    s, st = fresh(tmp_path)
    for kind, data in (("gift", {"sender": "Morgan"}), ("inbox", {"sender": "Briar"}), ("work", {"result": "setback", "surprise": "worse"}),
                       ("experiment", {"outcome": "clue"}), ("creation_made", {"name": "Gear Clock"}), ("garden", {"crop": "tomato"}),
                       ("alert", {"stat": "hunger"}), ("tool", {"tool": "plant", "result": "error: no plot"}),
                       ("outreach", {"what": "postcard", "delivered": True})):
        emo.appraise(st, s, kind, data, T)
    got = {c for _, c in causes(st)}
    assert got == {"Morgan gave a gift", "Briar wrote", "work went setback, worse than expected", "an experiment: clue",
                   "finished Gear Clock", "tomato ripened", "hunger needs attention", "plant failed", "a postcard went out"}


def test_causes_when_the_event_is_missing_details(tmp_path):
    s, st = fresh(tmp_path)
    for kind in ("gift", "inbox", "creation_made", "garden"):
        emo.appraise(st, s, kind, {}, T)
    assert {c for _, c in causes(st)} == {"someone gave a gift", "someone wrote", "finished something", "a crop ripened"}


def test_work_without_a_surprise_has_no_direction_in_its_cause(tmp_path):
    s, st = fresh(tmp_path)
    emo.appraise(st, s, "work", {"result": "good"}, T)
    assert {c for _, c in causes(st)} == {"work went good"}


def test_unknown_results_move_nothing(tmp_path):
    s, st = fresh(tmp_path)
    for kind, data in (("work", {"result": "???"}), ("experiment", {"outcome": "???"}), ("alert", {"stat": "boredom"})):
        emo.appraise(st, s, kind, data, T)
    assert st.emotion_log() == []


def test_the_given_time_is_used_throughout(tmp_path):
    s, st = fresh(tmp_path)
    emo.appraise(st, s, "gift", {"sender": "Morgan"}, T)
    assert {r["ts"] for r in st.emotion_log()} == {T}
    emo.appraise(st, s, "woke", {}, T + 10 * H)
    woke = [r for r in st.emotion_log() if r["cause"] == "a night's sleep"]
    assert woke and {r["ts"] for r in woke} == {T + 10 * H}


def test_ease_uses_the_given_time_and_cause(tmp_path):
    s, st = fresh(tmp_path)
    emo.nudge(st, {"anger": 60}, "x", T)                                 # anger 68 at T
    lv = emo.ease(st, 0.5, "rest", T + 180 * 60)                         # one half-life later it is 38; easing halves that gap
    assert lv["anger"] == pytest.approx(8 + (38 - 8) * 0.5)
    last = [r for r in st.emotion_log() if r["cause"] == "rest"]
    assert last and all(r["ts"] == T + 180 * 60 for r in last)


def test_readout_shows_exactly_ten_points_from_usual_and_no_filler_without_a_blend(tmp_path):
    s, st = fresh(tmp_path)
    emo.nudge(st, {"sadness": 10}, "x", T)
    assert emo.readout(st, T) == ["Emotion state (0-100): sadness 25 (+10).", "Overall: pleasant, calm."]
    emo.nudge(st, {"sadness": -1}, "x", T)                               # 9 points: no longer worth showing
    assert emo.readout(st, T) == ["Emotion state: close to your usual self (pleasant, calm)."]


def test_readouts_use_the_time_they_are_asked_for(tmp_path):
    s, st = fresh(tmp_path)
    emo.nudge(st, {"joy": 30}, "x", T)                                   # joy 75
    assert emo.readout(st, T)[0].startswith("Emotion state (0-100): joy 75 (+30)")
    assert emo.readout(st, T + 360 * 60)[0] == "Emotion state (0-100): joy 60 (+15)."   # a half-life on
    assert emo.perception(st, s, T)[0].startswith("Emotion state (0-100): joy 75")
    assert emo.perception(st, s, T + 360 * 60) == emo.readout(st, T + 360 * 60)
    assert emo.snapshot(st, T + 360 * 60)["emotions"][0]["value"] == 60


def test_blend_needs_eight_points_and_ties_go_to_the_first_pair():
    base = {k: float(v) for k, v in emo.BASELINE.items()}
    assert emo.blend({**base, "joy": 52, "trust": 62}) is None           # 7 points each: not enough
    assert emo.blend({**base, "joy": 53, "trust": 63}) == "warmth"       # exactly 8 each: enough
    tie = {**base, "joy": 60, "trust": 70, "anticipation": 50}           # warmth and optimism both 15
    assert emo.blend(tie) == "warmth"


def test_loneliness_edges_and_wording(tmp_path):
    s, st = fresh(tmp_path)
    st.set_meta(born_at=T - 8 * H)
    emo.drift(st, s, T)                                                  # exactly eight hours alone counts
    assert causes(st) == {("sadness", "alone for about 8 hours"), ("trust", "alone for about 8 hours")}
    assert {r["ts"] for r in st.emotion_log()} == {T}
    emo.drift(st, s, T + H - 1)
    assert len(st.emotion_log()) == 2                                    # not again within the hour
    emo.drift(st, s, T + H)                                              # exactly an hour later counts
    assert len(st.emotion_log()) == 4 and st.meta("emotion_drift_ts") == str(T + H)


def test_just_under_eight_hours_alone_is_fine(tmp_path):
    s, st = fresh(tmp_path)
    st.set_meta(born_at=T - 8 * H + 1)
    emo.drift(st, s, T)
    assert st.emotion_log() == [] and st.meta("emotion_drift_ts") is None


def test_hours_are_counted_not_rounded(tmp_path):
    s, st = fresh(tmp_path)
    st.set_meta(born_at=T - 20 * H)
    emo.drift(st, s, T)
    assert ("sadness", "alone for about 20 hours") in causes(st)


def test_loneliness_is_off_when_emotions_are_off(tmp_path):
    s, st = fresh(tmp_path)
    s.emotions = "off"
    st.set_meta(born_at=T - 20 * H)
    emo.drift(st, s, T)
    assert st.emotion_log() == []


def test_attach_listens_once_and_never_when_off(tmp_path):
    s, st, gm, agent = make(tmp_path, emotions="on")
    assert len(st.listeners) == 1
    (tmp_path / "off").mkdir()
    s2, st2, gm2, agent2 = make(tmp_path / "off", emotions="off")
    assert st2.listeners == []


def test_settle_records_exactly_what_happened(tmp_path):
    s, st = fresh(tmp_path)
    emo.nudge(st, {"anger": 60}, "x", T)
    ok, text = emo.settle(st, s, "  ANGER ", "tea", T)
    assert ok and text == "You take a quiet moment. Anger eases from 68 to 33."
    row = [r for r in st.emotion_log() if r["cause"].startswith("settled")][0]
    assert row["cause"] == "settled: tea" and row["delta"] == pytest.approx(-35) and row["ts"] == T and row["value"] == pytest.approx(33)
    assert emo.levels(st, T)["anger"] == pytest.approx(33)
    ok, _ = emo.settle(st, s, "anger", "", T)                            # 33 is 25 over usual: allowed; no 'how'
    assert [r["cause"] for r in st.emotion_log() if r["cause"].startswith("settled")][-1] == "settled"


def test_settle_refusals_have_exact_words(tmp_path):
    s, st = fresh(tmp_path, emotion_settle_per_day=1)
    assert emo.settle(st, s, "bogus", "", T) == (False, "you can settle one of: " + ", ".join(emo.NAMES))
    assert emo.settle(st, s, "", "", T)[0] is False
    assert emo.settle(st, s, "joy", "", T) == (False, "you're already settled: joy is near its usual level")
    emo.nudge(st, {"anger": 5}, "x", T)                                  # exactly the minimum excess to settle
    ok, text = emo.settle(st, s, "anger", "", T)
    assert ok and emo.levels(st, T)["anger"] == pytest.approx(8)         # never below usual


def test_the_cap_message(tmp_path):
    s, st = fresh(tmp_path, emotion_settle_per_day=1)
    emo.nudge(st, {"anger": 60}, "x")
    assert emo.settle(st, s, "anger")[0]
    emo.nudge(st, {"anger": 60}, "x")
    assert emo.settle(st, s, "anger") == (False, "you've taken enough quiet moments today; it will ease on its own")


def test_four_below_the_minimum_is_not_worth_settling(tmp_path):
    s, st = fresh(tmp_path)
    emo.nudge(st, {"anger": 4}, "x", T)
    assert emo.settle(st, s, "anger", "", T)[0] is False


def test_the_daily_cap_resets_at_midnight(tmp_path):
    s, st = fresh(tmp_path, emotion_settle_per_day=1)
    emo.nudge(st, {"anger": 60}, "x")
    assert emo.settle(st, s, "anger")[0]
    emo.nudge(st, {"anger": 60}, "x")
    assert not emo.settle(st, s, "anger")[0]
    tomorrow = (datetime.now().replace(hour=0, minute=1, second=0, microsecond=0) + timedelta(days=1)).timestamp()  # not +86400s: a DST day is 25h
    emo.nudge(st, {"anger": 60}, "x", tomorrow)                           # the first nudge has decayed by then, whatever the hour
    assert emo.settle(st, s, "anger", "", tomorrow)[0]                   # a new day, a new allowance


def test_today_is_local_midnight():
    assert emo._today(datetime(2026, 11, 3, 23, 59, 59).timestamp()) == datetime(2026, 11, 3).timestamp()
    assert emo._today(datetime(2026, 11, 3, 0, 0, 0).timestamp()) == datetime(2026, 11, 3).timestamp()
    assert emo._today(datetime(2026, 11, 3, 12, 30, 15, 500).timestamp()) == datetime(2026, 11, 3).timestamp()


def test_settle_event_text(tmp_path):
    s, st = fresh(tmp_path)
    emo.nudge(st, {"fear": 40}, "x")
    emo.settle(st, s, "fear", "a" * 300)
    (ev,) = [e["data"] for e in st.events(5) if e["kind"] == "settled"]
    assert len(ev["how"]) == 120 and ev["emotion"] == "fear"


def test_the_event_kinds_the_listener_skips_do_not_loop(tmp_path):
    s, st = fresh(tmp_path)
    emo.nudge(st, {"fear": 55}, "scare")                                 # logs an 'emotion' event
    st.log("settled", emotion="fear", **{"from": 65, "to": 30}, how="")
    assert len(st.emotion_log()) == 1                                    # neither event appraised anything


def test_settle_reads_the_level_at_the_time_it_is_given(tmp_path):
    s, st = fresh(tmp_path)
    past = datetime.now().timestamp() - 6 * H
    emo.nudge(st, {"anger": 60}, "x", past)                              # 68 then; by now it would have faded to 23
    ok, text = emo.settle(st, s, "anger", "", past)
    assert ok and text == "You take a quiet moment. Anger eases from 68 to 33."


def test_settling_without_saying_how_records_no_how(tmp_path):
    s, st = fresh(tmp_path)
    emo.nudge(st, {"anger": 60}, "x")
    emo.settle(st, s, "anger")
    (ev,) = [e["data"] for e in st.events(5) if e["kind"] == "settled"]
    assert ev["how"] == ""
