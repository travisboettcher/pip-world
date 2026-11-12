"""The hooks phase 5b added (docs/DESIGN-world-packs.md, "Phase 5 in detail"): structured asks, and bringing characters into the world
and asking a neighbour to write."""
import time

import pytest

from app import modules as M
from app import neighbors as nb
from tests.test_modules import NOW, live, modular, rule
from tests.test_projects import make, report


def refused(fn, *args):
    with pytest.raises(M.Refused) as e:
        fn(*args)
    return str(e.value)


PROPS = {"name": {"type": "string"}, "age": {"type": "integer", "description": "years"}}


def test_an_ask_may_want_its_answer_as_data():
    got = M._ask({"prompt": "p", "schema": {"properties": PROPS, "required": ["name"]}, "mentions": True})
    assert got == {"prompt": "p", "purpose": "", "most": 300, "schema": {"type": "object", "properties": PROPS, "required": ["name"]}, "mentions": True}
    assert "schema" not in M._ask({"prompt": "p"}) and "mentions" not in M._ask({"prompt": "p", "mentions": False})
    assert M._ask({"prompt": "p", "schema": {"properties": {f"a{c}": {"type": "string"} for c in "abcdefghijkl"}}})["schema"]["required"] == []
    shape = "`ask.schema` is {properties, required?}: up to 12 answers, each {type (string, integer, number, boolean), description?, enum?}"
    for bad in ({"properties": {}}, {"properties": {f"a{c}": {"type": "string"} for c in "abcdefghijklm"}}, {"properties": PROPS, "required": ["x"]},
                {"properties": {"n": {"type": "list"}}}, {"properties": PROPS, "x": 1}, {"properties": PROPS, "required": "name"}, []):
        assert refused(M._ask, {"prompt": "p", "schema": bad}) == shape
    for bad in ({"prompt": "p", "x": 1}, {"prompt": "p", "mentions": "yes"}):
        assert refused(M._ask, bad).startswith("`ask` is {prompt, purpose?, most?, schema?, mentions?}")


async def test_a_structured_answer_is_checked(tmp_path):
    s, st, gm, agent = make(tmp_path, [report(name="Ann", age="7", extra="x"), report(name="Ann", age="old"), report(age=3),
                                       report(name=" Ann  Lee ", mentions_place={"place": "Fen"})])
    a = {"prompt": "Who?", "purpose": "who", "most": 300, "schema": {"type": "object", "properties": PROPS, "required": ["name"]}}
    assert await M._answered(st, s, agent.gm, a) == {"text": "", "data": {"name": "Ann", "age": 7}}
    assert await M._answered(st, s, agent.gm, a) == {"text": "", "data": None}             # not a whole number
    assert await M._answered(st, s, agent.gm, a) == {"text": "", "data": None}             # no name
    got = await M._answered(st, s, agent.gm, {**a, "mentions": True})
    assert got == {"text": "", "data": {"name": "Ann Lee"}, "mentions_place": {"place": "Fen"}}
    assert "Only if your words point Pip to a place" in gm.calls[-1]["messages"][0]["content"]
    assert await M._answered(st, s, None, a) == {"text": "", "data": None}
    assert await M._answered(st, s, None, {"prompt": "p", "purpose": "", "most": 30}) == {"text": ""}


def test_a_character_brought_into_the_world(tmp_path):
    s, st, agent = modular(tmp_path)
    st.add_character("Oriel", "neighbor", None, "x", 60, 0)
    ok = {"name": " Ann ", "kind": "neighbor", "persona": "p", "about": "a"}
    assert M._character(st, ok) == {"name": "Ann", "kind": "neighbor", "persona": "p", "about": "a"}
    full = M._character(st, {**ok, "letter": " Hi. ", "mentions_place": {"place": "Fen"}})
    assert full["letter"] == "Hi." and full["mentions_place"] == {"place": "Fen"}
    assert M._character(st, {**ok, "name": "N" * 40, "persona": "p" * 800, "about": "a" * 160, "letter": "l" * 1200})["name"] == "N" * 40
    shape = "`character` is {name, kind (neighbor), persona, about, letter?, mentions_place?}"
    for bad in ({**ok, "kind": "resident"}, {**ok, "x": 1}, []):
        assert refused(M._character, st, bad) == shape
    assert refused(M._character, st, {**ok, "name": "N" * 41}) == "`character.name` is at most 40 characters"
    assert refused(M._character, st, {**ok, "name": ""}) == "`character.name` is a line of text"
    for name in ("oriel", "PIP"):
        assert refused(M._character, st, {**ok, "name": name}) == f"someone called {name} is already in the world"
    for key, most in (("persona", 800), ("about", 160), ("letter", 1200)):
        assert refused(M._character, st, {**ok, key: "x" * (most + 1)}) == f"`character.{key}` is a line of text of at most {most} characters"
        assert refused(M._character, st, {**ok, key: " "}) == f"`character.{key}` is a line of text of at most {most} characters"
    assert refused(M._character, st, {**ok, "persona": None}).startswith("`character.persona`")
    assert refused(M._character, st, {**ok, "mentions_place": "Fen"}).startswith("`character.mentions_place` is")


def test_asking_a_neighbour_to_write(tmp_path):
    s, st, agent = modular(tmp_path)
    st.add_character("Oriel", "neighbor", None, "x", 60, nb.NOT_YET)
    st.add_character("Tock", "creation", None, "x", 60, 0)
    assert M._letter(st, {"from": " oriel "}) == {"from": "Oriel"}
    for bad in ({"from": "Tock"}, {"from": "Nobody"}):
        assert refused(M._letter, st, bad) == f"there is no neighbour called {bad['from']!r}"
    for bad in ({}, {"from": "Oriel", "x": 1}, {"from": 3}, []):
        assert refused(M._letter, st, bad) == "`letter` is {from: a neighbour's name}"


def test_characters_and_letters_land_and_count(tmp_path):
    s, st, agent = modular(tmp_path)
    m = live(st, rule(name="town", proposes=["character", "letter"]), "x")
    M.apply(st, m, M.plan(st, m, {"character": {"name": "Ann", "kind": "neighbor", "persona": "p", "about": "a", "letter": "Hello."}}, NOW, "on_tick"), NOW)
    (ann,) = st.characters("neighbor")
    assert (ann["name"], ann["persona"], ann["next_chatter_at"]) == ("Ann", "p", nb.NOT_YET) and st.letters()[0]["text"] == "Hello."
    m = st.module(m["id"])
    assert M._budget(m, NOW)["character"] == 1
    assert refused(M.plan, st, m, {"character": {"name": "Bo", "kind": "neighbor", "persona": "p", "about": "a"}}, NOW, "on_tick") == "it has used today's 1 `character`"
    for _ in range(2):
        M.apply(st, m, M.plan(st, m, {"letter": {"from": "Ann"}}, NOW, "on_tick"), NOW)
        m = st.module(m["id"])
    assert st.characters("neighbor")[0]["next_chatter_at"] == NOW and M._budget(m, NOW)["letter"] == 2
    assert refused(M.plan, st, m, {"letter": {"from": "Ann"}}, NOW, "on_tick") == "it has used today's 2 `letter`"


def test_a_new_neighbour_without_a_first_letter(tmp_path):
    s, st, agent = modular(tmp_path)
    nb.arrive(st, s, {"name": "Ann", "kind": "neighbor", "persona": "p", "about": "a"}, 1000.0)
    assert st.letters() == [] and st.characters("neighbor")[0]["chatter_minutes"] == s.neighbor_writes_every_hours * 60


class Recorder:
    def __init__(self, raw=None):
        self.raw, self.calls = raw, []

    async def structured(self, prompt, schema, mentions=False):
        self.calls.append((prompt, schema, mentions))
        return self.raw

    async def words(self, prompt, most):
        self.calls.append((prompt, most))
        return "x" * 5000


async def test_what_the_model_is_asked_for_a_structured_answer(tmp_path):
    s, st, agent = modular(tmp_path)
    a = {"prompt": "Who?", "purpose": "who", "most": 300, "schema": {"type": "object", "properties": PROPS, "required": []}}
    gm = Recorder({"name": "y" * 3000})
    assert await M._answered(st, s, gm, a) == {"text": "", "data": {"name": "y" * 2400}}           # long words are cut
    assert gm.calls == [("Who?", a["schema"], False)]
    gm = Recorder(None)
    await M._answered(st, s, gm, {**a, "mentions": True})
    assert gm.calls[0][0].startswith("Who?\nOnly if your words point Pip") and gm.calls[0][2] is True
    assert await M._answered(st, s, Recorder({}), a) == {"text": "", "data": None}
    assert await M._answered(st, s, Recorder(), {"prompt": "p", "purpose": "", "most": 30}) == {"text": "x" * 5000}


async def test_the_model_sees_an_answers_choices(tmp_path):
    from tests.test_gm_prompts import master
    gm, b, _ = master(tmp_path)
    await gm.structured("Pick.", {"type": "object", "properties": {"c": {"type": "string", "enum": ["a", "b"]}}, "required": []})
    assert b.schemas[0]["properties"] == {"c": {"type": "string", "enum": ["a", "b"]}}


async def test_only_live_modules_with_ears_hear_their_answers(tmp_path):
    s, st, agent = modular(tmp_path)
    src = "def on_answer(ctx):\n    return {'state': {'got': ctx['answer']['text']}}\n"
    on = live(st, rule(name="ears", hooks=["on_answer"], proposes=["ask", "state"]), src)
    deaf = live(st, rule(name="deaf", hooks=["on_tick"], proposes=["ask"]), "def on_tick(ctx):\n    return {}\n")
    off = live(st, rule(name="off", hooks=["on_answer"], proposes=["ask", "state"]), src)
    for m in (on, deaf, off):
        st.update_module(m["id"], asks=[{"id": 1, "prompt": "p", "purpose": "x", "most": 30, "ts": NOW}])
    st.update_module(off["id"], status="disabled")
    gm = Recorder()
    await M.answer(st, s, gm, agent.runner, NOW)
    assert st.module(on["id"])["state"] == {"got": "x" * 5000} and st.module(on["id"])["asks"] == []
    assert st.module(deaf["id"])["asks"] == [] and st.module_calls(deaf["id"]) == []
    assert st.module(off["id"])["asks"] != [] and len(gm.calls) == 2


async def test_the_neighbours_step_hands_on_what_it_has(tmp_path, monkeypatch):
    from app import looks
    s, st, agent = modular(tmp_path)
    seen = []

    async def rec(name, *args):
        seen.append((name, args))
    monkeypatch.setattr(nb, "ensure_wares", lambda *a: rec("wares", *a))
    monkeypatch.setattr(looks, "ensure", lambda *a: rec("looks", *a))
    monkeypatch.setattr(looks, "ensure_scenes", lambda *a: rec("scenes", *a))
    await nb.step(st, s, "gm", __import__("random").Random(1), 1000.0, library="lib")
    assert seen == [("wares", (st, s, "gm", 1000.0)), ("looks", (st, s, "gm", 1000.0)), ("scenes", (st, s, "gm", "lib", 1000.0))]
    ch = st.add_character("Ann", "resident", None, "x", 60, 0)
    st.update_character(ch["id"], upcoming=[{"what": "a fair", "due_at": 0}])
    await nb.step(st, s, "gm", __import__("random").Random(1), 1000.0 + 4 * 86400)
    assert st.characters("resident")[0]["upcoming"] == [{"what": "a fair", "due_at": 0}]      # a neighbour's plans, not a resident's
