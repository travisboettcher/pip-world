"""World packs, phase 4a (docs/DESIGN-world-packs.md, "Phase 4 in detail"): what a feature needs to be a module. Tools the agent uses,
storage, belongings taken and given, status lines, logged moments with a kind, requests between modules, and sessions."""
import time
from types import SimpleNamespace

import pytest

from app import modules as M
from app import tools as T
from app.llm.base import ToolCall
from tests.test_modules import NOW, live, modular, rule

POTS = '''
def on_action(ctx):
    pots = ctx["store"].get("pots", {})
    if ctx["tool"] == "pot":
        seed = next((i for i in ctx["items"] if i["name"] == ctx["args"]["seed"]), None)
        n = str(len(pots) + 1)
        return {"store": {"pots": {n: {"seed": seed["name"], "crop": seed["attrs"].get("crop", "?")}}},
                "take": [{"item": seed["name"], "qty": 1}], "reply": "potted " + seed["name"] + " in pot " + n,
                "status": {"title": "Your pots", "lines": ["pot " + n + ": " + seed["name"]], "next_at": ctx["now"] + 600}}
    if ctx["tool"] == "empty_pot":
        n = str(ctx["args"]["pot"])
        crop = pots[n]["crop"]
        return {"store": {"pots": {n: None}}, "give": [{"item": crop, "qty": 2, "kind": "food", "description": "from a pot",
                                                         "attrs": {"restores": {"hunger": 0.3}}}],
                "reply": "emptied pot " + n, "status": {}, "log": {"text": "A pot gave " + crop + ".", "kind": "ripe", "feel": {"joy": 3}}}
    if ctx["tool"] == "tidy":
        return {"session": {"minutes": 30, "label": "tidying the pots", "working": True}, "reply": "you start tidying"}

def on_time(ctx):
    s = ctx.get("session") or {}
    return {"store": {"log": {"last": {"label": s.get("label"), "interrupted": s.get("interrupted")}}}}

def on_request(ctx):
    r = ctx["request"]
    if r["what"] == "count":
        return {"reply": str(len(ctx["store"].get("pots", {}))) + " pots"}
    return {"store": {"pots": {}}, "reply": "watered (" + r["from"] + ", " + str(r["apply"]) + ")"}
'''

TOOLS = [{"name": "pot", "help": "Put a seed in a pot.", "where": "home",
          "params": {"type": "object", "properties": {"seed": {"type": "string"}}, "required": ["seed"]}},
         {"name": "empty_pot", "help": "Empty a pot.", "params": {"type": "object", "properties": {"pot": {"type": "integer"}}, "required": ["pot"]}},
         {"name": "tidy", "help": "Tidy the pots for a while."}]


def pots(**extra):
    return rule(name="pots", hooks=["on_action", "on_time", "on_request"], proposes=["store", "take", "give", "status", "log", "session"],
                reads=["items"], tools=TOOLS, belongings={"takes": ["seed"], "gives": ["food"], "most": 3},
                answers={"water": "water the pots", "count": "say how many pots are in use"}, **extra)


def setup(tmp_path):
    s, st, agent = modular(tmp_path)
    st.add_item("bean seeds", 2, "seed", "", {"crop": "beans", "grow_minutes": 60, "yield": 2, "food_value": 0.3})
    m = live(st, pots(), POTS)
    return s, st, agent, m


async def use(agent, name, **args):
    return await agent._run_tool(ToolCall(id="1", name=name, arguments=args), 0)


# --- manifests -----------------------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("extra,why", [
    ({"tools": [{"name": "Bad Name", "help": "x"}]}, "a tool's `name` is 2 to 24 lowercase letters and underscores"),
    ({"tools": [{"name": "dig", "help": "x"}, {"name": "dig", "help": "y"}]}, "there is already a tool called dig"),
    ({"tools": []}, "`tools` is a list of up to 6"),
    ({"tools": [{"name": "dig", "help": "x", "params": {"type": "object", "properties": {"n": {"type": "list"}}}}]}, "`dig`'s `params` is"),
    ({"tools": [{"name": "dig", "help": "x", "params": {"type": "object", "properties": {}, "required": ["n"]}}]}, "`dig`'s `params` is"),
    ({"tools": [{"name": "dig", "help": "x", "where": ""}]}, "`dig`'s `where` is anywhere, home, neighbor, offered, or a place's key (or a list of them)"),
    ({"tools": [{"name": "dig"}]}, "`dig.help` is a line of text"),
])
def test_a_modules_tools_are_checked(extra, why):
    man = rule(name="digger", hooks=["on_action"], proposes=["state"], **extra)
    with pytest.raises(M.Refused, match=f"^{__import__('re').escape(why)}"):
        M.check_manifest(man, "world")


def test_what_goes_together_in_a_manifest():
    with pytest.raises(M.Refused, match="through on_action"):
        M.check_manifest(rule(name="digger", tools=[{"name": "dig", "help": "x"}]), "world")
    with pytest.raises(M.Refused, match="`take`/`give` and `belongings` go together"):
        M.check_manifest(rule(name="digger", proposes=["take"]), "world")
    with pytest.raises(M.Refused, match=r"`belongings` is \{takes\?, gives\?, most, coins\?\}"):
        M.check_manifest(rule(name="digger", proposes=["take"], belongings={"takes": ["gold"], "most": 1}), "world")
    with pytest.raises(M.Refused, match="`on_request` and `answers` go together"):
        M.check_manifest(rule(name="digger", hooks=["on_request"]), "world")
    with pytest.raises(M.Refused, match="`answers` maps up to 8 words"):
        M.check_manifest(rule(name="digger", hooks=["on_request"], answers={"Dig Up": "x"}), "world")
    with pytest.raises(M.Refused, match="a `session` starts from on_action and ends in on_time"):
        M.check_manifest(rule(name="digger", hooks=["on_action"], proposes=["session"]), "world")
    with pytest.raises(M.Refused, match="not for Pip's programs"):
        M._tools([{"name": "dig", "help": "x"}], "pip")
    got = M.check_manifest(pots(), "world")
    assert got["tools"][1] == {"name": "empty_pot", "help": "Empty a pot.", "where": "anywhere",
                               "params": {"type": "object", "properties": {"pot": {"type": "integer"}}, "required": ["pot"]}}
    assert got["belongings"] == {"takes": ["seed"], "gives": ["food"], "most": 3} and set(got["answers"]) == {"water", "count"}


def test_arguments_are_checked_against_the_tools_schema():
    p = {"type": "object", "properties": {"n": {"type": "integer"}, "x": {"type": "number"}, "ok": {"type": "boolean"},
                                          "how": {"type": "string", "enum": ["fast", "slow"]}}, "required": ["n"]}
    assert M.check_args(p, {"n": "3", "x": "1.5", "ok": True, "how": "slow"}) == ({"n": 3, "x": 1.5, "ok": True, "how": "slow"}, "")
    assert M.check_args(p, {"n": 2, "how": None}) == ({"n": 2}, "")
    for args, why in (([], "the arguments are an object"), ({}, "`n` is needed"), ({"n": ""}, "`n` is needed"), ({"n": 1, "y": 2}, "it takes: n, x, ok, how"),
                      ({"n": "two"}, "`n` is a integer"), ({"n": True}, "`n` is a integer"), ({"n": 1, "x": "a"}, "`x` is a number"),
                      ({"n": 1, "ok": "yes"}, "`ok` is a boolean"), ({"n": 1, "how": "odd"}, "`how` is one of fast, slow"), ({"n": 1.5}, "`n` is a integer")):
        assert M.check_args(p, args) == ({}, why)
    assert M.check_args({"type": "object", "properties": {}, "required": []}, {"a": 1}) == ({}, "it takes: nothing")


# --- tools, storage, belongings, status, a moment with a kind ---------------------------------------------------------------------------
async def test_the_agent_uses_a_modules_tools(tmp_path):
    s, st, agent, m = setup(tmp_path)
    names = [t.name for t in agent._specs()]
    assert {"pot", "empty_pot", "tidy"} <= set(names)
    r = await use(agent, "pot", seed="bean seeds")
    assert r["content"] == "potted bean seeds in pot 1" and not r["followup"]
    assert st.store("pots") == {"pots": {"1": {"seed": "bean seeds", "crop": "beans"}}} and st.find_item("bean seeds")[0]["qty"] == 1
    ev = st.events(3)[0]
    assert ev["kind"] == "tool" and ev["data"]["tool"] == "pot" and ev["data"]["result"] == "potted bean seeds in pot 1"
    assert M.standing(st) == [{"title": "Your pots", "lines": ["pot 1: bean seeds"], "ready": False, "next_at": pytest.approx(time.time() + 600, abs=30),
                               "module": "pots"}]
    assert M.status_lines(st) == ["Your pots:", "- pot 1: bean seeds"] and "Your pots:" in agent._perception("test", [])
    r = await use(agent, "empty_pot", pot="1")
    assert r["content"] == "emptied pot 1" and st.store("pots") == {} and M.standing(st) == [] and M.status_lines(st) == []
    beans = st.find_item("beans")[0]
    assert (beans["qty"], beans["kind"], beans["description"], beans["attrs"]) == (2, "food", "from a pot", {"restores": {"hunger": 0.3}, "food_value": 0.3})
    ev = [e for e in st.events(5) if e["kind"] == "module"][0]["data"]
    assert (ev["name"], ev["moment"], ev["text"], ev["feel"]) == ("pots", "ripe", "A pot gave beans.", {"joy": 3})
    assert (await use(agent, "pot", seed=3))["content"] == "error: `seed` is a string"
    assert (await use(agent, "pot", seed="gold"))["content"].startswith("error:")
    r = await use(agent, "nothing_here")
    assert r["content"] == "error: unknown or disabled tool 'nothing_here'" and r["is_error"]


async def test_a_modules_tool_works_only_where_it_says(tmp_path):
    s, st, agent, m = setup(tmp_path)
    st.update_agent(location="woods")
    assert "pot" not in [t.name for t in agent._specs()] and "empty_pot" in [t.name for t in agent._specs()]
    r = await use(agent, "pot", seed="bean seeds")
    assert r["content"] == "you're at the woods; go_to home first" and r["followup"]
    assert T.module_specs(st, "woods", SimpleNamespace(scope="woods"), open_=False)[0].name == "empty_pot"


async def test_a_modules_first_moment_of_a_kind_can_be_a_first(tmp_path, monkeypatch):
    from app import firsts
    s, st, agent, m = setup(tmp_path)
    monkeypatch.setattr(firsts, "module_firsts", lambda: {"pots:ripe": "had a pot ripen"})
    await use(agent, "pot", seed="bean seeds")
    await use(agent, "empty_pot", pot=1)
    ev = [e for e in st.events(5) if e["kind"] == "module"][0]
    assert [(f["key"], f["label"]) for f in ev["data"]["firsts"]] == [("pots:ripe", "the first time you had a pot ripen")]


def test_what_a_module_logs_and_shows(tmp_path):
    for v, why in (({"text": "x", "kind": "Bad"}, "`log` is a line, or {text, kind, feel?, items?, tool?}"), ({"text": "x", "kind": "a", "z": 1}, "`log` is a line"),
                   ({"text": "x", "kind": "a", "feel": {"joy": 6}}, "`log.feel` maps emotions"), ({"text": "x", "kind": "a", "feel": {"glee": 1}}, "`log.feel`"),
                   ({"text": "x", "kind": "a", "feel": {"joy": True}}, "`log.feel`"), ({"kind": "a"}, "`log.text` is a line of text")):
        with pytest.raises(M.Refused, match=__import__("re").escape(why)):
            M._log(v)
    assert M._log({"text": " x ", "kind": "a", "feel": {"joy": -5}}) == {"text": "x", "kind": "a", "feel": {"joy": -5}}
    assert M._log({"text": "x", "kind": "a"}) == {"text": "x", "kind": "a"} and M._log("plain") == "plain"
    assert M._status({}) == {} and M._status(None) == {}
    assert M._status({"title": "T", "lines": ["a"], "ready": True, "next_at": 5}) == {"title": "T", "lines": ["a"], "ready": True, "next_at": 5.0}
    for v in ({"title": "T"}, {"title": "T", "lines": ["a"] * (M.STATUS_LINES + 1)}, {"title": "T", "lines": [], "ready": "yes"}, {"title": "T", "lines": [], "x": 1},
              {"title": "T", "lines": [], "next_at": "soon"}, []):
        with pytest.raises(M.Refused, match="`status` is"):
            M._status(v)
    with pytest.raises(M.Refused, match="`status.title` is at most 40"):
        M._status({"title": "T" * 41, "lines": []})


def test_a_modules_store_is_kept_by_name_and_capped(tmp_path):
    s, st, agent = modular(tmp_path)
    st.merge_store("pots", {"pots": {"1": {"a": 1}, "2": [1]}, "notes": {"x": "y"}})
    assert st.store("pots") == {"notes": {"x": "y"}, "pots": {"1": {"a": 1}, "2": [1]}} and st.store("other") == {}
    st.merge_store("pots", {"pots": {"1": None}})
    assert st.store("pots")["pots"] == {"2": [1]}
    assert M._store(st, "pots", {"pots": {"2": None}}) == {"pots": {"2": None}}
    for v in ([], {"Bad": {}}, {"pots": []}, {"pots": {"a/b": 1}}, {f"c{i}": {"k": 1} for i in range(9)}, {"pots": {str(i): 1 for i in range(201)}}):
        with pytest.raises(M.Refused, match="`store` is"):
            M._store(st, "pots", v)
    with pytest.raises(M.Refused, match="its store would be over 64000 bytes"):
        M._store(st, "pots", {"big": {"a": "x" * 64_000}})


def test_belongings_taken_and_given_within_the_manifest(tmp_path):
    s, st, agent, m = setup(tmp_path)
    man = m["manifest"]
    st.add_item("brass", 4, "material", "")
    assert M._take(st, man, [{"item": "bean seeds", "qty": 2}])[0][1:] == (2, "bean seeds")
    for v, why in (({}, "`take` is a list"), ([{"item": "bean seeds", "qty": 4}], "`take` qty is 1 to 3"), ([{"item": "brass"}], "it can only take: seed"),
                   ([{"item": "bean seeds", "qty": 3}], "there are only 2 bean seeds"), ([{"item": "gold"}], "you don't have"),
                   ([{"item": "bean seeds", "qty": True}], "`take` qty")):
        with pytest.raises(M.Refused, match=__import__("re").escape(why)):
            M._take(st, man, v)
    good = {"item": "pea", "qty": 3, "kind": "food"}
    assert M._give(st, man, [good]) == [{"item": "pea", "qty": 3, "kind": "food", "description": "", "attrs": {}}]
    for v, why in (({}, "`give` is a list"), ([{**good, "x": 1}], "each thing in `give`"), ([{**good, "kind": "seed"}], "it can only give: food"),
                   ([{**good, "qty": 4}], "`give` qty is 1 to 3"), ([{**good, "item": "p" * 41}], "at most 40 characters"),
                   ([{**good, "attrs": {"restores": {"luck": 0.1}}}], "`attrs` is up to 8"), ([{**good, "attrs": {"restores": {"hunger": 2}}}], "`attrs`"),
                   ([{**good, "attrs": {"a": [1]}}], "`attrs`"), ([{**good, "attrs": {f"a{i}": 1 for i in range(9)}}], "`attrs`")):
        with pytest.raises(M.Refused, match=__import__("re").escape(why)):
            M._give(st, man, v)


# --- requests ---------------------------------------------------------------------------------------------------------------------------
ASKER = "def on_tick(ctx):\n    return {'request': {'module': 'pots', 'what': 'water', 'args': {'how': 'gently'}}}\n"


async def test_a_module_asks_another_and_it_answers(tmp_path):
    s, st, agent, m = setup(tmp_path)
    st.merge_store("pots", {"pots": {"1": {"seed": "x"}}})
    asker = live(st, rule(name="rain", proposes=["request"]), ASKER)
    await M.step(st, s, agent.runner, NOW)                              # pots ran before rain asked: it hears it on the next step
    assert st.module(m["id"])["requests"] == [{"what": "water", "args": {"how": "gently"}, "from": "rain", "ts": NOW}]
    await M.step(st, s, agent.runner, NOW + 60)
    calls = st.module_calls(m["id"])
    assert calls[0]["hook"] == "on_request" and calls[0]["summary"] == "store, reply" and [r["ts"] for r in st.module(m["id"])["requests"]] == [NOW + 60]
    assert st.module(asker["id"])["budget"]["request"] == 2
    assert await M.ask_module(st, s, agent.runner, "pots", "count", {}, False) == "1 pots"
    assert await M.ask_module(st, s, agent.runner, "pots", "water", {}, True, tone="good") == "watered (engine, True)"


async def test_what_can_and_cant_be_asked(tmp_path):
    s, st, agent, m = setup(tmp_path)
    asker = live(st, rule(name="rain", proposes=["request"]), ASKER)
    for v, why in (({"module": "nobody", "what": "water"}, "there is no live module called 'nobody'"), ({"module": "pots", "what": "dig"}, "pots answers: water, count"),
                   ({"module": "pots", "what": "water", "args": []}, "`request` is {module, what, args?}"), ([], "`request` is"),
                   ({"module": "pots", "what": "water", "args": {"a": "x" * 2000}}, "`request` is")):
        with pytest.raises(M.Refused, match=__import__("re").escape(why)):
            M._request(st, asker, v)
    with pytest.raises(M.Refused, match="changes its own state itself"):
        M._request(st, m, {"module": "pots", "what": "water"})
    with pytest.raises(M.Refused, match="pots answers"):
        await M.ask_module(st, s, agent.runner, "pots", "dig", {}, True)
    live(st, rule(name="broken", hooks=["on_request"], answers={"x": "y"}), "def on_request(ctx):\n    return {'nope': 1}\n")
    with pytest.raises(M.Refused, match="it returned nope"):
        await M.ask_module(st, s, agent.runner, "broken", "x", {}, True)
    with pytest.raises(M.Refused, match="can't run right now"):
        await M.ask_module(st, s, None, "broken", "x", {}, True)


# --- sessions ---------------------------------------------------------------------------------------------------------------------------
async def test_a_module_tool_starts_a_session_that_ends_in_on_time(tmp_path):
    s, st, agent, m = setup(tmp_path)
    r = await use(agent, "tidy")
    assert r["content"] == "you start tidying"
    sess = st.session()
    assert (sess["kind"], sess["target"], sess["expect"], sess["stage"], sess["minutes"]) == ("module", "pots", "tidying the pots", 1, 30)
    assert T.busy(agent.ctx).startswith("you're tidying the pots (about 30 min left)")
    assert (await use(agent, "tidy"))["content"] == "error: Pip is busy with something else"
    st.update_agent(updated_at=time.time() - 3600)
    before = st.agent()["energy"]
    st.apply_decay()
    assert st.agent()["energy"] < before - 0.05                           # a working session tires like work
    st.db.execute("UPDATE work_session SET ends_at = ?", (time.time() - 1,))
    assert await agent.finish_work() and st.session() is None
    assert st.store("pots")["log"]["last"] == {"label": "tidying the pots", "interrupted": False}


async def test_resting_ends_a_modules_session_early(tmp_path):
    s, st, agent, m = setup(tmp_path)
    await use(agent, "tidy")
    r = await T.REGISTRY["rest"][1](agent.ctx, {})
    assert "(you stopped tidying the pots early)" in r.text and st.session() is None
    assert st.store("pots")["log"]["last"] == {"label": "tidying the pots", "interrupted": True}
    assert await M.end_session(st, s, agent.runner) is None


def test_session_shapes(tmp_path):
    s, st, agent = modular(tmp_path)
    assert M._session(st, {"minutes": 1, "label": "x"}) == {"minutes": 1.0, "label": "x", "working": False, "about": ""}
    for v in ({"minutes": 0, "label": "x"}, {"minutes": 241, "label": "x"}, {"minutes": 5, "label": "x", "working": 1}, {"minutes": 5, "label": "x", "y": 1}, []):
        with pytest.raises(M.Refused, match=r"`session` is \{minutes \(1 to 240\), label, working\?, about\?\}"):
            M._session(st, v)
    with pytest.raises(M.Refused, match="`session.label` is a line of text"):
        M._session(st, {"minutes": 5})


async def test_only_on_action_starts_a_session_or_replies(tmp_path):
    s, st, agent, m = setup(tmp_path)
    for result, why in (({"session": {"minutes": 5, "label": "x"}}, "only on_action can start a session"), ({"reply": "x"}, "only on_action can reply")):
        with pytest.raises(M.Refused, match=why):
            M.plan(st, m, result, NOW, "on_time", s)
    assert M.plan(st, m, {"reply": "x"}, NOW, "on_request", s) == [("reply", "x")]


async def test_free_time_reads_what_modules_say_waits(tmp_path):
    s, st, agent, m = setup(tmp_path)
    now = time.time()
    st.update_module(m["id"], standing={"title": "Pots", "lines": ["a"], "ready": False, "next_at": now + 7200})
    assert agent._free_time(now)[0] == "Nothing needs you for about 2 hours."
    st.update_module(m["id"], standing={"title": "Pots", "lines": ["a"], "ready": True})
    assert agent._free_time(now) == []


# --- a world effect or a happening asks a module ----------------------------------------------------------------------------------------
async def test_a_world_effect_can_be_a_modules_change(tmp_path, monkeypatch):
    from app import world_effects as W
    s, st, agent, m = setup(tmp_path)
    reg = {"pots": W.WorldEffect("pots", "more pots", ("pot",), W._applier("request:pots:water", ""), 2, W._request("request:pots:water")),
           "count": W.WorldEffect("count", "x", (), W._applier("request:pots:count", ""), 2, ("pots", "count")),
           "gone": W.WorldEffect("gone", "x", (), W._applier("request:nobody:water", ""), 2, ("nobody", "water"))}
    monkeypatch.setattr(W, "registry", lambda: reg)
    spec = {"capabilities": {"world": {"effect": "pots"}}}
    assert await W.apply(st, spec) == "watered (engine, True)" and "world" in spec["capabilities"]
    spec = {"capabilities": {"world": {"effect": "gone"}}}
    assert await W.apply(st, spec) is None and "world" not in spec["capabilities"]          # no such module: no change, not claimed
    assert W._request("add_plot") is None and W._request("request:a") is None and W._request("request:a:b") == ("a", "b")
    assert W._applier("request:a:b", "x")(st) is None


SIZER = '''
def on_request(ctx):
    r = ctx["request"]
    if r["args"].get("fail"):
        return {}
    if r["apply"]:
        return {"store": {"pots": {"1": {"sped": r["severity"]}}}, "reply": "done"}
    return {"reply": "Pot 1 grows a little " + ("faster" if r["tone"] == "good" else "slower")}
'''


async def test_a_happening_can_ask_a_module_to_change_itself(tmp_path):
    from app import happenings as H
    from tests.test_happen import Writer
    s, st, agent = modular(tmp_path, happenings="on")
    live(st, rule(name="pots", hooks=["on_request"], proposes=["store"], answers={"grow": "a pot's growing turns"}), SIZER)
    asker = live(st, rule(name="porch", proposes=["happen"]), "x")
    turn = {"category": "garden", "tone": "good", "severity": "medium", "effects": [{"kind": "request", "module": "pots", "what": "grow", "args": {}}],
            "fallback": {"title": "A kind spell", "text": "The light is kind to the pots this morning."}}
    st.update_module(asker["id"], happen=[turn])
    assert await H.from_modules(st, s, Writer(), time.time()) is True
    h = st.happenings(1)[0]
    assert h["effects_line"] == "(Pot 1 grows a little faster.)" and st.store("pots") == {"pots": {"1": {"sped": "medium"}}}
    assert H.describe(h["effects"][0]) == "Pot 1 grows a little faster."
    st.update_happening(h["id"], status="resolved")
    st.update_module(asker["id"], happen=[{**turn, "effects": [{**turn["effects"][0], "args": {"fail": True}}]}])
    assert await H.from_modules(st, s, Writer(), time.time() + 7200) is False
    ev = next(e["data"] for e in st.events(5) if e["kind"] == "happening_dropped")
    assert ev["reason"] == "pots didn't say what it would change" and ev["category"] == "garden"


def test_a_request_effect_must_be_something_a_live_module_answers():
    from app import happenings as H
    w = {"answers": {"pots": ["grow"]}}
    assert H._intent(w, "bad", "minor", {"kind": "request", "module": "pots", "what": "grow"}, None).effects == [
        {"kind": "request", "module": "pots", "what": "grow", "args": {}}]
    for i, why in (({"kind": "request", "module": "pots", "what": "dig"}, "`module` is a live module and `what` something it answers: pots: grow"),
                   ({"kind": "request", "module": "pots", "what": "grow", "args": []}, "`args` is an object")):
        with pytest.raises(ValueError, match=__import__("re").escape(why)):
            H._intent(w, "bad", "minor", i, None)
    with pytest.raises(ValueError, match="no module answers anything"):
        H._intent({}, "bad", "minor", {"kind": "request", "module": "x", "what": "y"}, None)


async def test_status_shows_what_modules_show(tmp_path):
    from app import commands
    s, st, agent, m = setup(tmp_path)
    st.update_module(m["id"], standing={"title": "Your pots", "lines": ["pot 1: beans"], "ready": True})
    assert commands.answer(st, s, "/status").endswith("\nYour pots:\n- pot 1: beans")


async def test_a_module_asked_to_do_something_may_say_why_it_wont(tmp_path):
    s, st, agent = modular(tmp_path)
    live(st, rule(name="pots", hooks=["on_request"], answers={"grow": "x"}), "def on_request(ctx):\n    return {'refuse': 'nothing is growing'}\n")
    with pytest.raises(M.Refused, match="^nothing is growing$"):
        await M.ask_module(st, s, agent.runner, "pots", "grow", {}, True)
    m = st.modules("live")[0]
    with pytest.raises(M.Refused, match="it returned refuse"):
        M.plan(st, m, {"refuse": "x"}, NOW, "on_tick", s)
    with pytest.raises(M.Refused, match="`refuse` is a line of text"):
        M.plan(st, m, {"refuse": ""}, NOW, "on_request", s)


def test_a_status_line_says_how_long_as_it_is_shown(tmp_path):
    assert M.until("ready in about {in:1000}", 1000 - 45 * 60) == "ready in about 45 min"
    assert M.until("ready in about {in:1000.5}", 1000.5 - 3 * 3600) == "ready in about 3 hours"
    assert M.until("{in:1000} and {in:1060}", 1000 - 61) == "2 min and 3 min" and M.until("{in:10}", 100) == "0 min"
    assert M.until("no time {in:x}", 0) == "no time {in:x}"
    s, st, agent = modular(tmp_path)
    m = live(st, rule(name="pots"), "x")
    st.update_module(m["id"], standing={"title": "Pots", "lines": ["ready in {in:5000}"], "ready": False})
    assert M.standing(st, 5000 - 600)[0]["lines"] == ["ready in 10 min"] and st.module(m["id"])["standing"]["lines"] == ["ready in {in:5000}"]
