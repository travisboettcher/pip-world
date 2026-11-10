"""Modules, step 2 (docs/DESIGN-modules.md, "Places and anchors"): what a module shows, where it goes, and how the referee checks it."""
import json
import time

import pytest

from app import anchors as A
from app import modules as M
from app import world_view as WV
from tests.test_modules import NOW, live, modular, rule, shipped_layouts
from tests.test_world_view import clock

PIC = {"rows": ["kk..", "kkkk", "kkkk", "..kk"], "palette": {"k": "#123"}}
WALL = [{"id": "a", "type": "wall", "tags": ["inside", "back"], "at": [0, 2, -7], "normal": [0, 0, 1], "extent": [1.0, 0.8]},
        {"id": "b", "type": "wall", "tags": ["inside"], "at": [3, 2, -7], "normal": [0, 0, 1], "extent": [0.7, 0.7]},
        {"id": "side", "type": "wall", "tags": ["inside"], "at": [-8, 2, -6], "normal": [1, 0, 0], "extent": [2.0, 1.0]},
        {"id": "shelf", "type": "surface", "tags": ["inside"], "at": [0, 1, -6], "normal": [0, 1, 0], "extent": [1.0, 0.5]}]


def obj(oid, type_="wall", size=0.5, frame=False, tags=None, near=None, rows=None):
    at = {"type": type_, "place": "home", "tags": tags or []} | ({"near": near} if near else {})
    return {"id": oid, "sprite": {"rows": rows or PIC["rows"], "palette": PIC["palette"]}, "size": size, "frame": frame, "at": at}


# --- the manifests ----------------------------------------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_every_shipped_layout_has_anchors_that_make_sense(tmp_path):
    from app import layouts as L
    from tests.test_modules import shipped_layouts
    s, st, agent = modular(tmp_path)
    await shipped_layouts(st, s, "home")
    for key, kind in (("workshop", "home"),):
        anchors = L.anchors_for(st, key, kind)
        ids = [a["id"] for a in anchors]
        assert anchors and len(ids) == len(set(ids)), key
        for a in anchors:
            assert a["type"] in A.TYPES and a["tags"] and len(a["at"]) == 3 and len(a["extent"]) == 2 and all(e > 0 for e in a["extent"])
            assert (a["normal"] == [0, 1, 0]) == (a["type"] != "wall"), a                     # walls face out; the rest face up
    home = L.anchors_for(st, "workshop", "home")
    assert {a["id"] for a in home if a["type"] == "wall" and "back" in a["tags"]} == {"back-wall-by-window", "back-wall-over-bench", "back-wall-under-shelf"}
    assert L.anchors_for(st, "woods", "wild") is None                                           # no layout built: nowhere to put anything


# --- placing ---------------------------------------------------------------------------------------------------------------
def test_an_objects_size_is_its_longest_side_and_a_frame_adds_a_border():
    assert A.size(obj("x", size=0.5)) == (0.5, 0.5)
    assert A.size(obj("x", size=0.8, rows=["kkkk", "kkkk"])) == (0.8, 0.4)
    assert A.size(obj("x", size=0.8, rows=["kkkk", "kkkk"], frame=True)) == (0.8, 0.6)
    assert A.size(obj("x", size=0.9, rows=["kkkkkkkk", "kkkkkkkk", "kkkkkkkk"])) == (0.9, 0.3375)
    assert A.size({k: v for k, v in obj("x").items() if k != "size"}) == (0.6, 0.6)


def test_objects_pack_along_matching_anchors_in_order_and_what_doesnt_fit_is_named():
    placed, unplaced = A.place(WALL, [obj("one"), obj("two", size=0.38), obj("three", size=0.6), obj("four", size=0.7), obj("big", size=0.9),
                                      obj("shelf", type_="surface"), obj("hang", type_="hang"), obj("back", tags=["back"])])
    where = {p["id"]: (p["anchor"], p["pos"]) for p in placed}
    assert where["one"] == ("a", [-0.25, 2, -6.98])                                       # from the left edge, a little off the wall
    assert where["two"] == ("a", [0.31, 2, -6.98])                                        # 0.5 + the gap, then its own half: exactly full
    assert where["three"] == ("b", [2.95, 2, -6.98])
    assert where["four"] == ("side", [-7.98, 2, -5.35])                                   # packed across a wall that faces x
    assert where["big"] == ("side", [-7.98, 2, -6.27]) and where["shelf"] == ("shelf", [-0.25, 1.25, -6])  # stands on the shelf
    assert unplaced == ["hang: no hang anchor here", "back: no room left on any wall tagged back anchor"]
    p = next(p for p in placed if p["id"] == "one")
    assert p["upright"] and p["normal"] == [0, 0, 1] and (p["w"], p["h"]) == (0.5, 0.5) and not next(p for p in placed if p["id"] == "shelf")["upright"]


def test_too_tall_for_a_wall_and_exactly_fitting():
    wall = [{"id": "w", "type": "wall", "tags": ["inside"], "at": [0, 2, 0], "normal": [0, 0, 1], "extent": [1.0, 0.5]}]
    assert A.place(wall, [obj("tall", size=0.6)])[1] == ["tall: no room left on any wall anchor"]
    assert [p["id"] for p in A.place(wall, [obj("fits", size=0.5)])[0]] == ["fits"]
    two = A.place(wall, [obj("a", size=0.44, rows=["kkkk", "kkkk"]), obj("b", size=0.44, rows=["kkkk", "kkkk"])])[0]
    assert [p["id"] for p in two] == ["a", "b"]                                             # 0.44 + 0.12 + 0.44 = exactly 1.0
    shelf = [{"id": "s", "type": "surface", "tags": ["x"], "at": [0, 1, 0], "normal": [0, 1, 0], "extent": [1.0, 0.3]}]
    assert [p["id"] for p in A.place(shelf, [obj("tall", type_="surface", size=1.0)])[0]] == ["tall"]   # nothing stands too tall on a shelf


def test_near_puts_one_anchor_first():
    placed, _ = A.place(WALL, [obj("x", near="b")])
    assert placed[0]["anchor"] == "b"
    assert [a["id"] for a in A.matching(WALL, {"type": "wall", "near": "side"})] == ["side", "a", "b"]
    assert [a["id"] for a in A.matching(WALL, {"type": "wall", "tags": ["back"]})] == ["a"]


# --- show, as the referee sees it --------------------------------------------------------------------------------------------
def test_show_is_checked_object_by_object(tmp_path):
    s, st, agent = modular(tmp_path)
    m = live(st, rule(proposes=["show"]), "x")
    ok = {"id": "p1", "sprite": PIC, "at": {"type": "wall", "place": "home", "tags": ["Inside "], "near": "x" * 50}, "frame": 1,
          "motion": "bob", "tip": {"title": "t" * 80, "text": "x"}}
    [(kind, shown)] = M.plan(st, m, {"show": [ok]}, NOW, "on_tick")
    assert kind == "show" and shown == [{"id": "p1", "sprite": {"rows": PIC["rows"], "palette": {"k": "#123"}}, "size": 0.6, "frame": True,
                                         "at": {"type": "wall", "place": "home", "tags": ["inside"], "near": "x" * 40}, "motion": "bob",
                                         "tip": {"title": "t" * 60, "text": "x"}}]
    plain = M.plan(st, m, {"show": [{"id": "p", "sprite": PIC, "size": 1.5, "at": {"type": "floor", "place": " Brygdon "}}]}, NOW, "on_tick")[0][1][0]
    assert plain == {"id": "p", "sprite": {"rows": PIC["rows"], "palette": {"k": "#123"}}, "size": 1.5, "frame": False,
                     "at": {"type": "floor", "place": "Brygdon", "tags": []}}

    def bad(objs):
        with pytest.raises(M.Refused) as e:
            M.plan(st, m, {"show": objs}, NOW, "on_tick")
        return str(e.value)
    assert bad("x") == "`show` is a list of at most 8 objects" and bad([ok] * 9) == "`show` is a list of at most 8 objects"
    assert bad([{**ok, "id": "Bad Id"}]) == "each object in `show` needs its own `id`: up to 24 lowercase letters, digits and dashes"
    assert bad([ok, ok]).startswith("each object in `show` needs its own `id`") and bad(["x"]).startswith("each object")
    assert bad([{**ok, "sprite": {"rows": ["zz"], "palette": {}}}]).startswith("`show` p1: a pixel picture is 4 to 32 rows tall")
    assert bad([{**ok, "sprite": "pic"}]) == "`show` p1: `sprite` is {rows, palette}, a pixel picture"
    for size in (0.1, 1.6, True, "big"):
        assert bad([{**ok, "size": size}]) == "`show` p1: `size` is 0.2 to 1.5"
    for at in ({"type": "roof", "place": "home"}, {"type": "wall"}, {"type": "wall", "place": " "}, "home"):
        assert bad([{**ok, "at": at}]) == "`show` p1: `at` is {type, place, tags?, near?}; type is one of wall, surface, floor, ground, hang"
    assert bad([{**ok, "at": {**ok["at"], "tags": ["a"] * 5}}]) == "`show` p1: `at.tags` is a list of up to 4 words"
    assert bad([{**ok, "at": {**ok["at"], "tags": "a"}}]).endswith("`at.tags` is a list of up to 4 words") and bad([{**ok, "at": {**ok["at"], "tags": [1]}}]).endswith("4 words")
    assert bad([{**ok, "motion": "dance"}]) == "`show` p1: `motion` is one of bob, sway, spin"
    assert bad([{**ok, "tip": "hi"}]) == "`show` p1: `tip` is {title, text}" and bad([{**ok, "tip": {"title": 1}}]) == "`show` p1: `tip` is {title, text}"
    assert bad([{**ok, "tip": {"text": 1}}]) == "`show` p1: `tip` is {title, text}"
    assert M.plan(st, m, {"show": []}, NOW, "on_tick") == [("show", [])]


async def ground_for_the_woods(st, s, agent):
    """The woods laid out with one ground anchor (they have no hand-written scene any more)."""
    from app import layouts as L
    src = ('def on_build(ctx):\n    return {"anchors": [{"id": "ground", "type": "ground", "tags": ["outside"], "at": [0, 0, -3], "extent": [12, 3]}]}\n')
    m = live(st, {"name": "woods-ground", "kind": "place", "api": 1, "hooks": ["on_build"], "place": "woods"}, src)
    await L.step(st, s, agent.runner, NOW)
    return m


@pytest.mark.asyncio
async def test_what_a_module_shows_lands_on_the_right_place_or_nowhere(tmp_path):
    s, st, agent = modular(tmp_path)
    await ground_for_the_woods(st, s, agent)
    await shipped_layouts(st, s, "home")
    c = clock(st)
    src = ("def on_tick(ctx):\n    p = {'rows': ['kkkk'] * 4, 'palette': {'k': '#000'}}\n"
           "    return {'show': [{'id': 'a', 'sprite': p, 'at': {'type': 'wall', 'place': 'subject'}},"
           " {'id': 'b', 'sprite': p, 'at': {'type': 'ground', 'place': 'woods'}}, {'id': 'c', 'sprite': p, 'at': {'type': 'wall', 'place': 'home'}}]}\n")
    thing = live(st, rule(kind="thing", name="clock-face", subject="Gear Clock", proposes=["show"]), src)
    older = live(st, rule(name="older", proposes=["show"]), src.replace("'subject'", "'home'"))
    await M.call(st, s, agent.runner, thing, "on_tick", NOW)
    await M.call(st, s, agent.runner, older, "on_tick", NOW)
    home = WV.scene_view(st, s, None)["objects"]
    assert [o["key"] for o in home] == ["clock-face:a", "clock-face:c", "older:a"]                # oldest module first; and older:c didn't fit
    assert set(home[0]) == {"key", "rows", "palette", "frame", "w", "h", "pos", "normal", "upright"}
    assert M.objects_for(st, "workshop", "home")[1] == ["older:c: no room left on any wall anchor"]
    assert [o["key"] for o in WV.scene_view(st, s, None, "woods")["objects"]] == ["clock-face:b", "older:b"]
    assert M.where(st, thing, "subject") == "workshop" and M.where(st, older, "subject") is None and M.where(st, older, "home") == "workshop"
    st.give_creation(c["id"], "Oriel")
    assert M.where(st, thing, "subject") is None and M.where(st, thing, "Brygdon") == "Brygdon"
    assert [o["key"] for o in WV.scene_view(st, s, None)["objects"]] == ["clock-face:c", "older:a", "older:c"]
    M.disable(st, older["id"])
    assert [o["key"] for o in WV.scene_view(st, s, None)["objects"]] == ["clock-face:c"]


def test_the_new_reads_works_and_stalls(tmp_path):
    s, st, agent = modular(tmp_path)
    for i in range(M.WORKS_SHOWN + 2):
        st.add_work("drawing", f"P{i}", "<svg/>", pixels={"rows": ["kkkk"] * 4, "palette": {"k": "#000"}}, subject="Gear Clock" if i == 0 else "")
    st.add_work("drawing", "svg only", "<svg/>")
    st.set_stall("Brygdon", "P1", name="P1", kind="work", qty=3, ask=4, attrs={"work": "drawing"})
    st.set_stall("Brygdon", "carrots", name="carrots", kind="food", qty=2, ask=1, attrs={})
    st.set_stall("Saltholm", "Gear Clock", name="Gear Clock", kind="creation", qty=1, ask=9, attrs={})
    ctx = M.context(st, s, live(st, rule(reads=["works", "stalls"]), "x"), NOW)
    assert len(ctx["works"]) == M.WORKS_SHOWN and ctx["works"][0]["title"] == f"P{M.WORKS_SHOWN + 1}"
    assert set(ctx["works"][0]) == {"id", "title", "subject", "rows", "palette"}
    assert ctx["stalls"] == [{"place": "Brygdon", "item": "P1", "kind": "work", "qty": 3, "work": "drawing"},
                             {"place": "Brygdon", "item": "carrots", "kind": "food", "qty": 2},
                             {"place": "Saltholm", "item": "Gear Clock", "kind": "creation", "qty": 1}]
    assert [r["item"] for r in st.stall_rows()] == ["P1", "carrots", "Gear Clock"] and [r["item"] for r in st.stall_rows("Saltholm")] == ["Gear Clock"]


@pytest.mark.asyncio
async def test_the_dry_run_says_where_things_would_go_and_what_wouldnt_fit(tmp_path):
    s, st, agent = modular(tmp_path)
    await ground_for_the_woods(st, s, agent)
    await shipped_layouts(st, s, "home")
    p = "{'rows': ['kkkk'] * 4, 'palette': {'k': '#000'}}"
    src = (f"def on_install(ctx):\n    p = {p}\n    return {{'show': [{{'id': 'a', 'sprite': p, 'size': 0.9, 'at': {{'type': 'wall', 'place': 'home'}}}},"
           " {'id': 'b', 'sprite': p, 'at': {'type': 'hang', 'place': 'home'}}, {'id': 'c', 'sprite': p, 'at': {'type': 'ground', 'place': 'Atlantis'}},"
           " {'id': 'd', 'sprite': p, 'at': {'type': 'ground', 'place': 'woods'}}]}\n")
    r = await M.propose(st, s, agent.runner, "world", rule(hooks=["on_install"], proposes=["show"]), src, now=NOW)
    rep = r["report"]
    assert rep["placed"] == ["a: back-wall-by-window at workshop", "d: ground at woods"]
    assert rep["unplaced"] == ["b: no hang anchor here", "c: 'Atlantis' isn't a place in the world"] and rep["clean"] is False
    good = src.replace("'hang'", "'floor'").replace("'Atlantis'", "'home'")
    r = await M.propose(st, s, agent.runner, "world", rule(name="good", hooks=["on_install"], proposes=["show"]), good, now=NOW)
    assert r["report"]["unplaced"] == [] and r["report"]["clean"] and len(r["report"]["placed"]) == 4


@pytest.mark.asyncio
async def test_the_world_proposes_its_rules_once(tmp_path, caplog):
    s, st, agent = modular(tmp_path)
    made = await M.offer_library(st, s, agent.runner, now=NOW)
    assert [(st.module(i)["name"], st.module(i)["reason"]) for i in made] == list(M.RULES.items())
    assert all(st.module(i)["report"]["clean"] for i in made)
    M.reject(st, made[0])
    assert await M.offer_library(st, s, agent.runner, now=NOW) == []
    import logging
    for m in st.modules():
        st.db.execute("DELETE FROM modules WHERE id = ?", (m["id"],))
    st.db.commit()
    real = M.library
    M.library = lambda name: (real(name)[0], "import os")
    try:
        with caplog.at_level(logging.WARNING, logger="app.modules"):
            assert await M.offer_library(st, s, agent.runner, now=NOW) == []
    finally:
        M.library = real
    assert caplog.records[0].getMessage().startswith("library module gallery-wall refused: line 1: `import os`")


def test_show_accepts_its_limits_exactly(tmp_path):
    s, st, agent = modular(tmp_path)
    m = live(st, rule(proposes=["show"]), "x")
    one = lambda i, **kw: {"id": f"o{i}", "sprite": PIC, "at": {"type": "floor", "place": "home"}, **kw}
    assert len(M.plan(st, m, {"show": [one(i) for i in range(M.SHOW_MAX)]}, NOW, "on_tick")[0][1]) == M.SHOW_MAX
    got = M.plan(st, m, {"show": [one(0, size=0.2, tip={"text": "t"}, at={"type": "wall", "place": "home", "tags": ["a", "b", "c", "d"]}),
                                  one(1, tip={"title": "x"})]}, NOW, "on_tick")[0][1]
    assert got[0]["size"] == 0.2 and got[0]["tip"] == {"title": "", "text": "t"} and got[0]["at"]["tags"] == ["a", "b", "c", "d"]
    assert got[1]["tip"] == {"title": "x", "text": ""}
    assert A.place(WALL, [obj("x", tags=["inside", "nowhere"])])[1] == ["x: no wall tagged inside, nowhere anchor here"]
