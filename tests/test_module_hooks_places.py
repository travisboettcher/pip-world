"""The hooks phase 5a added (docs/DESIGN-world-packs.md, "Phase 5 in detail"): the `here` and `abilities` reads, `practice`, `deplete`,
`doing`, `owe`, a moment's `items` and `tool`, and tools offered where a place lists them."""
import time
from datetime import datetime
from types import SimpleNamespace

import pytest

from app import finds as F
from app import modules as M
from app import tools as T
from tests.test_modules import NOW, live, modular, rule


def refused(fn, *args):
    with pytest.raises(M.Refused) as e:
        fn(*args)
    return str(e.value)


def daytime(s):
    h = datetime.now().hour
    s.bedtime_hour, s.wake_hour = (h + 3) % 24, (h + 8) % 24


# --- reads ---------------------------------------------------------------------------------------------------------------------------------
def test_here_is_the_place_the_agent_is_at(tmp_path):
    s, st, agent = modular(tmp_path)
    daytime(s)
    m = live(st, rule(name="eye", reads=["here", "abilities"]), "x")
    st.update_agent(location="woods")
    st.add_ability_xp({"handiness": 540})
    now = time.time()
    st.set_meta(**{"stock:woods": 50, "stock_at:woods": now})
    ctx = M.context(st, s, m, now)
    h = ctx["here"]
    assert (h["key"], h["label"], h["kind"], h["open"], h["gerund"], h["stock"], h["full_at"]) == ("woods", "the woods", "wild", True, "foraging", 50, 60)
    assert (h["session"], h["capacity"], h["refill"], h["shop_hours"], h["trades"]) == ([15, 60], 120, 15, False, False)
    assert h["finds"][0] == list(F.loot()["woods"][0][:3]) + [list(F.loot()["woods"][0][3]), F.loot()["woods"][0][4], F.loot()["woods"][0][5]]
    assert "gather" in h["verbs"] and ctx["abilities"] == {"handiness": 3}
    st.start_session(0, 0, 10, now + 600, kind="walk", target="junkyard")
    assert M.context(st, s, m, now)["here"] is None                                # on the way somewhere


def test_here_at_a_shop(tmp_path):
    from tests.test_invented_places import real_shop
    s, st, agent = modular(tmp_path)
    real_shop(st)
    st.update_agent(location="Saltholm")
    h = M.here_read(st, s, time.time())
    assert (h["kind"], h["shop_hours"], h["trades"], h["capacity"], h["refill"], h["session"], h["full_at"]) == ("shop", True, True, 40, 2, [15, 30], 20)


# --- proposals -----------------------------------------------------------------------------------------------------------------------------
def test_practice_deplete_doing_and_owe_at_their_edges(tmp_path):
    from tests.test_invented_places import real_shop
    s, st, agent = modular(tmp_path)
    assert M._practice({"handiness": 120, "patience": 120}) == {"handiness": 120.0, "patience": 120.0}
    for bad in ({"handiness": 121, "patience": 120}, {"juggling": 1}, {"handiness": -1}, {}, []):
        assert refused(M._practice, bad).startswith("`practice` maps abilities (")
    st.update_agent(location="woods")
    assert M._deplete(st, {"amount": 240}) == {"place": "woods", "amount": 240.0}
    assert M._deplete(st, {"amount": 0, "place": "junkyard"}) == {"place": "junkyard", "amount": 0.0}
    for bad in ({"amount": 241}, {"amount": -1}, {"amount": 5, "x": 1}, []):
        assert refused(M._deplete, st, bad) == "`deplete` is {amount (0 to 240), place?}"
    st.start_session(0, 0, 10, time.time() + 600, kind="walk", target="junkyard")
    assert refused(M._deplete, st, {"amount": 1}) == "`deplete.place` is a place's key (the agent is between places)"
    assert M._doing({"activity": "gathering", "description": " out "}) == {"activity": "gathering", "description": "out"}
    for bad in ({"activity": "Bad", "description": "x"}, {"activity": "a", "description": "x", "y": 1}, []):
        assert refused(M._doing, bad) == "`doing` is {activity (a word), description}"
    assert refused(M._doing, {"activity": "a"}) == "`doing.description` is a line of text"
    real_shop(st)
    assert M._owe(st, {"place": "Saltholm", "items": {"wire": 2}}) == {"place": "Saltholm", "items": {"wire": 2}}
    shape = "`owe` is {place, items: {name: qty}}: up to 8 things"
    for bad in ({"place": "Saltholm", "items": {}}, {"place": "Saltholm", "items": {f"t{i}": 1 for i in range(9)}}, {"place": "Saltholm", "items": {"w": 0}},
                {"place": "Saltholm", "items": {"w": 51}}, {"place": "Saltholm", "items": {"w": True}}, {"place": "Saltholm", "items": {" ": 1}},
                {"place": "Saltholm", "items": {"w": 1}, "x": 1}, []):
        assert refused(M._owe, st, bad) == shape
    assert refused(M._owe, st, {"place": "woods", "items": {"w": 1}}) == "`owe.place` is a place that trades"


def test_the_proposals_land(tmp_path):
    from tests.test_invented_places import real_shop
    s, st, agent = modular(tmp_path)
    real_shop(st)
    st.update_place("Saltholm", on_account={"wire": 1})
    st.update_agent(location="woods")
    m = live(st, rule(name="hands", proposes=["practice", "deplete", "doing", "owe"]), "x")
    M.apply(st, m, M.plan(st, m, {"practice": {"handiness": 30}, "deplete": {"amount": 20}, "doing": {"activity": "digging", "description": "in the woods"},
                                  "owe": {"place": "Saltholm", "items": {"wire": 2, "nails": 1}}}, NOW, "on_tick"), NOW)
    assert st.abilities()["handiness"] == 30 and F.stock(st, "woods", NOW) == 100
    assert (st.agent()["activity"], st.agent()["description"]) == ("digging", "in the woods")
    assert st.place_row("Saltholm")["on_account"] == {"wire": 3, "nails": 1}


def test_a_moment_says_what_came_of_it(tmp_path):
    assert M._log({"text": "x", "kind": "gathered", "items": [{"name": " wire ", "qty": 2}, {"name": "nut"}], "tool": "gather"}) == {
        "text": "x", "kind": "gathered", "items": [{"name": "wire", "qty": 2}, {"name": "nut", "qty": 1}], "tool": "gather"}
    assert M._log({"text": "x", "kind": "k", "items": []})["items"] == []
    for bad in ([{"name": ""}], [{"qty": 1}], "wire", [{"name": "a", "qty": -1}], [{"name": "a"}] * 9):
        assert refused(M._log, {"text": "x", "kind": "k", "items": bad}) == "`log.items` is a list of up to 8 {name, qty}: what came of it"
    assert refused(M._log, {"text": "x", "kind": "k", "tool": "Bad Tool"}) == "`log.tool` is the name of the tool the moment comes of"


def test_a_moment_with_what_came_of_it_is_a_recent_event_a_memory_and_a_first(tmp_path):
    from app import capabilities as C
    from tests.test_projects import make
    s, st, gm, agent = make(tmp_path)
    st.log("module", name="hands", text="You find a coil of wire.", moment="gathered", items=[{"name": "wire", "qty": 1}], tool="gather")
    st.log("module", name="hands", text="It hums.")
    ev = st.events(2)[1]
    assert [f["key"] for f in ev["data"]["firsts"]] == ["found:wire"]
    p = agent._perception("timer", [])
    assert "- You find a coil of wire." in p and "- It hums." not in p
    assert st.recall("coil of wire")
    assert C.collect(st.events(5))["tool"]["gather"] == {"tries": 1, "good": 1, "neutral": 0, "bad": 0}
    st.log("tool", tool="gather", args={}, result="you set about it", module="hands")
    assert C.collect(st.events(5))["tool"]["gather"]["tries"] == 1                  # the tool's own use isn't judged: what came of it is


# --- tools offered where a place lists them ------------------------------------------------------------------------------------------------
def test_a_tool_offered_where_a_place_lists_it(tmp_path):
    s, st, agent = modular(tmp_path)
    daytime(s)
    live(st, rule(name="dig", hooks=["on_action"], tools=[{"name": "gather", "help": "Gather.", "where": "offered"}]), "x")
    woods = SimpleNamespace(scope="woods", verbs={"gather": ("forage", "Forage in the woods.")})
    assert [(t.name, t.description) for t in T.module_specs(st, "woods", woods)] == [("gather", "Forage in the woods.")]
    plain = SimpleNamespace(scope="x", verbs={"gather": ("forage", None)})
    assert [t.description for t in T.module_specs(st, "x", plain)] == ["Gather."]
    assert T.module_specs(st, "woods", woods, open_=False) == [] and T.module_specs(st, "", woods) == []
    assert T.module_specs(st, "woods", None) == [] and T.module_specs(st, "home", SimpleNamespace(scope="home", verbs={})) == []
    st.update_agent(location="woods")
    assert T.offered_here(agent.ctx, "gather") == ""
    st.update_agent(location="workshop")
    assert T.offered_here(agent.ctx, "gather") == "there's nothing to gather at home"
    assert T.offered_here(agent.ctx, "look_about") == "there's nothing to look about at home"
    st.update_agent(location="woods")
    st.start_session(0, 0, 10, time.time() + 600, kind="walk", target="junkyard")
    assert T.offered_here(agent.ctx, "gather") == "you're on the way to the junkyard; wait until you get there"


def test_what_the_agent_has_been_able_to_do_counted_exactly():
    from app import capabilities as C
    ev = lambda kind, **d: {"kind": kind, "data": d}  # noqa: E731
    got = C.collect([
        ev("gathered", items=[{"name": "a"}]), ev("gathered", items=[]), ev("gathered", items=[{"name": "a"}], interrupted=True),
        ev("module", tool="gather", items=[{"name": "b"}]), ev("module", tool="gather", items=[]), ev("module", tool="gather"), ev("module", items=[]),
        ev("tool", tool="gather", result="ok"), ev("tool", tool="plant", result="ok", module="garden"), ev("tool", tool="say", result="hi"),
        ev("tool", tool="recall", result="error: x"), ev("tool", tool="recall"), ev("tool", tool="recall", result="ok", noop=True),
        ev("work", result="breakthrough", craft="clocks", abilities=["handiness"]), ev("work", result="slow", project_id=1, stage="s"),
        ev("work", result="good", interrupted=True, craft="clocks"), ev("work", craft="clocks"), ev("work", result="awful", craft="clocks"),
        ev("experiment", outcome="insight", craft="clocks"), ev("experiment", outcome="surprise", project_id=1), ev("experiment", outcome="clue"),
        ev("experiment", outcome="nothing", interrupted=True), ev("experiment", craft="clocks"), ev("experiment", outcome="dud", project_id=2),
    ], crafts={1: "kites"}, stage_abilities={(1, "s"): ["patience"]})
    assert got["tool"] == {"gather": {"tries": 4, "good": 2, "neutral": 0, "bad": 2}, "recall": {"tries": 2, "good": 1, "neutral": 0, "bad": 1}}
    assert got["craft"] == {"clocks": {"tries": 3, "good": 2, "neutral": 0, "bad": 1}, "kites": {"tries": 2, "good": 1, "neutral": 1, "bad": 0}}
    assert got["ability"] == {"handiness": {"tries": 1, "good": 1, "neutral": 0, "bad": 0}, "patience": {"tries": 1, "good": 0, "neutral": 1, "bad": 0},
                              "ingenuity": {"tries": 4, "good": 2, "neutral": 1, "bad": 1}, "knowledge": {"tries": 4, "good": 2, "neutral": 1, "bad": 1}}


def test_the_reads_and_proposals_at_their_last_edges(tmp_path):
    from tests.test_invented_places import real_shop
    s, st, agent = modular(tmp_path)
    assert M._practice({"handiness": 0}) == {"handiness": 0.0}
    assert refused(M._practice, {"x": 1}) == "`practice` maps abilities (precision, patience, ingenuity, knowledge, handiness) to minutes, 240 in all at most"
    real_shop(st)
    assert len(M._owe(st, {"place": "Saltholm", "items": {f"t{c}": 50 for c in "abcdefgh"}})["items"]) == 8
    assert refused(M._owe, st, {"items": {"w": 1}}) == "`owe.place` is a place that trades"
    st.update_agent(location="woods")
    now = time.time()
    st.set_meta(**{"stock:woods": 50.123456, "stock_at:woods": now - 3600})
    h = M.here_read(st, s, now)
    assert h["stock"] == 65.12                                                     # refilled an hour (15), to two places
