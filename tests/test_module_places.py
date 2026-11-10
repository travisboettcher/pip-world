"""Modules, step 6 (docs/DESIGN-modules.md, "The builder proposes places"): a new place written as a module enters the world the way
invented places do, and becomes real as the module describes it."""
import json

import pytest

from app import builder as B
from app import invented_places as invented
from app import layouts as L
from app import module_places as P
from app import modules as M
from tests.test_modules import NOW, modular
from tests.test_projects import make, report

NEW = {"label": "the old mill", "kind": "sight", "description": "An old water mill on the river. Its wheel is quiet now. People come to watch the water.",
       "distance": "near", "items": ["Watercress", "driftwood"], "setting": "riverside"}
LAYOUT = ('def on_build(ctx):\n    return {"shapes": [{"shape": "box", "size": [30, 2, 16], "at": [0, -1, -4], "faces": {"top": {"texture": "grass"},'
          ' "side": {"texture": "cliff"}}}], "anchors": [{"id": "pip", "type": "ground", "tags": ["pip"], "at": [0, 0, 0]}]}\n')


def man(name="old-mill", **new):
    return {"name": name, "kind": "place", "api": 1, "hooks": ["on_build"], "new": {**NEW, **new}}


def test_a_new_place_is_checked_and_keyed_like_any_mentioned_place(tmp_path):
    s, st, agent = modular(tmp_path)
    got = M.check_manifest(man(), "world", st)
    assert got["place"] == invented.key_for("the old mill") and got["new"] == {**NEW, "items": ["watercress", "driftwood"]}
    assert P.check_new({**NEW, "label": "Hollis's seed shop.", "kind": "shop", "opens": 9, "closes": 24})["label"] == "Hollis's seed shop"
    assert P.check_new({**NEW, "label": "the mill’s pond"})["label"] == "the mill's pond"
    shop = P.check_new({**NEW, "kind": "shop", "opens": 9, "closes": 17})
    assert (shop["opens"], shop["closes"]) == (9, 17) and "opens" not in P.check_new({**NEW, "opens": 9, "closes": 17})   # a sight keeps no hours

    def bad(**kw):
        with pytest.raises(M.Refused) as e:
            M.check_manifest(man(**kw), "world", st)
        return str(e.value)
    assert bad(label="x") == "`new.label` is the place's name as people say it: 3 to 40 letters (and spaces, digits, apostrophes, dashes)"
    assert bad(label="9 lives").startswith("`new.label`") and bad(label="a" * 41).startswith("`new.label`") and bad(label="the @mill").startswith("`new.label`")
    assert bad(kind="castle") == "`new.kind` is one of wild, yard, shop, market, sight"
    assert bad(description="short") == "`new.description` says what the place is like, in a sentence or three"
    assert bad(distance="very far") == "`new.distance` is near or far"
    assert bad(items=["a"] * 7) == "`new.items` is a list of up to 6 things that can be found there" and bad(items=[" "]).startswith("`new.items`")
    assert bad(setting="moon").startswith("`new.setting` is one of wood, heath")
    assert bad(kind="shop", opens=25) == "`new.opens` is an hour, 0 to 24" and bad(kind="shop", closes=True).startswith("`new.closes`")
    assert bad(label="the woods") == "there is already a place called 'the woods'"
    with pytest.raises(ValueError) as e:
        P.check_new("mill")
    assert str(e.value).startswith("`new` describes the place")
    assert P.check_new({k: v for k, v in NEW.items() if k != "distance"})["distance"] == "far"


@pytest.mark.asyncio
async def test_approved_someone_tells_pip_of_it_and_the_map_has_it(tmp_path):
    s, st, agent = modular(tmp_path)
    st.add_character("Oriel Vantosh", "neighbor", None, "a widow by the marsh", 0, 0)
    r = await M.propose(st, s, agent.runner, "world", man(), LAYOUT, "A mill for the river.", now=NOW)
    key = st.module(r["id"])["manifest"]["place"]
    assert r["report"]["clean"] and st.place_row(key) is None                                   # waiting: nobody knows of it yet
    await M.approve(st, s, agent.runner, r["id"], now=NOW)
    rec = st.place_row(key)
    assert rec["status"] == "heard" and rec["kind"] == "sight" and rec["distance"] == "near" and 12 <= rec["walk_minutes"] <= 20
    assert rec["mentions"] == [{"by": "Oriel Vantosh", "there": "An old water mill on the river.", "items": ["watercress", "driftwood"], "ts": NOW}]
    heard = next(e for e in st.events(10) if e["kind"] == "heard_of_place")["data"]
    assert heard == {"place": key, "by": "Oriel Vantosh", "there": "An old water mill on the river.", "distance": "near"}
    assert st.meta(P.LINK + key) == "old-mill" and json.loads(st.meta(f"scene:{key}"))["setting"] == "riverside"
    from app import places
    assert f"- Oriel Vantosh told you about {places.label(key)}: An old water mill on the river." in agent._perception("timer", [])
    assert key in {p["key"] for p in __import__("app.worldmap", fromlist=["x"]).snapshot(st, s, None, NOW)["places"]}
    assert P.introduce(st, st.module(r["id"]), NOW) is None                                     # once
    assert await L.step(st, s, agent.runner, NOW) == 1 and L.for_scene(st, key)


@pytest.mark.asyncio
async def test_first_arrival_makes_it_real_as_written_without_the_gm(tmp_path):
    s, st, agent = modular(tmp_path)
    r = await M.propose(st, s, agent.runner, "world", man(kind="shop", opens=8, closes=18, items=["brass wire", "string"]), LAYOUT, now=NOW)
    await M.approve(st, s, agent.runner, r["id"], now=NOW)
    key = st.module(r["id"])["manifest"]["place"]
    assert P.module_for(st, key)["id"] == r["id"]
    raw = P.design(st, key)
    assert raw == {"description": NEW["description"], "kind": "shop", "loot": [{"name": "brass wire", "kind": "material"}, {"name": "string", "kind": "material"}],
                   "opens": 8, "closes": 18}
    rec = await invented.realise(st, None, key, "the old mill", now=NOW)                         # no GM at all
    assert rec["status"] == "real" and rec["description"] == NEW["description"] and rec["hours"] == [8, 18] and rec["kind"] == "shop"
    assert {e[0] for e in rec["loot"]} >= {"brass wire", "string"}
    assert P.design(st, "nowhere") is None and P.module_for(st, "nowhere") is None


def test_who_tells_and_what_counts_as_existing(tmp_path):
    s, st, agent = modular(tmp_path)
    assert P.teller(st, "Mill") == "a passing traveller"
    st.add_character("Oriel", "neighbor", None, "x", 0, 0)
    st.add_character("Bran", "resident", None, "y", 0, 0, place="Saltholm")
    st.add_character("Gearwhistle", "companion", None, "z", 0, 0)
    names = {P.teller(st, k) for k in ("a", "b", "c", "d", "e", "f", "g", "h")}
    assert names == {"Oriel", "Bran"} and P.teller(st, "Mill") == P.teller(st, "Mill")
    assert P.exists(st, "the woods") and P.exists(st, "the garden") and not P.exists(st, "the old mill")
    assert P.first_sentence("One. Two.") == "One." and P.first_sentence("x" * 400) == invented.clip("x" * 400, invented.THERE_CHARS)


@pytest.mark.asyncio
async def test_a_revision_keeps_its_place_and_rejected_versions_dont_describe_it(tmp_path):
    s, st, agent = modular(tmp_path)
    r = await M.propose(st, s, agent.runner, "world", man(), LAYOUT, now=NOW)
    await M.approve(st, s, agent.runner, r["id"], now=NOW)
    key = st.module(r["id"])["manifest"]["place"]
    two = await M.propose(st, s, agent.runner, "world", man(description="An old water mill, its wheel turning again since spring."), LAYOUT, replaces=r["id"], now=NOW)
    assert "id" in two                                                                             # its own place isn't "already there"
    assert P.module_for(st, key)["id"] == r["id"]                                                 # the waiting version doesn't count yet
    other = await M.propose(st, s, agent.runner, "world", man(name="another-mill"), LAYOUT, now=NOW)
    assert other["error"] == "there is already a place called 'the old mill'"
    await M.approve(st, s, agent.runner, two["id"], now=NOW)
    assert P.module_for(st, key)["id"] == two["id"] and len([e for e in st.events(20) if e["kind"] == "heard_of_place"]) == 1
    st.update_module(two["id"], status="rejected")
    assert P.module_for(st, key)["id"] == r["id"]


# --- the builder proposes a place ----------------------------------------------------------------------------------------------
def place_draft(**kw):
    return report(**{"action": "propose", "module": "place", "name": "old mill", "reason": "The land has no river yet.", "label": "the old mill",
                     "place_kind": "sight", "description": NEW["description"], "distance": "near", "items": ["watercress"], "setting": "riverside",
                     "code": LAYOUT, **kw})


@pytest.mark.asyncio
async def test_the_builder_proposes_a_place_and_its_fix_can_change_its_fields(tmp_path):
    s, st, gm, agent = make(tmp_path, [place_draft(place_kind="fortress"), report(fits=True, why="ok"),
                                       report(code=LAYOUT, place_kind="sight", label="the old mill")],
                            modules="on", module_runner="local", module_builder="on")
    r = await B.night(st, s, agent.gm, agent.runner, NOW)
    m = st.module(r["module"])
    assert r["outcome"] == "proposed" and m["manifest"]["new"]["kind"] == "sight" and m["manifest"]["place"] == invented.key_for("the old mill")
    fix = gm.calls[2]["messages"][0]["content"]
    assert 'place_kind: "fortress"' in fix and "`new.kind` is one of wild, yard, shop, market, sight" in fix and "any of the place's fields you change" in fix
    assert "A new place, the old mill (fortress, riverside): " in gm.calls[1]["messages"][0]["content"]


def test_the_builders_page_lists_kinds_settings_textures_and_live_parts(tmp_path):
    s, st, agent = modular(tmp_path)
    text = B.api(st)
    for marker in ("PLACE_KINDS", "SETTINGS", "TEXTURES", "PARTS", "ANCHORS", "EVENT_KINDS"):
        assert marker not in text
    assert "sight (somewhere just to go and see" in text and "riverside" in text and "stripes" in text and "(none yet: no place for now)" in text
    from tests.test_modules import live
    tree = live(st, {"name": "tree", "kind": "part", "api": 1, "hooks": ["on_build"], "params": {"scale": 1}}, "x")
    st.update_module(tree["id"], reason="A tree.")
    assert "  tree (params {'scale': 1}): A tree." in B.api(st)
    assert B.place_manifest(LAYOUT, {"name": "m", "label": "the mill", "place_kind": "shop", "description": "d", "items": None, "setting": "town",
                                     "opens": 9}) == {"name": "m", "kind": "place", "api": 1, "hooks": ["on_build"],
                                                      "new": {"label": "the mill", "kind": "shop", "description": "d", "distance": "far", "items": [],
                                                              "setting": "town", "opens": 9}}


def test_the_renderer_sets_out_a_counter_and_its_keeper():
    from pathlib import Path
    js = (Path(M.__file__).resolve().parent.parent / "web" / "world" / "layout.js").read_text()
    assert 'const counter = tagged("counter")' in js and "keeper.stand(counter.at[0], 0, counter.at[2] - 0.9)" in js


@pytest.mark.asyncio
async def test_a_new_shop_is_heard_of_with_its_hours_and_scene(tmp_path):
    s, st, agent = modular(tmp_path)
    r = await M.propose(st, s, agent.runner, "world", man(name="hollis-shop", label="Hollis's seed shop", kind="shop", opens=8, closes=18, setting="town",
                                                          items=["tomato seed"]), LAYOUT, now=NOW)
    await M.approve(st, s, agent.runner, r["id"], now=NOW)
    key = st.module(r["id"])["manifest"]["place"]
    rec = st.place_row(key)
    assert key == "Hollis" and rec["hours"] == [8, 18] and rec["daylight_only"] == 0 and rec["aliases"] == [] and rec["core"] == invented.core("Hollis's seed shop")
    from app.looks import clean_scene
    assert json.loads(st.meta(f"scene:{key}")) == clean_scene({"setting": "town"}, key, "shop", NEW["description"])
    assert json.loads(st.meta(f"scene:{key}"))["setting"] == "town"
    sight = await M.propose(st, s, agent.runner, "world", man(name="old-mill"), LAYOUT, now=NOW)
    await M.approve(st, s, agent.runner, sight["id"], now=NOW)
    mill = st.place_row(st.module(sight["id"])["manifest"]["place"])
    assert mill["hours"] is None and mill["daylight_only"] == 1


def test_the_bounds_exactly():
    ok = lambda **kw: P.check_new({**NEW, **kw})
    assert ok(label="Ash")["label"] == "Ash" and ok(label="a" * 40)["label"] == "a" * 40
    assert ok(description="x" * 20)["description"] == "x" * 20 and ok(description="x" * 600)["description"] == invented.clip("x" * 600, 500)
    assert len(ok(items=["a", "b", "c", "d", "e", "f"])["items"]) == 6 and ok(items=["x" * 50])["items"] == [invented.clip("x" * 50, 40).lower()]
    assert ok(kind="shop", opens=0, closes=24)["opens"] == 0
    for kw in ({"label": "Ab"}, {"label": "a" * 41}, {"description": "x" * 19}, {"opens": -1, "kind": "shop"}):
        with pytest.raises(ValueError):
            ok(**kw)


def test_the_builders_place_fields_reach_the_manifest():
    got = B.place_manifest(LAYOUT, {"name": "m", "label": "the mill", "place_kind": "shop", "description": "d", "distance": "near",
                                    "items": ["flour"], "setting": "town", "opens": 9, "closes": 17})
    assert got["new"] == {"label": "the mill", "kind": "shop", "description": "d", "distance": "near", "items": ["flour"], "setting": "town",
                          "opens": 9, "closes": 17}
    with pytest.raises(M.sandbox.Rejected):
        B.place_manifest("import os", {"name": "m"})
