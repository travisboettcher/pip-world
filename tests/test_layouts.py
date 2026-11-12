"""Modules, step 5 (docs/DESIGN-modules.md, "Parts and layouts"): shapes checked, parts built, places laid out from them."""
import json
import time

import pytest

from app import geometry as G
from app import layouts as L
from app import modules as M
from app import world_view as WV
from tests.test_modules import NOW, live, modular, shipped_layouts

BOX = {"shape": "box", "size": [1, 2, 3], "at": [0, 1, 0], "material": {"texture": "planks", "repeat": [1, 2], "color": "#5A3D27"}}


def bad(fn, *args):
    with pytest.raises(G.Bad) as e:
        fn(*args)
    return str(e.value)


# --- shapes ------------------------------------------------------------------------------------------------------------------
def test_every_shape_is_checked_and_normalised():
    assert G.shape(BOX, 0) == {"shape": "box", "at": [0.0, 1.0, 0.0], "size": [1.0, 2.0, 3.0],
                               "material": {"texture": "planks", "repeat": [1.0, 2.0], "color": "#5a3d27"}}
    cyl = G.shape({"shape": "cylinder", "radius": 1, "height": 2, "at": [0, 0, 0], "rot": [0, 45, 0], "scale": [1, 0.5, 1],
                   "material": {"color": "#fff", "metal": 0.5, "rough": 0.2, "emissive": "#ffc070", "lamp": True, "double": True, "opacity": 0.5},
                   "sway": True, "shadow": False, "tip": {"title": "t" * 80}}, 1)
    assert cyl == {"shape": "cylinder", "at": [0.0, 0.0, 0.0], "rot": [0.0, 45.0, 0.0], "scale": [1.0, 0.5, 1.0], "radius": 1.0, "height": 2.0,
                   "segments": 10, "top": 1.0, "material": {"color": "#fff", "emissive": "#ffc070", "metal": 0.5, "rough": 0.2, "opacity": 0.5,
                                                           "lamp": True, "double": True}, "sway": True, "shadow": False, "tip": {"title": "t" * 60, "text": ""}}
    assert G.shape({"shape": "cone", "radius": 1, "height": 1, "segments": 7, "material": {"color": "#000"}}, 0)["segments"] == 7
    assert G.shape({"shape": "sphere", "radius": 1, "material": {"color": "#000"}}, 0)["segments"] == 8
    assert "segments" not in G.shape({"shape": "ico", "radius": 1, "material": {"color": "#000"}}, 0)
    assert G.shape({"shape": "gable", "width": 4, "height": 2, "material": {"color": "#000"}}, 0)["width"] == 4.0
    assert G.shape({"shape": "plane", "size": [1, 1], "material": {"texture": "door"}}, 0)["material"] == {"texture": "door", "repeat": [1.0, 1.0]}
    assert G.shape({"shape": "sprite", "size": [1, 1], "art": "reed"}, 0) == {"shape": "sprite", "at": [0.0, 0.0, 0.0], "size": [1.0, 1.0], "art": "reed"}
    pix = G.shape({"shape": "sprite", "size": [1, 1], "pixels": {"rows": ["kkkk"] * 4, "palette": {"k": "#000"}}}, 0)
    assert pix["pixels"] == {"rows": ["kkkk"] * 4, "palette": {"k": "#000"}}
    assert G.shape({"shape": "light", "lamp": True}, 0) == {"shape": "light", "at": [0.0, 0.0, 0.0], "color": "#ffc070", "strength": 1.0, "range": 8.0, "lamp": True}
    assert G.shape({"shape": "box", "size": [1, 1, 1], "faces": {"top": {"texture": "grass"}, "side": {"texture": "cliff", "repeat": [2, 1]}}}, 0)["faces"] == \
        {"top": {"texture": "grass", "repeat": [1.0, 1.0]}, "side": {"texture": "cliff", "repeat": [2.0, 1.0]}}


@pytest.mark.parametrize("s,why", [
    ({"shape": "pyramid"}, "shape 3: `shape` is one of box, plane"),
    ("box", "shape 3: `shape` is one of"),
    ({**BOX, "size": [1, 2]}, "shape 3 (box): size [w, h, d] is a list of 3 numbers"),
    ({**BOX, "size": [1, 2, 0]}, "shape 3 (box): size [w, h, d] is a number from 0.01 to 60"),
    ({**BOX, "at": [0, 0, 61]}, "shape 3 (box): at is a number from -60 to 60"),
    ({**BOX, "at": [0, 0, float("nan")]}, "at is a number"),
    ({**BOX, "at": [0, 0, True]}, "at is a number"),
    ({**BOX, "rot": [0, 400, 0]}, "rot (degrees) is a number from -360 to 360"),
    ({**BOX, "scale": [0, 1, 1]}, "scale is a number from 0.01 to 20"),
    ({**BOX, "material": "wood"}, "`material` is an object"),
    ({**BOX, "material": {"texture": "marble"}}, "texture is one of grass"),
    ({**BOX, "material": {}}, "a material needs a texture or a color"),
    ({**BOX, "material": {"color": "red"}}, "color is a colour like"),
    ({**BOX, "material": {"color": "#000", "metal": 2}}, "metal is a number from 0 to 1"),
    ({**BOX, "material": {"texture": "grass", "repeat": [0, 1]}}, "repeat is a number from 0.1 to 40"),
    ({"shape": "cylinder", "radius": 1, "material": {"color": "#000"}}, "height is a number"),
    ({"shape": "cone", "radius": 1, "height": 1, "segments": 2, "material": {"color": "#000"}}, "segments is a number from 3 to 32"),
    ({"shape": "gable", "width": 1, "material": {"color": "#000"}}, "height is a number"),
    ({"shape": "sprite", "size": [1, 1]}, "a sprite has `pixels` ({rows, palette}) or `art` (one of reed, flower, curlew, spark, coin, note, carrots)"),
    ({"shape": "sprite", "size": [1, 1], "pixels": {"rows": ["k"], "palette": {"k": "#000"}}}, "shape 3 (sprite): a pixel picture is 4 to 32 rows tall"),
    ({"shape": "light", "strength": 5}, "strength is a number from 0 to 3"),
    ({"shape": "light", "color": "warm"}, "color is a colour like"),
    ({"shape": "plane", "size": [1, 1], "faces": {"top": {"color": "#000"}, "side": {"color": "#000"}}}, "`faces` is for a box"),
    ({**BOX, "faces": {"top": {"color": "#000"}}}, "`faces` is for a box"),
    ({**BOX, "tip": "hi"}, "`tip` is {title, text}"),
])
def test_what_a_shape_cant_be_is_named(s, why):
    assert why in bad(G.shape, s, 3)


def test_anchors_and_whole_parts_are_checked():
    ok = G.anchor({"id": "back-wall", "type": "wall", "tags": ["Inside ", "back"], "at": [0, 1, -2], "extent": [3, 1]}, 0)
    assert ok == {"id": "back-wall", "type": "wall", "tags": ["inside", "back"], "at": [0.0, 1.0, -2.0], "normal": [0.0, 0.0, 1.0], "extent": [3.0, 1.0]}
    assert G.anchor({"id": "f", "type": "floor", "tags": ["x"], "at": [0, 0, 0], "normal": [1, 0, 0], "extent": [1, 1]}, 0)["normal"] == [0.0, 1.0, 0.0]
    assert G.anchor({"id": "w", "type": "wall", "tags": ["x"], "at": [0, 0, 0], "normal": [1, 0, 0], "extent": [1, 1]}, 0)["normal"] == [1.0, 0.0, 0.0]
    assert bad(G.anchor, {"id": "Bad Id", "type": "wall"}, 2) == "anchor 2: `id` is lowercase letters, digits and dashes"
    assert bad(G.anchor, {"id": "a", "type": "roof"}, 2) == "anchor 2: `type` is one of wall, surface, floor, ground, hang"
    assert bad(G.anchor, {"id": "a", "type": "floor", "tags": []}, 2) == "anchor 2: `tags` is a list of 1 to 6 words"
    assert bad(G.anchor, {"id": "a", "type": "floor", "tags": ["x"], "at": [0, 0, 0], "extent": [0, 1]}, 2).endswith("is a number from 0.05 to 60")
    assert G.built({"shapes": [BOX]}) == {"shapes": [G.shape(BOX, 0)], "anchors": []}
    assert bad(G.built, []) == 'on_build returns {"shapes": [...], "anchors": [...]}'
    assert bad(G.built, {"shapes": []}) == "a part has 1 to 400 shapes" and bad(G.built, {"shapes": [BOX] * 401}) == "a part has 1 to 400 shapes"
    a = {"id": "a", "type": "floor", "tags": ["x"], "at": [0, 0, 0], "extent": [1, 1]}
    assert bad(G.built, {"shapes": [BOX], "anchors": [a] * 25}) == "a part has at most 24 anchors"
    assert bad(G.built, {"shapes": [BOX], "anchors": "a"}) == "a part has at most 24 anchors"
    assert bad(G.built, {"shapes": [BOX], "anchors": [a, a]}) == "each anchor needs its own id"


def test_a_part_is_moved_and_turned_into_place():
    part = G.built({"shapes": [{**BOX, "at": [1, 0.5, 0]}, {**BOX, "at": [0, 0, 2], "rot": [10, 5, 0]}],
                    "anchors": [{"id": "front", "type": "wall", "tags": ["inside"], "at": [0, 1, 1], "normal": [0, 0, 1], "extent": [1, 1]}]})
    moved = G.place(part, [10, 0, -5], 90, "house")
    assert [s["at"] for s in moved["shapes"]] == [[10.0, 0.5, -6.0], [12.0, 0.0, -5.0]]           # three.js turns +90: x -> -z, z -> +x
    assert [s["rot"] for s in moved["shapes"]] == [[0.0, 90.0, 0.0], [10.0, 95.0, 0.0]]
    a = moved["anchors"][0]
    assert a["id"] == "house-front" and a["tags"] == ["inside", "house"] and a["at"] == [11.0, 1.0, -5.0] and a["normal"] == [1.0, 0.0, 0.0]
    assert G.place(part, [0, 0, 0], 0, "inside")["anchors"][0]["tags"] == ["inside"]                # a role already among the tags isn't doubled
    assert G.place(part, [0, 0, 0], 0, "x")["shapes"][0] == {**part["shapes"][0], "rot": [0.0, 0.0, 0.0]}


# --- parts and places as modules ----------------------------------------------------------------------------------------------
TREE = ('def on_build(ctx):\n    s = ctx["params"]["scale"]\n'
        '    return {"shapes": [{"shape": "box", "size": [s, s, s], "at": [0, s / 2, 0], "material": {"texture": "leaves"}}],'
        ' "anchors": [{"id": "shade", "type": "ground", "tags": ["shade"], "at": [0, 0, 1], "extent": [1, 1]}]}\n')
PLACE = ('def on_build(ctx):\n    return {"parts": [{"part": "tree", "params": {"scale": 2}, "at": [3, 0, -4], "turn": 90, "role": "big"},'
         ' {"part": "tree", "at": [-3, 0, -4]}, {"part": "tree", "params": {"scale": 2}, "at": [0, 0, -8]}],'
         ' "shapes": [{"shape": "box", "size": [20, 1, 10], "at": [0, -0.5, -4], "faces": {"top": {"texture": "grass"}, "side": {"texture": "cliff"}}}],'
         ' "anchors": [{"id": "pip", "type": "ground", "tags": ["pip", "outside"], "at": [0, 0, 0], "extent": [4, 2]}]}\n')


def part_man(name="tree", **kw):
    return {"name": name, "kind": "part", "api": 1, "hooks": ["on_build"], "params": {"scale": 1}, **kw}


def place_man(name="glade", place="woods"):
    return {"name": name, "kind": "place", "api": 1, "hooks": ["on_build"], "place": place}


def test_parts_and_places_are_the_worlds_and_only_build(tmp_path):
    s, st, agent = modular(tmp_path)
    assert M.check_manifest(part_man(), "world") == {"name": "tree", "kind": "part", "api": 1, "hooks": ["on_build"], "reads": [], "proposes": [],
                                                    "params": {"scale": 1}, "events": [], "consumes": {}}
    assert M.check_manifest(place_man(place=" woods "), "world")["place"] == "woods"

    def refused(m, author="world"):
        with pytest.raises(M.Refused) as e:
            M.check_manifest(m, author)
        return str(e.value)
    assert refused(part_man(), "pip") == "parts and places are the world's; they have just on_build, and read and propose nothing"
    assert refused(part_man(hooks=["on_build", "on_tick"])) == "`hooks` is a list drawn from: on_build"
    assert refused(part_man(reads=["time"])).startswith("parts and places are the world's")
    assert refused({**part_man(), "hooks": ["on_tick"]}) == "`hooks` is a list drawn from: on_build"
    assert refused(part_man(params={"a": [1]})) == "`params` maps up to 16 names to plain default values"
    assert refused(part_man(params={str(i): 1 for i in range(17)})) == "`params` maps up to 16 names to plain default values"
    assert refused(place_man(place=" ")) == "a place module names the place it lays out: `place` (or describes a new one: `new`, or covers `kinds`)"
    assert refused({**rule_like(), "hooks": ["on_build"]}) == "`hooks` is a list drawn from: on_install, on_tick, on_time, on_event, on_action, on_message, on_answer, on_request"


def rule_like():
    return {"name": "bells", "kind": "rule", "api": 1, "hooks": ["on_tick"]}


@pytest.mark.asyncio
async def test_a_part_and_a_place_are_tried_by_building_them(tmp_path):
    s, st, agent = modular(tmp_path)
    r = await M.propose(st, s, agent.runner, "world", part_man(), TREE, now=NOW)
    assert r["report"] == {"calls": 1, "errors": [], "refused": [], "perceived": [], "logged": [], "replies": [], "offers": [], "placed": [],
                           "unplaced": [], "built": "1 shapes, 1 anchors", "clean": True}
    p = await M.propose(st, s, agent.runner, "world", place_man(), PLACE, now=NOW)                    # its part is only waiting: fine for a trial
    assert p["report"]["built"] == "4 shapes, 4 anchors" and p["report"]["calls"] == 2 and p["report"]["clean"]
    broken = await M.propose(st, s, agent.runner, "world", part_man("broken"), 'def on_build(ctx):\n    return {"shapes": []}\n', now=NOW)
    assert broken["report"]["errors"] == ["on_build: part broken: a part has 1 to 400 shapes"] and not broken["report"]["clean"]
    none = await M.propose(st, s, agent.runner, "world", part_man("empty"), 'x = 1\n', now=NOW)
    assert none["report"]["errors"] == ["on_build: part empty has no on_build"]
    crash = await M.propose(st, s, agent.runner, "world", part_man("crash"), 'def on_build(ctx):\n    return 1/0\n', now=NOW)
    assert crash["report"]["errors"] == ["on_build: part crash: line 2: ZeroDivisionError: division by zero"]
    lost = await M.propose(st, s, agent.runner, "world", place_man("lost"), PLACE.replace('"tree"', '"oak"'), now=NOW)
    assert lost["report"]["errors"] == ["on_build: there is no part called 'oak'"]


async def laid_out(tmp_path, **kw):
    s, st, agent = modular(tmp_path, modules_approval="", **kw)
    await M.propose(st, s, agent.runner, "world", part_man(), TREE, now=NOW)
    p = await M.propose(st, s, agent.runner, "world", place_man(), PLACE, now=NOW)
    return s, st, agent, st.module(p["id"])


@pytest.mark.asyncio
async def test_a_live_place_is_built_from_its_parts_and_drawn_instead_of_its_template(tmp_path):
    s, st, agent, m = await laid_out(tmp_path)
    assert WV.scene_view(st, s, None, "woods")["layout"] is None                                      # not built yet
    assert await L.step(st, s, agent.runner, NOW) == 1 and await L.step(st, s, agent.runner, NOW) == 0
    b = st.module(m["id"])["built"]
    assert b["parts"] == {"tree": st.modules()[0]["id"]} and b["season"] == L.season(s, NOW) and b["version"] == 1
    assert [sh["at"] for sh in b["shapes"]] == [[0.0, -0.5, -4.0], [3.0, 1.0, -4.0], [-3.0, 0.5, -4.0], [0.0, 1.0, -8.0]]
    assert [a["id"] for a in b["anchors"]] == ["pip", "big-shade", "tree-1-shade", "tree-2-shade"]
    assert b["anchors"][1]["at"] == [4.0, 0.0, -4.0] and "big" in b["anchors"][1]["tags"]               # turned: its shade is to the side
    assert st.events(1)[0]["kind"] == "layout_built" and st.events(1)[0]["data"] == {"name": "glade", "place": "woods", "shapes": 4, "anchors": 4}
    lay = WV.scene_view(st, s, None, "woods")["layout"]
    assert lay == {"shapes": b["shapes"], "anchors": b["anchors"], "module": "glade", "version": 1}
    assert L.anchors_for(st, "woods") == tuple(b["anchors"]) and L.anchors_for(st, "junkyard") is None and L.for_scene(st, "workshop") is None


@pytest.mark.asyncio
async def test_objects_go_on_a_layouts_anchors(tmp_path):
    s, st, agent, m = await laid_out(tmp_path)
    await L.step(st, s, agent.runner, NOW)
    shower = live(st, {"name": "mushrooms", "kind": "rule", "api": 1, "hooks": ["on_tick"], "proposes": ["show"]}, "x")
    st.update_module(shower["id"], show=[{"id": "m", "sprite": {"rows": ["kkkk"] * 4, "palette": {"k": "#c33"}}, "size": 0.5, "frame": False,
                                          "at": {"type": "ground", "place": "woods", "tags": ["shade"], "near": "big-shade"}}])
    [o] = WV.scene_view(st, s, None, "woods")["objects"]
    assert o["pos"][0] == pytest.approx(4.0 - 0.5 + 0.25) and o["pos"][2] == 4.0 - 8.0          # in the big tree's shade


@pytest.mark.asyncio
async def test_a_layout_is_rebuilt_when_the_season_or_a_part_changes_and_a_failure_waits_an_hour(tmp_path):
    s, st, agent, m = await laid_out(tmp_path)
    await L.step(st, s, agent.runner, NOW)
    assert not L.stale(st, s, st.module(m["id"]), NOW)
    assert L.stale(st, s, st.module(m["id"]), NOW + 100 * 86400)                                          # another season
    tree = L.part_named(st, "tree")
    two = await M.propose(st, s, agent.runner, "world", part_man(), TREE.replace("s / 2", "s"), replaces=tree["id"], now=NOW)
    assert L.stale(st, s, st.module(m["id"]), NOW) and await L.step(st, s, agent.runner, NOW) == 1
    assert st.module(m["id"])["built"]["parts"] == {"tree": two["id"]}
    M.disable(st, two["id"])
    assert L.part_named(st, "tree") is None and L.part_named(st, "tree", waiting=True) is None
    assert await L.step(st, s, agent.runner, NOW) == 0                                                    # its part is gone: it can't build
    got = st.module(m["id"])["built"]
    assert got["error"] == "there is no part called 'tree'" and got["failed_at"] == NOW and got["shapes"]   # the last good build stays
    assert st.events(1)[0]["kind"] == "layout_failed"
    assert await L.step(st, s, agent.runner, NOW + 60) == 0 and len([e for e in st.events(10) if e["kind"] == "layout_failed"]) == 1
    await M.approve(st, s, agent.runner, two["id"])
    assert await L.step(st, s, agent.runner, NOW + 3601) == 1
    assert await L.step(st, s, None, NOW) == 0


@pytest.mark.asyncio
async def test_one_place_module_lays_out_a_place_and_a_bad_plan_is_named(tmp_path):
    s, st, agent, m = await laid_out(tmp_path)
    other = await M.propose(st, s, agent.runner, "world", place_man("grove"), PLACE, now=NOW)
    assert st.module(m["id"])["status"] == "replaced" and L.place_module(st, "woods")["id"] == other["id"]
    for plan, why in (('{"parts": "x"}', "a place's on_build returns"), ('{"parts": [{"at": [0, 0, 0]}]}', "part entry 0: needs `part`"),
                      ('{"parts": [{"part": "tree", "params": {"a": [1]}, "at": [0, 0, 0]}]}', "part entry 0: `params` maps names to plain values"),
                      ('{"parts": [{"part": "tree", "at": [0, 0, 0]}] * 81}', "a place has at most 80 parts"),
                      ('{"parts": [], "anchors": "x"}', "`shapes` and `anchors` are lists"),
                      ('{"parts": [{"part": "tree", "at": [0, 0, 0], "role": "a"}, {"part": "tree", "at": [1, 0, 0], "role": "a"}]}', "two anchors share an id")):
        with pytest.raises(L.Bad) as e:
            await L.build_place(st, s, agent.runner, {**st.module(other["id"]), "source": f"def on_build(ctx):\n    return {plan}\n"}, NOW)
        assert why in str(e.value)
    big = 'def on_build(ctx):\n    return {"parts": [{"part": "tree", "at": [0, 0, 0], "role": f"t{i}"} for i in range(80)]}\n'
    many = 'def on_build(ctx):\n    return {"shapes": [{"shape": "box", "size": [1, 1, 1], "at": [0, 0, 0], "material": {"color": "#000"}}] * 40}\n'
    st.update_module(L.part_named(st, "tree")["id"], source=many)
    with pytest.raises(L.Bad) as e:
        await L.build_place(st, s, agent.runner, {**st.module(other["id"]), "source": big}, NOW)
    assert str(e.value) == "a place has at most 3000 shapes"
    with pytest.raises(L.Bad) as e:
        await L.build_place(st, s, agent.runner, {**st.module(other["id"]), "source": "def on_build(ctx):\n    return 1/0\n"}, NOW)
    assert str(e.value) == "grove: line 2: ZeroDivisionError: division by zero"


@pytest.mark.asyncio
async def test_the_librarys_parts_and_the_outdoors_layout_build(tmp_path):
    s, st, agent = modular(tmp_path)
    made = await M.offer_library(st, s, agent.runner, now=NOW)
    assert all(st.module(i)["status"] == "live" for i in made), [(st.module(i)["name"], st.module(i)["report"]) for i in made]
    assert await L.step(st, s, agent.runner, NOW) >= 2                                             # the woods and the junkyard
    woods, yard = L.for_scene(st, "woods", "wild"), L.for_scene(st, "junkyard", "yard")
    assert woods["module"] == yard["module"] == "outdoors"
    assert len(woods["shapes"]) == 2 + 11 * 5 + 18 * 4 and {"pip", "finds", "open-ground"} <= {a["id"] for a in woods["anchors"]}
    assert sum(sh.get("hitbox", False) for sh in yard["shapes"]) == 4 and any(a["id"].startswith("heap-") for a in yard["anchors"])
    assert L.for_scene(st, "woods") is None and L.anchors_for(st, "woods", "wild") == tuple(woods["anchors"])
    assert st.module(made[0])["built"] == {} and "woods" in L.kind_module(st, "wild")["built"]["places"]
    winter = await L.build_part(agent.runner, L.part_named(st, "pine-tree"), {}, "winter", 1)
    assert winter["shapes"][1]["material"]["color"] == "#3f5a46"
    house = await L.build_part(agent.runner, L.part_named(st, "cutaway"), {"door": False, "walls": "whitewash"}, "summer", 1)
    assert [a["id"] for a in house["anchors"]] == ["back-wall", "floor", "front"] and not any(sh["material"].get("texture") == "door" for sh in house["shapes"] if "material" in sh)


@pytest.mark.asyncio
async def test_the_outdoors_layout_follows_each_places_details(tmp_path):
    s, st, agent = modular(tmp_path)
    await M.offer_library(st, s, agent.runner, now=NOW)
    m = L.kind_module(st, "sight")
    base = {"key": "x", "label": "x", "kind": "wild", "coastal": False, "props": [], "walls": "stone", "roof": "slate", "palette": "warm"}
    async def built(**d):
        return await L.build_place(st, s, agent.runner, m, NOW, key="x", details={**base, **d})
    shore = (await built(setting="shore"))["shapes"]
    assert any(sh.get("animate") == "tide" for sh in shore) and not any(sh.get("art") == "reed" for sh in shore)
    assert sum(sh.get("art") == "reed" for sh in (await built(setting="marsh"))["shapes"]) == 50
    assert any(sh.get("animate") == "flow" for sh in (await built(setting="riverside"))["shapes"])
    assert sum(sh["shape"] == "sphere" for sh in (await built(setting="hills"))["shapes"]) == 5
    sight = await built(kind="sight", setting="heath")
    assert "bench-seat" in {a["id"] for a in sight["anchors"]} and any(sh.get("tip", {}).get("title") == "The old stones" for sh in sight["shapes"])
    lit = await built(kind="sight", setting="shore", props=["lighthouse"])
    assert any(sh.get("material", {}).get("lamp") for sh in lit["shapes"]) and not any(sh.get("tip", {}).get("title") == "The old stones" for sh in lit["shapes"])


def test_the_browser_draws_layouts_with_one_renderer(tmp_path):
    from pathlib import Path
    web = Path(M.__file__).resolve().parent.parent / "web" / "world"
    scene, layout = (web / "scene.js").read_text(), (web / "layout.js").read_text()
    assert 'import * as layout from "./layout.js"' in scene and "data.layout ? layout : null" in scene and "templates/" not in scene
    assert 'obj.rotation.order = "YXZ"' in layout
    for shape in G.SHAPES:
        assert f'"{shape}"' in layout, shape


# --- precisely ---------------------------------------------------------------------------------------------------------------
def test_placing_rounds_and_lifts_exactly():
    part = G.built({"shapes": [{**BOX, "at": [1, 0.5, 0], "rot": [0, 0.123456, 0]}],
                    "anchors": [{"id": "w", "type": "wall", "tags": ["x"], "at": [1, 1, 0], "normal": [0, 0, 1], "extent": [1, 1]}]})
    m = G.place(part, [0.123456, 2, 0.654321], 30, "r")
    assert m["shapes"][0]["at"] == [round(0.866025 + 0.123456, 4), 2.5, round(-0.5 + 0.654321, 4)] and m["shapes"][0]["rot"] == [0.0, 30.1235, 0.0]
    a = m["anchors"][0]
    assert a["at"] == [round(0.866025 + 0.123456, 4), 3.0, round(-0.5 + 0.654321, 4)] and a["normal"] == [0.5, 0.0, 0.866]
    assert G._turn(0, 1, 90) == pytest.approx((1.0, 0.0))


def test_shape_fields_exactly():
    c = {"color": "#000"}
    assert G.shape({"shape": "sphere", "radius": 2.5, "segments": 24, "material": c}, 0) == {"shape": "sphere", "at": [0.0, 0.0, 0.0], "radius": 2.5, "segments": 24, "material": c}
    assert G.shape({"shape": "ico", "radius": 2, "material": c}, 0) == {"shape": "ico", "at": [0.0, 0.0, 0.0], "radius": 2.0, "material": c}
    assert G.shape({"shape": "torus", "radius": 0.3, "tube": 0.1, "material": c}, 0) == {"shape": "torus", "at": [0.0, 0.0, 0.0], "radius": 0.3, "tube": 0.1, "material": c}
    assert G.shape({"shape": "dodeca", "radius": 60, "material": c}, 0)["radius"] == 60.0
    assert G.shape({"shape": "cylinder", "radius": 1, "top": 0, "height": 60, "segments": 32, "material": c}, 0) == \
        {"shape": "cylinder", "at": [0.0, 0.0, 0.0], "radius": 1.0, "height": 60.0, "segments": 32, "top": 0.0, "material": c}
    assert G.shape({"shape": "gable", "width": 60, "height": 0.01, "material": c}, 0) == {"shape": "gable", "at": [0.0, 0.0, 0.0], "width": 60.0, "height": 0.01, "material": c}
    assert G.shape({"shape": "plane", "size": [60, 0.01], "material": c}, 0)["size"] == [60.0, 0.01]
    assert G.shape({"shape": "light", "range": 40, "color": "#FFF"}, 0) == {"shape": "light", "at": [0.0, 0.0, 0.0], "color": "#fff", "strength": 1.0, "range": 40.0}
    assert G.shape({"shape": "light", "range": 0.5}, 0)["range"] == 0.5 and "40" in bad(G.shape, {"shape": "light", "range": 41}, 0)
    assert G.shape({**BOX, "tip": {"text": "t" * 300}}, 0)["tip"] == {"title": "", "text": "t" * 200}
    assert G.shape({**BOX, "faces": {"top": {"color": "#111"}, "side": {"color": "#222"}}}, 0)["faces"] == {"top": {"color": "#111"}, "side": {"color": "#222"}}
    for s, why in (({"shape": "sphere", "radius": 1, "segments": 2, "material": c}, "shape 0 (sphere): segments is a number from 3 to 24"),
                   ({"shape": "sphere", "radius": 1, "segments": 25, "material": c}, "segments is a number from 3 to 24"),
                   ({"shape": "ico", "radius": 61, "material": c}, "shape 0 (ico): radius is a number from 0.01 to 60"),
                   ({"shape": "torus", "radius": 1, "material": c}, "shape 0 (torus): tube (radius) is a number from 0.01 to 60"),
                   ({"shape": "torus", "tube": 1, "material": c}, "shape 0 (torus): radius is a number from 0.01 to 60"),
                   ({"shape": "dodeca", "material": c}, "shape 0 (dodeca): radius is a number"),
                   ({"shape": "cylinder", "radius": 1, "height": 1, "top": 61, "material": c}, "shape 0 (cylinder): top (radius) is a number from 0 to 60"),
                   ({"shape": "cylinder", "radius": 1, "height": 61, "material": c}, "shape 0 (cylinder): height is a number from 0.01 to 60"),
                   ({"shape": "cylinder", "radius": 1, "height": 1, "segments": 33, "material": c}, "segments is a number from 3 to 32"),
                   ({"shape": "gable", "width": 61, "height": 1, "material": c}, "shape 0 (gable): width is a number from 0.01 to 60"),
                   ({"shape": "gable", "width": 1, "height": 0, "material": c}, "shape 0 (gable): height is a number from 0.01 to 60"),
                   ({"shape": "plane", "size": [1, 61], "material": c}, "shape 0 (plane): size [w, h] is a number from 0.01 to 60"),
                   ({"shape": "box", "size": [1, 1, 61], "material": c}, "shape 0 (box): size [w, h, d] is a number from 0.01 to 60"),
                   ({"shape": "box", "size": [1, 1, 1]}, "shape 0 (box): `material` is an object"),
                   ({**BOX, "faces": {"top": {"color": "x"}, "side": c}}, "shape 0 (box): top: color is a colour like"),
                   ({**BOX, "tip": {"title": 5}}, "`tip` is {title, text}"), ({**BOX, "tip": {"text": 5}}, "`tip` is {title, text}")):
        assert why in bad(G.shape, s, 0), (s, why)


@pytest.mark.asyncio
async def test_what_a_place_and_its_parts_are_told(tmp_path):
    s, st, agent = modular(tmp_path, modules_approval="", hemisphere="south")
    echo = ('def on_build(ctx):\n    return {"shapes": [{"shape": "box", "size": [1, 1, 1], "at": [ctx["seed"] % 50, 0, 0], "material": {"color": "#000"},'
            ' "tip": {"title": ctx["season"], "text": str(sorted(ctx["params"].items()))}}]}\n')
    await M.propose(st, s, agent.runner, "world", part_man("echo", params={"a": 1, "b": "x"}), echo, now=NOW)
    plan = ('def on_build(ctx):\n    return {"parts": [{"part": "echo", "params": {"b": "y"}, "at": [0, 0, 0], "role": "Big Oak!"}],'
            ' "shapes": [{"shape": "box", "size": [1, 1, 1], "at": [ctx["seed"] % 50, 0, 0], "material": {"color": "#000"},'
            ' "tip": {"title": ctx["place"], "text": ctx["season"] + str(ctx["params"])}}]}\n')
    p = await M.propose(st, s, agent.runner, "world", place_man(), plan, now=NOW)
    b = await L.build_place(st, s, agent.runner, st.module(p["id"]), NOW)
    own, part = b["shapes"]
    assert own["tip"] == {"title": "woods", "text": L.season(s, NOW) + "{}"} and own["at"][0] == L.seed_of("woods") % 50
    assert part["tip"] == {"title": L.season(s, NOW), "text": "[('a', 1), ('b', 'y')]"}
    assert part["at"][0] == L.seed_of("woods", "echo", '{"b": "y"}') % 50
    assert L.season(s, NOW) != L.season(type(s)(hemisphere="north"), NOW)                                      # the hemisphere counts
    assert L.seed_of("woods") == int(__import__("hashlib").sha256(b"woods").hexdigest()[:8], 16)


@pytest.mark.asyncio
async def test_a_plans_defaults_and_cleaning(tmp_path):
    s, st, agent = modular(tmp_path, modules_approval="")
    await M.propose(st, s, agent.runner, "world", part_man(), TREE, now=NOW)
    plan = L._plan({"parts": [{"part": "tree", "at": [0, 0, 0], "role": "Big Oak!"}, {"part": "tree", "at": [1, 0, 0]}]})
    assert plan["parts"] == [{"part": "tree", "params": {}, "at": [0.0, 0.0, 0.0], "turn": 0.0, "role": "big-oak-"},
                             {"part": "tree", "params": {}, "at": [1.0, 0.0, 0.0], "turn": 0.0, "role": "tree-1"}]
    assert L._plan({}) == {"parts": [], "own": {"shapes": [], "anchors": []}}
    assert L._plan({"parts": [{"part": "tree", "at": [0, 0, 0], "role": "x" * 50}]})["parts"][0]["role"] == "x" * 40
    a = {"id": "a", "type": "floor", "tags": ["x"], "at": [0, 0, 0], "extent": [1, 1]}
    assert len(L._plan({"anchors": [{**a, "id": f"a{i}"} for i in range(24)]})["own"]["anchors"]) == 24
    for spec, why in (({"anchors": [{**a, "id": f"a{i}"} for i in range(25)]}, "`shapes` and `anchors` are lists (at most 24 anchors)"),
                      ({"shapes": "x"}, "`shapes` and `anchors` are lists"),
                      ({"shapes": [{"shape": "x"}]}, "shape 0: `shape` is one of"), ({"anchors": [a, {"id": "B"}]}, "anchor 1: `id` is"),
                      ({"parts": [{"part": "tree", "at": [0, 0, 0], "turn": 361}]}, "part entry 0: turn is a number from -360 to 360"),
                      ({"parts": [{"part": "tree", "at": [0, 0]}]}, "part entry 0: at is a list of 3 numbers")):
        with pytest.raises(L.Bad) as e:
            L._plan(spec)
        assert why in str(e.value), (spec, why)
    with pytest.raises(L.Bad) as e:
        await L.build_place(st, s, agent.runner, {**place_man(), "id": 0, "name": "glade", "version": 1, "manifest": place_man(), "source": "x = 1\n"}, NOW)
    assert str(e.value) == "a place's on_build returns {\"parts\": [...], \"shapes\": [...], \"anchors\": [...]}"


@pytest.mark.asyncio
async def test_the_step_builds_every_live_place_once_and_logs_failures_fully(tmp_path):
    s, st, agent = modular(tmp_path, modules_approval="")
    await M.propose(st, s, agent.runner, "world", part_man(), TREE, now=NOW)
    for name, place in (("glade", "woods"), ("tip", "junkyard"), ("waits", "library")):
        await M.propose(st, s, agent.runner, "world", place_man(name, place), PLACE, now=NOW)
    st.update_module(L.place_module(st, "library")["id"], status="waiting")
    assert await L.step(st, s, agent.runner, NOW) == 2 and L.for_scene(st, "library") is None
    tip = L.place_module(st, "junkyard")
    st.update_module(tip["id"], source="def on_build(ctx):\n    return 1/0\n", built={})
    assert await L.step(st, s, agent.runner, NOW) == 0
    e = st.events(1)[0]
    assert e["kind"] == "layout_failed" and e["data"] == {"name": "tip", "place": "junkyard", "error": "tip: line 2: ZeroDivisionError: division by zero"}
    assert st.module(tip["id"])["built"] == {"error": "tip: line 2: ZeroDivisionError: division by zero", "failed_at": NOW,
                                             "failed_parts": L.live_parts(st)}
    assert await L.step(st, s, agent.runner, NOW + 3599) == 0 and await L.step(st, s, agent.runner, NOW + 3600) == 0
    assert len([x for x in st.events(20) if x["kind"] == "layout_failed"]) == 2                      # an hour on, tried again


def test_which_part_a_name_means(tmp_path):
    s, st, agent = modular(tmp_path)
    one = live(st, part_man(), TREE)
    two = live(st, part_man(), TREE)
    assert L.part_named(st, "tree")["id"] == two["id"]
    st.update_module(two["id"], status="waiting")
    assert L.part_named(st, "tree")["id"] == one["id"] and L.part_named(st, "tree", waiting=True)["id"] == one["id"]     # live first
    st.update_module(one["id"], status="rejected")
    assert L.part_named(st, "tree") is None and L.part_named(st, "tree", waiting=True)["id"] == two["id"]
    st.update_module(two["id"], status="proposed")
    assert L.part_named(st, "tree", waiting=True)["id"] == two["id"]
    st.update_module(two["id"], status="disabled")
    assert L.part_named(st, "tree", waiting=True) is None
    r = live(st, {"name": "tree", "kind": "rule", "api": 1, "hooks": ["on_tick"]}, "x")
    assert L.part_named(st, "tree") is None                                                       # a rule with the name isn't a part


@pytest.mark.asyncio
async def test_a_layout_approved_before_its_parts_builds_as_soon_as_they_are_live(tmp_path):
    s, st, agent = modular(tmp_path)
    part = await M.propose(st, s, agent.runner, "world", part_man(), TREE, now=NOW)
    place = await M.propose(st, s, agent.runner, "world", place_man(), PLACE, now=NOW)
    await M.approve(st, s, agent.runner, place["id"], now=NOW)                                   # the layout first, its part still waiting
    assert await L.step(st, s, agent.runner, NOW) == 0 and st.module(place["id"])["built"]["failed_parts"] == []
    assert await L.step(st, s, agent.runner, NOW + 60) == 0                                       # nothing changed: it waits
    await M.approve(st, s, agent.runner, part["id"], now=NOW)
    assert L.live_parts(st) == [part["id"]] and await L.step(st, s, agent.runner, NOW + 120) == 1  # its part is live: no hour's wait



# --- moving features into modules (0.23.0) -----------------------------------------------------------------------------------
def test_shapes_can_animate_and_hitboxes_carry_a_tip():
    sea = G.shape({**BOX, "animate": "tide"}, 0)
    assert (sea["animate"], sea["speed"]) == ("tide", 0.02) and G.shape({**BOX, "animate": "flow", "speed": 1}, 0)["speed"] == 1.0
    assert bad(G.shape, {**BOX, "animate": "wobble"}, 0) == "shape 0 (box): `animate` is one of flow, tide, spin, wander (a sprite: wander)"
    assert bad(G.shape, {"shape": "light", "animate": "flow"}, 0).endswith("`animate` is one of flow, tide, spin, wander (a sprite: wander)")
    assert bad(G.shape, {**BOX, "animate": "flow", "speed": 2}, 0).endswith("speed is a number from 0 to 1")
    hb = G.shape({"shape": "box", "size": [1, 1, 1], "hitbox": True, "tip": {"title": "Heap"}}, 0)
    assert hb == {"shape": "box", "at": [0.0, 0.0, 0.0], "size": [1.0, 1.0, 1.0], "material": {"color": "#000000"}, "hitbox": True,
                  "tip": {"title": "Heap", "text": ""}}
    assert bad(G.shape, {"shape": "box", "size": [1, 1, 1], "hitbox": True}, 0) == "shape 0 (box): a `hitbox` is an invisible box with a `tip`"
    assert bad(G.shape, {"shape": "plane", "size": [1, 1], "hitbox": True, "tip": {}}, 0).endswith("a `hitbox` is an invisible box with a `tip`")
    assert G.anchor({"id": "g", "type": "ground", "tags": ["x"], "at": [0, 0, 0]}, 0)["extent"] == [2.0, 1.0]
    assert G.anchor({"id": "w", "type": "wall", "tags": ["x"], "at": [0, 0, 0]}, 0)["extent"] == [1.0, 1.0]


def test_a_kind_layout_is_checked(tmp_path):
    s, st, agent = modular(tmp_path)
    kinds = {"name": "fields", "kind": "place", "api": 1, "hooks": ["on_build"], "kinds": ["wild", "sight", "wild"]}
    assert M.check_manifest(kinds, "library")["kinds"] == ["wild", "sight"] and M.check_manifest(kinds, "world")["kinds"] == ["wild", "sight"]
    for k in ([], ["castle"], "wild"):
        with pytest.raises(M.Refused) as e:
            M.check_manifest({**kinds, "kinds": k}, "world")
        assert str(e.value) == "`kinds` is a list drawn from: home, neighbor, library, wild, yard, shop, market, sight"
    with pytest.raises(M.Refused):
        M.check_manifest(kinds, "pip")


KIND = ('def on_build(ctx):\n    d = ctx["details"]\n'
        '    return {"shapes": [{"shape": "box", "size": [1, 1, 1], "at": [0, 0, 0], "material": {"color": "#000"}, "tip": {"title": d["kind"], "text": d.get("setting", "")}}],'
        ' "anchors": [{"id": "pip", "type": "ground", "tags": ["pip"], "at": [0, 0, 0]}]}\n')


@pytest.mark.asyncio
async def test_a_kind_layout_lays_out_every_place_of_its_kinds_unless_a_place_has_its_own(tmp_path):
    s, st, agent = modular(tmp_path, modules_approval="")
    r = await M.propose(st, s, agent.runner, "world", {"name": "fields", "kind": "place", "api": 1, "hooks": ["on_build"], "kinds": ["wild", "yard"]}, KIND, now=NOW)
    assert r["report"]["built"] == "2 shapes, 2 anchors" and r["report"]["calls"] == 3 and r["report"]["clean"]
    assert await L.step(st, s, agent.runner, NOW) == 2 and await L.step(st, s, agent.runner, NOW) == 0
    woods = L.for_scene(st, "woods", "wild")
    assert woods["module"] == "fields" and woods["shapes"][0]["tip"]["title"] == "wild" and L.for_scene(st, "woods") is None
    assert L.for_scene(st, "junkyard", "yard")["shapes"][0]["tip"]["title"] == "yard" and L.for_scene(st, "library", "library") is None
    from app import world_view as WV2
    assert WV2.scene_view(st, s, None, "woods")["layout"]["module"] == "fields"
    own = live(st, place_man("woods-own"), PLACE)
    await M.propose(st, s, agent.runner, "world", part_man(), TREE, now=NOW)
    await L.step(st, s, agent.runner, NOW)
    assert L.for_scene(st, "woods", "wild")["module"] == "woods-own"                                 # a place's own layout first
    details = st.module(r["id"])["built"]["places"]["junkyard"]["details"]
    assert details == WV2.place_details(st, s, "junkyard", "yard") and set(details) == {"key", "label", "kind", "coastal", "props", "walls", "roof", "palette", "setting"}
    st.set_meta(**{"scene:junkyard": json.dumps({**{k: details[k] for k in ("walls", "roof", "palette")}, "setting": "shore", "props": []})})
    assert await L.step(st, s, agent.runner, NOW) == 1                                                # its details changed: rebuilt
    assert L.for_scene(st, "junkyard", "yard")["shapes"][0]["tip"]["text"] == "shore"


@pytest.mark.asyncio
async def test_a_kind_layout_that_fails_for_one_place_keeps_the_others(tmp_path):
    s, st, agent = modular(tmp_path, modules_approval="")
    src = KIND.replace('d = ctx["details"]', 'd = ctx["details"]\n    if d["kind"] == "yard":\n        return 1/0')
    await M.propose(st, s, agent.runner, "world", {"name": "fields", "kind": "place", "api": 1, "hooks": ["on_build"], "kinds": ["wild", "sight"]}, KIND, now=NOW)
    m = L.kind_module(st, "wild")
    st.update_module(m["id"], source=src, manifest={**m["manifest"], "kinds": ["wild", "yard"]})
    assert await L.step(st, s, agent.runner, NOW) == 1
    places = st.module(m["id"])["built"]["places"]
    assert "shapes" in places["woods"] and places["junkyard"]["error"] == "fields: line 4: ZeroDivisionError: division by zero"
    failed = [e["data"] for e in st.events(10) if e["kind"] == "layout_failed"]
    assert failed == [{"name": "fields", "place": "junkyard", "error": "fields: line 4: ZeroDivisionError: division by zero"}]
    assert L.for_scene(st, "junkyard", "yard") is None


@pytest.mark.asyncio
async def test_shipped_modules_run_without_a_runner(tmp_path):
    s, st, agent = modular(tmp_path)
    m = live(st, {"name": "ticker", "kind": "rule", "api": 1, "hooks": ["on_tick"], "proposes": ["state"]},
             "def on_tick(ctx):\n    return {'state': {'n': ctx['state'].get('n', 0) + 1}}\n", author="library")
    w = live(st, {"name": "worldly", "kind": "rule", "api": 1, "hooks": ["on_tick"], "proposes": ["state"]},
             "def on_tick(ctx):\n    return {'state': {'n': 1}}\n")
    await M.step(st, s, None, NOW)
    assert st.module(m["id"])["state"] == {"n": 1} and st.module(w["id"])["state"] == {}
    k = live(st, {"name": "fields", "kind": "place", "api": 1, "hooks": ["on_build"], "kinds": ["wild"]}, KIND, author="library")
    assert await L.step(st, s, None, NOW) == 1 and L.for_scene(st, "woods", "wild")["module"] == "fields"


def test_the_renderer_knows_hitboxes_animation_and_seats():
    from pathlib import Path
    js = (Path(M.__file__).resolve().parent.parent / "web" / "world" / "layout.js").read_text()
    assert "if (s.hitbox) { obj = kit.hitbox(" in js and 'if (kind === "tide")' in js and 'seat = tagged("seat")' in js
    assert not (Path(M.__file__).resolve().parent.parent / "web" / "world" / "templates" / "outdoors.js").exists()


@pytest.mark.asyncio
async def test_the_builder_hears_the_anchors_a_kind_layout_has_built(tmp_path):
    from app import builder as B
    s, st, agent = modular(tmp_path, modules_approval="")
    assert B.anchor_list() == B.anchor_list(None)
    await shipped_layouts(st, s, "home")
    text = B.anchor_list(st)
    assert text.splitlines()[-1] == "  neighbor/library/wild/yard/shop/market/sight: ground tagged outside (once its layout is built)"
    assert text.splitlines()[0].startswith("  home: ") and "wall tagged inside, back" in text.splitlines()[0]
    await M.propose(st, s, agent.runner, "world", {"name": "fields", "kind": "place", "api": 1, "hooks": ["on_build"], "kinds": ["wild", "yard"]}, KIND, now=NOW)
    await L.step(st, s, agent.runner, NOW)
    lines = B.anchor_list(st).splitlines()
    assert "  wild/yard: ground tagged pip" in lines and "  neighbor/library/shop/market/sight: ground tagged outside (once its layout is built)" in lines
    assert "reserved" not in lines[0] and "clock" not in lines[0]                                    # where the scene draws its own: not offered
    assert len([l for l in lines if l.startswith("  wild")]) == 1


@pytest.mark.asyncio
async def test_a_kind_trial_builds_each_kind_once(tmp_path):
    s, st, agent = modular(tmp_path)
    await M.propose(st, s, agent.runner, "world", part_man(), TREE, now=NOW)
    src = KIND.replace('"anchors": [', '"parts": [{"part": "tree", "at": [0, 0, 0]}], "anchors": [')
    r = await M.propose(st, s, agent.runner, "world", {"name": "fields", "kind": "place", "api": 1, "hooks": ["on_build"], "kinds": ["wild", "yard", "sight"]}, src, now=NOW)
    rep = r["report"]
    assert rep["built"] == "6 shapes, 6 anchors" and rep["calls"] == 1 + 3 * 2 and rep["errors"] == [] and rep["clean"]
    bad = await M.propose(st, s, agent.runner, "world", {"name": "broken", "kind": "place", "api": 1, "hooks": ["on_build"], "kinds": ["wild"]},
                          "def on_build(ctx):\n    return 1/0\n", now=NOW)
    assert bad["report"]["errors"] == ["on_build: broken: line 2: ZeroDivisionError: division by zero"] and not bad["report"]["clean"]
    seen = await L.build_place(st, s, agent.runner, st.module(r["id"]), NOW, waiting=True, key="trial-wild",
                               details={"key": "trial-wild", "label": "a place", "kind": "wild", "coastal": False, "setting": "wood"})
    assert seen["shapes"][0]["tip"] == {"title": "wild", "text": "wood"}


def test_a_places_details_exactly(tmp_path):
    from app import world_view as WV2
    s, st, agent = modular(tmp_path)
    st.add_place("Saltholm", "saltholm", kind="shop", status="real", created_at=NOW, heard_at=NOW, hours=[9, 17], daylight_only=0, walk_minutes=10.0,
                 description="An ironmonger by the harbour, with lanterns and rope.", blurb="An ironmonger.")
    d = WV2.place_details(st, s, "Saltholm", "shop")
    from app import looks
    scene = looks.place_scene(st, "Saltholm", "shop", looks.place_text(st, "Saltholm"))
    assert {k: d[k] for k in ("walls", "roof", "palette", "setting")} == {k: scene[k] for k in ("walls", "roof", "palette", "setting")}
    assert d["props"] == list(dict.fromkeys(scene["props"] + looks.props(looks.place_text(st, "Saltholm"))))
    assert d["coastal"] is True and set(d["props"]) >= {"lanterns", "rope"} and d["label"] == "Saltholm" and d["kind"] == "shop"
    assert WV2.place_details(st, s, "woods", "wild")["coastal"] is False


# --- live elements; the last templates retired (0.24.0) ----------------------------------------------------------------------
@pytest.mark.asyncio
async def test_a_shipped_module_the_engine_changed_is_upgraded_unless_the_owner_stepped_in(tmp_path, monkeypatch):
    s, st, agent = modular(tmp_path)
    await M.offer_library(st, s, agent.runner, now=NOW)
    assert await M.offer_library(st, s, agent.runner, now=NOW) == []                             # nothing changed: nothing offered
    real = M.library
    def changed(name):
        man, src = real(name)
        return (man, src + "\n# a new version\n") if name in ("well", "bench") else (man, src)
    monkeypatch.setattr(M, "library", changed)
    M.disable(st, L.part_named(st, "bench")["id"])                                                 # the owner switched this one off
    made = await M.offer_library(st, s, agent.runner, now=NOW)
    assert [st.module(i)["name"] for i in made] == ["well"]
    well = L.part_named(st, "well")
    assert (well["id"], well["version"], well["status"], well["author"]) == (made[0], 2, "live", "library") and well["source"].endswith("# a new version\n")
    assert [m["status"] for m in st.modules() if m["name"] == "well"] == ["replaced", "live"]
    assert await M.offer_library(st, s, agent.runner, now=NOW) == []                             # once per change
    st.update_module(well["id"], author="world")                                                   # shipped before shipped modules had an author
    monkeypatch.setattr(M, "library", lambda name: (real(name)[0], real(name)[1] + "\n# again\n"))
    assert "well" in [st.module(i)["name"] for i in await M.offer_library(st, s, agent.runner, now=NOW)]
    assert L.part_named(st, "well")["author"] == "library"


def test_shapes_can_show_only_while_something_holds_and_turn_and_glow():
    c = {"color": "#000"}
    assert G.shape({**BOX, "when": "open"}, 0)["when"] == ["open"]
    assert G.shape({**BOX, "when": ["night", "high-tide", "night", "booth-3"]}, 0)["when"] == ["night", "high-tide", "booth-3"]
    assert "when" not in G.shape(BOX, 0)
    for when in ([], ["dusk"], "booth-9", ["open", 3]):
        assert bad(G.shape, {**BOX, "when": when}, 2).startswith("shape 2 (box): `when` is one or more of open, shut, day, night, high-tide, low-tide")
    assert G.shape({**BOX, "animate": "spin", "speed": 0.6}, 0)["animate"] == "spin"
    assert G.shape({"shape": "sprite", "art": "curlew", "size": [1, 1], "animate": "wander"}, 0)["animate"] == "wander"
    assert bad(G.shape, {**BOX, "animate": "wander"}, 0).endswith("(a sprite: wander)")
    assert bad(G.shape, {"shape": "sprite", "art": "reed", "size": [1, 1], "animate": "spin"}, 0).endswith("(a sprite: wander)")
    sp = {"shape": "sprite", "art": "note", "size": [1, 1]}
    assert G.shape({**sp, "frame": 7}, 0)["frame"] == 7 and "frame" not in G.shape(sp, 0) and "frame" not in G.shape({**BOX, "frame": 2}, 0)
    assert bad(G.shape, {**sp, "frame": 10}, 1) == "shape 1 (sprite): frame is a number from 0 to 9"
    assert G.shape({**sp, "art": "carrots"}, 0)["art"] == "carrots"
    assert G.material({"color": "#000", "lamp": True}, "m")["lamp"] == 1.0 and G.material({"color": "#000", "lamp": 0.3}, "m")["lamp"] == 0.3
    assert "lamp" not in G.material({"color": "#000", "lamp": False}, "m") and "lamp" not in G.material(c, "m")
    assert G.material({"color": "#000", "lamp": 2}, "m")["lamp"] == 2.0 and bad(G.material, {"color": "#000", "lamp": 3}, "m") == "m: lamp is a number from 0 to 2"
    assert G.material({"color": "#fff", "beam": 1}, "m") == {"color": "#fff", "beam": True} and "beam" not in G.material({**c, "beam": 0}, "m")
    assert {"chart", "book"} <= set(G.TEXTURES) and {f"booth-{i}" for i in range(1, 9)} <= set(G.CONDITIONS)


def test_a_part_placed_with_when_shows_only_while_it_holds():
    part = {"shapes": [G.shape({**BOX, "when": ["open"]}, 0), G.shape(BOX, 1)], "anchors": []}
    moved = G.place(part, [1, 0, 0], 0, "stall-1", ["booth-1", "open"])
    assert [s["when"] for s in moved["shapes"]] == [["open", "booth-1"], ["booth-1", "open"]]
    assert [("when" in s) for s in G.place(part, [1, 0, 0], 0, "x")["shapes"]] == [True, False]
    plan = L._plan({"parts": [{"part": "stall", "at": [0, 0, 0], "when": "booth-2"}, {"part": "stall", "at": [0, 0, 0]}]})
    assert plan["parts"][0]["when"] == ["booth-2"] and "when" not in plan["parts"][1]
    with pytest.raises(L.Bad) as e:
        L._plan({"parts": [{"part": "stall", "at": [0, 0, 0], "when": ["sometimes"]}]})
    assert str(e.value).startswith("part entry 0: `when` is one or more of open, shut")


def test_a_place_module_takes_over_from_the_one_it_covers():
    assert M._covers({"place": "woods"}, {"place": "woods"}) and not M._covers({"place": "woods"}, {"place": "fen"})
    assert not M._covers({"place": "woods"}, {"kinds": ["wild"]}) and not M._covers({"kinds": ["wild"]}, {"place": "woods"})
    assert M._covers({"kinds": ["wild", "yard"]}, {"kinds": ["wild"]}) and M._covers({"kinds": ["wild"]}, {"kinds": ["wild"]})
    assert not M._covers({"kinds": ["wild"]}, {"kinds": ["wild", "yard"]}) and not M._covers({"kinds": ["home"]}, {"kinds": ["market"]})


@pytest.mark.asyncio
async def test_the_shipped_layouts_build_every_kind_of_place_from_its_details(tmp_path):
    s, st, agent = modular(tmp_path)
    await shipped_layouts(st, s, "neighbor", "market", "shop", "library", "home")
    async def build(name, **details):
        m = next(m for m in st.modules("live") if m["name"] == name)
        return await L.build_place(st, s, M.LocalRunner(), m, NOW, key="x", details={"key": "x", "props": [], **details})
    coast = await build("neighbor", coastal=True, props=["shingle", "birds", "lighthouse", "tide chart", "tin", "books", "vegetables", "reeds"])
    arts = [sh.get("art") for sh in coast["shapes"]]
    assert arts.count("curlew") == 18 and arts.count("reed") == 60 and arts.count("carrots") == 6 and "note" in arts
    assert {tuple(sh["when"]) for sh in coast["shapes"] if sh.get("art") == "curlew"} == {("low-tide",), ("high-tide",)}
    assert any(sh.get("animate") == "spin" and sh["material"].get("beam") for sh in coast["shapes"]) and any(sh.get("animate") == "tide" for sh in coast["shapes"])
    assert {"resident", "resident-evening", "visitor", "flats", "wares-0", "back-wall"} <= {a["id"] for a in coast["anchors"]}
    inland = await build("neighbor", props=["beehives"])
    assert not any(sh.get("art") == "curlew" for sh in inland["shapes"]) and "flats" not in {a["id"] for a in inland["anchors"]}
    assert sum(sh.get("tip", {}).get("title") == "A beehive" for sh in inland["shapes"]) == 3 and "pine-tree" in inland["parts"]
    market = await build("market", props=["barrow", "crates", "well"])
    booths = [a for a in market["anchors"] if "booth" in a["tags"]]
    assert len(booths) == 6 and all("reserved" in a["tags"] for a in booths) and "well" in market["parts"]
    assert {tuple(sh["when"]) for sh in market["shapes"] if sh.get("material", {}).get("texture") == "stripes"} >= {("open", "booth-1"), ("shut", "booth-1"), ("open", "pip-stall"), ("no-pip-stall",)}
    assert [a["id"] for a in market["anchors"] if "pip" in a["tags"] and "stall" in a["tags"]][0] == "pip-stall" and market["camera"]["look"] == [0, 0.4, -3]
    harbour = await build("shop", coastal=True, props=["boats", "rope", "lanterns", "drawers"])
    assert sum(sh.get("tip", {}).get("title") == "A boat" for sh in harbour["shapes"]) == 2 and sum(sh["shape"] == "torus" for sh in harbour["shapes"]) == 3
    assert any(sh.get("when") == ["shut"] and sh.get("art") == "note" for sh in harbour["shapes"]) and [a["id"] for a in harbour["anchors"]][:4] == ["counter", "stock-0", "stock-1", "stock-2"]
    inland_shop = await build("shop")
    assert not any(sh.get("tip", {}).get("title") == "A boat" for sh in inland_shop["shapes"]) and not any(sh["shape"] == "torus" for sh in inland_shop["shapes"])
    lib = await build("library")
    assert {"reading", "browse", "table"} <= {a["id"] for a in lib["anchors"]} and lib["camera"]["at"] == [0, 13, 21]
    home = await build("home")
    ids = [a["id"] for a in home["anchors"]]
    assert ids[:6] == ["back-wall-by-window", "back-wall-over-bench", "back-wall-under-shelf", "bench", "floor", "yard"]
    assert {"plot-1", "plot-4", "clock-1", "shelf", "walkers", "seat", "workbench", "garden-path", "pip"} <= set(ids)
    assert all(("reserved" in a["tags"]) == (a["id"] not in ids[:6] and not a["id"].startswith("tree")) for a in home["anchors"])


def test_the_renderer_draws_live_elements_on_tagged_anchors():
    from pathlib import Path
    web = Path(M.__file__).resolve().parent.parent / "web" / "world"
    js = (web / "layout.js").read_text()
    for tag in ("finds", "counter", "stock", "booth", "pip-stall", "wares", "plot", "clock", "shelf", "walkers", "resident", "resident-evening",
                "resident-walk", "people", "crowd", "seat", "bed", "workbench", "reading", "garden-path", "browse", "visitor"):
        assert f'"{tag}"' in js, tag
    import re
    for cond in (c for c in G.CONDITIONS if not c.startswith("booth-")):                       # each one the renderer works out
        assert re.search(r'[\s{"]' + re.escape(cond) + r'"?[:,]', js), cond
    assert "`booth-${i + 1}`" in js and 'case "torus"' in js
    for token in ("$label", "$description", "$blurb", "$belongings", "$project", "$hours", "$note", "$resident", "$wares", "$stock", "$stall"):
        assert f'"{token}"' in js, token
    assert not (web / "templates").exists() and not (web / "anchors").exists()
