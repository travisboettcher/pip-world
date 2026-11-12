"""The module system's glue at its edges (modules.py): what a hook is told, how its proposals land, a call's record, the engine's step,
and asking a module; and the world view's session and facts."""
import time

import pytest

from app import modules as M
from tests.test_modules import NOW, live, modular, rule


# --- what a hook is told --------------------------------------------------------------------------------------------------------------------
def test_the_context_carries_only_what_the_manifest_asks_for(tmp_path):
    s, st, agent = modular(tmp_path)
    plain = live(st, rule(name="plain", reads=[]), "x")
    ctx = M.context(st, s, plain, NOW)
    assert "voices" not in ctx and "asking" not in ctx and "store" not in ctx and "params" not in ctx
    talk = live(st, rule(name="talk", hooks=["on_tick", "on_message", "on_answer"], proposes=["voices", "ask"], params={"n": 1}), "x")
    st.update_module(talk["id"], voices=[{"name": "Fen", "at": "home", "about": ""}], asks=[{"id": 1}, {"id": 2}])
    ctx = M.context(st, s, st.module(talk["id"]), NOW)
    assert ctx["voices"] == [{"name": "Fen", "at": "home", "about": ""}] and ctx["asking"] == 2 and ctx["params"] == {"n": 1}
    st.update_module(talk["id"], voices=[])
    assert M.context(st, s, st.module(talk["id"]), NOW)["voices"] == []


def test_the_agent_read_is_its_own_worlds(tmp_path):
    from app.state import State
    from tests.test_mut_stats import WASTE, pack
    s = pack(tmp_path, "waste", WASTE)
    st = State(s)
    m = live(st, rule(name="eye", reads=["agent"]), "x")
    a = M.context(st, s, m, NOW)["agent"]
    assert a["radiation"] == 0.1 and a["stamina"] == 0.8 and "hunger" not in a


def test_people_and_happenings_as_a_module_reads_them(tmp_path):
    from app import happenings as hp
    s, st, agent = modular(tmp_path, happenings="on")
    st.add_character("Oriel", "neighbor", None, "x", 60, NOW)
    st.add_character("Bell", "creation", None, "x", 60, NOW)
    m = live(st, rule(name="eye", reads=["people", "happenings"]), "x")
    now = time.time()
    start = hp._today_start(now)
    for ts in (start, start - 1):
        st.add_happening(ts=ts, slot=str(ts), category="fog", tone="neutral", severity="minor", lens="joy", seed="s", context={}, effects=[],
                         effects_line="", meaning={}, text="t", title="T", author="template", status="resolved")
    ctx = M.context(st, s, m, now)
    assert ctx["people"] == [{"name": "Oriel", "kind": "neighbor"}] and ctx["happenings"]["today"] == 1
    assert ctx["happenings"]["can_remember"] is False
    for i in range(hp.MIN_DIARY):
        st.add_memory(f"note {i}", "diary")
    assert M.context(st, s, m, now)["happenings"]["can_remember"] is False                 # enough notes, but none old enough
    st.db.execute("UPDATE memories SET ts = ? WHERE id = (SELECT MIN(id) FROM memories WHERE section = 'diary')",
                  (now - hp.OLD_NOTE_DAYS * 86400 - 1,))
    st.db.commit()
    assert M.context(st, s, m, now)["happenings"]["can_remember"] is True


# --- how proposals land ------------------------------------------------------------------------------------------------------------------------
def test_proposals_land_and_count(tmp_path):
    s, st, agent = modular(tmp_path)
    st.add_item("oat seeds", 5, "seed", "")
    m = live(st, rule(name="pots", hooks=["on_tick", "on_action", "on_answer", "on_time"], proposes=["perceive", "take", "give", "ask", "affect", "session"],
                      belongings={"takes": ["seed"], "gives": ["food"], "most": 3}), "x")
    for line in ("one", "two"):
        M.apply(st, m, M.plan(st, m, {"perceive": line}, NOW, "on_tick"), NOW)
        m = st.module(m["id"])
    assert [l["text"] for l in m["lines"]] == ["one", "two"]
    M.apply(st, m, M.plan(st, m, {"take": [{"item": "oat seeds", "qty": 2}], "give": [{"item": "oats", "qty": 1, "kind": "food"}],
                                  "ask": {"prompt": "p"}, "affect": {"mood": "glad", "energy": 0.05}}, NOW, "on_tick"), NOW)
    m = st.module(m["id"])
    b = M._budget(m, NOW)
    assert (b["take"], b["give"], b["ask"], b["affect"]) == (1, 1, 1, 1) and st.find_item("oat seeds")[0]["qty"] == 3
    assert st.agent()["mood"] == "glad" and m["asks"][0]["id"] == 1 and m["asks"][0]["ts"] == NOW
    M.apply(st, m, M.plan(st, m, {"ask": {"prompt": "q"}}, NOW, "on_tick"), NOW)
    assert [a["id"] for a in st.module(m["id"])["asks"]] == [1, 2]
    M.apply(st, m, [("affect", {"mood": "calm", "luck": 0.1})], NOW)
    assert st.agent()["mood"] == "calm"
    M.apply(st, st.module(m["id"]), M.plan(st, st.module(m["id"]), {"session": {"minutes": 5, "label": "x"}}, NOW, "on_action"), NOW)
    sess = st.session()
    assert (sess["project_id"], sess["ends_at"], sess["minutes"]) == (0, NOW + 300, 5)


def test_requests_wait_ten_at_most(tmp_path):
    s, st, agent = modular(tmp_path)
    target = live(st, rule(name="pots", hooks=["on_request"], answers={"water": "x"}), "x")
    asker = live(st, rule(name="rain", proposes=["request"]), "x")
    for i in range(12):
        M.apply(st, asker, [("request", {"module": "pots", "what": "water", "args": {"i": i}})], NOW)
    assert [r["args"]["i"] for r in st.module(target["id"])["requests"]] == list(range(2, 12))


def test_a_due_time_that_passed_is_cleared_unless_asked_again(tmp_path):
    s, st, agent = modular(tmp_path)
    m = live(st, rule(name="bell"), "x")
    st.update_module(m["id"], due=NOW - 1)
    M.apply(st, st.module(m["id"]), [], NOW)
    assert st.module(m["id"])["due"] is None


# --- a call's record --------------------------------------------------------------------------------------------------------------------------
async def test_a_misfire_is_recorded_as_one(tmp_path, monkeypatch):
    s, st, agent = modular(tmp_path)
    m = live(st, rule(name="bell"), "def on_tick(ctx):\n    return {}\n")
    monkeypatch.setattr(M, "misfires", lambda *a: True)
    assert await M.call(st, s, agent.runner, m, "on_tick", NOW) == {"ok": True, "error": "", "refused": "", "wake": False, "reply": "",
                                                                     "misfired": True, "changed": False}
    c = st.module_calls(m["id"])[0]
    assert (c["ok"], c["ms"], c["summary"]) == (1, 0, "misfired (the work is rough)")


async def test_failing_code_is_switched_off_saying_why(tmp_path):
    s, st, agent = modular(tmp_path)
    m = live(st, rule(name="bell"), "def on_tick(ctx):\n    return 1 / 0\n")
    for i in range(3):
        await M.call(st, s, agent.runner, m, "on_tick", NOW + i)
    assert m["status"] == "disabled" and st.module(m["id"])["note"].startswith("its code failed 3 times in a row: ")
    assert "ZeroDivisionError" in st.module(m["id"])["note"]
    assert len(st.module_calls(m["id"])[0]["summary"]) <= 300


# --- the engine's step --------------------------------------------------------------------------------------------------------------------------
TICKER = "def on_time(ctx):\n    return {'state': {'ran': ctx['due']}}\n"


async def test_the_step_runs_what_is_due_for_live_modules_only(tmp_path):
    s, st, agent = modular(tmp_path)
    m = live(st, rule(name="bell", hooks=["on_time"]), TICKER)
    off = live(st, rule(name="off", hooks=["on_time"]), TICKER)
    st.update_module(m["id"], due=NOW)
    st.update_module(off["id"], due=NOW, status="disabled")
    await M.step(st, s, agent.runner, NOW)                                    # due exactly now: it runs
    assert st.module(m["id"])["state"] == {"ran": NOW} and st.module(off["id"])["state"] == {}


WAKER = '''
def on_message(ctx):
    return {"wake": ctx["message"]["text"] == "wake"}

def on_request(ctx):
    return {"wake": ctx["request"]["args"].get("wake", False), "reply": "ok" if ctx["request"]["apply"] else "no"}
'''


async def test_any_heard_line_or_request_that_wakes_the_agent_wakes_it(tmp_path):
    s, st, agent = modular(tmp_path)
    m = live(st, rule(name="fen", hooks=["on_message", "on_request"], proposes=["voices", "wake"], answers={"poke": "x"}), WAKER)
    st.update_module(m["id"], heard=[{"to": "Fen", "text": "wake"}, {"to": "Fen", "text": "sleep"}])
    assert await M.step(st, s, agent.runner, NOW) is True and st.module(m["id"])["heard"] == []
    st.update_module(m["id"], requests=[{"what": "poke", "args": {"wake": True}, "from": "x"}, {"what": "poke", "args": {}, "from": "x"}])
    assert await M.step(st, s, agent.runner, NOW + 60) is True and st.module(m["id"])["requests"] == []
    assert [c["summary"] for c in st.module_calls(m["id"])][:2] == ["reply", "wake, reply"]           # newest first
    st.update_module(m["id"], heard=[{"to": "Fen", "text": "hi"}], status="disabled")
    await M.step(st, s, agent.runner, NOW + 120)
    assert st.module(m["id"])["heard"] == [{"to": "Fen", "text": "hi"}]


async def test_a_modules_events_come_fifty_at_a_time(tmp_path):
    s, st, agent = modular(tmp_path)
    m = live(st, rule(name="ears", hooks=["on_event"], events=["module"]), "def on_event(ctx):\n    return {}\n")
    for i in range(60):
        st.log("module", name="x", text=str(i))
    await M.step(st, s, agent.runner, NOW)
    assert len(st.module_calls(m["id"], limit=100)) == 50


# --- asking a module ----------------------------------------------------------------------------------------------------------------------------
async def test_a_module_that_fails_when_asked_says_so(tmp_path):
    s, st, agent = modular(tmp_path)
    live(st, rule(name="pots", hooks=["on_request"], answers={"x": "y"}), "def on_request(ctx):\n    return 1 / 0\n")
    with pytest.raises(M.Refused, match=r"^pots failed: .*ZeroDivisionError"):
        await M.ask_module(st, s, agent.runner, "pots", "x", {}, True)


# --- the world view -------------------------------------------------------------------------------------------------------------------------------
def test_the_scene_shows_a_modules_session_and_only_live_facts(tmp_path):
    from app import world_view as WV
    s, st, agent = modular(tmp_path)
    on = live(st, rule(name="pots"), "x")
    off = live(st, rule(name="old"), "x")
    st.update_module(on["id"], facts={"a": 1})
    st.update_module(off["id"], facts={"b": 2}, status="disabled")
    st.start_session(0, 0, 30, time.time() + 1800, kind="module", target="pots", expect="tidying")
    d = WV.scene_view(st, s, None)
    assert d["facts"] == {"pots": {"a": 1}} and d["pip"]["session"]["label"] == "tidying"
    st.start_session(0, 0, 30, time.time() + 1800, kind="walk", target="woods")
    assert "label" not in (WV.scene_view(st, s, None, "woods")["pip"]["session"] or {})
