"""Emotion state: numbers the engine keeps, moved by events by fixed rules (DESIGN-emotions.md)."""
import time

import pytest

from app import emotions as emo
from tests.test_projects import call, make

HOUR = 3600.0


def fresh(tmp_path, **kw):
    s, st, gm, agent = make(tmp_path, emotions="on", **kw)
    return s, st, agent


# --- the pure rules --------------------------------------------------------------
def test_there_are_eight_emotions_with_baselines_and_half_lives():
    assert emo.NAMES == ("joy", "sadness", "anger", "fear", "trust", "disgust", "surprise", "anticipation")
    assert set(emo.BASELINE) == set(emo.HALF_LIFE_MIN) == set(emo.NAMES)
    assert emo.BASELINE["trust"] == 55 and emo.BASELINE["joy"] == 45
    assert emo.HALF_LIFE_MIN["surprise"] < emo.HALF_LIFE_MIN["anger"] < emo.HALF_LIFE_MIN["sadness"] < emo.HALF_LIFE_MIN["trust"]


def test_decay_halves_the_distance_from_baseline_each_half_life():
    assert emo.decayed(80, 20, 60, 0) == 80
    assert emo.decayed(80, 20, 60, 60) == pytest.approx(50)
    assert emo.decayed(80, 20, 60, 120) == pytest.approx(35)
    assert emo.decayed(0, 20, 60, 60) == pytest.approx(10)             # below baseline rises back
    assert emo.decayed(80, 20, 60, -5) == 80                          # the clock never runs backwards


def test_a_new_world_sits_at_baseline(tmp_path):
    s, st, agent = fresh(tmp_path)
    assert emo.levels(st) == {k: float(v) for k, v in emo.BASELINE.items()}


def test_nudge_moves_clamps_and_persists(tmp_path):
    s, st, agent = fresh(tmp_path)
    now = time.time()
    lv = emo.nudge(st, {"joy": 20, "sadness": -50, "anger": 500}, "test", now)
    assert lv["joy"] == pytest.approx(65) and lv["sadness"] == 0 and lv["anger"] == 100
    assert emo.levels(st, now)["joy"] == pytest.approx(65)
    assert emo.levels(st, now + 360 * 60)["joy"] == pytest.approx(55)   # one half-life later: halfway back to 45


def test_nudge_ignores_unknown_emotions_and_zero(tmp_path):
    s, st, agent = fresh(tmp_path)
    before = emo.levels(st)
    emo.nudge(st, {"bogus": 10, "joy": 0}, "test")
    assert emo.levels(st) == before and st.emotion_log() == []


def test_every_move_is_logged_with_its_cause(tmp_path):
    s, st, agent = fresh(tmp_path)
    now = time.time()
    emo.nudge(st, {"joy": 12, "trust": -3}, "a visitor wrote", now)
    rows = st.emotion_log()
    assert {(r["emotion"], r["delta"], r["cause"]) for r in rows} == {("joy", 12.0, "a visitor wrote"), ("trust", -3.0, "a visitor wrote")}
    assert all(r["ts"] == now for r in rows) and {r["emotion"]: r["value"] for r in rows}["joy"] == pytest.approx(57)


def test_entering_a_high_band_is_an_event_once(tmp_path):
    s, st, agent = fresh(tmp_path)
    emo.nudge(st, {"joy": 10}, "small")
    assert not [e for e in st.events(10) if e["kind"] == "emotion"]
    emo.nudge(st, {"fear": 55}, "the blow-up")
    (ev,) = [e["data"] for e in st.events(10) if e["kind"] == "emotion"]
    assert ev["emotion"] == "fear" and ev["value"] == pytest.approx(65) and ev["cause"] == "the blow-up"
    emo.nudge(st, {"fear": 5}, "still scared")                          # already high: no second event
    assert len([e for e in st.events(10) if e["kind"] == "emotion"]) == 1


def test_ease_pulls_everything_toward_baseline(tmp_path):
    s, st, agent = fresh(tmp_path)
    now = time.time()
    emo.nudge(st, {"anger": 50, "joy": -45}, "x", now)                 # anger 58, joy 0
    lv = emo.ease(st, 0.4, "slept", now)
    assert lv["anger"] == pytest.approx(58 - 0.4 * 50) and lv["joy"] == pytest.approx(0.4 * 45)


# --- derived readings ---------------------------------------------------------------
def test_valence_and_arousal_at_baseline_and_extremes():
    base = {k: float(v) for k, v in emo.BASELINE.items()}
    assert emo.valence(base) == round((45 + 55 + 35) / 3 - (15 + 8 + 10 + 5) / 4)
    assert emo.arousal(base) == round((8 + 10 + 10 + 35 + 45) / 5)
    glad = {**base, "joy": 100, "trust": 100, "anticipation": 100, "sadness": 0, "anger": 0, "fear": 0, "disgust": 0}
    assert emo.valence(glad) == 100
    grim = {**base, "joy": 0, "trust": 0, "anticipation": 0, "sadness": 100, "anger": 100, "fear": 100, "disgust": 100}
    assert emo.valence(grim) == -100


def test_blend_names_the_strongest_pair_above_baseline():
    base = {k: float(v) for k, v in emo.BASELINE.items()}
    assert emo.blend(base) is None                                       # nothing stands out
    assert emo.blend({**base, "joy": 70, "trust": 75}) == "warmth"
    assert emo.blend({**base, "fear": 50, "surprise": 45}) == "awe"
    assert emo.blend({**base, "anticipation": 60, "joy": 60}) == "optimism"
    assert emo.blend({**base, "sadness": 40, "disgust": 35}) == "remorse"
    assert emo.blend({**base, "joy": 70}) is None                        # one emotion alone is not a blend
    assert emo.blend({**base, "joy": 80, "trust": 90, "fear": 30, "surprise": 25}) == "warmth"   # strongest pair wins (35 over 20)
    assert emo.blend({**base, "joy": 60, "trust": 90, "fear": 30, "surprise": 25}) == "submission"   # trust+fear (20) beats joy+trust (15)


def test_snapshot_has_values_baselines_and_words(tmp_path):
    s, st, agent = fresh(tmp_path)
    snap = emo.snapshot(st)
    assert [e["name"] for e in snap["emotions"]] == list(emo.NAMES)
    assert snap["emotions"][0] == {"name": "joy", "value": 45, "baseline": 45}
    assert snap["valence"] == emo.valence(emo.levels(st)) and snap["arousal"] == emo.arousal(emo.levels(st))
    assert snap["valence_word"] == "pleasant" and snap["arousal_word"] == "calm" and snap["blend"] is None


def test_words_for_valence_and_arousal():
    assert [emo.valence_word(v) for v in (80, 55, 54, 25, 24, 0, -1, -25, -26)] == [
        "very good", "very good", "pleasant", "pleasant", "neutral", "neutral", "unpleasant", "unpleasant", "bad"]
    assert [emo.arousal_word(a) for a in (0, 14, 15, 29, 30, 49, 50, 90)] == [
        "very calm", "very calm", "calm", "calm", "stirred up", "stirred up", "highly activated", "highly activated"]


# --- what Pip is shown --------------------------------------------------------------
def test_readout_is_quiet_when_nothing_stands_out(tmp_path):
    s, st, agent = fresh(tmp_path)
    assert emo.readout(st) == ["Emotion state: close to your usual self (pleasant, calm)."]


def test_readout_lists_the_notable_ones_with_the_blend(tmp_path):
    s, st, agent = fresh(tmp_path)
    now = time.time()
    emo.nudge(st, {"joy": 25, "trust": 15, "anticipation": 12, "sadness": 3}, "x", now)
    lines = emo.readout(st, now)
    assert lines == ["Emotion state (0-100): joy 70 (+25), trust 70 (+15), anticipation 47 (+12).",
                     "Overall: " + emo.valence_word(emo.valence(emo.levels(st, now))) + ", "
                     + emo.arousal_word(emo.arousal(emo.levels(st, now))) + "; it feels like warmth."]


def test_readout_shows_at_most_four_and_negative_deviations(tmp_path):
    s, st, agent = fresh(tmp_path)
    now = time.time()
    emo.nudge(st, {"joy": -30, "anger": 40, "fear": 30, "sadness": 25, "disgust": 20, "trust": -12}, "x", now)
    first = emo.readout(st, now)[0]
    assert first.count("(+") + first.count("(-") == 4                    # the four furthest from usual, not all six
    assert "anger 48 (+40)" in first and "joy 15 (-30)" in first and "fear 40 (+30)" in first and "sadness 40 (+25)" in first
    assert "disgust" not in first and "trust" not in first
    assert first.index("anger") < first.index("joy") < first.index("fear") < first.index("sadness")   # biggest gap first


def test_quiet_and_off_modes_show_nothing_to_pip(tmp_path):
    s, st, agent = fresh(tmp_path)
    emo.nudge(st, {"joy": 30}, "x")
    assert "Emotion state" in agent._perception("timer", [])
    s.emotions = "quiet"
    assert "Emotion state" not in agent._perception("timer", [])
    s.emotions = "off"
    assert "Emotion state" not in agent._perception("timer", [])


# --- appraisal: events in, moves out ----------------------------------------------------
FULL = {"work": dict(project="gear clock", stage="cut", text="Progress."),
        "experiment": dict(project="gear clock", hypothesis="h", text="Tried."),
        "creation_made": dict(id=1, name="Gear Clock", description="keeps time", quality="sound"),
        "outreach": dict(text="hello out there")}


def moves(st, kind, **data):
    data = {**FULL.get(kind, {}), **data}
    before = emo.levels(st)
    st.log(kind, **data)
    after = emo.levels(st)
    return {k: round(after[k] - before[k]) for k in emo.NAMES if round(after[k] - before[k])}


def test_a_gift_and_a_visitor_lift_joy_and_trust(tmp_path):
    s, st, agent = fresh(tmp_path)
    assert moves(st, "gift", sender="Morgan", item="pendulum", qty=1) == {"joy": 10, "trust": 6, "surprise": 8}
    assert moves(st, "inbox", id=1, text="hi", sender="Morgan") == {"joy": 5, "trust": 4, "sadness": -6}


def test_work_results_move_the_right_emotions(tmp_path):
    s, st, agent = fresh(tmp_path)
    assert moves(st, "work", result="breakthrough") == {"joy": 10, "surprise": 6, "anticipation": 5}
    assert moves(st, "work", result="good") == {"joy": 4, "anticipation": 3}
    assert moves(st, "work", result="slow") == {"sadness": 2}
    assert moves(st, "work", result="setback") == {"sadness": 8, "anger": 6}
    assert moves(st, "work", result="blowup") == {"fear": 12, "sadness": 8, "anger": 8, "surprise": 8}


def test_a_surprise_adds_a_direction(tmp_path):
    s, st, agent = fresh(tmp_path)
    assert moves(st, "work", result="good", surprise="better") == {"joy": 8, "anticipation": 3, "surprise": 6}
    assert moves(st, "work", result="good", surprise="worse") == {"joy": 4, "anticipation": 3, "surprise": 6, "fear": 3, "sadness": 3}


def test_experiment_outcomes(tmp_path):
    s, st, agent = fresh(tmp_path)
    assert moves(st, "experiment", outcome="nothing") == {"sadness": 3, "anger": 2}
    assert moves(st, "experiment", outcome="clue") == {"anticipation": 3}
    assert moves(st, "experiment", outcome="insight") == {"joy": 6, "anticipation": 4}
    assert moves(st, "experiment", outcome="surprise") == {"surprise": 12, "joy": 4}


def test_finishing_something_is_the_big_joy(tmp_path):
    s, st, agent = fresh(tmp_path)
    assert moves(st, "creation_made", id=1, name="Gear Clock") == {"joy": 20, "anticipation": 6}


def test_small_events(tmp_path):
    s, st, agent = fresh(tmp_path)
    assert moves(st, "garden", plot=1, crop="tomato") == {"joy": 3}
    assert moves(st, "alert", stat="hunger") == {"anger": 6, "sadness": 2}
    assert moves(st, "alert", stat="energy") == {"sadness": 5, "anger": 2}
    assert moves(st, "tool", tool="plant", args={}, result="error: no free plot") == {"anger": 2}
    assert moves(st, "tool", tool="plant", args={}, result="planted tomato") == {}
    assert moves(st, "outreach", what="postcard", delivered=True) == {"anticipation": 6}
    assert moves(st, "outreach", what="postcard", delivered=False) == {}
    assert moves(st, "tick", reason="timer") == {}                       # unrelated events change nothing


def test_waking_eases_the_night_away(tmp_path):
    s, st, agent = fresh(tmp_path)
    emo.nudge(st, {"anger": 50}, "x")
    st.log("woke", hours=7.5, early=False)
    assert emo.levels(st)["anger"] == pytest.approx(58 - 0.4 * 50, abs=0.5)


def test_off_records_nothing(tmp_path):
    s, st, gm, agent = make(tmp_path, emotions="off")
    st.log("gift", sender="Morgan", item="x", qty=1)
    assert emo.levels(st) == {k: float(v) for k, v in emo.BASELINE.items()} and st.emotion_log() == []


def test_quiet_still_records(tmp_path):
    s, st, gm, agent = make(tmp_path, emotions="quiet")
    st.log("gift", sender="Morgan", item="x", qty=1)
    assert emo.levels(st)["joy"] > 45 and st.emotion_log()


def test_a_broken_listener_never_breaks_logging(tmp_path):
    s, st, agent = fresh(tmp_path)
    st.listeners.append(lambda kind, data, ts: 1 / 0)
    assert isinstance(st.log("garden", plot=1, crop="x"), int)


# --- loneliness ---------------------------------------------------------------------------
def test_being_alone_for_hours_slowly_saddens(tmp_path):
    s, st, agent = fresh(tmp_path)
    t0 = time.time()
    st.set_meta(born_at=t0 - 20 * HOUR)
    emo.drift(st, s, t0)
    assert emo.levels(st, t0)["sadness"] == pytest.approx(18) and emo.levels(st, t0)["trust"] == pytest.approx(54)
    emo.drift(st, s, t0 + 600)                                            # too soon after the last nudge
    assert emo.levels(st, t0 + 600)["sadness"] < 18.1
    emo.drift(st, s, t0 + HOUR)
    assert emo.levels(st, t0 + HOUR)["sadness"] > 16


def test_company_stops_the_loneliness(tmp_path):
    s, st, agent = fresh(tmp_path)
    t0 = time.time()
    st.set_meta(born_at=t0 - 20 * HOUR)
    st.log("inbox", id=1, text="hi", sender="Morgan")                    # someone wrote just now
    before = emo.levels(st)["sadness"]
    emo.drift(st, s, time.time() + 10)
    assert emo.levels(st)["sadness"] == pytest.approx(before, abs=0.1)


def test_no_loneliness_while_asleep(tmp_path):
    s, st, agent = fresh(tmp_path)
    t0 = time.time()
    st.set_meta(born_at=t0 - 20 * HOUR)
    st.update_agent(activity="sleeping")
    emo.drift(st, s, t0)
    assert emo.levels(st, t0)["sadness"] == pytest.approx(15)


# --- settling ---------------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_settle_eases_a_strong_feeling(tmp_path):
    s, st, agent = fresh(tmp_path)
    s.tools = list(s.tools) + ["settle"]
    emo.nudge(st, {"anger": 60}, "x")
    ok, text = emo.settle(st, s, "anger", "a slow walk round the bench")
    assert ok and text == "You take a quiet moment. Anger eases from 68 to 33." 
    assert emo.levels(st)["anger"] == pytest.approx(33, abs=0.01)                # it keeps easing by itself while the test runs
    (ev,) = [e["data"] for e in st.events(5) if e["kind"] == "settled"]
    assert ev["emotion"] == "anger" and ev["from"] == 68 and ev["to"] == 33 and ev["how"] == "a slow walk round the bench"


def test_settle_never_goes_below_baseline_and_needs_something_to_settle(tmp_path):
    s, st, agent = fresh(tmp_path)
    emo.nudge(st, {"fear": 20}, "x")                                     # fear 30: 20 over baseline
    ok, text = emo.settle(st, s, "fear")
    assert ok and emo.levels(st)["fear"] == pytest.approx(10)
    ok, text = emo.settle(st, s, "fear")
    assert not ok and "already settled" in text
    ok, text = emo.settle(st, s, "bogus")
    assert not ok and "joy" in text and "anticipation" in text


def test_settle_has_a_daily_cap(tmp_path):
    s, st, agent = fresh(tmp_path, emotion_settle_per_day=2)
    for _ in range(3):
        emo.nudge(st, {"anger": 60}, "x")
        ok, text = emo.settle(st, s, "anger")
    assert not ok and "enough" in text
    assert len([e for e in st.events(50) if e["kind"] == "settled"]) == 2


@pytest.mark.asyncio
async def test_settle_is_a_tool_only_when_emotions_are_on(tmp_path):
    from app import tools as tools_mod
    s, st, gm, agent = make(tmp_path, emotions="on")
    s.tools = list(s.tools) + ["settle"]
    assert "settle" in tools_mod.enabled_tools(s)
    s.emotions = "off"
    assert "settle" not in tools_mod.enabled_tools(s)
    s.emotions = "on"
    agent.tools = tools_mod.enabled_tools(s)
    emo.nudge(st, {"sadness": 50}, "x")
    r = await call(agent, "settle", emotion="sadness", how="tea")
    assert "eases" in r.text and emo.levels(st)["sadness"] < 40


# --- API and slash command ---------------------------------------------------------------
def test_the_api_shows_the_state_and_why(tmp_path):
    from fastapi.testclient import TestClient
    from app.config import Settings
    from app.llm.fake import FakeBackend
    from app.main import create_app
    s = Settings(db_path=str(tmp_path / "t.db"), persona_path="/x", pacing="manual")
    with TestClient(create_app(s, FakeBackend())) as c:
        r = c.get("/emotions").json()
        assert r["mode"] == "on" and [e["name"] for e in r["emotions"]] == list(emo.NAMES) and r["log"] == []
        assert r["valence_word"] == "pleasant" and r["blend"] is None
        c.app.state.agent.state.log("gift", sender="Morgan", item="x", qty=1)
        r = c.get("/emotions").json()
        joy = next(e for e in r["emotions"] if e["name"] == "joy")
        assert joy["value"] > joy["baseline"] == 45
        assert {x["emotion"] for x in r["log"]} == {"joy", "trust", "surprise"} and r["log"][0]["cause"] == "Morgan gave a gift"
        assert len(c.get("/emotions?limit=2").json()["log"]) == 2


def test_the_emotions_slash_command(tmp_path):
    from app import commands
    s, st, agent = fresh(tmp_path)
    assert commands.answer(st, s, "/emotions") == (
        "Emotions\njoy 45, sadness 15, anger 8, fear 10, trust 55, disgust 5, surprise 10, anticipation 35\n"
        "Overall: pleasant, calm.")
    emo.nudge(st, {"joy": 25, "trust": 15}, "x")
    text = commands.answer(st, s, "/emotions")
    assert "joy 70" in text and text.endswith("it feels like warmth.")
    assert "/emotions" in commands.answer(st, s, "/help")
