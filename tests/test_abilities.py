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
    assert cr.tend(st, listed(st, "radio"), t0 + 2 * DAY).startswith("you tend")
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


def test_news_per_day_is_counted_on_the_creation(tmp_path):
    s, st, *_ = make(tmp_path)
    t0 = time.time()
    c = radio(st, now=t0)
    assert A.news_left(c, t0) == 3
    rt = {**c["runtime"], "news_log": [t0 - 100, t0 - 50, t0 - DAY - 5]}
    assert A.news_left({**c, "runtime": rt}, t0) == 1                       # the day-old one has dropped out
    assert A.news_left({**c, "runtime": {**rt, "news_log": [t0 - 1] * 3}}, t0) == 0
    assert A.news_left(clock(st), t0) == 0                                   # not a news provider


@pytest.mark.asyncio
async def test_listening_asks_the_gm_for_a_bulletin_and_counts_it(tmp_path):
    s, st, gm, agent = make(tmp_path, [report(text="You switch it on.", bulletin="The ferry is late again and the geese are loud.")])
    radio(st)
    r = await call(agent, "use_item", item="radio", purpose="listen to the news")
    assert r.text.startswith("You switch it on.") and "Bulletin: The ferry is late again and the geese are loud." in r.text
    prompt = gm.calls[0]["messages"][0]["content"]
    assert "`bulletin`" in prompt and "world only" in prompt and "3 left" not in prompt
    assert len(listed(st, "radio")["runtime"]["news_log"]) == 1
    what = [e["data"]["what"] for e in st.events(10) if e["kind"] == "creation"]
    assert what == ["news", "used"]                                          # newest first
    news = [e["data"] for e in st.events(10) if e["kind"] == "creation" and e["data"]["what"] == "news"][0]
    assert news["name"] == "radio" and news["text"] == "The ferry is late again and the geese are loud."


@pytest.mark.asyncio
async def test_a_radio_that_has_told_its_three_bulletins_is_only_static(tmp_path):
    s, st, gm, agent = make(tmp_path, [report(text="Hiss.", bulletin="More news.")])
    c = radio(st)
    st.set_runtime(c["id"], {**c["runtime"], "news_log": [time.time() - 10] * 3})
    r = await call(agent, "use_item", item="radio", purpose="listen")
    assert "`bulletin`" not in gm.calls[0]["messages"][0]["content"]
    assert r.text.startswith("Hiss.") and "Bulletin" not in r.text and "only static" in r.text
    assert len(listed(st, "radio")["runtime"]["news_log"]) == 3


@pytest.mark.asyncio
async def test_only_a_news_provider_is_ever_asked_for_a_bulletin(tmp_path):
    s, st, gm, agent = make(tmp_path, [report(text="It turns.", bulletin="Invented news.")])
    clock(st)
    r = await call(agent, "use_item", item="Gear Clock", purpose="listen to the news")
    assert "`bulletin`" not in gm.calls[0]["messages"][0]["content"] and "Bulletin" not in r.text


@pytest.mark.asyncio
async def test_a_bulletin_is_clipped_and_an_empty_one_does_not_use_up_a_slot(tmp_path):
    s, st, gm, agent = make(tmp_path, [report(text="Static.", bulletin="  "), report(text="On.", bulletin="x" * 500)])
    radio(st)
    r = await call(agent, "use_item", item="radio", purpose="listen")
    assert "Bulletin" not in r.text and "news_log" not in listed(st, "radio")["runtime"]
    r = await call(agent, "use_item", item="radio", purpose="listen")
    assert "Bulletin: " + "x" * 300 + "..." in r.text
    assert len(listed(st, "radio")["runtime"]["news_log"]) == 1


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


def test_a_news_allowance_frees_up_after_exactly_a_day(tmp_path):
    s, st, *_ = make(tmp_path)
    t0 = time.time()
    c = radio(st, now=t0)
    log = lambda *ts: {**c, "runtime": {**c["runtime"], "news_log": list(ts)}}                 # noqa: E731
    assert A.news_left(log(t0 - DAY), t0) == 3 and A.news_left(log(t0 - DAY + 1), t0) == 2


@pytest.mark.asyncio
async def test_the_last_bulletin_of_the_day_is_still_told_and_old_ones_drop_out_of_the_log(tmp_path):
    s, st, gm, agent = make(tmp_path, [report(text="On.", bulletin="One more.")])
    c = radio(st)
    now = time.time()
    # two told today, one told exactly a day ago (gone), one older still (gone)
    st.set_runtime(c["id"], {**c["runtime"], "news_log": [now - 20, now - 10, now - DAY, now - 3 * DAY]})
    r = await call(agent, "use_item", item="radio", purpose="listen")
    assert "`bulletin`" in gm.calls[0]["messages"][0]["content"] and "Bulletin: One more." in r.text
    log = listed(st, "radio")["runtime"]["news_log"]
    assert len(log) == 3 and log[:2] == [now - 20, now - 10] and log[2] >= now


@pytest.mark.asyncio
async def test_static_is_announced_in_words(tmp_path):
    s, st, gm, agent = make(tmp_path, [report(text="Hiss.")])
    c = radio(st)
    st.set_runtime(c["id"], {**c["runtime"], "news_log": [time.time() - 5] * 3})
    r = await call(agent, "use_item", item="radio", purpose="listen")
    assert r.text.startswith("Hiss. (only static now: it has told you all the news it has today; it keeps going")
