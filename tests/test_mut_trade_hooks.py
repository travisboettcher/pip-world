"""The generic hooks trade proved (0.38.0), at their edges: `coins`, `part_with`, `whereabouts`, `notes`, the `for_sale` fact, and what a
given thing the world knows becomes (modules.py)."""
import pytest

from app import modules as M
from app.world import normalize_attrs
from tests.test_modules import live, modular, rule


def refused(fn, *args):
    with pytest.raises(M.Refused) as e:
        fn(*args)
    return str(e.value)


def test_coins_in_whole_numbers_up_to_the_manifests_most_and_never_more_than_the_agent_has(tmp_path):
    s, st, agent = modular(tmp_path)
    man = {"belongings": {"coins": 5}}
    assert M._coins(st, man, 5) == 5 and M._coins(st, man, -5) == -5 and M._coins(st, man, 1) == 1
    shape = "`coins` is a whole number of coins to the agent (or less than 0, from it), at most 5 either way"
    for bad in (0, 6, -6, True, 1.0, "2"):
        assert refused(M._coins, st, man, bad) == shape
    assert refused(M._coins, st, {}, 1) == "`coins` is a whole number of coins to the agent (or less than 0, from it), at most 0 either way"
    assert refused(M._coins, st, {"belongings": None}, 1).endswith("at most 0 either way")
    st.add_coins("pip", -7)                                                   # 3 left
    rich = {"belongings": {"coins": 500}}
    assert M._coins(st, rich, -3) == -3 and refused(M._coins, st, rich, -4) == "Pip has only 3 coins"
    st.add_coins("pip", -3)
    assert M._coins(st, rich, 1) == 1 and refused(M._coins, st, rich, -1) == "Pip has only 0 coins"


def test_part_with_names_a_creation_the_agent_has_and_who_has_it_now(tmp_path):
    s, st, agent = modular(tmp_path)
    st.add_creation("Brass Walker", "it walks", None, "fine", {"capabilities": {}}, {})
    assert M._part_with(st, {"creation": "brass walker", "to": " a buyer "}) == {"creation": "Brass Walker", "to": "a buyer"}
    for bad in ([], {"creation": "Brass Walker"}, {"creation": "Brass Walker", "to": "x", "y": 1}, {"creation": 3, "to": "x"}):
        assert refused(M._part_with, st, bad) == "`part_with` is {creation, to}"
    assert refused(M._part_with, st, {"creation": "Kite", "to": "x"}) == "Pip has no creation called 'Kite'"
    assert refused(M._part_with, st, {"creation": "Brass Walker", "to": " "}) == "`part_with.to` is a line of text"


def test_whereabouts_and_notes_are_about_people_in_the_world(tmp_path):
    s, st, agent = modular(tmp_path)
    st.add_character("Oriel", "neighbor", None, "x", 60, 0)
    st.add_character("Ann", "resident", None, "x", 60, 0)
    st.add_character("Bell", "creation", None, "x", 60, 0)
    assert M._whereabouts(st, {"Oriel": {"at": " Brygdon ", "doing": " at a stall "}, "Ann": {"at": "Quay", "doing": " "}}) == \
        {"Oriel": {"at": "Brygdon", "doing": "at a stall"}, "Ann": {"at": "Quay"}}
    assert M._whereabouts(st, {}) == {} and M._whereabouts(st, {"Ann": {"at": "Quay", "doing": "d" * 200}})["Ann"]["doing"] == "d" * 200
    shape = "`whereabouts` maps people in the world to {at: a place's key, doing?}; {} when they are all at home"
    for bad in ([], {"Bell": {"at": "x"}}, {"Nobody": {"at": "x"}}, {"Oriel": "Brygdon"}, {"Oriel": {"at": "x", "y": 1}}, {"Oriel": {"at": 3}},
                {"Oriel": {"at": " "}}, {"Oriel": {"doing": "x"}}, {"Oriel": {"at": "x", "doing": 3}}, {"Oriel": {"at": "x", "doing": "d" * 201}}):
        assert refused(M._whereabouts, st, bad) == shape
    for i in range(8):
        st.add_character(f"N{i}", "neighbor", None, "x", 60, 0)
    assert len(M._whereabouts(st, {f"N{i}": {"at": "x"} for i in range(8)})) == 8
    assert refused(M._whereabouts, st, {**{f"N{i}": {"at": "x"} for i in range(8)}, "Oriel": {"at": "x"}}) == shape
    assert M._notes(st, {"Oriel": "  sells   floats ", "Ann": "n" * 300}) == {"Oriel": "sells floats", "Ann": "n" * 300}
    for bad in ([], {"Bell": "x"}, {"Oriel": " "}, {"Oriel": 3}, {"Oriel": "n" * 301}, {f"N{i}": "x" for i in range(8)} | {"Oriel": "x"}):
        assert refused(M._notes, st, bad) == "`notes` maps people in the world to a line (at most 300 characters); {} clears them"


def test_only_live_modules_say_where_people_are_what_they_are_like_and_what_is_for_sale(tmp_path):
    s, st, agent = modular(tmp_path)
    a = live(st, rule(name="aaa"), "x")
    b = live(st, rule(name="bbb"), "x")
    st.update_module(a["id"], whereabouts={"Oriel": {"at": "Brygdon"}}, notes={"Oriel": "sells floats"},
                     facts={"for_sale": [["Brygdon", "floats", 3, "Oriel"], ["Saltholm", "wire", 2], ["Quay", "rope", 4, 5], ["x", "y"],
                                         ["x", "y", "3"], [1, "y", 3], ["x", 2, 3], "row", {"a": 1}]})
    st.update_module(b["id"], whereabouts={"Ann": {"at": "Quay"}}, notes={"Oriel": "keeps bees"}, facts={"for_sale": "nope"})
    assert M.whereabouts(st, "Oriel") == {"at": "Brygdon"} and M.whereabouts(st, "Ann") == {"at": "Quay"} and M.whereabouts(st, "Bo") is None
    assert M.notes_on(st, "Oriel") == ["sells floats", "keeps bees"] and M.notes_on(st, "Ann") == []
    assert M.for_sale(st) == [("Brygdon", "floats", 3, "Oriel"), ("Saltholm", "wire", 2, ""), ("Quay", "rope", 4, "")]
    M.disable(st, a["id"])
    assert M.whereabouts(st, "Oriel") is None and M.notes_on(st, "Oriel") == ["keeps bees"] and M.for_sale(st) == []


def test_a_given_thing_the_world_knows_gets_the_worlds_attributes(tmp_path):
    from app import finds
    known = next(e for t in finds.loot().values() for e in t if e[0] == "carrot seeds")
    assert M._as_known({"item": "Carrot Seed", "kind": "seed", "attrs": {}}) == normalize_attrs("Carrot Seed", "seed", dict(known[5]))
    assert M._as_known({"item": "carrot seeds", "kind": "seed", "attrs": {"yield": 9}}) == normalize_attrs("carrot seeds", "seed", {"yield": 9})
    assert M._as_known({"item": "carrot seeds", "kind": "material", "attrs": {}}) == {}                 # the same name, another kind
    assert M._as_known({"item": "moon pips", "kind": "seed", "attrs": {}}) == normalize_attrs("moon pips", "seed", {})
    assert M._as_known({"item": "moon pips", "kind": "seed", "attrs": {}})["crop"] == "moon pips"
    assert M._as_known({"item": "bun", "kind": "food", "attrs": {}})["food_value"] > 0


WARE = {"type": "object", "properties": {"name": {"type": "string"}, "per_day": {"type": "integer"}}, "required": ["name"]}


def test_a_list_answer_keeps_the_items_that_fit_and_at_most_twelve():
    params = {"properties": {"wares": {"type": "array", "items": WARE}, "n": {"type": "number"}}, "required": []}
    got, why = M.check_args(params, {"wares": [{"name": "a", "per_day": "2"}, {"per_day": 1}, {"name": "b", "x": 1}, "c", {"name": "d"}]})
    assert why == "" and got == {"wares": [{"name": "a", "per_day": 2}, {"name": "d"}]}
    assert M.check_args(params, {"wares": "a"}) == ({}, "`wares` is a list")
    assert len(M.check_args(params, {"wares": [{"name": str(i)} for i in range(13)]})[0]["wares"]) == 12
    loose = {"properties": {"wares": {"type": "array", "items": {"type": "object", "properties": {"name": {"type": "string"}}}}}, "required": []}
    assert M.check_args(loose, {"wares": [{}, {"name": "a"}]})[0] == {"wares": [{}, {"name": "a"}]}         # no `required`: none needed
    assert M.check_args(params, {"n": True}) == ({}, "`n` is a number") and M.check_args(params, {"n": 2})[0] == {"n": 2}


def test_what_a_list_answer_may_ask_for():
    ok = {"type": "array", "items": WARE}
    assert M._list_ok("wares", ok) and M._list_ok("wares", {**ok, "description": "d" * 200})
    assert M._list_ok("wares", {**ok, "items": {"type": "object", "properties": {"name": {"type": "string"}}}})
    eight = {f"p{c}": {"type": "string"} for c in "abcdefgh"}
    assert M._list_ok("wares", {**ok, "items": {"type": "object", "properties": eight}})
    for bad in ({**ok, "description": "d" * 201}, {**ok, "description": 3}, {**ok, "x": 1}, {**ok, "type": "object"},
                {**ok, "items": {**WARE, "type": "array"}}, {**ok, "items": {**WARE, "x": 1}}, {**ok, "items": {"type": "object", "properties": {}}},
                {**ok, "items": {"type": "object", "properties": {**eight, "pi": {"type": "string"}}}},
                {**ok, "items": {**WARE, "required": ["nope"]}}, {**ok, "items": {**WARE, "required": "name"}},
                {**ok, "items": {"type": "object", "properties": {"n": {"type": "list"}}}}, {**ok, "items": {"type": "object", "properties": []}}):
        assert not M._list_ok("wares", bad), bad
    assert not M._list_ok("Bad Name", ok) and not M._list_ok("wares", {**ok, "items": "x"}) and not M._list_ok("wares", "x")


async def test_a_shipped_rule_the_engine_no_longer_ships_steps_aside(tmp_path):
    s, st, agent = modular(tmp_path)
    old = live(st, rule(name="stall-customers"), "x", author=M.SHIPPED)
    mine = live(st, rule(name="my-rule"), "x", author="world")
    await M.offer_library(st, s, None, 1000.0)
    got = st.module(old["id"])
    assert (got["status"], got["note"], got["decided_at"]) == ("disabled", "the engine no longer ships it", 1000.0)
    assert st.module(mine["id"])["status"] == "live"                          # not the engine's: left alone
    assert [e["data"]["why"] for e in st.events(200) if e["kind"] == "module_disabled" and e["data"]["name"] == "stall-customers"] == ["the engine no longer ships it"]


def test_the_reads_trade_added(tmp_path):
    import time
    s, st, agent = modular(tmp_path)
    st.add_character("Oriel", "neighbor", None, "x", 60, 0)
    st.update_character(st.characters("neighbor")[0]["id"], about="reads tides")
    st.add_character("Ann", "resident", None, "x", 60, 0)
    now = time.time()
    for key, kind in (("Brygdon", "market"), ("Fen", "wild")):
        st.add_place(key, key.lower(), kind=kind, status="real", created_at=now, heard_at=now, hours=[9, 17], daylight_only=0, walk_minutes=10.0,
                     loot=[["awl", "tool", 3, [1, 2], "an awl", {"x": 1}]], verbs={"gather": ["forage", "foraging"]})
    a = live(st, rule(name="aaa", hooks=["on_request"], answers={"grow": "x", "dig": "y"}), "x")
    live(st, rule(name="bbb", hooks=["on_request"], answers={"sow": "x"}), "x")
    st.update_module(live(st, rule(name="ccc", hooks=["on_request"], answers={"hide": "x"}), "x")["id"], status="disabled")
    ctx = M.context(st, s, live(st, rule(name="eye", reads=["answers", "people", "places"]), "x"), now)
    assert ctx["answers"] == {"aaa": ["dig", "grow"], "bbb": ["sow"]} and a["id"]
    assert ctx["people"] == [{"name": "Oriel", "kind": "neighbor", "about": "reads tides", "home": "Oriel's home"},
                             {"name": "Ann", "kind": "resident", "about": ""}]
    by = {p["key"]: p for p in ctx["places"]}
    assert by["Brygdon"] == {"key": "Brygdon", "label": "Brygdon", "kind": "market", "trades": True, "stalls": True, "hours": [9, 17],
                             "goods": [{"name": "awl", "kind": "tool", "weight": 3, "span": [1, 2], "attrs": {"x": 1}}]}
    assert by["Fen"]["goods"] == [] and by["Fen"]["trades"] is False and by["Fen"]["hours"] == [9, 17]      # finds, but no booth: nothing for sale
    from app import finds
    assert finds.goods(st, "Fen")[0][0] == "awl"
    assert "answers" not in M.context(st, s, live(st, rule(name="other", reads=["people"]), "x"), now)


def tool(**t):
    return M._tools([{"name": "dig", "help": "dig here", **t}], "world")[0]


def test_where_a_tool_works_may_be_a_list_and_kinds_of_place(tmp_path):
    assert tool(where=[" offered ", "neighbor"], kinds=["shop", "market"]) == {"name": "dig", "help": "dig here", "where": ["offered", "neighbor"],
                                                                              "kinds": ["shop", "market"], "params": {"type": "object", "properties": {}, "required": []}}
    assert tool(where=" home ")["where"] == "home" and "kinds" not in tool() and tool()["where"] == "anywhere"
    assert tool(where=["a", "b", "c", "d"])["where"] == ["a", "b", "c", "d"] and tool(where=["x" * 60])["where"] == ["x" * 60]
    assert tool(kinds=list("abcdefgh"))["kinds"] == list("abcdefgh")
    where = "`dig`'s `where` is anywhere, home, neighbor, offered, or a place's key (or a list of them)"
    for bad in ([], ["a", "b", "c", "d", "e"], [" "], [3], ["x" * 61], 3, "x" * 61, " "):
        with pytest.raises(M.Refused) as e:
            tool(where=bad)
        assert str(e.value) == where, bad
    for bad in ([], list("abcdefghi"), "shop", ["Shop"], [3], ["shop", 3]):
        with pytest.raises(M.Refused) as e:
            tool(kinds=bad)
        assert str(e.value) == "`dig`'s `kinds` is a list of the kinds of place it works at", bad


def test_belongings_may_carry_coins(tmp_path):
    assert M._belongings({"most": 1}) == {"takes": [], "gives": [], "most": 1}
    assert M._belongings({"most": 20, "coins": 500, "gives": ["food"], "takes": ["seed"]}) == {"takes": ["seed"], "gives": ["food"], "most": 20, "coins": 500}
    assert M._belongings({"most": 3, "coins": 0}) == {"takes": [], "gives": [], "most": 3}
    for bad in ({"most": 0}, {"most": 21}, {"most": 2, "coins": 501}, {"most": 2, "coins": -1}, {"most": 2, "coins": "5"}, {"most": 2, "x": 1}, [],
                {"most": 2, "gives": ["gold"]}, {"most": 2, "takes": "food"}):
        with pytest.raises(M.Refused) as e:
            M._belongings(bad)
        assert str(e.value).startswith("`belongings` is {takes?, gives?, most, coins?}: kinds of thing (") and str(e.value).endswith(
            "), at most 1 to 20 at a time, and coins (at most 500 a call)"), bad


def test_eight_people_at_most_have_notes(tmp_path):
    s, st, agent = modular(tmp_path)
    for c in "abcdefgh":
        st.add_character(f"N{c}", "neighbor", None, "x", 60, 0)
    assert len(M._notes(st, {f"N{c}": "x" for c in "abcdefgh"})) == 8 and M._notes(st, {}) == {}


def test_an_empty_argument_is_skipped_not_the_rest():
    params = {"properties": {"a": {"type": "string"}, "b": {"type": "integer"}}, "required": []}
    assert M.check_args(params, {"a": None, "b": "3"}) == ({"b": 3}, "") and M.check_args(params, {"a": "", "b": "x"}) == ({}, "`b` is a integer")


async def test_a_creations_workings_are_not_retired_with_the_rules(tmp_path):
    s, st, agent = modular(tmp_path)
    from tests.test_world_view import clock
    clock(st)
    await M.offer_library(st, s, None, 1000.0)
    work = [m for m in st.modules("live") if m["kind"] == "thing"]
    assert work                                                             # a clock's workings: shipped, a thing, not a rule
    await M.offer_library(st, s, None, 2000.0)
    assert [m["id"] for m in st.modules("live") if m["kind"] == "thing"] == [m["id"] for m in work]


def test_tool_and_belongings_edges_word_for_word():
    from app import world as world_content
    assert tool(kinds=["shop"])["kinds"] == ["shop"]
    with pytest.raises(M.Refused) as e:
        M._tools([{"name": "dig", "help": " "}], "world")
    assert str(e.value) == "`dig.help` is a line of text"
    with pytest.raises(M.Refused) as e:
        M._text("x" * 201, "what")
    assert str(e.value) == "`what` is at most 200 characters" and M._text(" x ", "what") == "x" and M._text("x" * 300, "what", 300) == "x" * 300
    with pytest.raises(M.Refused) as e:
        M._belongings({"most": 0})
    assert str(e.value) == (f"`belongings` is {{takes?, gives?, most, coins?}}: kinds of thing ({', '.join(sorted(world_content.kinds()))}), at most 1 to 20 "
                            "at a time, and coins (at most 500 a call)")


def test_an_argument_after_a_list_is_checked_too():
    params = {"properties": {"wares": {"type": "array", "items": WARE}, "n": {"type": "integer"}}, "required": []}
    assert M.check_args(params, {"wares": [{"name": "a"}], "n": "2"}) == ({"wares": [{"name": "a"}], "n": 2}, "")
    assert M.check_args(params, {"wares": [], "n": "x"}) == ({}, "`n` is a integer")


# --- the engine reading what modules say ----------------------------------------------------------------------------------------------
async def test_meeting_a_neighbour_away_from_home_says_what_they_are_doing(tmp_path):
    import time
    import app.neighbors as nb
    from tests.test_neighbor import neighbor
    from tests.test_projects import FixedRng, make, report
    s, st, gm, agent = make(tmp_path, [report(text="Pip! Buying or selling?"), report(text="Hello again.")], modules="on", module_runner="local")
    neighbor(st, s)
    now = time.time()
    st.add_place("Brygdon", "brygdon", kind="market", status="real", created_at=now, heard_at=now, hours=[0, 24], daylight_only=0, walk_minutes=10.0,
                 loot=[], verbs={})
    m = live(st, rule(name="aaa"), "x")
    st.update_module(m["id"], whereabouts={"Marigold": {"at": "Brygdon", "doing": "minding a stall at Brygdon today"}})
    st.update_agent(location="Brygdon")
    st.set_meta(arrived_at=str(now))
    await nb.step(st, s, agent.gm, FixedRng(), now)
    task = gm.calls[0]["messages"][0]["content"]
    assert "who Pip meets at Brygdon" in task and "Pip seems " in task and " Marigold is minding a stall at Brygdon today." in task
    st.update_module(m["id"], whereabouts={"Marigold": {"at": "Brygdon"}})
    st.set_meta(arrived_at=str(now + 7200))
    await nb.step(st, s, agent.gm, FixedRng(), now + 7200)
    assert " Marigold is at Brygdon." in gm.calls[-1]["messages"][0]["content"]


def test_a_neighbours_notes_and_wares_each_bring_a_trade_note(tmp_path):
    import app.neighbors as nb
    from tests.test_neighbor import neighbor
    from tests.test_projects import FixedRng
    s, st, agent = modular(tmp_path)
    ch = neighbor(st, s)
    m = live(st, rule(name="aaa"), "x")
    st.update_module(m["id"], notes={"Marigold": "keeps bees"})
    assert nb.trade_note(st, ch, FixedRng(0.1)) == "Marigold keeps bees"
    live2 = live(st, rule(name="bbb"), "x")
    st.update_module(live2["id"], notes={"Marigold": "mends nets"})
    assert nb.trade_note(st, ch, FixedRng(0.9)) == "Marigold keeps bees Marigold mends nets"
    assert "(keeps bees; mends nets)" in "\n".join(nb.perception(st))
    st.update_module(m["id"], notes={}, facts={"for_sale": [["Marigold's home", "honey", 4, "Marigold"]]})
    st.update_module(live2["id"], notes={})
    assert nb.trade_note(st, ch, FixedRng(0.1)) == "If it fits, Marigold could offer Pip honey (4 coins each)."
    assert nb.trade_note(st, ch, FixedRng(0.9)) == ""


def test_the_kind_of_a_place(tmp_path):
    from app import places as P
    s, st, agent = modular(tmp_path)
    assert P.kind_of(st, P.HOME) == "home" and P.kind_of(st, "Marigold's home") == "neighbor" and P.kind_of(st, "Nowhere") == ""
    assert P.kind_of(st, "woods") == "wild" and P.kind_of(st, "junkyard") == "yard"
    st.add_place("Brygdon", "brygdon", kind="market", status="real", created_at=0, heard_at=0)
    assert P.kind_of(st, "Brygdon") == "market"


def test_a_scene_takes_only_live_modules_scene_facts_and_ignores_odd_ones(tmp_path):
    from app import world_view as WV
    from tests.test_neighbor import neighbor
    s, st, agent = modular(tmp_path)
    neighbor(st, s)
    home = "Marigold's home"
    lh = WV.scene_view(st, s, None, home)["lives_here"]
    assert (lh["wares"], lh["market_day"], lh["away_at"]) == ([], None, None)
    a, b = live(st, rule(name="aaa"), "x"), live(st, rule(name="bbb"), "x")
    st.update_module(a["id"], facts={"scene": {home: {"lives_here": {"wares": ["honey"]}, "booths": [{"booth": home, "whose": "Marigold", "items": []}, "odd"],
                                               "stall": [{"item": "x"}]}}})
    st.update_module(b["id"], facts={"scene": ["not", "a", "map"]})
    v = WV.scene_view(st, s, None, home)
    assert v["lives_here"]["wares"] == ["honey"] and v["lives_here"]["away_at"] is None and v["stall"] == [{"item": "x"}]
    assert [x["whose"] for x in v["booths"]] == ["Marigold"] and "look" in v["booths"][0]
    M.disable(st, a["id"])
    v = WV.scene_view(st, s, None, home)
    assert v["lives_here"]["wares"] == [] and v["booths"] == [] and v["stall"] == []


def test_a_wish_names_each_place_once(tmp_path):
    from app import wishes as W
    s, st, agent = modular(tmp_path)
    m = live(st, rule(name="aaa"), "x")
    st.update_module(m["id"], facts={"for_sale": [["Brygdon", "brass wire", 3], ["Brygdon", "fine brass wire", 5], ["Quay", "brass wire", 4]]})
    assert W.sources(st, "brass wire", 0) == ["Brygdon sells brass wire (3 coins)", "Quay sells brass wire (4 coins)"]


SHOP = {"type": "object", "properties": {}, "required": []}


async def test_a_module_tool_says_why_it_cant_be_used_here(tmp_path):
    from app import tools as T
    from tests.test_projects import make
    s, st, gm, agent = make(tmp_path, modules="on", module_runner="local")
    src = "def on_action(ctx):\n    return {'reply': 'done'}\n"
    live(st, rule(name="aaa", hooks=["on_action"], tools=[{"name": "dig_deep", "help": "dig", "where": ["neighbor"], "kinds": ["market"], "params": SHOP},
                                                            {"name": "haggle", "help": "haggle", "where": "offered", "params": SHOP},
                                                            {"name": "wave", "help": "wave", "where": "library", "params": SHOP}]), src)
    run = lambda name: T.module_tool(agent.ctx, name, {})  # noqa: E731
    st.update_agent(location="Marigold's home")
    r = await run("dig_deep")
    assert (r.text, r.followup) == ("there's nothing to dig deep at Marigold's home", True)
    st.update_agent(location="woods")
    assert (await run("dig_deep")).text == "you're not at the neighbor; go_to neighbor first"
    assert (await run("haggle")).text == "there's nothing to haggle at the woods"
    assert (await run("wave")).text == "you're not at the library; go_to library first"
    st.update_agent(location="library")
    assert (await run("wave")).text == "done"
    st.start_session(0, 0, 10, 10**10, kind="walk", target="woods")
    assert (await run("wave")).text.startswith("you're on the way to")
    assert await T.module_tool(agent.ctx, "nope", {}) is None


async def test_where_no_module_tool_applies_the_engines_own_answers(tmp_path):
    from app import tools as T
    from app.llm.base import ToolCall
    from tests.test_projects import make
    from tests.test_gather import daytime
    s, st, gm, agent = make(tmp_path, modules="on", module_runner="local")
    daytime(s)
    agent.tools["browse"] = T.REGISTRY["browse"]
    live(st, rule(name="aaa", hooks=["on_action"], tools=[{"name": "browse", "help": "look at the stalls", "where": "neighbor", "params": SHOP}]),
         "def on_action(ctx):\n    return {'reply': 'stalls'}\n")
    st.update_agent(location="junkyard")
    r = (await agent._run_tool(ToolCall(id="1", name="browse", arguments={}), 0))["content"]
    assert r.startswith("Looking over the junkyard")
    specs = {sp.name: sp.description for sp in agent._specs()}
    assert specs["browse"].startswith("Look over what is lying about")
    st.update_agent(location="Marigold's home")
    assert (await agent._run_tool(ToolCall(id="1", name="browse", arguments={}), 0))["content"] == "stalls"
    assert {sp.name: sp.description for sp in agent._specs()}["browse"] == "look at the stalls"
    assert sum(1 for sp in agent._specs() if sp.name == "browse") == 1


async def test_a_shut_place_offers_only_what_works_anywhere_and_an_invented_one_its_own_verbs(tmp_path):
    import random
    import time
    from app import invented_places as IP
    from app import tools as T
    from tests.test_gather import daytime, night
    from tests.test_projects import make
    s, st, gm, agent = make(tmp_path, modules="on", module_runner="local")
    agent.tools.update({n: T.REGISTRY[n] for n in ("browse", "say")})
    live(st, rule(name="aaa", hooks=["on_action"], tools=[{"name": "dig_deep", "help": "dig", "where": "junkyard", "params": SHOP}]), "x")
    st.update_agent(location="junkyard")
    daytime(s)
    assert {"browse", "say", "dig_deep"} <= {sp.name for sp in agent._specs()}
    night(s)
    assert {sp.name for sp in agent._specs()} & {"browse", "dig_deep"} == set() and "say" in {sp.name for sp in agent._specs()}
    daytime(s)
    rec = IP.accept(st, "Briar", "Grimsby Tip is all scrap heaps.", {"place": "Grimsby Tip", "there": "scrap heaps"}, now=time.time())
    IP.design(st, rec, {"kind": "yard", "description": "Heaps.", "loot": [{"name": "scrap iron", "kind": "material"}, {"name": "chain", "kind": "material"}]},
              random.Random(1))
    st.update_agent(location="Grimsby Tip")
    assert "browse" in {sp.name for sp in agent._specs()} and "dig_deep" not in {sp.name for sp in agent._specs()}


def test_two_modules_offering_a_tool_of_one_name_list_it_once(tmp_path):
    from app import tools as T
    s, st, agent = modular(tmp_path)
    live(st, rule(name="aaa", hooks=["on_action"], tools=[{"name": "dig_deep", "help": "first", "params": SHOP}]), "x")
    live(st, rule(name="bbb", hooks=["on_action"], tools=[{"name": "dig_deep", "help": "second", "params": SHOP}]), "x")
    assert [(sp.name, sp.description) for sp in T.module_specs(st, "woods")] == [("dig_deep", "first")]
