"""The feature hooks (modules.py, world packs phase 4) at their edges: each limit at its exact value, each refusal word for word."""
import json
import time

import pytest

from app import modules as M
from tests.test_module_hooks import setup, use
from tests.test_modules import NOW, live, modular, rule


def refused(fn, *args):
    with pytest.raises(M.Refused) as e:
        fn(*args)
    return str(e.value)


def tool(**kw):
    return {"name": "dig", "help": "Dig.", **kw}


# --- tools -----------------------------------------------------------------------------------------------------------------------------
def test_tools_at_their_limits():
    assert len(M._tools([tool(name=f"dig_{c}") for c in "abcdef"], "world")) == 6
    shape = "`tools` is a list of up to 6 {name, help, params?, where?} (and not for Pip's programs)"
    assert refused(M._tools, [tool(name=f"dig_{c}") for c in "abcdefg"], "world") == shape
    assert refused(M._tools, "dig", "world") == shape
    assert refused(M._tools, [tool(), tool()], "world") == "there is already a tool called dig"
    params = lambda n: {"type": "object", "properties": {f"a{c}": {"type": "string"} for c in "abcdefghi"[:n]}}  # noqa: E731
    assert len(M._tools([tool(params=params(8))], "world")[0]["params"]["properties"]) == 8
    why = ("`dig`'s `params` is {type: object, properties, required?}: up to 8 arguments, each {type (string, integer, number, boolean), "
           "description?, enum?}")
    for bad in (params(9), {"type": "array", "properties": {}}, {"type": "object", "properties": {}, "required": "a"}, [1], {"properties": {}}):
        assert refused(M._tools, [tool(params=bad)], "world") == why
    assert M._tools([tool(where="x" * 60)], "world")[0]["where"] == "x" * 60
    assert refused(M._tools, [tool(where="x" * 61)], "world") == "`dig`'s `where` is anywhere, home, or a place's key"
    assert M._tools([tool(first=" x" * 30)], "world")[0]["first"] == ("x " * 30).strip()
    first = "`dig`'s `first` is a few words for the first time it's used (\"planted something\")"
    for bad in ("x" * 61, " ", 3):
        assert refused(M._tools, [tool(first=bad)], "world") == first
    assert "first" not in M._tools([tool()], "world")[0]


def test_a_tools_arguments_at_their_limits():
    ok = {"type": "string", "description": "d" * 200, "enum": ["a"]}
    assert M._param_ok("n", ok) and M._param_ok("n", {**ok, "enum": list("abcdefghijkl")}) and M._param_ok("n", {"type": "integer"})
    for bad in ({**ok, "description": "d" * 201}, {**ok, "enum": []}, {**ok, "enum": list("abcdefghijklm")}, {**ok, "enum": "ab"},
                {**ok, "x": 1}, {"type": "list"}, "string"):
        assert not M._param_ok("n", bad)
    assert not M._param_ok("Bad", {"type": "string"})


# --- belongings, logs, the store, status --------------------------------------------------------------------------------------------------
def test_belongings_at_their_limits():
    assert M._belongings({"most": 1}) == {"takes": [], "gives": [], "most": 1}
    assert M._belongings({"gives": ["food"], "most": 20})["gives"] == ["food"]
    why = ("`belongings` is {takes?, gives?, most}: kinds of thing (food, material, seed, tool), and at most 1 to 20 at a time")
    for bad in ({"most": 0}, {"most": 21}, {"most": 2, "x": 1}, [], {"gives": ["gold"], "most": 1}, {"takes": "seed", "most": 1}):
        assert refused(M._belongings, bad) == why


def test_belongings_in_a_world_with_no_kinds(tmp_path):
    from app import world_pack as W
    from app.config import Settings
    from tests.test_world_pack import pack_dir
    try:
        W.set_active(W.load(Settings(world_pack=str(pack_dir(tmp_path)))))
        assert refused(M._belongings, {"takes": ["seed"], "most": 1}).startswith("`belongings` is {takes?, gives?, most}: kinds of thing (this world has none)")
    finally:
        W.set_active(W.load(Settings()))


def test_log_words_and_limits():
    assert refused(M._log, "") == "`log` is a line of text"
    assert refused(M._log, {"text": "x"}) == "`log` is a line, or {text, kind, feel?, items?, tool?}: kind is a word (lowercase letters and underscores)"
    assert M._log({"text": "x", "kind": "a", "feel": {"joy": 5}})["feel"] == {"joy": 5}
    assert refused(M._log, {"text": "x", "kind": "a", "feel": {"joy": 6}}) == (
        "`log.feel` maps emotions (joy, sadness, anger, fear, trust, disgust, surprise, anticipation) to whole numbers from -5 to 5")


def test_the_store_counts_what_is_already_there_and_what_goes(tmp_path):
    s, st, agent = modular(tmp_path)
    st.merge_store("pots", {"a": {f"k{i}": 1 for i in range(200)}})
    assert M._store(st, "pots", {"a": {"k0": None, "new": 1}})                      # one goes, one comes: still 200
    with pytest.raises(M.Refused):
        M._store(st, "pots", {"a": {"new": 1}})                                        # 201
    st.merge_store("pots", {"a": {f"k{i}": None for i in range(200)}})
    assert M._store(st, "pots", {f"c{i}": {"k": 1} for i in range(8)})
    big = 64_000 - len(json.dumps({"big": {"a": ""}}))
    assert M._store(st, "pots", {"big": {"a": "x" * big}})                           # exactly 64000 bytes
    with pytest.raises(M.Refused, match="its store would be over 64000 bytes"):
        M._store(st, "pots", {"big": {"a": "x" * (big + 1)}})


def test_status_at_its_limits():
    assert len(M._status({"title": "T" * 40, "lines": ["a"] * 8, "next_at": 0.5})["lines"]) == 8
    assert M._status({"title": "T", "lines": [], "next_at": 1e12})["next_at"] == 1e12
    with pytest.raises(M.Refused, match="`status` is"):
        M._status({"title": "T", "lines": [], "next_at": 1e12 + 1})
    assert refused(M._status, {"lines": []}) == "`status.title` is a line of text"
    assert refused(M._status, {"title": "T", "lines": [""]}) == "`status line` is a line of text"
    assert M._status({"title": "T", "lines": []})["ready"] is False


def test_taking_and_giving_at_their_limits(tmp_path):
    s, st, agent, m = setup(tmp_path)
    man = m["manifest"]
    st.add_item("pea seeds", 1, "seed", "")
    st.add_item("oat seeds", 4, "seed", "")
    assert M._take(st, man, [{"item": "pea seeds"}])[0][1] == 1                       # one, unless it says
    st.add_item("oat seeds", 4, "seed", "")
    assert len(M._take(st, man, [{"item": "oat seeds"}] * 8)) == 8
    assert refused(M._take, st, man, [{"item": "oat seeds"}] * 9) == "`take` is a list of up to 8 {item, qty}"
    assert refused(M._take, st, man, ["oat seeds"]) == "`take` is a list of up to 8 {item, qty}"
    assert refused(M._take, st, man, []) == "`take` is a list of up to 8 {item, qty}"
    st.add_item("brass", 1, "material", "")
    two = {**man, "belongings": {**man["belongings"], "takes": ["seed", "tool"]}}
    assert refused(M._take, st, two, [{"item": "brass"}]) == "it can only take: seed, tool"
    assert refused(M._take, st, {**man, "belongings": {**man["belongings"], "takes": []}}, [{"item": "brass"}]) == "it can only take: nothing"
    g = {"item": "pea", "kind": "food"}
    assert M._give(st, man, [g])[0]["qty"] == 1 and len(M._give(st, man, [g] * 8)) == 8
    assert M._give(st, man, [{**g, "item": "p" * 40, "qty": 1}])[0]["item"] == "p" * 40
    shape = "`give` is a list of up to 8 {item, qty, kind, description?, attrs?}"
    for bad in ([g] * 9, [], "ab"):
        assert refused(M._give, st, man, bad) == shape
    assert refused(M._give, st, man, [{**g, "x": 1}]) == "each thing in `give` is {item, qty, kind, description?, attrs?, at?}"
    assert refused(M._give, st, man, ["pea"]) == "each thing in `give` is {item, qty, kind, description?, attrs?, at?}"
    assert refused(M._give, st, man, [{**g, "item": None}]) == "`give.item` is a line of text"
    assert refused(M._give, st, man, [{**g, "item": "p" * 41}]) == "`give.item` is a name of at most 40 characters"
    assert refused(M._give, st, man, [{**g, "description": 5}]) == "`give.description` is a line of text"
    assert refused(M._give, st, {**man, "belongings": {**man["belongings"], "gives": ["food", "tool"]}}, [{**g, "kind": "seed"}]) == "it can only give: food, tool"
    assert refused(M._give, st, {**man, "belongings": {**man["belongings"], "gives": []}}, [g]) == "it can only give: nothing"
    for qty in (0, True, "1", 4):
        assert refused(M._give, st, man, [{**g, "qty": qty}]) == "`give` qty is 1 to 3"


def test_attributes_at_their_limits():
    assert len(M._attrs({f"a{c}": 1 for c in "abcdefgh"})) == 8
    assert M._attrs({"a": "x" * (500 - len(json.dumps({"a": ""})))})
    why = "`attrs` is up to 8 plain values; `restores` maps the world's stats (hunger, energy) to 0 to 1"
    assert refused(M._attrs, {"a": "x" * (501 - len(json.dumps({"a": ""})))}) == why
    assert refused(M._attrs, []) == why


# --- requests -----------------------------------------------------------------------------------------------------------------------------
def test_requests_at_their_limits(tmp_path):
    s, st, agent, m = setup(tmp_path)
    asker = live(st, rule(name="rain", proposes=["request"]), "x")
    assert M._request(st, asker, {"module": "pots", "what": "water"}) == {"module": "pots", "what": "water", "args": {}}
    room = 2000 - len(json.dumps({"a": ""}))
    assert M._request(st, asker, {"module": "pots", "what": "water", "args": {"a": "x" * room}})["args"]["a"] == "x" * room
    assert refused(M._request, st, asker, {"module": "pots", "what": "water", "args": {"a": "x" * (room + 1)}}) == "`request` is {module, what, args?}"
    assert refused(M._request, st, m, {"module": "pots", "what": "water"}) == "a module changes its own state itself, not by asking"
    live(st, rule(name="deaf"), "x")
    assert refused(M.answering, st, "deaf", "x") == "deaf answers: nothing"


# --- tools offered, used; sessions; status lines --------------------------------------------------------------------------------------------
async def test_only_live_modules_offer_tools(tmp_path):
    s, st, agent, m = setup(tmp_path)
    M.disable(st, m["id"])
    assert M.tools_offered(st) == [] and await use(agent, "pot", seed="x") == {"id": "1", "name": "pot", "followup": True, "is_error": True,
                                                                               "content": "error: unknown or disabled tool 'pot'"}


async def test_using_a_tool_says_what_happened(tmp_path):
    s, st, agent = modular(tmp_path)
    src = "def on_action(ctx):\n    return {'state': {'n': 1}} if ctx['args'].get('n') else {}\n"
    t = {"name": "empty_pot", "help": "x", "params": {"type": "object", "properties": {"n": {"type": "integer"}}, "required": []}}
    m = live(st, rule(name="pots", hooks=["on_action"], tools=[t]), src)
    tool_ = m["manifest"]["tools"][0]
    assert await M.use_tool(st, s, agent.runner, m, tool_, {"n": 1}) == ("you empty pot.", True)
    assert await M.use_tool(st, s, agent.runner, m, tool_, {}) == ("you empty pot.", False)
    assert await M.use_tool(st, s, agent.runner, m, tool_, {"n": "x"}) == ("error: `n` is a integer", False)
    assert await M.use_tool(st, s, None, m, tool_, {}) == ("error: that can't be done right now", False)    # the world's: needs the runner
    shipped = {**m, "author": M.SHIPPED}
    assert await M.use_tool(st, s, None, shipped, tool_, {"n": 1}) == ("you empty pot.", True)           # the engine's own run here
    bad = live(st, rule(name="bad", hooks=["on_action"], tools=[{**t, "name": "bad_tool"}]), "def on_action(ctx):\n    return {'nope': 1}\n")
    assert await M.use_tool(st, s, agent.runner, bad, bad["manifest"]["tools"][0], {}) == ("error: it returned nope, which its manifest doesn't propose", False)
    broken = live(st, rule(name="broken", hooks=["on_action"], tools=[{**t, "name": "broke"}]), "def on_action(ctx):\n    return 1 / 0\n")
    text, changed = await M.use_tool(st, s, agent.runner, broken, broken["manifest"]["tools"][0], {})
    assert text.startswith("error: it didn't work (") and "ZeroDivisionError" in text and changed is False


TIMED = "def on_action(ctx):\n    return {'session': {'minutes': 30, 'label': ''}}\n\ndef on_time(ctx):\n    return {'state': {'s': ctx['session'], 'hour': ctx['time']['hour']}}\n"


async def test_a_session_ends_in_on_time_with_how_long_it_ran(tmp_path):
    s, st, agent = modular(tmp_path)
    m = live(st, rule(name="nap", hooks=["on_action", "on_time"], proposes=["session", "state"]), TIMED, author=M.SHIPPED)
    st.start_session(0, 0, 30, time.time() + 1800, kind="module", target="nap", expect="")
    st.db.execute("UPDATE work_session SET started_at = ?", (NOW,))
    st.db.commit()
    assert M.busy_with(st.session()) == "something"
    assert await M.end_session(st, s, None, now=NOW + 1800) == {"label": "something", "module": "nap", "interrupted": False}
    assert st.module(m["id"])["state"] == {"s": {"label": "something", "interrupted": False, "minutes": 30}, "hour": time.localtime(NOW + 1800).tm_hour}


async def test_a_session_whose_module_is_gone_or_deaf_just_ends(tmp_path):
    s, st, agent = modular(tmp_path)
    st.start_session(0, 0, 30, time.time() + 1800, kind="module", target="gone", expect="digging")
    assert await M.end_session(st, s, agent.runner, interrupted=True) == {"label": "digging", "module": "gone", "interrupted": True}
    m = live(st, rule(name="deaf", hooks=["on_tick"]), "def on_tick(ctx):\n    return {}\n")
    st.start_session(0, 0, 30, time.time() + 1800, kind="module", target="deaf", expect="x")
    assert (await M.end_session(st, s, agent.runner))["module"] == "deaf" and st.module_calls(m["id"]) == []
    w = live(st, rule(name="world", hooks=["on_action", "on_time"], proposes=["session", "state"]), TIMED)
    st.start_session(0, 0, 30, time.time() + 1800, kind="module", target="world", expect="x")
    await M.end_session(st, s, None)                                        # the world's module, with no runner: not run
    assert st.module_calls(w["id"]) == [] and st.session() is None


def test_status_lines_from_every_module(tmp_path):
    s, st, agent = modular(tmp_path)
    for name in ("pots", "bees"):
        m = live(st, rule(name=name), "x")
        st.update_module(m["id"], standing={"title": name.title(), "lines": ["a"], "ready": False})
    assert M.status_lines(st) == ["Pots:", "- a", "Bees:", "- a"]


def test_a_thing_given_where_it_was_found(tmp_path):
    s, st, agent, m = setup(tmp_path)
    man = m["manifest"]
    assert M._give(st, man, [{"item": "pea", "kind": "food", "at": "woods"}])[0]["at"] == "woods"
    assert refused(M._give, st, man, [{"item": "pea", "kind": "food", "at": "Nowhere"}]) == "`give.at` is the key of the place it was found"
    assert refused(M._give, st, man, [{"item": "pea", "kind": "food", "at": 3}]) == "`give.at` is the key of the place it was found"
