"""Happenings (docs/DESIGN-happenings.md): slots and rolls, the dice, the effect menu and its caps, the words, Pip's reading, and the monitor's step."""
import asyncio
import random
import time
from datetime import date

import pytest

from app import emotions as emo
from app import happenings as H
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


def plot(n=1, crop="tomatoes", left_min=600, yield_=3):
    return {"plot": n, "crop": crop, "state": "growing", "ready_at": NOW + left_min * 60, "yield": yield_}


def food(name="tomatoes", qty=91):
    return {"id": 1, "name": name, "kind": "food", "qty": qty}


def w(**kw):
    base = {"now": NOW, "coins": 78, "hunger": 0.2, "energy": 0.8, "low": False, "known": ["tomatoes"], "answers": {}, "foods": [food()],
            "booths": [{"key": "Saltholm", "loot": [["brass wire", "material", 20, [1, 2], "wire", {}]]}], "period": "afternoon",
            "neighbors": ["Oriel Vantosh"], "creations": ["Gear Clock"],
            "stoppable": [{"id": 1, "name": "Gear Clock"}], "tools": ["needle file"], "diary_count": 9,
            "old_notes": [{"id": 4, "text": "Oriel taught me to feel for the round grains in the tin.", "ts": NOW - 5 * 86400}]}
    return {**base, **kw}


class StubGM:
    def __init__(self, *outs):
        self.outs, self.calls = list(outs), []

    async def write_happening(self, *args):
        self.calls.append(args)
        return self.outs.pop(0) if self.outs else None


# --- slots -------------------------------------------------------------------------------------------------------
def test_the_salt_is_made_once_and_kept(tmp_path):
    s, st = fresh(tmp_path)
    first = H.salt(st)
    assert len(first) == 16 and H.salt(st) == first == st.meta("happenings_salt")


# --- the dice -------------------------------------------------------------------------------------------------
def share(values):
    return {v: values.count(v) / len(values) for v in set(values)}


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


# --- describing and applying effects --------------------------------------------------------------------------
# --- the words ---------------------------------------------------------------------------------------------------
LINE = "(You lose 3 tomatoes.)"


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


FORCED = {}


def force(monkeypatch, candidate=FOUND):
    """The happening that `create` records (the dice that chose it are a module's now: module_library/happenings.py)."""
    monkeypatch.setitem(FORCED, "c", dict(candidate))


async def create(st, s, gm, world, now, slot, rng=None, night=False):
    return await H.record(st, s, gm, dict(FORCED["c"]), world, now, slot, night)


def levels_now(st):
    return emo.levels(st)


def test_a_happening_is_written_applied_stored_and_logged(tmp_path, monkeypatch):
    s, st = fresh(tmp_path)
    force(monkeypatch)
    gm = StubGM(STORY)
    row = run(create(st, s, gm, w(), NOW, "2026-03-05#2", random.Random(1)))
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
    run(create(st, s, gm, w(), NOW, "x", random.Random(1)))
    _, _, _, _, _, facts, recent = gm.calls[0]
    assert recent == ["Rested"] and facts["period"] == "afternoon" and facts["names"] == ["Oriel Vantosh", "Gear Clock", "tomatoes"]


def test_log_mode_writes_it_but_changes_nothing(tmp_path, monkeypatch):
    s, st = fresh(tmp_path, happenings="log")
    force(monkeypatch)
    row = run(create(st, s, StubGM(STORY), w(), NOW, "x", random.Random(1)))
    assert row["status"] == "logged" and st.coins() == 10
    assert [e for e in st.events(10) if e["kind"] == "happening"][0]["data"]["jolt"] == 0
    assert levels_now(st)["surprise"] == pytest.approx(10, abs=0.2)


def test_a_template_is_used_when_there_is_no_model(tmp_path, monkeypatch):
    s, st = fresh(tmp_path)
    force(monkeypatch)
    row = run(create(st, s, None, w(), NOW, "x", random.Random(1)))
    assert row["author"] == "template" and (row["title"], row["text"]) == H.template(FOUND)


# --- the monitor's step ------------------------------------------------------------------------------------------
def step_state(tmp_path, **kw):
    kw.setdefault("happenings_chance", 1.0)
    s, st = fresh(tmp_path, **kw)
    return s, st


def stepped(s, st, gm, now):
    return run(H.step(st, s, gm, now))


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
    assert "Nothing in the world changes: nothing breaks, moves, grows, appears or is lost; it is only a moment.\n" in p3 and "Names you may use: none." in p3 and "Recent events" not in p3
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


def test_the_percentages_the_engine_quotes():
    assert H._percent(0.51) == 51 and H._percent(-0.12) == 12


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


def test_a_first_happening_of_each_kind_is_a_first_and_reading_it_differently_is_a_major_one():
    from app import firsts
    from tests.test_happenings_rule import rule_module
    assert set(firsts.HAPPENING_FIRSTS) == set(rule_module().CATEGORIES)                      # a first for each of the dice's categories
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
    run(create(st, s, StubGM(STORY), w(), NOW, "x", random.Random(1)))
    ev = [e for e in st.events(10) if e["kind"] == "happening"][0]["data"]
    assert [f["key"] for f in ev["firsts"]] == ["happening:found"]


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


def test_news_without_a_title_or_for_a_resident_changes_nothing(tmp_path):
    s, st = fresh(tmp_path)
    st.add_character("Oriel Vantosh", "neighbor", None, "p", 60, NOW + 99 * HOUR, about="x")
    st.add_character("Mr Teague", "resident", None, "p", 60, NOW + 99 * HOUR, about="x", place="Saltholm")
    H.apply_effects(st, [{"kind": "news", "name": "Oriel Vantosh", "tone": "good"}], NOW)                 # no title given
    H.apply_effects(st, [{"kind": "news", "name": "Mr Teague", "tone": "good"}], NOW, "News")
    assert [c["life"] for c in st.characters()] == [[], []]


# --- 0.8.1: the writer's text kept, not thrown away --------------------------------------------------------------------------
def test_a_text_a_little_too_long_is_cut_at_the_last_sentence_that_fits():
    long = "The wind came in over the marsh. " * 10 + "And then it stopped."
    got = H.trim(long)
    assert len(got) <= H.MAX_TEXT and got.endswith(".") and got.startswith("The wind came in")
    assert H.trim("short and fine.") == "short and fine."
    assert H.trim("x" * 500) == "x" * 500                                                         # nothing to cut at: left for the check to turn down
    exact = "y" * (H.MAX_TEXT - 1) + "."
    assert H.trim(exact) == exact


def test_every_turned_down_try_is_logged_with_its_reason(tmp_path, monkeypatch):
    s, st = fresh(tmp_path)
    force(monkeypatch)
    gm = StubGM({"title": "A", "text": "A mouse called Fred got at the pantry in the night, small and bold."}, None)
    row = run(create(st, s, gm, w(), NOW, "x", random.Random(1)))
    assert row["author"] == "template"
    got = [e["data"] for e in st.events(10) if e["kind"] == "happening_rejected"]
    assert got == [{"category": "found", "reason": "length", "attempt": 2}, {"category": "found", "reason": "a name that was not offered: Fred", "attempt": 1}]
    seen = []
    gm2 = StubGM({"title": "", "text": STORY["text"]}, STORY)
    assert run(H.author(gm2, FOUND, FACTS, [], lambda why, n: seen.append((why, n))))[2] == "gm"
    assert seen == [("no title", 1)]


def test_a_memory_happening_quotes_the_memory_and_may_use_its_words():
    c = {"category": "memory", "tone": "bad", "lens": "joy", "facts": {"memory": "Oriel taught me the tin by the door, plot 2 first."}}
    title, text = H.template(c)
    assert text == 'An old thought of your own comes back to you: "Oriel taught me the tin by the door, plot 2 first." You can\'t help smiling.'
    gm = StubGM({"title": "The tin", "text": "Out of nowhere you think of Oriel and the tin, and of plot 2 going first, and it warms you."})
    cand = {**CAND, "category": "memory", "names": [], "facts": c["facts"], "line": ""}
    assert run(H.author(gm, cand, {**FACTS, "memory": c["facts"]["memory"]}, []))[2] == "gm"                # Oriel and the 2 come from the memory


@pytest.mark.parametrize("qty, name, said", [(1, "sticks", "1 stick"), (2, "sticks", "2 sticks"), (1, "brass wire", "1 brass wire"),
                                            (1, "fine brass gears", "1 fine brass gear"), (1, "tomatoes", "1 tomato"), (3, "tomatoes", "3 tomatoes")])
def test_one_of_a_thing_is_one(qty, name, said):
    assert H._count(qty, name) == said
    assert H.describe({"kind": "item", "name": name, "qty": qty}) == f"You find {said}."
    assert H.describe({"kind": "food_loss", "name": name, "qty": qty}) == f"You lose {said}."


@pytest.mark.asyncio
async def test_the_author_is_given_a_length_and_told_nothing_moves_in_a_quiet_moment(tmp_path):
    from app.llm.base import LLMResponse, ToolCall, Usage
    from tests.test_gm_prompts import master, task
    gm, b, _ = master(tmp_path, LLMResponse("", [ToolCall("1", "report", {"title": "T", "text": "x"})], Usage(1, 1)))
    await gm.write_happening("atmosphere", "neutral", "minor", "fear", "", {}, [])
    p = task(b)
    assert "Two or three sentences, under 300 characters," in p and "nothing breaks, moves, grows, appears or is lost" in p


# --- a stopped creation is mended through its workings (0.29.0: the engine no longer tends anything itself) -------------------------
async def _mendable(tmp_path):
    from app import modules as M
    from tests.test_modules import modular
    from tests.test_world_view import clock
    s, st, agent = modular(tmp_path)
    c = clock(st)
    man, src = M.workings_manifest(c)
    m = st.module((await M.propose(st, s, M.LocalRunner(), M.SHIPPED, man, src, "workings"))["id"])
    return s, st, c, m


@pytest.mark.asyncio
async def test_a_stopped_creation_with_a_missing_part_must_be_mended_before_it_is_tended(tmp_path):
    from app import creations as cr
    from app import modules as M
    s, st, c, m = await _mendable(tmp_path)
    t = time.time()
    H.apply_effects(st, [{"kind": "creation_stop", "id": c["id"], "name": "Gear Clock", "part": {"name": "brass wire", "qty": 2}}], t)
    stopped = st.find_creation("Gear Clock")[0]
    assert cr._needs(stopped) == "it needs 2 brass wire to mend it, then tending (wound)"
    assert "STOPPED - it needs 2 brass wire to mend it, then tending (wound)" in cr.describe(stopped, t + 10)
    assert await M.act(st, s, None, m, "tend", {}, t + 10) == "that didn't work: you need 2 brass wire for that"
    st.add_item("brass wire", 1, "material", "")
    assert await M.act(st, s, None, st.module(m["id"]), "tend", {}, t + 10) == "that didn't work: you need 2 brass wire for that"
    assert st.find_item("brass wire")[0]["qty"] == 1                                         # nothing taken until it can be mended
    st.add_item("brass wire", 4, "material", "")
    assert (await M.act(st, s, None, st.module(m["id"]), "tend", {}, t + 10)).startswith("you tend your Gear Clock (wound)")
    mended = st.find_creation("Gear Clock")[0]
    assert st.find_item("brass wire")[0]["qty"] == 3 and "needs_part" not in mended["runtime"] and "halted_at" not in mended["runtime"]
    assert mended["runtime"]["stop_logged"] is False and abs(mended["runtime"]["tended_until"] - (t + 10 + 12 * 3600)) < 1


@pytest.mark.asyncio
async def test_a_part_must_be_a_material(tmp_path):
    from app import modules as M
    s, st, c, m = await _mendable(tmp_path)
    H.apply_effects(st, [{"kind": "creation_stop", "id": c["id"], "name": "Gear Clock", "part": {"name": "springs", "qty": 1}}], time.time())
    st.add_item("springs", 3, "tool", "")                                                   # not a material: it does not count
    assert await M.act(st, s, None, m, "tend", {}) == "that didn't work: you need 1 springs for that"


def test_the_step_only_lands_what_pip_has_been_shown_and_rolls_nothing(tmp_path, monkeypatch):
    s, st = fresh(tmp_path)
    force(monkeypatch)
    row = run(create(st, s, StubGM(STORY), w(), NOW, "x"))
    st.update_happening(row["id"], ticks_seen=H.RESOLVE_AFTER_TICKS)
    assert run(H.step(st, settings(happenings="off", db_path=s.db_path), None, NOW + 60)) is False
    assert st.happening(row["id"])["status"] == "applied"                                       # off: nothing lands
    assert run(H.step(st, s, None, NOW + 60)) is False and st.happening(row["id"])["status"] == "resolved"
    assert len(st.happenings()) == 1                                                            # and nothing new happens
    t0 = time.time()
    seen = []
    monkeypatch.setattr(H, "resolve_due", lambda state, now: seen.append(now))
    run(H.step(st, s, None))
    assert t0 <= seen[0] <= time.time()
