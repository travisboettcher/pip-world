"""The module API consolidated (docs/DESIGN-engine-audit.md, D; 0.53.0): `api: 2`. Belongings go in and out by `take` and `give` (what
`consume`, `find`, `coins` and `part_with` did), a line for the record or a whole event by `event` (what `log` did), and the weather is a
published fact like any other. `api: 1` manifests still work: their old proposals are made into the new ones, with the old limits."""
import pytest

from app import capabilities, firsts
from app import modules as M
from tests.test_modules import NOW, live, modular, rule

FOLDED = {"log", "consume", "find", "coins", "part_with"}


def v2(**kw):
    return rule(**{"api": 2, **kw})


def run(st, m, result, hook="on_tick", now=NOW):
    return M.apply(st, m, M.plan(st, m, result, now, hook), now)


def refused(st, m, result, hook="on_tick"):
    with pytest.raises(M.Refused) as e:
        M.plan(st, m, result, NOW, hook)
    return str(e.value)


def clock(st):
    from tests.test_world_view import clock as made
    return made(st)


# --- what api 2 is ------------------------------------------------------------------------------------------------------------------
def test_api_2_proposes_fewer_things_and_reads_the_weather_as_a_fact():
    assert M.API == 2 and M.APIS == (1, 2)
    assert set(M.PROPOSES_V1) - set(M.PROPOSES) == FOLDED and set(M.PROPOSES) <= set(M.PROPOSES_V1) and len(M.PROPOSES) == 29
    assert set(M.READS_V1) - set(M.READS) == {"weather"} and len(M.READS) == 18
    for old in sorted(FOLDED):
        with pytest.raises(M.Refused, match="^`proposes` is a list drawn from: state, publish"):
            M.check_manifest(v2(proposes=["state", old]), "world")
    with pytest.raises(M.Refused, match="^`reads` is a list drawn from: time,"):
        M.check_manifest(v2(reads=["weather"]), "world")
    assert M.check_manifest(rule(proposes=["state", "log"]), "world")["api"] == 1                 # api 1 is still taken
    assert M.check_manifest(v2(), "world")["api"] == 2
    with pytest.raises(M.Refused, match=r"^`api` is 1 or 2$"):
        M.check_manifest(rule(api=3), "world")


def test_the_agents_programs_and_the_worlds_rules_are_written_in_api_2():
    from app import builder
    assert "log" not in M.AGENT_PROPOSES and {"event", "take"} <= set(M.AGENT_PROPOSES) and "log" not in builder.RULE_PROPOSES
    c = {"name": "Gear Clock", "spec": {"capabilities": {"upkeep": {"verb": "wound", "hours": 12}}}}
    man = M.program_manifest("def on_tick(ctx):\n    return {}\n", c)
    assert man["api"] == 2 and man["belongings"] == {"takes": ["material"], "gives": [], "most": 2} and "consumes" not in man
    assert M.check_manifest(man, "agent")["belongings"] == {"takes": ["material"], "gives": [], "most": 2}
    assert builder.manifest("def on_tick(ctx):\n    return {}\n", "bells", [])["api"] == 2


# --- take and give ----------------------------------------------------------------------------------------------------------------
def test_take_takes_things_coins_and_a_creation(tmp_path):
    s, st, agent = modular(tmp_path)
    st.add_item("brass wire", 5, "material", "")
    st.add_coins("agent", 20 - st.coins())
    clock(st)
    m = live(st, v2(name="shop", proposes=["take"], belongings={"takes": ["material", "creation"], "gives": [], "most": 5, "coins": 10}), "x")
    run(st, m, {"take": [{"item": "brass wire", "qty": 2}, {"coins": 4}, {"creation": "gear clock", "to": "Oriel"}]})
    assert st.find_item("brass wire")[0]["qty"] == 3 and st.coins() == 16 and M._creation(st, "Gear Clock") is None
    assert st.module(m["id"])["budget"]["take"] == 1                                              # one `take`, whatever it held


@pytest.mark.parametrize("take,why", [
    ({"item": "brass wire", "qty": 5}, "you need 5 brass wire for that (you have 4)"),
    ({"item": "gold"}, "you need 1 gold for that"),
    ({"item": "springs", "kind": "material"}, "you need 1 springs for that"),          # a tool called springs isn't the material
    ({"item": "springs"}, "it can only take: material, creation"),
    ({"item": "brass wire", "kind": "food"}, "it can only take: material, creation"),
    ({"item": "brass wire", "qty": 9}, "`take` qty is 1 to 5"),
    ({"coins": 11}, "`take` coins is a whole number from 1 to 10"),
    ({"coins": 0}, "`take` coins is a whole number from 1 to 10"),
    ({"coins": True}, "`take` coins is a whole number from 1 to 10"),
    ({"coins": 9}, "Pip has only 8 coins"),
    ({"creation": "Vase", "to": "Oriel"}, "Pip has no creation called 'Vase'"),
    ({"creation": "Gear Clock"}, "`take` of a creation is {creation, to}: who has it now"),
    ({"creation": "Gear Clock", "to": "Oriel", "x": 1}, "each thing in `take` is {item, qty?, kind?}, {coins} or {creation, to}"),
    ("brass wire", "each thing in `take` is {item, qty?, kind?}, {coins} or {creation, to}"),
])
def test_what_take_cant_take_is_named(tmp_path, take, why):
    s, st, agent = modular(tmp_path)
    st.add_item("brass wire", 4, "material", "")
    st.add_item("springs", 3, "tool", "")
    st.add_coins("agent", 8 - st.coins())
    clock(st)
    m = live(st, v2(name="shop", proposes=["take"], belongings={"takes": ["material", "creation"], "gives": [], "most": 5, "coins": 10}), "x")
    assert refused(st, m, {"take": [take]}) == why


def test_coins_and_creations_are_taken_only_by_a_module_that_says_so(tmp_path):
    s, st, agent = modular(tmp_path)
    clock(st)
    m = live(st, v2(name="shop", proposes=["take"], belongings={"takes": ["material"], "gives": [], "most": 5}), "x")
    assert refused(st, m, {"take": [{"coins": 1}]}) == "`take` coins is a whole number from 1 to 0"
    assert refused(st, m, {"take": [{"creation": "Gear Clock", "to": "Oriel"}]}) == "it can only take: material"
    with pytest.raises(M.Refused, match=r"^`belongings` is \{takes\?, gives\?, most, coins\?\}: kinds of thing"):
        M.check_manifest(v2(proposes=["take"], belongings={"takes": ["gold"], "gives": [], "most": 1}), "world")  # noqa


def test_give_gives_things_and_coins(tmp_path):
    s, st, agent = modular(tmp_path)
    st.add_coins("agent", 20 - st.coins())
    m = live(st, v2(name="till", proposes=["give"], belongings={"takes": [], "gives": ["material"], "most": 2, "coins": 10}), "x")
    run(st, m, {"give": [{"item": "acorn", "qty": 2, "kind": "material", "description": "a nut"}, {"coins": 7}]})
    assert st.find_item("acorn")[0]["qty"] == 2 and st.coins() == 27
    assert refused(st, m, {"give": [{"coins": 11}]}) == "`give` coins is a whole number from 1 to 10"
    assert refused(st, m, {"give": [{"coins": 1, "item": "x"}]}) == "each thing in `give` is {item, qty, kind, description?, attrs?, at?} or {coins}"


# --- event: a line, or a whole event --------------------------------------------------------------------------------------------
def test_an_event_may_be_just_a_line_for_the_record(tmp_path):
    s, st, agent = modular(tmp_path)
    m = live(st, v2(name="bells", proposes=["event"]), "x")
    run(st, m, {"event": "The bell rings for market day."})
    e = st.events(1)[0]
    assert e["kind"] == "module" and e["data"]["text"] == "The bell rings for market day." and e["data"]["name"] == "bells"
    assert st.module(m["id"])["budget"]["log"] == 1 and st.module(m["id"])["budget"].get("event", 0) == 0     # a line counts as a line
    assert refused(st, m, {"event": "x" * 201}) == "`event` is at most 200 characters"
    assert refused(st, m, {"event": {"kind": "ring", "data": {}}}).startswith("`event` is {kind, data, read?, expect?}: kind is one it logs (none)")


def test_a_whole_event_says_how_it_reads_and_the_pack_may_name_its_first(tmp_path):
    s, st, agent = modular(tmp_path)
    m = live(st, v2(name="garden", hooks=["on_time"], proposes=["event"], logs=["ripe"]), "x")
    read = {"line": "Your peas in plot 1 ripened", "moment": "Your peas in plot 1 ripened", "feel": {"joy": 3}}
    run(st, m, {"event": {"kind": "ripe", "data": {"plot": 1, "crop": "peas"}, "read": read}}, "on_time")
    e = st.events(1)[0]
    assert e["kind"] == "ripe" and e["data"]["by"] == "garden" and e["data"]["read"] == read
    got = firsts.facets("ripe", e["data"], s, NOW)
    assert ("garden:ripe", "the first time you had a crop ripen", firsts.MINOR) in got                     # Pip's content.json
    said = firsts.facets("finished_book", {"by": "reading", "read": {"line": "x"}}, s, NOW)
    assert ("book_finished", "the first time you finished a book", firsts.MINOR) in said                    # {as, said}: the old first
    assert firsts.facets("ripe", {"by": "orchard", "read": {"line": "x"}}, s, NOW) == []


def test_an_event_may_say_how_a_tool_went(tmp_path):
    read = {"line": "You gathered 2 acorns.", "tally": [{"group": "tool", "name": "gather", "outcome": "good"}],
            "firsts": [{"key": f"found:{n}", "label": f"found {n}"} for n in "abcdefgh"]}
    assert M._read(read)["tally"] == read["tally"] and len(M._read(read)["firsts"]) == 8
    got = capabilities.collect([{"kind": "haul", "data": {"by": "gathering", "read": read}}])
    assert got["tool"]["gather"] == {"tries": 1, "good": 1, "neutral": 0, "bad": 0}
    with pytest.raises(M.Refused, match="group \\(craft, ability, tool\\)"):
        M._read({"tally": [{"group": "skill", "name": "x", "outcome": "good"}]})
    with pytest.raises(M.Refused, match="^`event.read.firsts` is up to 8"):
        M._read({"firsts": [{"key": f"k{i}", "label": "x"} for i in range(9)]})


# --- the weather is a fact ------------------------------------------------------------------------------------------------------
def test_the_weather_is_read_from_what_is_published(tmp_path):
    from app.state import State  # noqa: F401
    s, st, agent = modular(tmp_path)
    sky = live(st, v2(name="sky", proposes=["publish"]), "x")
    st.update_module(sky["id"], facts={"weather": {"condition": "rain", "temp": 9.5, "unit": "C", "daylight": True}})
    old = M.context(st, s, live(st, rule(name="old-garden", reads=["weather"]), "x"), NOW)
    assert old["weather"] == {"condition": "rain", "temp": 9.5, "unit": "C", "daylight": True}               # api 1 still reads it
    new = M.context(st, s, live(st, v2(name="new-garden", reads=["facts"]), "x"), NOW)
    assert "weather" not in new and new["facts"]["sky"]["weather"]["condition"] == "rain"


# --- api 1, made into api 2 -----------------------------------------------------------------------------------------------------
def test_an_api_1_module_still_uses_up_finds_pays_and_parts_with_as_it_did(tmp_path):
    s, st, agent = modular(tmp_path)
    st.add_item("brass wire", 5, "material", "")
    st.add_item("springs", 3, "tool", "")
    st.add_coins("agent", 20 - st.coins())
    c = clock(st)
    thing = live(st, {**rule(name="gear-clock-workings", proposes=["consume", "find"], consumes={"brass wire": 2}, finds=["acorn"]),
                      "kind": "thing", "subject": c["name"]}, "x")
    run(st, thing, {"consume": {"brass wire": 2}, "find": {"item": "acorn", "qty": 1}})
    assert st.find_item("brass wire")[0]["qty"] == 3 and st.find_item("acorn")[0]["description"] == "found by your Gear Clock"
    assert refused(st, thing, {"consume": {"brass wire": 3}}) == "it may use up 1 to 2 brass wire at a time"
    assert refused(st, thing, {"consume": {"springs": 1}}) == "its manifest doesn't let it use up springs"
    assert refused(st, thing, {"consume": ["brass wire"]}) == "`consume` maps item names to quantities"
    assert refused(st, thing, {"find": {"item": "gold"}}) == "it can only find: acorn"
    assert refused(st, thing, {"find": {"item": "acorn", "qty": 3}}) == "`find.qty` is 1 or 2"
    st.take_item(st.find_item("brass wire")[0]["id"], 2)
    assert refused(st, thing, {"consume": {"brass wire": 2}}) == "you need 2 brass wire for that (you have 1)"
    shop = live(st, rule(name="old-shop", proposes=["coins", "part_with"], belongings={"takes": [], "gives": [], "most": 1, "coins": 5}), "x")
    run(st, shop, {"coins": 3})
    run(st, shop, {"coins": -2, "part_with": {"creation": "Gear Clock", "to": "Oriel"}})
    assert st.coins() == 21 and M._creation(st, "Gear Clock") is None
    assert refused(st, shop, {"coins": 6}) == "`coins` is a whole number of coins to the agent (or less than 0, from it), at most 5 either way"
    assert refused(st, shop, {"part_with": {"creation": "Gear Clock"}}) == "`part_with` is {creation, to}"


def test_an_api_1_log_is_kept_as_it_was(tmp_path):
    s, st, agent = modular(tmp_path)
    m = live(st, rule(name="bells", proposes=["log"]), "x")
    run(st, m, {"log": {"text": "The bell rang.", "kind": "rang", "feel": {"joy": 1}}})
    run(st, m, {"log": "Quiet again."})
    ev = [e for e in st.events(5) if e["kind"] == "module"]
    assert [e["data"]["text"] for e in ev] == ["Quiet again.", "The bell rang."] and ev[1]["data"]["moment"] == "rang"
    assert st.module(m["id"])["budget"]["log"] == 2
    assert refused(st, m, {"event": "x"}) == "it returned event, which its manifest doesn't propose"


def test_an_api_2_module_cant_use_the_old_words(tmp_path):
    s, st, agent = modular(tmp_path)
    m = live(st, v2(name="bells", proposes=["event", "take"], belongings={"takes": ["material"], "gives": [], "most": 1}), "x")
    for old in ({"log": "x"}, {"consume": {"a": 1}}, {"coins": 1}):
        assert refused(st, m, old).startswith("it returned ") and refused(st, m, old).endswith(", which its manifest doesn't propose")


def test_a_first_may_be_named_for_anything_found():
    assert M._read({"firsts": [{"key": "found:jay's feather", "label": "found jay's feather"}]})["firsts"][0]["key"] == "found:jay's feather"
    for bad in ("", " found", "a\nb", "x" * 81):
        with pytest.raises(M.Refused, match="^`event.read.firsts` is up to 8"):
            M._read({"firsts": [{"key": bad, "label": "x"}]})


def test_take_and_give_at_their_edges(tmp_path):
    s, st, agent = modular(tmp_path)
    st.add_item("brass wire", 4, "material", "")
    st.add_item("oat seeds", 2, "seed", "")
    st.add_item("pea seeds", 2, "seed", "")
    st.add_coins("agent", 20 - st.coins())
    clock(st)
    two = {"belongings": {"takes": ["material", "seed"], "gives": ["material"], "most": 5, "coins": 5}}
    none = {"belongings": {"takes": [], "gives": [], "most": 5}}
    assert refused_fn(M._take, st, two, [{"item": "brass wire", "x": 1}]) == M.TAKE_SHAPE
    assert refused_fn(M._take, st, two, [{"creation": "Gear Clock", "to": "Oriel"}]) == "it can only take: material, seed"
    assert refused_fn(M._take, st, none, [{"creation": "Gear Clock", "to": "Oriel"}]) == "it can only take: nothing"
    assert refused_fn(M._take, st, none, [{"item": "oat seeds", "kind": "seed"}]) == "it can only take: nothing"
    assert refused_fn(M._take, st, none, [{"item": "oat seeds"}]) == "it can only take: nothing"
    assert refused_fn(M._take, st, two, [{"item": "seeds"}]).startswith("which one? ")                    # more than one is called that
    assert refused_fn(M._take, st, two, [{"item": "brass", "qty": 5}]) == "you need 5 brass wire for that (you have 4)"   # by its own name
    both = {"belongings": {"takes": ["creation", "material"], "gives": [], "most": 5, "coins": 5}}
    got = M._take(st, both, [{"creation": "Gear Clock", "to": "Oriel"}, {"coins": 2}, {"item": "brass wire"}])
    assert [sorted(x) for x in got] == [["creation", "to"], ["coins"], ["id", "name", "qty"]]                         # each, in order
    assert M._give(st, two, [{"coins": 1}, {"item": "acorn", "kind": "material"}])[1]["item"] == "acorn"


def test_an_api_1_result_is_made_into_api_2_whole(tmp_path):
    s, st, agent = modular(tmp_path)
    st.add_item("brass wire", 5, "material", "")
    st.add_item("oil", 3, "material", "")
    c = clock(st)
    m = {"name": "x", "manifest": {"api": 1, "subject": c["name"], "consumes": {"*": 2}, "finds": ["acorn"], "proposes": ["consume", "find", "part_with"]}}
    rest, changes = M._from_api1(st, m, {"consume": {"brass wire": 2, "oil": 1}, "part_with": {"creation": "Gear Clock", "to": "Oriel"},
                                         "find": {"item": "acorn"}, "state": {"n": 1}})
    assert rest == {"state": {"n": 1}}
    assert changes == [("take", [{"id": st.find_item("brass wire")[0]["id"], "qty": 2, "name": "brass wire"},
                                 {"id": st.find_item("oil")[0]["id"], "qty": 1, "name": "oil"}, {"creation": "Gear Clock", "to": "Oriel"}]),
                       ("give", [{"item": "acorn", "qty": 1, "kind": "material", "description": "found by your Gear Clock", "attrs": {}}])]
    for bad in (True, 0, 3, "1"):
        assert refused_fn(M._from_api1, st, m, {"consume": {"oil": bad}}) == "it may use up 1 to 2 oil at a time"


def refused_fn(fn, *args):
    with pytest.raises(M.Refused) as e:
        fn(*args)
    return str(e.value)


def test_what_api_2_manifests_and_programs_may_not_say():
    prog = {"name": "bell-by-agent", "kind": "thing", "api": 2, "subject": "Bell", "hooks": ["on_tick"], "reads": ["time"], "proposes": ["log"]}
    with pytest.raises(M.Refused, match="^`proposes` is a list drawn from"):
        M.check_manifest(prog, "agent")
    assert M.check_manifest({**prog, "api": 1}, "agent")["proposes"] == ["log"]                         # an old program still runs
    with pytest.raises(M.Refused, match="^your programs can't use: wishes, take$"):                     # api 1: the weather, not take
        M.check_manifest({**prog, "reads": ["weather", "wishes"], "proposes": ["take"], "api": 1,
                          "belongings": {"takes": ["material"], "gives": [], "most": 1}}, "agent")
    with pytest.raises(M.Refused, match="^`reads` is a list drawn from"):                                # api 2: no weather at all
        M.check_manifest({**prog, "reads": ["weather"], "proposes": ["take"]}, "agent")
    with pytest.raises(M.Refused, match="^your programs can't use: wishes, give$"):
        M.check_manifest({**prog, "reads": ["facts", "wishes"], "proposes": ["take", "give"],
                          "belongings": {"takes": ["material"], "gives": ["material"], "most": 1}}, "agent")
    with pytest.raises(M.Refused, match=r"^`consumes` is api 1's: say what it may `take` in `belongings`$"):
        M.check_manifest(v2(consumes={"*": 2}), "world")
    with pytest.raises(M.Refused, match=r"^`finds` is api 1's: say what it may `give` in `belongings`$"):
        M.check_manifest(v2(finds=["acorn"]), "world")
    with pytest.raises(M.Refused, match=r"^`consume` and `consumes` go together"):
        M.check_manifest(rule(consumes={"*": 2}), "world")
    with pytest.raises(M.Refused, match=r"^`find` and `finds` go together"):
        M.check_manifest(rule(finds=["acorn"]), "world")


def test_a_manifest_saying_no_api_is_api_1_and_the_days_caps_hold(tmp_path):
    s, st, agent = modular(tmp_path)
    m = live(st, rule(name="till", proposes=["coins", "log"], belongings={"takes": [], "gives": [], "most": 1, "coins": 5}), "x")
    old = {**m, "manifest": {k: v for k, v in m["manifest"].items() if k != "api"}}                   # stored before it said
    assert M.plan(st, old, {"coins": 3}, NOW, "on_tick") == [("give", [{"coins": 3}])]
    st.update_module(m["id"], budget={"day": M._day(NOW), "give": M.PER_DAY["give"]})
    assert refused(st, st.module(m["id"]), {"coins": 3}) == f"it has used today's {M.PER_DAY['give']} `give`"
    st.update_module(m["id"], budget={"day": M._day(NOW), "give": M.PER_DAY["give"] - 1})
    assert M.plan(st, st.module(m["id"]), {"coins": 3}, NOW, "on_tick") == [("give", [{"coins": 3}])]      # one left
    line = live(st, v2(name="crier", proposes=["event"]), "x")
    st.update_module(line["id"], budget={"day": M._day(NOW), "log": M.PER_DAY["log"] - 1})
    run(st, st.module(line["id"]), {"event": "Hear ye."})
    assert refused(st, st.module(line["id"]), {"event": "Hear ye again."}) == f"it has used today's {M.PER_DAY['log']} lines for the record"


def test_coins_given_first_leave_the_rest_given_too(tmp_path):
    s, st, agent = modular(tmp_path)
    st.add_coins("agent", 20 - st.coins())
    m = live(st, v2(name="till", proposes=["give", "take"], belongings={"takes": ["material"], "gives": ["material"], "most": 2, "coins": 5}), "x")
    st.add_item("brass wire", 2, "material", "")
    run(st, m, {"give": [{"coins": 2}, {"item": "acorn", "qty": 1, "kind": "material"}], "take": [{"coins": 1}, {"item": "brass wire"}]})
    assert st.coins() == 21 and st.find_item("acorn")[0]["qty"] == 1 and st.find_item("brass wire")[0]["qty"] == 1


@pytest.mark.asyncio
async def test_a_trial_reports_a_modules_own_events_by_their_lines(tmp_path):
    s, st, agent = modular(tmp_path)
    src = ('def on_tick(ctx):\n'
           '    n = ctx["state"].get("n", 0) + 1\n'
           '    out = {"state": {"n": n}}\n'
           '    if n == 1:\n'
           '        out["event"] = "The bell is hung."\n'
           '    elif n == 2:\n'
           '        out["event"] = {"kind": "rang", "data": {"n": n}, "read": {"line": "The bell rang twice."}}\n'
           '    elif n == 3:\n'
           '        out["event"] = {"kind": "rang", "data": {"n": n}}\n'
           '    return out\n')
    man = v2(name="bell", hooks=["on_tick"], proposes=["state", "event"], logs=["rang"])
    r = await M.propose(st, s, M.LocalRunner(), "world", man, src, "a bell", now=NOW)
    assert r["report"]["logged"] == ["The bell is hung.", "The bell rang twice."]                     # a line, and an event that reads as one


def test_affect_is_planned_and_capped(tmp_path):
    s, st, agent = modular(tmp_path)
    m = live(st, v2(name="purr", proposes=["affect"]), "x")
    assert M.plan(st, m, {"affect": {"energy": 0.05, "mood": "cosy"}}, NOW, "on_tick") == [("affect", {"energy": 0.05, "mood": "cosy"})]
    assert refused(st, m, {"affect": {}}) == "`affect` is {hunger?, energy?, mood?}"
    st.update_module(m["id"], budget={"day": M._day(NOW), "affect": M.PER_DAY["affect"] - 1})
    assert M.plan(st, st.module(m["id"]), {"affect": {"energy": 0.01}}, NOW, "on_tick") == [("affect", {"energy": 0.01})]
    st.update_module(m["id"], budget={"day": M._day(NOW), "affect": M.PER_DAY["affect"]})
    assert refused(st, st.module(m["id"]), {"affect": {"energy": 0.01}}) == f"it has used today's {M.PER_DAY['affect']} `affect`"
