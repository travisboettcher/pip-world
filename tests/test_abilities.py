import time
from datetime import datetime

import pytest

from app import abilities as A
from app import creations as cr
from tests.test_creations import DAY, build, project
from tests.test_projects import FixedRng, call, make, report

RADIO = {"description": "a crystal set", "capabilities": [{"type": "provides", "ability": "news"},
                                                          {"type": "upkeep", "verb": "charge", "hours": 24}]}


def radio(st, now=None, **kw):
    return build(st, RADIO, name="radio", now=now, **kw)


def clock(st, now=None):
    return build(st, {"description": "a clock", "capabilities": [{"type": "timekeeper"}]}, name="Gear Clock", now=now)


def listed(st, name):
    return next(c for c in st.creations() if c["name"] == name)


def test_the_registry_names_the_abilities_and_tells_the_gm_which_it_may_propose():
    assert set(A.ABILITIES) == {"time", "news"}
    line = A.gm_lines()
    assert "news" in line and "radio" in line and "time" not in line.split("give `ability` as one of:")[1]
    assert "a pond, a painting or a gift is just itself" in line


def test_the_gm_line_lists_exactly_what_it_may_propose():
    assert A.gm_lines() == (
        "provides: ONLY if what Pip finished gives it something it could not have without the thing, while the thing works - give "
        "`ability` as one of: news (a radio or other receiver that brings in short bulletins). For anything else never use it "
        "(a pond, a painting or a gift is just itself)")


def test_an_ability_is_proposed_only_for_work_that_is_plainly_about_it():
    radio_p = {"name": "Build a crystal radio", "goal": "hear the world", "difficulty": 2, "stages": [{"name": "wind the coil"}]}
    assert A.allowed("news", radio_p) and A.allowed("news", {**radio_p, "stages": []})
    assert not A.allowed("news", {**radio_p, "name": "Build a hat", "goal": "", "stages": [{"name": "sew"}]})
    assert not A.allowed("news", {**radio_p, "difficulty": 1})           # too simple a thing to carry a signal
    assert not A.allowed("time", radio_p) and not A.allowed("sorcery", radio_p) and not A.allowed(None, radio_p)


def test_sanitize_keeps_a_provided_ability_only_when_the_project_fits(tmp_path):
    p = {**project(3, "crystal radio"), "stages": []}
    _, _, spec = cr.sanitize_spec({"capabilities": [{"type": "provides", "ability": "news"}]}, p, "sound", [], FixedRng())
    assert spec["capabilities"] == {"provides": {"ability": "news"}}
    for raw in ({"type": "provides", "ability": "time"}, {"type": "provides", "ability": "sorcery"}, {"type": "provides"}):
        assert cr.sanitize_spec({"capabilities": [raw]}, p, "sound", [], FixedRng())[2]["capabilities"] == {}
    plain = {**project(3, "hourglass"), "stages": []}
    assert cr.sanitize_spec({"capabilities": [{"type": "provides", "ability": "news"}]}, plain, "sound", [], FixedRng())[2]["capabilities"] == {}


def test_only_a_working_provider_gives_the_ability(tmp_path):
    s, st, *_ = make(tmp_path)
    t0 = time.time()
    assert A.has(st, "news", t0) is False and A.has(st, "time", t0) is False
    r = radio(st, now=t0)
    c = clock(st, now=t0)
    assert A.has(st, "news", t0 + 60) and A.has(st, "time", t0 + 60)
    assert [x["name"] for x in A.providers(st, "news", t0 + 60)] == ["radio"]
    assert [x["name"] for x in A.providers(st, "time", t0 + 60)] == ["Gear Clock"]
    assert A.has(st, "news", t0 + 2 * DAY) is False                       # the radio went quiet: it needed charging
    st.set_runtime(c["id"], {**c["runtime"], "halted_at": t0 + 10})
    assert A.has(st, "time", t0 + 60) is False and A.providers(st, "time", t0 + 60) == []
    r = listed(st, "radio")
    st.set_runtime(r["id"], {**r["runtime"], "tended_until": t0 + 3 * DAY})                    # tended (by its workings)
    assert A.has(st, "news", t0 + 2 * DAY + 60) is True


def test_the_exact_time_is_told_only_while_a_clock_runs(tmp_path):
    s, st, *_ = make(tmp_path)
    t0 = datetime(2026, 11, 1, 14, 14).timestamp()
    assert A.perception(st, t0) == []
    clock(st, now=t0)
    line, = A.perception(st, t0)
    assert line.startswith("By your Gear Clock it is 2:14 PM") and "runs" not in line
    drifted = A.perception(st, t0 + 3 * DAY)               # long after: it stopped (no upkeep here, but halted below)
    assert drifted and drifted[0].startswith("By your Gear Clock it is")
    c = listed(st, "Gear Clock")
    st.set_runtime(c["id"], {**c["runtime"], "halted_at": t0})
    assert A.perception(st, t0 + 60) == []


def test_the_clock_line_says_how_far_off_it_runs(tmp_path):
    s, st, *_ = make(tmp_path)
    t0 = datetime(2026, 11, 1, 12, 0).timestamp()
    c = clock(st, now=t0)
    off = c["spec"]["capabilities"]["timekeeper"]["drift_per_day"]          # minutes per day, +- 5 for a sound clock
    line, = A.perception(st, t0 + DAY)
    assert f"about {round(abs(off))} min {'fast' if off > 0 else 'slow'}" in line


def test_describe_says_what_a_running_provider_brings(tmp_path):
    s, st, *_ = make(tmp_path)
    t0 = time.time()
    c = radio(st, now=t0)
    assert cr.describe(c, t0 + 60).endswith("; it brings you news")
    assert "it brings you news" not in cr.describe(c, t0 + 2 * DAY)         # stopped: it says so instead
    assert "STOPPED" in cr.describe(c, t0 + 2 * DAY)


def test_what_counts_as_the_projects_own_words(tmp_path):
    base = {"name": "A box", "goal": "", "difficulty": 2, "stages": [{"name": "cut the case"}]}
    assert not A.allowed("news", base) and not A.allowed("news", {k: v for k, v in base.items() if k not in ("goal", "stages")})
    assert A.allowed("news", {**base, "name": "A RADIO"}) and A.allowed("news", {**base, "goal": "a wireless for the evenings"})
    assert A.allowed("news", {**base, "stages": [{"name": "wind the aerial"}]})
    assert A.allowed("news", {**base, "goal": None, "name": "a receiver"})
    assert not A.allowed(["news"], base) and not A.allowed({"news": 1}, {**base, "name": "radio"})
    assert A.allowed("news", {**base, "name": "ra", "goal": "dio", "stages": []}) is False          # words don't run together


def test_the_clock_line_rounds_and_names_the_direction(tmp_path):
    s, st, *_ = make(tmp_path)
    t0 = datetime(2026, 11, 1, 9, 0).timestamp()
    c = clock(st, now=t0)

    def line(offset):
        st.set_runtime(c["id"], {**c["runtime"], "clock_offset": offset})
        return A.perception(st, t0)[0]
    assert line(0.5) == "By your Gear Clock it is 9:00 AM." and line(0.9) == "By your Gear Clock it is 9:00 AM."
    assert line(4.9) == "By your Gear Clock it is 9:04 AM."                          # a few minutes off is not worth mentioning
    assert line(5) == "By your Gear Clock it is 9:05 AM, about 5 min fast."
    assert line(5.5) == "By your Gear Clock it is 9:05 AM, about 6 min fast."
    assert line(-7) == "By your Gear Clock it is 8:53 AM, about 7 min slow."
    assert line(12) == "By your Gear Clock it is 9:12 AM, about 12 min fast."


