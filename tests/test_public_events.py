"""Public events (docs/DESIGN-world-packs.md, 5f): a module logs an event of a public kind its manifest names, with that kind's fields and
the expectations it settles, and the engine's readers (memory, firsts, emotions, the feed) take it as they take the engine's own."""
import pytest

from app import expectations as exp
from app import modules as M
from tests.test_modules import NOW, live, modular, rule

EXPERIMENT = {"project": "Raft", "hypothesis": "cork floats it", "outcome": "clue", "minutes": 30, "text": "It bobbed.", "finding": None,
              "project_done": False, "percent": 20}
REVISED = {"project": "Raft", "because": "a book on rafts"}
WORK = {"project": "Kite", "project_id": 7, "stage": "cut the frame", "result": "breakthrough", "craft": "kites", "abilities": ["handiness"],
        "minutes": 40, "text": "The frame came together cleanly.", "finished_stage": True, "project_done": False, "interrupted": False,
        "percent": 50}


def worker(st, **kw):
    return live(st, rule(name="crafting", proposes=["event"], logs=["work", "experiment", "plan_revised"], **kw), "x")


def refused(fn, *args):
    with pytest.raises(M.Refused) as e:
        fn(*args)
    return str(e.value)


def test_a_manifest_names_the_public_events_it_logs():
    assert M.check_manifest(rule(proposes=["event"], logs=["work"]), "world")["logs"] == ["work"] and "logs" not in M.check_manifest(rule(), "world")
    what = "`logs` lists the public events it logs: work, experiment, plan_revised (not for Pip's programs)"
    for bad in (["tick"], "work", ["work", "work"]):
        assert refused(M.check_manifest, rule(proposes=["event"], logs=bad), "world") == what
    assert refused(M.check_manifest, rule(proposes=["event"]), "world") == "`logs` and the `event` proposal go together: say which public events it logs"
    assert refused(M.check_manifest, rule(proposes=["state"], logs=["work"]), "world") == "`logs` and the `event` proposal go together: say which public events it logs"
    assert set(M.LOGGABLE) == {"work", "experiment", "plan_revised"}


def test_what_an_event_may_carry():
    man = {"logs": ["work"]}
    c = exp.compare_session("well", "setback")
    got = M._event(man, {"kind": "work", "data": WORK, "expect": [{**c, "subject": "cut the frame"}]})
    assert got == {"kind": "work", "data": WORK, "expect": [{**c, "subject": "cut the frame"}]}
    assert M._event(man, {"kind": "work", "data": WORK}) == {"kind": "work", "data": WORK, "expect": []}
    assert refused(M._event, man, {"kind": "work", "data": {"project": "Kite"}}) == \
        "a `work` event needs stage, result, minutes, text, finished_stage, project_done, percent"
    shape = "`event` is {kind, data, expect?}: kind is one it logs (work), data its fields, at most 4000 bytes, and up to 2 expectations"
    ok_e = {**c, "subject": "s"}
    for bad in ({"kind": "experiment", "data": {}}, {"kind": "work", "data": {"mood": "x"}}, {"kind": "work", "data": []}, {"kind": "work"},
                {"kind": "work", "data": {"text": "x" * 4001}}, {"kind": "work", "data": WORK, "x": 1}, {"kind": "work", "data": WORK, "expect": [ok_e] * 3},
                {"kind": "work", "data": WORK, "expect": [{**ok_e, "kind": "hunch"}]}, {"kind": "work", "data": WORK, "expect": [{**ok_e, "subject": " "}]},
                {"kind": "work", "data": WORK, "expect": [{**ok_e, "error": "big"}]}, {"kind": "work", "data": WORK, "expect": [{**ok_e, "surprise": "wow"}]},
                {"kind": "work", "data": WORK, "expect": [{**ok_e, "actual": 3}]}, {"kind": "work", "data": WORK, "expect": [{**ok_e, "expected": None}]},
                {"kind": "work", "data": WORK, "expect": [{**ok_e, "x": 1}]}, {"kind": "work", "data": WORK, "expect": "x"}, "work"):
        assert refused(M._event, man, bad) == shape, bad
    assert refused(M._event, {}, {"kind": "work", "data": {}}).startswith("`event` is {kind, data, expect?}: kind is one it logs (none)")


async def test_a_logged_event_is_read_as_the_engines_own(tmp_path):
    s, st, agent = modular(tmp_path)
    m = worker(st)
    c = exp.compare_session("badly", "breakthrough")                                      # a surprise: it went far better
    step = exp.compare_step(30, 90)
    M.apply(st, m, M.plan(st, m, {"event": {"kind": "work", "data": WORK, "expect": [{**c, "subject": "cut the frame"}, {**step, "subject": "cut the frame"}]}},
                          NOW, "on_tick"), NOW)
    ev = next(e for e in st.events(10) if e["kind"] == "work")
    assert {k: ev["data"][k] for k in WORK} == WORK and ev["data"]["by"] == "crafting"
    assert any(f["key"] == "work:breakthrough" for f in ev["data"].get("firsts", []))              # a first, as the engine's work is
    got = st.expectations(5)
    assert sorted((e["kind"], e["project_id"], e["craft"], e["subject"], e["event_id"], e["surprising"]) for e in got) == [
        ("session", 7, "kites", "cut the frame", ev["id"], 1), ("step", 7, "kites", "cut the frame", ev["id"], 1)]
    assert st.recall("frame cleanly")                                                              # remembered
    assert M._budget(st.module(m["id"]), NOW)["event"] == 1 and M.PER_DAY["event"] == 24 and M.SHIPPED_PER_DAY["event"] == 200


async def test_a_day_of_public_events_is_limited(tmp_path):
    s, st, agent = modular(tmp_path)
    m = worker(st)
    st.update_module(m["id"], budget={"day": M._day(NOW), "event": 24})
    assert refused(M.plan, st, st.module(m["id"]), {"event": {"kind": "work", "data": {}}}, NOW, "on_tick") == "it has logged 24 public events today"


# --- making a creation ---------------------------------------------------------------------------------------------------------------
KITE = {"name": "Red Kite", "description": "a red kite that hums in the wind", "quality": "fine", "quirks": ["one wing pulls left"], "scars": ["a torn spar"],
        "capabilities": [{"type": "periodic", "lines": ["It hums."], "every_minutes": 60}, {"type": "teleport"}],
        "made_of": {"id": 7, "name": "Kite", "goal": "a kite that hums", "difficulty": 2, "stages": ["cut the frame"]}}


async def test_a_module_makes_a_creation_the_engine_checks(tmp_path):
    from tests.test_projects import make
    s, st, gm, agent = make(tmp_path, modules="on", module_runner="local")
    src = "def on_action(ctx):\n    return {'creation': " + repr(KITE) + ", 'reply': 'made'}\n"
    m = live(st, rule(name="maker", hooks=["on_action"], proposes=["creation"], tools=[{"name": "make_it", "help": "make it",
                                                                                       "params": {"type": "object", "properties": {}, "required": []}}]), src)
    text, changed = await M.use_tool(st, s, M.LocalRunner(), m, m["manifest"]["tools"][0], {}, NOW)
    assert text == "made" and changed
    (c,) = st.creations()
    assert (c["name"], c["description"], c["quality"], c["project_id"]) == ("Red Kite", "a red kite that hums in the wind", "fine", 7)
    assert set(c["spec"]["capabilities"]) == {"periodic"} and c["spec"]["quirks"] == ["one wing pulls left"] and c["spec"]["scars"] == ["a torn spar"]
    ev = next(e["data"] for e in st.events(10) if e["kind"] == "creation_made")
    assert (ev["name"], ev["quality"], ev["capabilities"], ev["project"]) == ("Red Kite", "fine", ["periodic"], "Kite")
    assert M._budget(st.module(m["id"]), NOW)["creation"] == 1 and M.PER_DAY["creation"] == 2 and M.SHIPPED_PER_DAY["creation"] == 6
    st.update_module(m["id"], budget={"day": M._day(NOW), "creation": 2})
    assert (await M.use_tool(st, s, M.LocalRunner(), st.module(m["id"]), m["manifest"]["tools"][0], {}, NOW))[0] == "error: it has made 2 things today"


def test_what_a_creation_must_say():
    got = M._creation_made(KITE)
    assert got["quality"] == "fine" and got["made_of"] == {"id": 7, "name": "Kite", "goal": "a kite that hums", "difficulty": 2, "stages": [{"name": "cut the frame"}]}
    assert M._creation_made({**KITE, "made_of": {"name": " Kite ", "difficulty": 5}})["made_of"] == {"id": None, "name": "Kite", "goal": "", "difficulty": 5, "stages": []}
    shape = refused(M._creation_made, {**KITE, "quality": "superb"})
    assert shape.startswith("`creation` is {name, description, quality") and shape.endswith("quality is one of rough, sound, fine, masterwork")
    of = KITE["made_of"]
    for bad in ({**KITE, "x": 1}, {**KITE, "name": 3}, {**KITE, "description": None}, {**KITE, "capabilities": [{}] * 7}, {**KITE, "capabilities": "x"},
                {**KITE, "quirks": [1]}, {**KITE, "quirks": ["q"] * 6}, {**KITE, "scars": "x"}, {**KITE, "made_of": None}, {**KITE, "made_of": {**of, "x": 1}},
                {**KITE, "made_of": {**of, "name": " "}}, {**KITE, "made_of": {**of, "difficulty": 6}}, {**KITE, "made_of": {**of, "goal": 3}},
                {**KITE, "made_of": {**of, "stages": ["s"] * 9}}, {**KITE, "made_of": {**of, "id": "7"}}, {**KITE, "made_of": {**of, "id": True}},
                {**KITE, "description": "d" * 5000}, "kite"):
        assert refused(M._creation_made, bad) == shape, bad


def test_the_edges_of_events_creations_and_sessions(tmp_path):
    from tests.test_modules import modular
    full = {**KITE, "quirks": ["q"] * 5, "scars": ["s"] * 5, "capabilities": [{}] * 6, "made_of": {**KITE["made_of"], "difficulty": 1}}
    got = M._creation_made(full)
    assert got["scars"] == ["s"] * 5 and got["raw"]["quirks"] == ["q"] * 5 and got["made_of"]["difficulty"] == 1
    bare = {k: v for k, v in KITE.items() if k not in ("quirks", "scars", "capabilities")}
    assert M._creation_made(bare)["scars"] == [] and M._creation_made(bare)["raw"]["quirks"] is None
    man = {"logs": ["work", "experiment"]}
    for e in ({"error": -100}, {"error": 100}, {"surprise": "shorter"}, {"surprise": "longer"}):
        assert M._event(man, {"kind": "work", "data": WORK, "expect": [{"kind": "step", "subject": "s", "expected": "30 min", "actual": "9 min",
                                                                       "error": 0.3, "surprise": None, **e}]})["expect"][0]
    assert refused(M._event, man, {"kind": "plan_revised", "data": {}}).startswith("`event` is {kind, data, expect?}: kind is one it logs (work, experiment)")
    s, st, agent = modular(tmp_path)
    assert M._session(st, {"minutes": 5, "label": "x" * 100})["label"] == "x" * 80


async def test_what_is_told_of_a_made_creation(tmp_path):
    from tests.test_projects import make
    s, st, gm, agent = make(tmp_path)
    import random
    c = await __import__("app.creations", fromlist=["x"]).made(st, {"name": "Red Kite", "description": "red", "quirks": ["pulls left"]},
                                                               {"id": 3, "name": "Kite", "goal": "", "difficulty": 2, "stages": []}, "sound", [], random.Random(1))
    ev = next(e["data"] for e in st.events(5) if e["kind"] == "creation_made")
    assert ev == {"id": c["id"], "name": "Red Kite", "description": "red", "quality": "sound", "capabilities": [], "quirks": ["pulls left"], "project": "Kite",
                  **({"firsts": ev["firsts"]} if "firsts" in ev else {})}


async def test_counts_add_up_and_what_an_event_leaves_out(tmp_path):
    from tests.test_modules import modular
    s, st, agent = modular(tmp_path)
    m = worker(st)
    c = {"kind": "experiment", "subject": "does it float", "expected": "works", "actual": "it failed", "error": -2, "surprise": "worse"}
    for _ in range(2):
        M.apply(st, st.module(m["id"]), M.plan(st, st.module(m["id"]), {"event": {"kind": "experiment", "data": EXPERIMENT, "expect": [c]}},
                                               NOW, "on_tick"), NOW)
    assert M._budget(st.module(m["id"]), NOW)["event"] == 2
    e = st.expectations(1)[0]
    assert (e["kind"], e["project_id"], e["craft"], e["surprising"]) == ("experiment", None, "", 1)
    maker = live(st, rule(name="maker", proposes=["creation"]), "x")
    for _ in range(2):
        M.apply(st, st.module(maker["id"]), M.plan(st, st.module(maker["id"]), {"creation": KITE}, NOW, "on_tick"), NOW)
    assert M._budget(st.module(maker["id"]), NOW)["creation"] == 2
    sess = live(st, rule(name="sitter", hooks=["on_action", "on_time"], proposes=["session"]), "x")
    M.apply(st, sess, M.plan(st, sess, {"session": {"minutes": 30, "label": "x"}}, NOW, "on_action"), NOW)
    got = st.session()
    assert got["project_id"] == 0 and got["ends_at"] == pytest.approx(NOW + 1800, abs=1)
    for err in (-100.5, 100.5):
        assert refused(M._event, {"logs": ["work"]}, {"kind": "work", "data": WORK, "expect": [{**c, "kind": "session", "error": err}]}).startswith("`event` is")
    assert refused(M._creation_made, {**KITE, "scars": ["s"] * 6}).startswith("`creation` is")


def test_a_map_keeps_the_names_that_fit_after_one_that_doesnt():
    params = {"properties": {"m": {"type": "object", "additionalProperties": {"type": "integer"}}}, "required": []}
    assert M.check_args(params, {"m": {"a": "x", "b": 2, "n" * 40: 3, "n" * 41: 4}}) == ({"m": {"b": 2, "n" * 40: 3}}, "")


async def test_the_least_of_each_event_is_read_without_a_hitch(tmp_path):
    from tests.test_modules import modular
    s, st, agent = modular(tmp_path)
    m = worker(st)
    least = {"work": {f: WORK[f] for f in M.pv.EVENT_FIELDS["work"]}, "experiment": EXPERIMENT, "plan_revised": REVISED}
    for kind, data in least.items():
        M.apply(st, st.module(m["id"]), M.plan(st, st.module(m["id"]), {"event": {"kind": kind, "data": data}}, NOW, "on_tick"), NOW)
    assert [e["kind"] for e in st.events(3)] == ["plan_revised", "experiment", "work"]
    agent._perception("x", [])                                                  # the recent events read them as the engine's own
    from app import memory
    day = memory.compute_day_stats(st, __import__("time").time() - 3600, __import__("time").time() + 3600)
    assert day["work_sessions"] == 1 and day["experiments"] == 1


def test_arguments_after_a_map_or_an_empty_one_are_still_checked():
    params = {"properties": {"m": {"type": "object", "additionalProperties": {"type": "integer"}}, "e": {"type": "string"}, "n": {"type": "integer"}},
              "required": []}
    assert M.check_args(params, {"m": {"a": 1}, "n": "2"}) == ({"m": {"a": 1}, "n": 2}, "")
    assert M.check_args(params, {"e": "", "n": "x"}) == ({}, "`n` is a integer") and M.check_args(params, {"e": None, "n": "3"}) == ({"n": 3}, "")
