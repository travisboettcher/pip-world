"""Modules, step 1 (docs/DESIGN-modules.md): the sandbox, the referee, the lifecycle, and the clock's workings as a module."""
import json
import threading
import time
import urllib.request

import pytest
from fastapi.testclient import TestClient

from app import modules as M
from app import sandbox as S
from app import creations as cr
from app.config import Settings
from app.llm.fake import FakeBackend
from app.main import create_app
from tests.test_projects import call, make
from tests.test_world_view import clock

NOW = 1_800_000_000.0


def modular(tmp_path, **kw):
    kw.setdefault("modules", "on")
    kw.setdefault("module_runner", "local")
    s, st, gm, agent = make(tmp_path, **kw)
    agent.tools.update({n: __import__("app.tools", fromlist=["REGISTRY"]).REGISTRY[n] for n in ("tend", "use_item")})
    return s, st, agent


def rule(name="bells", hooks=("on_tick",), proposes=("state", "perceive"), **extra):
    return {"name": name, "kind": "rule", "api": 1, "hooks": list(hooks), "reads": ["time"], "proposes": list(proposes), **extra}


def live(st, manifest, source, author="world", state=None):
    """A module put straight into the store as live (no dry run), for testing the referee."""
    mid = st.add_module(name=manifest["name"], kind=manifest["kind"], author=author, api=1, subject=manifest.get("subject", ""),
                        manifest=M.check_manifest(manifest, author), source=source, status="live", created_at=NOW, state=state or {})
    return st.module(mid)


# --- the sandbox ------------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("source,why", [
    ("", "the code is empty"),
    ("x" * (S.SOURCE_MAX + 1), "too long"),
    ("def f(:\n  pass", "line 1:"),
    ("import os", "`import os` isn't allowed; you may import math"),
    ("from subprocess import run", "`from subprocess import` isn't allowed"),
    ("from . import x", "`from . import` isn't allowed"),
    ("import os.path", "`import os.path` isn't allowed"),
    ("x = open('f')", "`open` isn't allowed"),
    ("x = __builtins__", "`__builtins__` isn't allowed"),
    ("x = ().__class__", "`.__class__` isn't allowed"),
    ("x = 'a'._x", "`._x` isn't allowed"),
    ("x = '{0}'.format(1)", "`.format` isn't allowed; use an f-string"),
    ("x = '{a}'.format_map({})", "`.format_map` isn't allowed"),
    ("def f():\n    global y", "line 2: `global` isn't allowed"),
    ("def f():\n    x = 1\n    def g():\n        nonlocal x", "`nonlocal` isn't allowed"),
    ("x = getattr(1, 'real')", "`getattr` isn't allowed"),
    ("x = type(1)", "`type` isn't allowed"),
])
def test_the_source_is_read_before_it_runs_and_problems_are_named(source, why):
    with pytest.raises(S.Rejected) as e:
        S.check(source)
    assert why in str(e.value)


def test_allowed_code_passes_the_check():
    tree = S.check("import math\nfrom collections import Counter\ndef on_tick(ctx):\n    return {'state': {'n': math.floor(2.5)}}")
    assert len(tree.body) == 3 and S.check("import datetime\nfrom json import dumps")


@pytest.mark.asyncio
async def test_a_hook_runs_in_a_limited_subprocess_and_answers_in_json():
    r = await S.run("import math\nfrom dataclasses import dataclass\n@dataclass\nclass P:\n    x: int\n"
                    "def on_tick(ctx):\n    return {'state': {'n': ctx['n'] + P(1).x, 'r': math.sqrt(4)}}", "on_tick", {"n": 1})
    assert r == {"ok": True, "result": {"state": {"n": 2, "r": 2.0}}}
    assert await S.run("x = 1", "on_tick", {}) == {"ok": True, "missing": True}
    assert await S.run("def on_tick(ctx):\n    pass", "on_tick", {}) == {"ok": True, "result": {}}
    assert await S.run("def on_tick(ctx):\n    return 1/0", "on_tick", {}) == {"ok": False, "error": "line 2: ZeroDivisionError: division by zero"}
    assert await S.run("def on_tick(ctx):\n    return [1]", "on_tick", {}) == {"ok": False, "error": "on_tick must return a dict (or nothing), not list"}
    assert await S.run("def on_tick(ctx):\n    return {'a': {1}}", "on_tick", {}) == {"ok": False, "error": "TypeError: Object of type set is not JSON serializable"}
    assert await S.run("import os", "on_tick", {}) == {"ok": False, "error": "line 1: `import os` isn't allowed; you may import " + ", ".join(S.IMPORTS)}
    assert await S.run("def on_tick(ctx):\n    raise KeyError('x')", "on_tick", {}) == {"ok": False, "error": "line 2: KeyError: 'x'"}
    assert await S.run("x = 1/0", "on_tick", {}) == {"ok": False, "error": "line 1: ZeroDivisionError: division by zero"}
    assert await S.run("def on_tick(ctx):\n    import json\n    return {'a': json.loads(ctx['m'])}", "on_tick", {"m": "[1]"}) == {"ok": True, "result": {"a": [1]}}
    assert (await S.run("def on_tick(ctx):\n    return {'a': open}", "on_tick", {}))["error"] == "line 2: `open` isn't allowed"


@pytest.mark.asyncio
async def test_runaway_code_is_stopped():
    spin = await S.run("def on_tick(ctx):\n    while True:\n        pass", "on_tick", {})
    assert spin in ({"ok": False, "error": "it used more than its share of time"},                       # the CPU limit, usually;
                    {"ok": False, "error": f"it took longer than {S.WALL_SECONDS:g} seconds"})           # the clock, on a very busy machine
    assert await S.run("def on_tick(ctx):\n    x = [0] * (10 ** 9)", "on_tick", {}) == {"ok": False, "error": "line 2: MemoryError: "}
    assert (await S.run("def on_tick(ctx):\n    x = [0] * (10 ** 7)\n    return {'n': len(x)}", "on_tick", {}))["result"] == {"n": 10 ** 7}
    size = S.OUTPUT_MAX - len('{"ok": true, "result": {"a": ""}}')
    assert (await S.run(f"def on_tick(ctx):\n    return {{'a': 'x' * {size}}}", "on_tick", {}))["ok"]                   # exactly the most it may return
    assert await S.run(f"def on_tick(ctx):\n    return {{'a': 'x' * {size + 1}}}", "on_tick", {}) == {"ok": False, "error": f"it returned too much ({S.OUTPUT_MAX + 1} bytes; at most {S.OUTPUT_MAX})"}


def test_the_child_starts_isolated_with_its_limits():
    import sys
    args = S.spawn_args()
    assert args[:4] == [sys.executable, "-I", "-S", "-c"] and args[4] == S.CHILD and args[5:] == [",".join(S.IMPORTS), "1", str(512 * 2 ** 20)]
    import resource
    import subprocess
    probe = S.CHILD.split("def guarded_import")[0] + "\nprint([resource.getrlimit(r)[0] for r in (resource.RLIMIT_CPU, resource.RLIMIT_AS, resource.RLIMIT_FSIZE, resource.RLIMIT_NOFILE)])"
    out = subprocess.run([sys.executable, "-I", "-S", "-c", probe, "math", "1", str(512 * 2 ** 20)], capture_output=True, text=True).stdout
    assert out.strip() == f"[1, {512 * 2 ** 20}, 0, 64]"


@pytest.mark.asyncio
async def test_the_child_gets_only_a_path_and_runs_from_the_root(monkeypatch):
    import asyncio
    seen = {}
    real = asyncio.create_subprocess_exec

    async def spy(*args, **kw):
        seen.update(kw, args=args)
        return await real(*args, **kw)
    monkeypatch.setattr(asyncio, "create_subprocess_exec", spy)
    monkeypatch.setenv("SECRET_KEY", "x")
    await S.run("def on_tick(ctx):\n    return {}", "on_tick", {})
    assert seen["env"] == {"PATH": __import__("os").environ["PATH"]} and seen["cwd"] == "/" and seen["stderr"] == asyncio.subprocess.DEVNULL
    assert list(seen["args"]) == S.spawn_args() and "preexec_fn" not in seen
    monkeypatch.delenv("PATH")
    await S.run("def on_tick(ctx):\n    return {}", "on_tick", {})
    assert seen["env"] == {"PATH": ""}


@pytest.mark.asyncio
async def test_a_child_that_misbehaves_is_described(monkeypatch):
    import sys

    def child(code):
        monkeypatch.setattr(S, "spawn_args", lambda: [sys.executable, "-c", code])
    child("import sys; sys.stdin.read(); print('nope')")
    assert await S.run("x = 1", "on_tick", {}) == {"ok": False, "error": "what it returned isn't JSON (only plain numbers, strings, lists and dicts)"}
    child("import sys; sys.stdin.read(); print('[1]')")
    assert await S.run("x = 1", "on_tick", {}) == {"ok": False, "error": "it returned something unreadable"}
    child("import sys; sys.stdin.read(); print('{\"error\": 1}')")
    assert await S.run("x = 1", "on_tick", {}) == {"ok": False, "error": "it returned something unreadable"}
    child("import sys; sys.stdin.read(); sys.exit(3)")
    assert await S.run("x = 1", "on_tick", {}) == {"ok": False, "error": "it stopped without answering"}
    child("import os, signal, sys; sys.stdin.read(); os.kill(os.getpid(), signal.SIGKILL)")
    assert await S.run("x = 1", "on_tick", {}) == {"ok": False, "error": "it used more than its share of time"}
    child("import os, signal, sys; sys.stdin.read(); os.kill(os.getpid(), signal.SIGXCPU)")
    assert await S.run("x = 1", "on_tick", {}) == {"ok": False, "error": "it used more than its share of time"}
    child("import os, signal, sys; sys.stdin.read(); os.kill(os.getpid(), signal.SIGTERM)")
    assert await S.run("x = 1", "on_tick", {}) == {"ok": False, "error": "it stopped without answering"}
    child("import sys, time; sys.stdin.read(); time.sleep(10)")
    monkeypatch.setattr(S, "WALL_SECONDS", 0.3)
    assert await S.run("x = 1", "on_tick", {}) == {"ok": False, "error": "it took longer than 0.3 seconds"}


@pytest.mark.asyncio
async def test_the_runner_service_runs_hooks_over_http_and_a_unix_socket(tmp_path):
    from http.server import ThreadingHTTPServer
    from app.runner_service import Handler
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{srv.server_address[1]}"
    try:
        assert json.loads(urllib.request.urlopen(url + "/healthz").read()) == {"ok": True}
        r = await M.HttpRunner(url + "/").run("def on_tick(ctx):\n    return {'state': {'x': ctx['x']}}", "on_tick", {"x": 3})
        assert r == {"ok": True, "result": {"state": {"x": 3}}}
        bad = urllib.request.Request(url + "/run", data=json.dumps({"source": "x", "hook": "eval", "ctx": {}}).encode(), method="POST")
        with pytest.raises(urllib.error.HTTPError) as e:
            urllib.request.urlopen(bad)
        assert e.value.code == 400
    finally:
        srv.shutdown()
    sock = str(tmp_path / "runner.sock")
    from app.runner_service import serve_socket
    usrv = serve_socket(sock)
    threading.Thread(target=usrv.serve_forever, daemon=True).start()
    try:
        assert oct(__import__("os").stat(sock).st_mode & 0o777) == "0o666"
        r = await M.HttpRunner(f"unix://{sock}").run("def on_tick(ctx):\n    return {'state': {'y': 1}}", "on_tick", {})
        assert r == {"ok": True, "result": {"state": {"y": 1}}}
        usrv.shutdown()
        usrv.server_close()
        assert serve_socket(sock).server_address == sock                         # a stale socket is replaced
    finally:
        usrv.server_close()
    down = await M.HttpRunner("http://127.0.0.1:9").run("x", "on_tick", {})
    assert down["ok"] is False and down["runner_down"] and "couldn't be reached" in down["error"]


def test_the_runner_comes_from_the_settings():
    assert M.runner_for(Settings(modules="off", module_runner="local")) is None
    assert M.runner_for(Settings(modules="on", module_runner="")) is None
    assert M.runner_for(Settings(modules="on", module_runner="local")).name == "local"
    r = M.runner_for(Settings(modules="on", module_runner="http://pip-runner:8100"))
    assert r.name == "http" and r.url == "http://pip-runner:8100" and r.socket is None
    assert M.runner_for(Settings(modules="on", module_runner="unix:///run/pip-runner/runner.sock")).socket == "/run/pip-runner/runner.sock"


def test_module_settings_from_the_environment(monkeypatch):
    s = Settings.from_env()
    assert (s.modules, s.module_runner, s.modules_approval) == ("on", "", "world,pip")
    monkeypatch.setenv("MODULES", "off")
    monkeypatch.setenv("MODULE_RUNNER", "http://pip-runner:8100")
    monkeypatch.setenv("MODULES_APPROVAL", "")
    s = Settings.from_env()
    assert (s.modules, s.module_runner, s.modules_approval) == ("off", "http://pip-runner:8100", "")
    monkeypatch.setenv("MODULES", "sideways")
    assert Settings.from_env().modules == "on" and Settings().modules == "off"


# --- manifests --------------------------------------------------------------------------------------------------------------
def test_a_manifest_is_held_to_what_the_engine_offers(tmp_path):
    s, st, agent = modular(tmp_path)
    ok = M.check_manifest(rule(events=[], extra="ignored"), "world")
    assert ok == {"name": "bells", "kind": "rule", "api": 1, "hooks": ["on_tick"], "reads": ["time"], "proposes": ["state", "perceive"],
                  "events": [], "consumes": {}}

    def bad(m, author="world"):
        with pytest.raises(M.Refused) as e:
            M.check_manifest(m, author, st)
        return str(e.value)
    assert bad([]) == "the manifest must be an object" and bad(rule(), "god") == "unknown author 'god'"
    assert "`name` is 3 to 40" in bad(rule(name="X!")) and "`name`" in bad(rule(name="ab")) and "`kind` is one of thing, rule" in bad(rule(kind="place"))
    assert bad(rule(api=2)) == "`api` must be 1" and "`hooks` is a list drawn from" in bad(rule(hooks=["on_boot"]))
    assert "`reads` is a list" in bad(rule(reads="time")) and "`proposes` is a list" in bad(rule(proposes=["transfer"]))
    assert bad(rule(hooks=[])) == "`hooks` needs at least one hook"
    assert "a thing needs a `subject`" in bad(rule(kind="thing")) and bad(rule(kind="thing", subject="Moon Lamp")) == "there is no creation called 'Moon Lamp'"
    assert "only a thing has a subject" in bad(rule(subject="x")) and "only a thing" in bad(rule(reads=["subject"])) and "only a thing" in bad(rule(proposes=["runtime"]))
    assert "`events` is a list of public event kinds" in bad(rule(hooks=["on_event"], events=["inbox"]))
    assert "`on_event` and `events` go together" in bad(rule(hooks=["on_event"])) and "go together" in bad(rule(events=["garden"]))
    assert M.check_manifest(rule(hooks=["on_event"], events=["garden"]), "world")["events"] == ["garden"]
    assert "`consumes` maps item names" in bad(rule(proposes=["consume"], consumes={"oil": 6})) and "`consumes`" in bad(rule(proposes=["consume"], consumes={"oil": True}))
    assert "`consume` and `consumes` go together" in bad(rule(proposes=["consume"])) and "go together" in bad(rule(consumes={"oil": 1}))
    assert "`tends` is the name" in bad(rule(tends="tend"))
    clock(st)
    thing = M.check_manifest(rule(kind="thing", subject="gear clock", tends="wind it", hooks=["on_tick", "on_tick"]), "pip", st)
    assert thing["subject"] == "gear clock" and thing["tends"] == "wind it" and thing["hooks"] == ["on_tick"]
    assert "`tends`" in bad(rule(kind="thing", subject="Gear Clock", tends="Wind!"))


# --- the referee ------------------------------------------------------------------------------------------------------------
def test_proposals_are_checked_together_and_refused_with_a_reason(tmp_path):
    s, st, agent = modular(tmp_path)
    m = live(st, rule(proposes=list(M.PROPOSES[:6])), "x")

    def refused(result, hook="on_tick"):
        with pytest.raises(M.Refused) as e:
            M.plan(st, m, result, NOW, hook)
        return str(e.value)
    assert refused({"runtime": {}}) == "it returned runtime, which its manifest doesn't propose"
    assert refused({"reply": "hi"}) == "only on_action can reply" and M.plan(st, m, {"state": {}}, NOW, "on_tick") == [("state", {})]
    assert "`state` is an object of at most" in refused({"state": [1]}) and "at most" in refused({"state": {"x": "y" * M.STATE_MAX}})
    assert "`publish` is an object" in refused({"publish": "x"}) and "`publish`" in refused({"publish": {"x": "y" * M.FACTS_MAX}})
    assert refused({"perceive": ""}) == "`perceive` is a line of text" and "at most 200 characters" in refused({"log": "x" * 201})
    assert "`schedule` is a time" in refused({"schedule": NOW - 61}) and "`schedule`" in refused({"schedule": True})
    assert M.plan(st, m, {"schedule": NOW - 30}, NOW, "on_tick") == [("due", NOW - 30)] and M.plan(st, m, {"schedule": None}, NOW, "on_tick") == []
    assert "`offer` is a list of at most 4" in refused({"offer": [{"name": "Ring!", "help": "x"}]})
    assert "`offer`" in refused({"offer": [{"name": "ring", "help": "x"}] * 5}) and "`offer`" in refused({"offer": [{"name": "ring"}]})
    assert "`offer`" in refused({"offer": "ring"})
    full = M.plan(st, m, {"state": {"a": 1}, "publish": {"b": 2}, "perceive": " the bells ring ", "log": "Bells.", "schedule": NOW + 60,
                          "offer": [{"name": "ring", "help": "pull the rope"}]}, NOW, "on_tick")
    assert full == [("state", {"a": 1}), ("facts", {"b": 2}), ("perceive", "the bells ring"), ("log", "Bells."), ("due", NOW + 60),
                    ("offers", [{"name": "ring", "help": "pull the rope"}])]
    m["budget"] = {"day": M._day(NOW), "perceive": M.PER_DAY["perceive"], "log": M.PER_DAY["log"], "wake": M.PER_DAY["wake"]}
    assert refused({"perceive": "x"}) == "it has used today's 12 `perceive` lines" and "24 `log` lines" in refused({"log": "x"})
    m["manifest"]["proposes"].append("wake")
    assert refused({"wake": True}) == "it has woken Pip 4 times today" and M.plan(st, m, {"wake": False}, NOW, "on_tick") == []
    m["budget"]["day"] = "2000-01-01"                                                  # a new day, a new budget
    assert M.plan(st, m, {"wake": True, "perceive": "x"}, NOW, "on_tick") == [("perceive", "x"), ("wake", True)]


def test_consuming_and_runtime_are_limited_to_what_the_thing_may_touch(tmp_path):
    s, st, agent = modular(tmp_path)
    clock(st)
    st.add_item("brass wire", 3, "material", "")
    st.add_item("oil", 1, "material", "")
    m = live(st, rule(kind="thing", subject="Gear Clock", hooks=["on_action"], proposes=["consume", "runtime"], consumes={"brass wire": 2}), "x")

    def refused(result):
        with pytest.raises(M.Refused) as e:
            M.plan(st, m, result, NOW, "on_action")
        return str(e.value)
    assert refused({"consume": ["brass wire"]}) == "`consume` maps item names to quantities"
    assert refused({"consume": {"oil": 1}}) == "its manifest doesn't let it use up oil"
    assert refused({"consume": {"brass wire": 3}}) == "it may use up 1 to 2 brass wire at a time" and "1 to 2" in refused({"consume": {"brass wire": True}})
    m["manifest"]["consumes"] = {"*": 5}
    assert refused({"consume": {"oil": 2}}) == "you need 2 oil for that" and refused({"consume": {"glue": 1}}) == "you need 1 glue for that"
    assert M.plan(st, m, {"consume": {"Brass Wire": 2}}, NOW, "on_action")[0][1][0][1:] == (2, "brass wire")
    assert refused({"runtime": []}) == "`runtime` maps runtime fields to values"
    assert refused({"runtime": {"made_at": 1}}).startswith("`runtime` can only set: clock_set_at")
    assert refused({"runtime": {"tended_until": "soon"}}) == "`runtime.tended_until` must be a number (or null to clear it)"
    assert "must be a bool" in refused({"runtime": {"stop_logged": 1}}) and "must be a number" in refused({"runtime": {"clock_offset": True}})
    assert "must be a part" in refused({"runtime": {"needs_part": {"name": "x"}}}) and "must be a part" in refused({"runtime": {"needs_part": "x"}})
    ok = {"tended_until": 5, "clock_offset": 1.5, "stop_logged": True, "halted_at": None, "needs_part": {"name": "cog", "qty": 1}}
    assert M.plan(st, m, {"runtime": ok}, NOW, "on_action") == [("runtime", ok)]


@pytest.mark.asyncio
async def test_a_call_applies_everything_or_nothing_and_keeps_a_history(tmp_path):
    s, st, agent = modular(tmp_path)
    clock(st)
    st.add_item("brass wire", 3, "material", "")
    src = ("def on_action(ctx):\n    return {'state': {'n': ctx['state'].get('n', 0) + 1}, 'consume': {'brass wire': ctx['args']['n']},"
           " 'runtime': {'halted_at': None, 'stop_logged': True}, 'perceive': 'tick', 'log': 'It whirrs.', 'wake': True, 'reply': 'whirr',"
           " 'publish': {'n': 1}, 'offer': [{'name': 'whirr', 'help': 'make it whirr'}], 'schedule': ctx['now'] + 60}\n")
    man = rule(kind="thing", subject="Gear Clock", hooks=["on_action"], proposes=list(M.PROPOSES), consumes={"brass wire": 2})
    m = live(st, man, src)
    c = cr.tend(st, st.creations()[0], NOW) and st.creations()[0]
    st.set_runtime(c["id"], {**c["runtime"], "halted_at": NOW})
    r = await M.call(st, s, agent.runner, m, "on_action", NOW, action="whirr", args={"n": 3})
    assert r["refused"] == "it may use up 1 to 2 brass wire at a time" and r["ok"] and not r["wake"]
    assert st.module(m["id"])["state"] == {} and st.find_item("brass wire")[0]["qty"] == 3                      # nothing applied
    r = await M.call(st, s, agent.runner, m, "on_action", NOW, action="whirr", args={"n": 2})
    assert r == {"ok": True, "error": "", "refused": "", "wake": True, "reply": "whirr"}
    got = st.module(m["id"])
    assert got["state"] == {"n": 1} and got["facts"] == {"n": 1} and got["due"] == NOW + 60 and got["lines"] == [{"ts": NOW, "text": "tick"}]
    assert got["offers"] == [{"name": "whirr", "help": "make it whirr"}] and got["budget"] == {"day": M._day(NOW), "calls": 1, "perceive": 1, "log": 1, "wake": 1}
    assert st.find_item("brass wire")[0]["qty"] == 1 and "halted_at" not in st.creations()[0]["runtime"] and st.creations()[0]["runtime"]["stop_logged"]
    ev = [e for e in st.events(5) if e["kind"] == "module"][0]["data"]
    assert (ev["name"], ev["text"], ev["author"]) == ("bells", "It whirrs.", "world")
    calls = st.module_calls(m["id"])
    assert [c["summary"] for c in calls] == ["state, facts, perceive, log, wake, due, offers, consume, runtime, reply",
                                              "refused: it may use up 1 to 2 brass wire at a time"]
    assert [c["ok"] for c in calls] == [True, False] and calls[0]["hook"] == "on_action" and calls[0]["ts"] == NOW


@pytest.mark.asyncio
async def test_failing_code_is_switched_off_after_three_failures_in_a_row(tmp_path):
    s, st, agent = modular(tmp_path)
    m = live(st, rule(), "def on_tick(ctx):\n    if ctx['state'].get('ok'):\n        return {}\n    return 1/0\n")
    for i in range(2):
        r = await M.call(st, s, agent.runner, m, "on_tick", NOW)
        assert r["error"] == "line 4: ZeroDivisionError: division by zero" and st.module(m["id"])["fails"] == i + 1
    st.update_module(m["id"], state={"ok": True})
    m = st.module(m["id"])
    assert (await M.call(st, s, agent.runner, m, "on_tick", NOW))["ok"] and st.module(m["id"])["fails"] == 0   # a success resets the count
    st.update_module(m["id"], state={})
    m = st.module(m["id"])
    for _ in range(3):
        await M.call(st, s, agent.runner, m, "on_tick", NOW)
    got = st.module(m["id"])
    assert got["status"] == "disabled" and got["note"] == "its code failed 3 times in a row: line 4: ZeroDivisionError: division by zero"
    assert [e["kind"] for e in st.events(3)][0] == "module_disabled"
    assert (await M.step(st, s, agent.runner, NOW)) is False and len(st.module_calls(m["id"])) == 6       # off: it no longer runs


@pytest.mark.asyncio
async def test_a_day_has_a_call_budget_and_a_down_runner_costs_nothing(tmp_path):
    s, st, agent = modular(tmp_path)
    m = live(st, rule(), "def on_tick(ctx):\n    return {}\n")
    m["budget"] = {"day": M._day(NOW), "calls": M.PER_DAY["calls"]}
    r = await M.call(st, s, agent.runner, m, "on_tick", NOW)
    assert r["refused"] == "it has used today's 600 calls" and st.module_calls(m["id"]) == []

    class Down:
        async def run(self, *a):
            return {"ok": False, "error": "the runner couldn't be reached (ConnectError)", "runner_down": True}
    m["budget"] = {}
    for _ in range(4):
        await M.call(st, s, Down(), m, "on_tick", NOW)
    assert st.module(m["id"])["status"] == "live" and st.module(m["id"])["fails"] == 0 and st.module_calls(m["id"]) == []


# --- the step: time, events, ticks; and what Pip hears ----------------------------------------------------------------------
@pytest.mark.asyncio
async def test_the_step_runs_due_times_events_and_ticks_and_pip_hears_each_line_once(tmp_path):
    s, st, agent = modular(tmp_path)
    src = ("def on_time(ctx):\n    return {'perceive': 'the bell for ' + str(ctx['due']), 'schedule': ctx['now'] + 3600, 'wake': True}\n"
           "def on_event(ctx):\n    e = ctx['event']\n    return {'log': 'noticed ' + e['kind'] + ' ' + e['data']['crop']}\n"
           "def on_tick(ctx):\n    return {'state': {'ticks': ctx['state'].get('ticks', 0) + 1, 'hour': ctx['time']['hour']}}\n")
    man = rule(hooks=["on_time", "on_event", "on_tick"], proposes=["state", "perceive", "schedule", "wake", "log"], events=["garden"])
    m = live(st, man, src)
    st.log("garden", plot=1, crop="peas")                                         # before it was watching: not its business
    st.update_module(m["id"], cursor=st.events(1)[0]["id"], due=NOW - 5)
    st.log("garden", plot=2, crop="beans")
    st.log("say", text="hello")                                                   # not a kind it listens for
    assert await M.step(st, s, agent.runner, NOW) is True
    got = st.module(m["id"])
    assert got["due"] == NOW + 3600 and got["state"]["ticks"] == 1 and got["cursor"] == st.events(1)[0]["id"] - 1
    assert [e["data"]["text"] for e in st.events(10) if e["kind"] == "module"] == ["noticed garden beans"]
    assert M.perception(st) == ["Things in the world:", f"- the bell for {NOW - 5}"] and M.perception(st) == []
    assert await M.step(st, s, agent.runner, NOW + 60) is False and st.module(m["id"])["state"]["ticks"] == 2
    assert await M.step(st, s, None, NOW + 9999) is False and st.module(m["id"])["state"]["ticks"] == 2


@pytest.mark.asyncio
async def test_a_due_time_that_isnt_renewed_is_cleared(tmp_path):
    s, st, agent = modular(tmp_path)
    m = live(st, rule(hooks=["on_time"], proposes=["state"]), "def on_time(ctx):\n    return {'state': {'rang': True}}\n")
    st.update_module(m["id"], due=NOW - 1)
    await M.step(st, s, agent.runner, NOW)
    assert st.module(m["id"])["due"] is None and st.module(m["id"])["state"] == {"rang": True}


def test_the_context_holds_only_what_the_manifest_reads(tmp_path):
    s, st, agent = modular(tmp_path)
    clock(st)
    st.add_item("oil", 2, "material", "")
    st.update_agent(location="library", activity="reading")
    other = live(st, rule(name="fair", proposes=["publish"]), "x")
    st.update_module(other["id"], facts={"fair_today": True})
    bare = M.context(st, s, live(st, rule(name="bare", reads=[]), "x"), NOW, due=5)
    assert set(bare) == {"now", "seed", "state", "offers", "due"} and bare["seed"] == int(NOW) * 7919 + 2
    full = M.context(st, s, live(st, rule(kind="thing", name="all", subject="Gear Clock", reads=list(M.READS)), "x"), NOW)
    assert full["time"]["weekday"] and full["time"]["season"] in ("spring", "summer", "autumn", "winter") and 0 <= full["time"]["hour"] < 24
    assert full["pip"] == {"where": "library", "at_home": False, "activity": "reading", "asleep": False} and full["weather"] is None
    assert full["subject"]["name"] == "Gear Clock" and full["subject"]["capabilities"]["timekeeper"] == {"drift_per_day": 5}
    assert {"name": "oil", "qty": 2, "kind": "material"} in full["items"] and full["facts"] == {"fair": {"fair_today": True}}


# --- the lifecycle ----------------------------------------------------------------------------------------------------------
BELLS = ("def on_install(ctx):\n    return {'offer': [{'name': 'ring', 'help': 'ring the bell'}], 'schedule': ctx['now'] + 3600}\n"
         "def on_time(ctx):\n    return {'perceive': 'A bell rings somewhere.', 'schedule': ctx['now'] + 3 * 3600}\n"
         "def on_action(ctx):\n    return {'reply': 'you ring the bell'}\n")
BELLS_MAN = rule(hooks=["on_install", "on_time", "on_action"], proposes=["offer", "schedule", "perceive"])


@pytest.mark.asyncio
async def test_a_proposal_is_dry_run_and_waits_for_the_owner(tmp_path):
    s, st, agent = modular(tmp_path)
    r = await M.propose(st, s, agent.runner, "world", BELLS_MAN, BELLS, "a bell for the hours", now=NOW)
    m = st.module(r["id"])
    assert r["status"] == "waiting" and m["status"] == "waiting" and m["version"] == 1 and m["reason"] == "a bell for the hours"
    rep = r["report"]
    assert rep["clean"] and rep["errors"] == [] and rep["refused"] == [] and rep["offers"] == ["ring"] and rep["replies"] == ["ring: you ring the bell"]
    rings = len(range(1, M.DRY_HOURS, 3))                                                    # an hour in, then every three
    assert rep["perceived"] == ["A bell rings somewhere."] * rings and rep["calls"] == 1 + rings + 1
    assert m["offers"] == [] and m["due"] is None and st.module_calls(m["id"]) == []         # the dry run touched only its copy
    assert "already exists" in (await M.propose(st, s, agent.runner, "world", BELLS_MAN, BELLS, now=NOW))["error"]
    assert (await M.propose(st, s, agent.runner, "world", {**BELLS_MAN, "kind": "place"}, BELLS))["error"].startswith("`kind`")
    assert (await M.propose(st, s, agent.runner, "world", BELLS_MAN, "import os"))["error"].startswith("line 1: `import os`")
    ok = await M.approve(st, s, agent.runner, m["id"], "lovely", now=NOW)
    m = st.module(m["id"])
    assert ok == {"id": m["id"], "status": "live"} and m["status"] == "live" and m["note"] == "lovely" and m["decided_at"] == NOW
    assert m["offers"] == [{"name": "ring", "help": "ring the bell"}] and m["due"] == NOW + 3600                # installed
    assert st.events(1)[0]["kind"] == "module_live" and st.events(1)[0]["data"]["by"] == "owner"
    assert (await M.approve(st, s, agent.runner, m["id"]))["error"] == "only a waiting or disabled module can go live"
    assert M.reject(st, m["id"])["error"] == "only a waiting module can be rejected"


@pytest.mark.asyncio
async def test_a_new_version_replaces_the_old_when_it_goes_live(tmp_path):
    s, st, agent = modular(tmp_path)
    one = await M.propose(st, s, agent.runner, "world", BELLS_MAN, BELLS, now=NOW)
    await M.approve(st, s, agent.runner, one["id"], now=NOW)
    assert "no module #99" in (await M.propose(st, s, agent.runner, "world", BELLS_MAN, BELLS, replaces=99))["error"]
    assert (await M.propose(st, s, agent.runner, "pip", BELLS_MAN, BELLS, replaces=one["id"]))["error"] == "your programs make one of your creations work"
    two = await M.propose(st, s, agent.runner, "world", BELLS_MAN, BELLS.replace("ring the bell", "ring it"), replaces=one["id"], now=NOW)
    assert st.module(two["id"])["version"] == 2 and st.module(one["id"])["status"] == "live"
    await M.approve(st, s, agent.runner, two["id"], now=NOW)
    assert st.module(one["id"])["status"] == "replaced" and [m["id"] for m in st.modules("live")] == [two["id"]]


@pytest.mark.asyncio
async def test_rejecting_disabling_and_turning_back_on(tmp_path):
    s, st, agent = modular(tmp_path)
    r = await M.propose(st, s, agent.runner, "world", BELLS_MAN, BELLS, now=NOW)
    assert M.reject(st, r["id"], "not yet", now=NOW) == {"id": r["id"], "status": "rejected"}
    assert st.module(r["id"])["note"] == "not yet" and st.events(1)[0]["data"]["note"] == "not yet"
    assert M.disable(st, r["id"])["error"] == "only a live module can be switched off"
    again = await M.propose(st, s, agent.runner, "world", BELLS_MAN, BELLS, now=NOW)            # a rejected name may be proposed afresh
    await M.approve(st, s, agent.runner, again["id"], now=NOW)
    assert M.disable(st, again["id"], "too loud") == {"id": again["id"], "status": "disabled"} and st.module(again["id"])["note"] == "too loud"
    await M.approve(st, s, agent.runner, again["id"], now=NOW)
    assert st.module(again["id"])["status"] == "live"


@pytest.mark.asyncio
async def test_without_approval_a_clean_module_goes_live_and_a_dirty_one_still_waits(tmp_path):
    s, st, agent = modular(tmp_path, modules_approval="pip")
    assert M.needs_approval(s, "pip") and not M.needs_approval(s, "world")
    r = await M.propose(st, s, agent.runner, "world", BELLS_MAN, BELLS, now=NOW)
    assert r["status"] == "live" and [e["data"]["by"] for e in st.events(5) if e["kind"] == "module_live"] == ["auto"]
    assert st.module(r["id"])["offers"]
    bad = await M.propose(st, s, agent.runner, "world", rule(name="broken"), "def on_tick(ctx):\n    return 1/0\n", now=NOW)
    assert bad["status"] == "waiting" and not bad["report"]["clean"] and bad["report"]["errors"][0] == "on_tick: line 2: ZeroDivisionError: division by zero"
    assert len(bad["report"]["errors"]) == M.FAILS_TO_DISABLE
    none = await M.propose(st, s, None, "world", rule(name="norunner"), BELLS, now=NOW)
    assert none["status"] == "waiting" and none["report"] == {"skipped": "no runner"}


# --- the clock's workings as a module ---------------------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_the_world_offers_a_clock_its_workings_once(tmp_path):
    s, st, agent = modular(tmp_path)
    assert await M.offer_library(st, s, None) == []
    c = clock(st)
    st.add_creation("Paperweight", "a stone", None, "sound", {"capabilities": {}, "quirks": []}, {})
    made = await M.offer_library(st, s, agent.runner, now=NOW)
    assert [st.module(i)["name"] for i in made] == ["gallery-wall", "stall-pictures", "gear-clock-workings"]
    m = st.module(made[2])
    assert (m["name"], m["author"], m["subject"], m["status"]) == ("gear-clock-workings", "world", "Gear Clock", "waiting")
    assert m["report"]["clean"] and m["report"]["offers"] == ["tend", "set"] and "clockwork as code" in m["reason"]
    M.reject(st, m["id"])
    assert await M.offer_library(st, s, agent.runner, now=NOW) == []                                   # once, whatever was decided
    assert M.slug("Gear Clock!! (big)") == "gear-clock-big" and M.slug("!!") == "thing" and len(M.slug("x" * 50)) == 28


async def clockwork(tmp_path, **kw):
    s, st, agent = modular(tmp_path, **kw)
    c = clock(st, NOW)
    mid = [i for i in await M.offer_library(st, s, agent.runner, now=NOW) if st.module(i)["subject"]][0]
    await M.approve(st, s, agent.runner, mid, now=NOW)
    return s, st, agent, st.module(mid)


@pytest.mark.asyncio
async def test_the_clock_module_notices_it_stopping_once_instead_of_the_engine(tmp_path):
    s, st, agent, m = await clockwork(tmp_path)
    end = st.creations()[0]["runtime"]["tended_until"]
    assert m["due"] == end and m["offers"][0] == {"name": "tend", "help": "wound: keeps it going about 12 hours"}
    assert await M.step(st, s, agent.runner, end - 60) is False                                    # not yet
    assert cr.tick(st, agent.rng, end + 60, skip=set(M.bound(st))) is False                        # the engine leaves it to the module
    assert await M.step(st, s, agent.runner, end + 60) is True
    rt = st.creations()[0]["runtime"]
    assert rt["stop_logged"] and [e["data"]["text"] for e in st.events(5) if e["kind"] == "module"] == ["Your Gear Clock has stopped - it needs tending (wound)."]
    assert M.perception(st) == ["Things in the world:", "- Your Gear Clock has stopped - it needs tending (wound)."]
    assert not [e for e in st.events(10) if e["kind"] == "creation"]
    assert st.module(m["id"])["due"] is None and await M.step(st, s, agent.runner, end + 120) is False


@pytest.mark.asyncio
async def test_tending_and_setting_go_through_the_module(tmp_path):
    s, st, agent, m = await clockwork(tmp_path)
    c = st.creations()[0]
    st.set_runtime(c["id"], {**c["runtime"], "halted_at": time.time() - 3600, "needs_part": {"name": "brass wire", "qty": 1}})
    r = await call(agent, "tend", creation="gear clock")
    assert r.text == "that didn't work: you need 1 brass wire for that" and r.followup
    st.add_item("brass wire", 2, "material", "")
    r = await call(agent, "tend", creation="gear clock")
    rt = st.creations()[0]["runtime"]
    assert r.text == "you tend your Gear Clock (wound); it will keep going for about 12 hours" and not r.followup
    assert "halted_at" not in rt and "needs_part" not in rt and rt["stop_logged"] is False and st.find_item("brass wire")[0]["qty"] == 1
    assert rt["clock_offset"] < -50                                                    # it starts again from when it stopped, so it's behind
    assert abs(st.module(m["id"])["due"] - rt["tended_until"]) < 1
    r = await call(agent, "use_item", item="gear clock", purpose="fix the time", action="set")
    assert r.text == "you set your Gear Clock; it shows the right time now" and abs(st.creations()[0]["runtime"]["clock_offset"]) < 1e-9
    assert "isn't something it offers; it offers: tend, set" in (await call(agent, "use_item", item="gear clock", purpose="x", action="dance")).text
    lines = "\n".join(agent._projects())
    assert "actions (use_item with action): tend (wound: keeps it going about 12 hours); set (set it to the right time)" in lines


@pytest.mark.asyncio
async def test_without_a_live_module_the_built_in_workings_carry_on(tmp_path):
    s, st, agent = modular(tmp_path)
    clock(st)
    st.add_creation("Paperweight", "a stone", None, "sound", {"capabilities": {}, "quirks": []}, {})
    r = await call(agent, "use_item", item="paperweight", purpose="admire", action="spin")
    assert r.text == "error: your Paperweight doesn't list any actions; use it without `action`"
    assert (await call(agent, "tend", creation="gear clock")).text.startswith("you tend your Gear Clock (wound)")
    (tmp_path / "b").mkdir()
    s2, st2, agent2, m = await clockwork(tmp_path / "b")
    M.disable(st2, m["id"])
    assert M.bound(st2) == {} and (await call(agent2, "tend", creation="gear clock")).text.startswith("you tend your Gear Clock (wound)")
    agent2.ctx.runner = None
    await M.approve(st2, s2, agent2.runner, m["id"])
    assert (await call(agent2, "tend", creation="gear clock")).text.startswith("you tend")                     # no runner: built in
    assert (await M.act(st2, s2, None, st2.module(m["id"]), "set", {})) == "error: that can't be done right now"


@pytest.mark.asyncio
async def test_a_module_offer_without_a_reply_says_what_was_done_and_a_failure_says_so(tmp_path):
    s, st, agent = modular(tmp_path)
    m = live(st, rule(hooks=["on_action"], proposes=["state"]), "def on_action(ctx):\n    if ctx['action'] == 'kick':\n        return 1/0\n    return {}\n")
    st.update_module(m["id"], offers=[{"name": "pat", "help": "x"}, {"name": "kick", "help": "y"}])
    m = st.module(m["id"])
    assert await M.act(st, s, agent.runner, m, "pat", {}) == "you pat it."
    assert await M.act(st, s, agent.runner, m, "kick", {}) == "it doesn't respond (its workings failed: line 3: ZeroDivisionError: division by zero)"
    st.update_module(m["id"], offers=[])
    assert await M.act(st, s, agent.runner, st.module(m["id"]), "pat", {}) == "error: that isn't something it offers; it offers: nothing right now"


# --- the API ----------------------------------------------------------------------------------------------------------------
def test_the_owner_sees_and_decides_proposals_and_the_public_sees_only_whats_live(tmp_path):
    s = Settings(db_path=str(tmp_path / "t.db"), persona_path="/x", pacing="manual", public_hosts=["pip.example.org"],
                 modules="on", module_runner="local")
    with TestClient(create_app(s, FakeBackend())) as c:
        st = c.app.state.agent.state
        import asyncio
        r = asyncio.run(M.propose(st, s, c.app.state.agent.runner, "world", BELLS_MAN, BELLS, "bells", now=NOW))
        assert c.get("/modules", headers={"host": "pip.example.org"}).json() == []
        assert c.get(f"/modules/{r['id']}", headers={"host": "pip.example.org"}).status_code == 404
        own = c.get("/modules").json()
        assert own[0]["status"] == "waiting" and own[0]["source"] == BELLS and own[0]["report"]["clean"] and own[0]["reason"] == "bells"
        assert c.post(f"/modules/{r['id']}/approve", headers={"host": "pip.example.org"}).status_code in (403, 404, 405)
        assert c.post(f"/modules/{r['id']}/disable").status_code == 409
        assert c.post(f"/modules/{r['id']}/approve", json={"note": "fine"}).json() == {"id": r["id"], "status": "live"}
        pub = c.get("/modules", headers={"host": "pip.example.org"}).json()
        assert pub[0]["source"] == BELLS and "report" not in pub[0] and pub[0]["offers"] == [{"name": "ring", "help": "ring the bell"}]
        one = c.get(f"/modules/{r['id']}", headers={"host": "pip.example.org"}).json()
        assert one["calls"][0]["hook"] == "on_install" and "note" not in one
        assert c.get(f"/modules/{r['id']}").json()["note"] == "fine" and c.get("/modules/99").status_code == 404
        assert c.post(f"/modules/{r['id']}/disable").json()["status"] == "disabled"
        assert c.post(f"/modules/{r['id']}/reject").status_code == 409
        r2 = asyncio.run(M.propose(st, s, c.app.state.agent.runner, "world", {**BELLS_MAN, "name": "chimes"}, BELLS, now=NOW))
        assert c.post(f"/modules/{r2['id']}/reject", json={"note": "no"}).json()["status"] == "rejected"
        assert [m["name"] for m in c.get("/modules", headers={"host": "pip.example.org"}).json()] == ["bells"]
