"""Modules, step 1: the exact words and edges (docs/DESIGN-modules.md). What test_modules.py shows working, this pins down precisely."""
import json
import logging
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime

import pytest

from app import modules as M
from tests.test_modules import BELLS, BELLS_MAN, NOW, clockwork, live, modular, rule
from tests.test_world_view import clock


def refusal(fn, *args):
    with pytest.raises(M.Refused) as e:
        fn(*args)
    return str(e.value)


# --- manifests, word for word -----------------------------------------------------------------------------------------------
def test_manifest_refusals_word_for_word(tmp_path):
    s, st, agent = modular(tmp_path)
    bad = lambda m: refusal(M.check_manifest, m, "world", st)
    events = ", ".join(sorted(__import__("app.public_view", fromlist=["x"]).EVENT_FIELDS))
    assert bad({k: v for k, v in rule().items() if k != "name"}) == "`name` is 3 to 40 lowercase letters, digits and dashes, starting with a letter"
    assert bad(rule(hooks=["x"])) == "`hooks` is a list drawn from: on_install, on_tick, on_time, on_event, on_action, on_message, on_answer, on_request, on_source"
    assert bad(rule(kind="thing")) == "a thing needs a `subject`: the name of the creation it makes work"
    assert bad(rule(subject="x")) == "only a thing has a subject (and reads or changes its runtime)"
    assert bad(rule(hooks=["on_event"], events=["inbox"])) == "`events` is a list of public event kinds: " + events
    assert bad(rule(hooks=["on_event"])) == "`on_event` and `events` go together: list the event kinds the hook wants"
    assert bad(rule(proposes=["consume"], consumes={"oil": "1"})) == "`consumes` maps item names (or \"*\" for any material) to at most 5 per call"
    assert bad(rule(proposes=["consume"], consumes={1: 1})).startswith("`consumes` maps")
    assert bad(rule(proposes=["consume"], consumes={"oil": 0})).startswith("`consumes` maps") and M.check_manifest(rule(proposes=["consume"], consumes={"oil": 5}), "world")
    assert bad(rule(proposes=["consume"])) == "`consume` and `consumes` go together: say which materials it may use up"
    assert bad(rule(tends="x")) == "`tends` is the name of the offer that tending the thing means"


# --- the runner client ------------------------------------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_the_http_runner_trims_its_address_and_waits_long_enough(monkeypatch):
    assert M.HttpRunner("http://x//").url == "http://x" and M.HttpRunner("http://x/ ").url == "http://x/ "
    seen = {}

    class Client:
        def __init__(self, timeout, transport):
            seen.update(timeout=timeout, transport=transport)

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, json):
            seen.update(url=url, body=json)
            return type("R", (), {"json": lambda self: {"ok": True, "result": {}}})()
    import httpx
    monkeypatch.setattr(httpx, "AsyncClient", Client)
    assert await M.HttpRunner("http://pip-runner:8100/").run("src", "on_tick", {"a": 1}) == {"ok": True, "result": {}}
    assert seen == {"timeout": 8.0, "transport": None, "url": "http://pip-runner:8100/run", "body": {"source": "src", "hook": "on_tick", "ctx": {"a": 1}}}
    await M.HttpRunner("unix:///run/s.sock").run("src", "on_tick", {})
    assert seen["url"] == "http://runner/run" and isinstance(seen["transport"], httpx.AsyncHTTPTransport)


@pytest.mark.asyncio
async def test_a_runner_that_cant_be_reached_says_how():
    r = await M.HttpRunner("http://127.0.0.1:9").run("x", "on_tick", {})
    assert r == {"ok": False, "error": "the runner couldn't be reached (ConnectError)", "runner_down": True}


# --- what a hook knows ------------------------------------------------------------------------------------------------------
def test_the_context_word_for_word(tmp_path):
    s, st, agent = modular(tmp_path, hemisphere="south")
    clock(st)
    from tests.test_sky import sky_says
    sky_says(st, {"condition": "rain", "temp": 9.5, "unit": "C", "daylight": True, "next_rising": None, "next_setting": None})   # what the sky publishes
    st.update_agent(activity="sleeping", location="workshop")
    off = live(st, rule(name="gone", proposes=["publish"]), "x")
    st.update_module(off["id"], facts={"x": 1}, status="disabled")
    m = live(st, rule(kind="thing", name="all", subject="Gear Clock", reads=list(M.READS)), "x")
    ctx = M.context(st, s, m, NOW)
    t = datetime.fromtimestamp(NOW)
    from app.happenings import season_of
    assert ctx["time"] == {"hour": t.hour, "minute": t.minute, "weekday": t.strftime("%A"), "season": season_of(NOW, "south"),
                           "utc_offset": round(t.astimezone().utcoffset().total_seconds())}
    assert ctx["weather"] == {"condition": "rain", "temp": 9.5, "unit": "C", "daylight": True}
    assert ctx["pip"] == {"where": "workshop", "at_home": True, "activity": "sleeping", "asleep": True,
                          "hunger": 0.2, "energy": 0.9, "mood": "curious", "walking": False, "coins": 10, "name": "Pip", "lives": "lives alone in a workshop with a garden"}
    assert ctx["facts"] == {"says": {"weather": {"condition": "rain", "temp": 9.5, "unit": "C", "daylight": True, "next_rising": None, "next_setting": None}}}
    c = st.creations()[0]
    assert ctx["subject"] == {"name": "Gear Clock", "quality": "sound", "description": "a clock", "capabilities": c["spec"]["capabilities"], "runtime": c["runtime"], "quirks": []}
    st.give_creation(c["id"], "Oriel")
    assert M.context(st, s, m, NOW)["subject"] is None


# --- the referee's edges ----------------------------------------------------------------------------------------------------
def test_the_referees_edges(tmp_path):
    s, st, agent = modular(tmp_path)
    st.add_item("oil", 2, "material", "")
    st.add_item("apple", 3, "food", "")
    m = live(st, rule(proposes=list(M.PROPOSES[:7]), consumes={"*": 5}), "x")
    ref = lambda r, hook="on_tick": refusal(M.plan, st, m, r, NOW, hook)
    assert ref({"runtime": 1, "wake": 1}) == "it returned runtime, wake, which its manifest doesn't propose"
    big = {"x": "y" * (M.STATE_MAX - len('{"x": ""}'))}
    assert M.plan(st, m, {"state": big}, NOW, "on_tick") and ref({"state": {**big, "z": 1}}).startswith("`state`")
    facts = {"x": "y" * (M.FACTS_MAX - len('{"x": ""}'))}
    assert M.plan(st, m, {"publish": facts}, NOW, "on_tick") and ref({"publish": {"x": facts["x"] + "y"}}).startswith("`publish`")
    assert M.plan(st, m, {"log": "x" * 200}, NOW, "on_tick") == [("log", "x" * 200)]
    assert ref({"schedule": NOW - 60}) == "`schedule` is a time (seconds, like ctx['now']) still to come"
    assert ref({"schedule": NOW - 60.5}).startswith("`schedule`") and ref({"schedule": "soon"}).startswith("`schedule`")
    assert M.plan(st, m, {"schedule": NOW - 59}, NOW, "on_tick") == [("due", NOW - 59)]
    four = [{"name": f"do {c}", "help": "x"} for c in "abcd"]
    assert M.plan(st, m, {"offer": four}, NOW, "on_tick")[0][1] == four
    assert ref({"offer": [{"name": "ring", "help": ""}]}) == "`offer help` is a line of text"
    assert ref({"consume": {"apple": 1}}) == "you need 1 apple for that"                         # food isn't a material
    assert M.plan(st, m, {"consume": {"oil": 2}}, NOW, "on_tick")[0][1][0][1] == 2                 # exactly what Pip has
    assert ref({"consume": {"oil": 3}}) == "you need 3 oil for that"
    m["manifest"]["proposes"].append("runtime")
    assert ref({"runtime": {"x": 1}}) == "`runtime` can only set: clock_set_at, clock_offset, tended_until, halted_at, stop_logged, needs_part"
    assert ref({"reply": ""}, "on_action") == "`reply` is a line of text"
    assert M._day(NOW) == datetime.fromtimestamp(NOW).strftime("%Y-%m-%d") and len(M._day(NOW)) == 10 and M._day(NOW)[4] == "-"


@pytest.mark.asyncio
async def test_budgets_add_up_and_a_due_time_ends_on_its_moment(tmp_path):
    s, st, agent = modular(tmp_path)
    m = live(st, rule(hooks=["on_tick"], proposes=["perceive", "log", "wake"]), "def on_tick(ctx):\n    return {'perceive': 'a', 'log': 'b', 'wake': True}\n")
    st.update_module(m["id"], due=NOW)
    m = st.module(m["id"])
    for _ in range(2):
        r = await M.call(st, s, agent.runner, m, "on_tick", NOW)
    assert r == {"ok": True, "error": "", "refused": "", "wake": True, "reply": "", "changed": True}
    assert m["budget"] == st.module(m["id"])["budget"] == {"day": M._day(NOW), "calls": 2, "source": 0, "event": 0, "creation": 0, "perceive": 2, "log": 2, "wake": 2, "affect": 0, "find": 0, "ask": 0, "speak": 0, "happen": 0, "take": 0, "give": 0, "request": 0, "character": 0, "letter": 0}
    got = st.module(m["id"])
    assert got["due"] is None and [l["text"] for l in got["lines"]] == ["a", "a"]
    calls = st.module_calls(m["id"])
    assert 1 <= calls[0]["ms"] < 5000 and calls[0]["summary"] == "perceive, log, wake"
    m["budget"] = {"day": M._day(NOW), "calls": M.PER_DAY["calls"]}
    assert await M.call(st, s, agent.runner, m, "on_tick", NOW) == {"ok": False, "error": "", "refused": "it has used today's 600 calls", "wake": False, "reply": "", "changed": False}


@pytest.mark.asyncio
async def test_each_calls_history_line_says_what_happened(tmp_path):
    s, st, agent = modular(tmp_path)
    m = live(st, rule(hooks=["on_tick", "on_time"], proposes=["state"]), "def on_tick(ctx):\n    return {}\ndef on_time(ctx):\n    return 1/0\n")
    assert await M.call(st, s, agent.runner, m, "on_install", NOW) == {"ok": True, "error": "", "refused": "", "wake": False, "reply": "", "changed": False}
    await M.call(st, s, agent.runner, m, "on_tick", NOW)
    await M.call(st, s, agent.runner, m, "on_time", NOW)
    assert [c["summary"] for c in st.module_calls(m["id"])] == ["error: line 4: ZeroDivisionError: division by zero", "nothing", "(no such hook)"]
    assert M._summary({"ok": False}, None) == "error: ?"


@pytest.mark.asyncio
async def test_a_module_switched_off_mid_step_runs_no_more_hooks_and_only_live_ones_run(tmp_path):
    s, st, agent = modular(tmp_path)
    src = "def on_time(ctx):\n    return 1/0\ndef on_tick(ctx):\n    return {}\ndef on_event(ctx):\n    return {}\n"
    m = live(st, rule(hooks=["on_time", "on_tick", "on_event"], events=["garden"]), src)
    st.update_module(m["id"], fails=2, due=NOW - 1)
    st.log("garden", plot=1, crop="peas")
    waiting = live(st, rule(name="waiting"), "def on_tick(ctx):\n    return {}\n")
    st.update_module(waiting["id"], status="waiting")
    ticker = live(st, rule(name="ticker", hooks=["on_tick"], proposes=["wake"]), "def on_tick(ctx):\n    return {'wake': ctx['state'].get('w', True)}\n")
    quiet = live(st, rule(name="quiet", hooks=["on_tick"], proposes=["wake"]), "def on_tick(ctx):\n    return {'wake': False}\n")
    assert await M.step(st, s, agent.runner, NOW) is True                                         # one wakes, one doesn't: still woken
    assert [c["hook"] for c in st.module_calls(m["id"])] == ["on_time"] and st.module(m["id"])["status"] == "disabled"
    assert st.module_calls(waiting["id"]) == [] and [c["hook"] for c in st.module_calls(quiet["id"])] == ["on_tick"]
    st.log("garden", plot=2, crop="beans")
    assert [c["hook"] for c in st.module_calls(ticker["id"])] == ["on_tick"]                    # no on_event for a module that has none
    await M.step(st, s, agent.runner, NOW)
    assert [c["hook"] for c in st.module_calls(ticker["id"])] == ["on_tick", "on_tick"]


@pytest.mark.asyncio
async def test_lines_from_several_modules_are_heard_and_new_ones_after_that(tmp_path):
    s, st, agent = modular(tmp_path)
    src = "def on_tick(ctx):\n    return {'perceive': ctx['state'].get('say', 'x')}\n"
    a = live(st, rule(name="aaa", proposes=["perceive"]), src, state={"say": "one"})
    b = live(st, rule(name="bbb", proposes=["perceive"]), src, state={"say": "two"})
    await M.step(st, s, agent.runner, NOW)
    assert M.perception(st) == ["Things in the world:", "- one", "- two"]
    await M.step(st, s, agent.runner, NOW)
    assert M.perception(st) == ["Things in the world:", "- one", "- two"]


@pytest.mark.asyncio
async def test_an_action_gets_what_pip_meant(tmp_path):
    s, st, agent = modular(tmp_path)
    m = live(st, rule(hooks=["on_action"], proposes=["state"]), "def on_action(ctx):\n    return {'reply': ctx['action'] + ': ' + ctx['args']['purpose']}\n")
    st.update_module(m["id"], offers=[{"name": "pat", "help": "x"}])
    assert await M.act(st, s, agent.runner, st.module(m["id"]), "pat", {"purpose": "kindly"}) == "pat: kindly"


# --- the lifecycle, word for word -------------------------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_proposing_records_everything_and_names_clash(tmp_path):
    s, st, agent = modular(tmp_path)
    t0 = time.time()
    r = await M.propose(st, s, agent.runner, "world", BELLS_MAN, BELLS, "x" * 600)
    m = st.module(r["id"])
    assert t0 <= m["created_at"] <= time.time() and m["subject"] == "" and m["replaces"] is None and len(m["reason"]) == 500
    assert (await M.propose(st, s, agent.runner, "world", rule(kind="thing", name="lamp", subject="Moon Lamp"), BELLS))["error"] == "there is no creation called 'Moon Lamp'"
    for status in ("proposed", "live", "disabled"):
        st.update_module(m["id"], status=status)
        assert (await M.propose(st, s, agent.runner, "world", BELLS_MAN, BELLS))["error"] == "a module called bells already exists; send a new version of it instead"
    st.update_module(m["id"], status="live")
    two = await M.propose(st, s, agent.runner, "world", BELLS_MAN, BELLS, replaces=m["id"], now=NOW)
    assert st.module(two["id"])["replaces"] == m["id"] and st.module(two["id"])["created_at"] == NOW


@pytest.mark.asyncio
async def test_going_live_word_for_word(tmp_path):
    s, st, agent = modular(tmp_path, modules_approval="")
    r = await M.propose(st, s, agent.runner, "world", BELLS_MAN, BELLS, now=NOW)
    m = st.module(r["id"])
    assert m["status"] == "live" and m["decided_at"] == NOW and m["note"] == ""
    ev = next(e for e in st.events(10) if e["kind"] == "module_live")["data"]
    assert ev == {"name": "bells", "author": "world", "version": 1, "by": "auto", "subject": ""}
    st.update_module(m["id"], status="disabled", fails=2)
    await M.approve(st, s, None, m["id"], "x" * 600, now=NOW + 5)                                 # no runner: live, but nothing installs
    m = st.module(m["id"])
    assert m["status"] == "live" and m["fails"] == 0 and len(m["note"]) == 500 and m["decided_at"] == NOW + 5
    assert m["cursor"] == st.events(2)[1]["id"] and st.events(1)[0]["kind"] == "module_live"


@pytest.mark.asyncio
async def test_a_new_version_leaves_rejected_ones_alone(tmp_path):
    s, st, agent = modular(tmp_path)
    one = await M.propose(st, s, agent.runner, "world", BELLS_MAN, BELLS, now=NOW)
    M.reject(st, one["id"])
    two = await M.propose(st, s, agent.runner, "world", BELLS_MAN, BELLS, now=NOW)
    await M.approve(st, s, agent.runner, two["id"], now=NOW)
    assert st.module(one["id"])["status"] == "rejected"


def test_rejecting_and_switching_off_word_for_word(tmp_path):
    s, st, agent = modular(tmp_path)
    m = live(st, BELLS_MAN, BELLS)
    st.update_module(m["id"], status="proposed")
    t0 = time.time()
    assert M.reject(st, m["id"]) == {"id": m["id"], "status": "rejected"}
    got = st.module(m["id"])
    assert got["note"] == "" and t0 <= got["decided_at"] <= time.time()
    assert st.events(1)[0]["kind"] == "module_rejected" and st.events(1)[0]["data"] == {"name": "bells", "author": "world", "version": 1, "note": "", "subject": ""}
    st.update_module(m["id"], status="waiting")
    M.reject(st, m["id"], "n" * 600, now=NOW)
    assert len(st.module(m["id"])["note"]) == 500 and len(st.events(1)[0]["data"]["note"]) == 500 and st.module(m["id"])["decided_at"] == NOW
    st.update_module(m["id"], status="live")
    assert M.disable(st, m["id"]) == {"id": m["id"], "status": "disabled"}
    got = st.module(m["id"])
    assert got["note"] == "" and t0 <= got["decided_at"] <= time.time()
    assert st.events(1)[0]["kind"] == "module_disabled" and st.events(1)[0]["data"] == {"name": "bells", "author": "world", "why": "", "subject": ""}
    st.update_module(m["id"], status="live")
    M.disable(st, m["id"], "w" * 600, now=NOW)
    assert len(st.module(m["id"])["note"]) == 500 and len(st.events(1)[0]["data"]["why"]) == 300 and st.module(m["id"])["decided_at"] == NOW


# --- the dry run, precisely -------------------------------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_the_dry_run_report_precisely(tmp_path):
    s, st, agent = modular(tmp_path)
    st.log("module", name="earlier", text="from before", author="world")
    st.log("garden", plot=1, crop="peas")
    st.log("garden", plot=2, crop="beans")
    src = ("def on_tick(ctx):\n    t0 = ctx['state'].get('t0', ctx['now'] - 900)\n"
           "    return {'log': 'tick ' + str(int(ctx['now'] - t0) // 60), 'state': {'t0': t0}}\n"
           "def on_time(ctx):\n    return {}\n"
           "def on_event(ctx):\n    return {'perceive': 'saw ' + ctx['event']['data']['crop']}\n"
           "def on_install(ctx):\n    return {'offer': [{'name': 'poke', 'help': 'poke it'}]}\n"
           "def on_action(ctx):\n    return {'reply': ctx['args']['purpose']}\n")
    man = rule(hooks=["on_install", "on_tick", "on_event", "on_action"], proposes=["log", "state", "perceive", "offer"], events=["garden"])
    m = live(st, man, src)
    st.update_module(m["id"], status="proposed")
    rep = await M.dry_run(st, s, agent.runner, st.module(m["id"]), NOW)
    ticks = M.DRY_HOURS * 60 // M.DRY_STEP_MINUTES
    step = M.DRY_STEP_MINUTES
    assert rep["logged"][:3] == [f"tick {15 + step * i}" for i in range(3)] and M.PER_DAY["log"] <= len(rep["logged"]) <= ticks   # the budget is per day
    assert rep["perceived"] == ["saw beans"] and rep["replies"] == ["poke: trying it"] and rep["offers"] == ["poke"]
    assert rep["calls"] == 1 + ticks + 1 + 1 and rep["errors"] == [] and rep["clean"] is False         # it logs too much for one day
    assert rep["refused"] and set(rep["refused"]) == {"on_tick: it has used today's 24 `log` lines"}
    assert set(rep) == {"calls", "errors", "refused", "perceived", "logged", "replies", "offers", "slowest_ms", "clean", "placed", "unplaced", "asked", "spoken", "happened"} and 1 <= rep["slowest_ms"] < 5000
    assert [e["data"]["text"] for e in st.events(10) if e["kind"] == "module"] == ["from before"]               # the real world untouched


@pytest.mark.asyncio
async def test_the_dry_run_passes_due_and_is_dirty_when_anything_is_refused(tmp_path):
    s, st, agent = modular(tmp_path)
    src = ("def on_install(ctx):\n    return {'schedule': ctx['now'] + 600}\n"
           "def on_time(ctx):\n    return {'perceive': 'due ' + str(int(ctx['due']) % 3600)}\n"
           "def on_tick(ctx):\n    return {'state': 5}\n")
    m = live(st, rule(hooks=["on_install", "on_time", "on_tick"], proposes=["schedule", "perceive", "state"]), src)
    rep = await M.dry_run(st, s, agent.runner, m, NOW)
    assert rep["perceived"] == ["due 600"] and rep["errors"] == [] and rep["clean"] is False
    assert rep["refused"][0] == "on_tick: `state` is an object of at most 16000 bytes"
    bad = live(st, rule(name="bad"), "def on_tick(ctx):\n    return 1/0\n")
    rep = await M.dry_run(st, s, agent.runner, bad, NOW)
    assert rep["refused"] == [] and rep["clean"] is False and rep["calls"] == M.FAILS_TO_DISABLE


# --- the library ------------------------------------------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_only_clocks_that_need_tending_are_offered_workings_and_every_one_is(tmp_path, monkeypatch, caplog):
    s, st, agent = modular(tmp_path)
    clock(st)
    from tests.test_world_view import TIMEKEEPER
    st.add_creation("Sundial", "a dial", None, "sound", {"capabilities": {"timekeeper": {"drift_per_day": 1}}, "quirks": []}, {})
    st.add_creation("Second Clock", "another", None, "sound", TIMEKEEPER, __import__("app.creations", fromlist=["x"]).initial_runtime(TIMEKEEPER, NOW))
    t0 = time.time()
    made = await M.offer_library(st, s, agent.runner)
    assert [st.module(i)["subject"] for i in made] == [""] * len(M.RULES) + ["Gear Clock", "Second Clock"] and t0 <= st.module(made[0])["created_at"] <= time.time()
    st.add_creation("Third Clock", "a third", None, "sound", TIMEKEEPER, {})
    monkeypatch.setattr(M, "library", lambda name: (json.loads((M.LIBRARY / f"{name}.json").read_text()), "import os"))
    with caplog.at_level(logging.WARNING, logger="app.modules"):
        assert await M.offer_library(st, s, agent.runner) == []
    assert caplog.records[-1].getMessage().startswith("library module for Third Clock refused: line 1: `import os` isn't allowed")
    assert M.slug("--a--b--") == "a-b"


def test_what_the_public_and_the_owner_see_of_a_module(tmp_path):
    s, st, agent = modular(tmp_path)
    m = live(st, BELLS_MAN, BELLS, state={"n": 1})
    st.update_module(m["id"], facts={"f": 1}, fails=1, budget={"day": "d"}, note="hm", report={"clean": True}, reason="why")
    m = st.module(m["id"])
    pub = M.public_row(m)
    assert pub == {"id": m["id"], "name": "bells", "kind": "rule", "author": "world", "subject": "", "status": "live", "version": 1, "reason": "why",
                   "created_at": NOW, "decided_at": None, "offers": [], "hooks": BELLS_MAN["hooks"], "source": BELLS, "manifest": m["manifest"]}
    full = M.public_row(m, full=True)
    assert full == {**pub, "report": {"clean": True}, "note": "hm", "state": {"n": 1}, "facts": {"f": 1}, "fails": 1, "budget": {"day": "d"}}
    for status, shows in (("disabled", True), ("replaced", True), ("waiting", False), ("rejected", False)):
        assert ("source" in M.public_row({**m, "status": status})) is shows


# --- the runner service's answers -------------------------------------------------------------------------------------------
def test_the_runner_service_answers_precisely():
    from http.server import ThreadingHTTPServer
    from app.runner_service import Handler, REQUEST_MAX
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{srv.server_address[1]}"

    def ask(path, body=None, raw=None, headers=None):
        data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
        req = urllib.request.Request(url + path, data=data, method="POST" if data is not None else "GET", headers=headers or {})
        try:
            with urllib.request.urlopen(req) as r:
                return r.status, json.loads(r.read()), r.headers
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read()), e.headers
    try:
        code, body, headers = ask("/healthz")
        assert (code, body, headers["Content-Type"], headers["Content-Length"]) == (200, {"ok": True}, "application/json", str(len(b'{"ok": true}')))
        assert ask("/nope")[:2] == (404, {"error": "not found"}) and ask("/nope", {"a": 1})[:2] == (404, {"error": "not found"})
        assert ask("/run", raw=b"")[:2] == (413, {"ok": False, "error": "request too large"})
        assert ask("/run", raw=b"{")[:2] == (400, {"ok": False, "error": "expected {source, hook, ctx}"})
        assert ask("/run", raw=b"x" * (REQUEST_MAX + 1))[:2] == (413, {"ok": False, "error": "request too large"})
        assert ask("/run", {"source": 1, "hook": "on_tick", "ctx": {}})[0] == 400 and ask("/run", {"source": "x", "hook": 1, "ctx": {}})[0] == 400
        assert ask("/run", {"source": "x", "hook": "on_tick", "ctx": []})[0] == 400
        assert ask("/run", {"source": "x = 1", "hook": "on_tick", "ctx": {}})[:2] == (200, {"ok": True, "missing": True})
        body = json.dumps({"source": "def on_tick(c):\n    return {}", "hook": "on_tick", "ctx": {"p": "x" * 100}}).encode()
        assert ask("/run", raw=body.replace(b'"x', b'"x' + b"y" * (REQUEST_MAX - len(body)), 1))[0] == 200           # exactly the most it takes
    finally:
        srv.shutdown()


def test_the_source_check_edges():
    from app import sandbox as S
    assert S.check("import json.decoder\nfrom json.decoder import JSONDecoder\nimport math")
    assert S.check("x = 1" + " " * (S.SOURCE_MAX - 5))
    for src, msg in (("x = 'a'._x", "line 1: `._x` isn't allowed"), ("", "the code is empty"), ("  \n", "the code is empty"),
                     ("from os import path", "line 1: `from os import` isn't allowed; you may import " + ", ".join(S.IMPORTS)),
                     ("from . import x", "line 1: `from . import` isn't allowed; you may import " + ", ".join(S.IMPORTS))):
        with pytest.raises(S.Rejected) as e:
            S.check(src)
        assert str(e.value) == msg
