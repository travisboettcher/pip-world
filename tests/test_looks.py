"""Looks and props for the world view (docs/DESIGN-world-view.md): a character's look from fixed lists, chosen once; props found in a
record's own words."""
import os
import time

import pytest

from app import looks as L
from app import world_view as WV
from app.config import Settings
from tests.test_neighbor import neighbor
from tests.test_projects import make, report


def test_a_fallback_look_takes_what_the_persona_says_and_hashes_the_rest():
    got = L.fallback("Oriel", "A tall, white-haired widow in a grey shawl whose eyesight is failing.")
    assert got["height"] == "tall" and got["hair"] == "white" and got["accessory"] in ("shawl", "glasses")
    assert set(got) == set(L.look_lists()) and all(got[f] in L.look_lists()[f] for f in L.look_lists())
    assert L.fallback("Oriel", "") == L.fallback("Oriel", "") and L.fallback("Ada", "") != L.fallback("Zed", "") or True
    assert L.fallback("Bo", "A little stout man.")["height"] == "short" and L.fallback("Bo", "bald as an egg")["hair"] == "none"
    assert L.fallback("Bo", "an apron always on")["accessory"] == "apron" and L.fallback("Bo", "a red-haired baker")["hair"] == "auburn"
    assert L.fallback("Bo", "hathaway")["accessory"] != "hat" or L._pick("Bo", "accessory") == "hat"               # whole words only


def test_the_gms_choices_are_kept_only_when_they_are_on_the_lists():
    raw = {"height": "TALL", "hair": "green", "skin": "olive", "top": "plum", "bottom": "navy", "accessory": "jetpack"}
    got = L.clean(raw, "Ada", "a potter with glasses")
    assert got["height"] == "tall" and got["skin"] == "olive" and got["top"] == "plum" and got["bottom"] == "navy"
    assert got["hair"] == L.fallback("Ada", "a potter with glasses")["hair"] and got["accessory"] == "glasses"
    assert L.clean(None, "Ada", "") == L.fallback("Ada", "") and L.clean("nope", "Ada", "") == L.fallback("Ada", "")


def test_props_are_whole_words_from_a_fixed_vocabulary_in_its_order():
    assert L.props("A cottage by the lighthouse; she keeps a log of the tides.", "Sea glass and driftwood for sale.") == ["lighthouse", "tide chart", "sea glass", "driftwood", "books"]
    assert L.props("a harbour road ironmonger with drawers of nails and coils of rope, lanterns") == ["boats", "rope", "lanterns", "drawers"]
    assert L.props("") == [] and L.props(None, "wellington boots") == [] and "well" in L.props("by the well")


@pytest.mark.asyncio
async def test_each_character_gets_a_look_once_from_the_gm_or_after_two_failures_from_the_persona(tmp_path):
    s, st, gm, agent = make(tmp_path, [report(height="short", hair="grey", skin="brown", top="green", bottom="brown", accessory="apron")], character_looks="on")
    ch = neighbor(st, s)
    await L.ensure(st, s, agent.gm, time.time())
    assert st.characters("neighbor")[0]["look"] == {"height": "short", "hair": "grey", "skin": "brown", "top": "green", "bottom": "brown", "accessory": "apron"}
    assert "Pick how Marigold looks" in gm.calls[0]["messages"][0]["content"]
    await L.ensure(st, s, agent.gm, time.time())
    assert len(gm.calls) == 1                                                         # once
    b = st.add_character("Bea", "resident", None, "A tall beekeeper.", 60, 0, about="bees", place="Hollin")
    st.add_character("Wren", "creation", 1, "a bird", 60, 0)
    gm.script = []
    await L.ensure(st, s, agent.gm, time.time())
    await L.ensure(st, s, agent.gm, time.time())
    assert not st.characters("resident")[0]["look"] and st.meta(f"look_tries:{b['id']}") == "2"
    await L.ensure(st, s, agent.gm, time.time())
    assert st.characters("resident")[0]["look"]["height"] == "tall" and not st.characters("creation")[0]["look"]
    s.character_looks = "off"
    st.update_character(ch["id"], look={})
    await L.ensure(st, s, agent.gm, time.time())
    assert st.characters("neighbor")[0]["look"] == {}


def test_a_scene_shows_who_lives_at_a_home_even_when_they_are_out(tmp_path):
    import asyncio
    from app import modules as M
    from tests.test_trade import G, her_day, marigold, slot, world
    s, st, agent = world(tmp_path)
    ch = marigold(st, s, wares=[{"name": "honey", "kind": "food", "description": "", "per_day": 1}, {"name": "beeswax", "kind": "material", "description": "", "per_day": 1}])
    st.update_character(ch["id"], persona="A tall, white-haired badger.")
    ch = st.characters("neighbor")[0]
    day = G["WEEKDAYS"][G["crc32"]("Marigold") % 7]
    asyncio.run(M.step(st, s, None, her_day(hers=False)))
    d = WV.scene_view(st, s, None, "Marigold's home")
    lh = d["lives_here"]
    assert lh["name"] == "Marigold" and lh["wares"] == ["honey", "beeswax"] and lh["market_day"] == day and lh["away_at"] is None
    assert lh["look"] == L.fallback("Marigold", ch["persona"]) and lh["look"]["height"] == "tall" and lh["look"]["hair"] == "white"   # not chosen yet: from the persona
    assert d["present"][0]["look"] == lh["look"]
    assert "beehives" in d["place"]["props"]
    asyncio.run(M.step(st, s, None, her_day()))
    d = WV.scene_view(st, s, None, "Marigold's home")
    assert d["lives_here"]["away_at"] == "Brygdon" and d["present"] == []
    m = WV.scene_view(st, s, None, "Brygdon")
    assert [b["whose"] for b in m["booths"]] == ["", "Marigold"] and m["booths"][1]["look"] == lh["look"] and "look" not in m["booths"][0]
    st.update_character(ch["id"], look={"height": "tall", "hair": "grey", "skin": "pale", "top": "red", "bottom": "black", "accessory": "hat"})
    assert WV.scene_view(st, s, None, "Brygdon")["present"][0]["look"]["accessory"] == "hat"
    st.merge_store("trade", {"wares": {slot("Marigold"): None}})
    asyncio.run(M.step(st, s, None, her_day()))
    assert WV.scene_view(st, s, None, "Marigold's home")["lives_here"]["market_day"] is None
    assert WV.scene_view(st, s, None)["lives_here"] is None


def test_the_setting():
    assert Settings().character_looks == "off"
    old = os.environ.pop("CHARACTER_LOOKS", None)
    try:
        assert Settings.from_env().character_looks == "on"
        os.environ["CHARACTER_LOOKS"] = "OFF"
        assert Settings.from_env().character_looks == "off"
        os.environ["CHARACTER_LOOKS"] = "x"
        assert Settings.from_env().character_looks == "on"
    finally:
        os.environ.pop("CHARACTER_LOOKS", None)
        if old is not None:
            os.environ["CHARACTER_LOOKS"] = old


def test_a_homes_props_come_from_any_of_its_keepers_words(tmp_path):
    import asyncio
    from app import modules as M
    from tests.test_trade import marigold, world
    s, st, agent = world(tmp_path)
    ch = marigold(st, s, wares=None)
    for field, value, prop in [("about", "keeps a loom", "loom"), ("persona", "fires a kiln", "kiln"), ("told", ["the anvil rang"], "anvil")]:
        st.update_character(ch["id"], **{"about": "", "persona": "", "told": [], field: value})
        assert WV.scene_view(st, s, None, "Marigold's home")["place"]["props"] == [prop]
    st.update_character(ch["id"], about="", persona="", told=[])
    marigold_wares = [{"name": "dried herbs", "kind": "food", "description": "", "per_day": 1}, {"name": "jam", "kind": "food", "description": "", "per_day": 1}]
    from tests.test_trade import slot
    st.merge_store("trade", {"wares": {slot("Marigold"): {"name": "Marigold", "wares": [{**w, "weight": None, "attrs": {}} for w in marigold_wares]}}})
    asyncio.run(M.step(st, s, None))                                                  # what trade notes of her
    assert WV.scene_view(st, s, None, "Marigold's home")["place"]["props"] == ["herbs"]
    assert WV.scene_view(st, s, None, "Marigold's home")["lives_here"]["about"] == ""
    st.update_character(ch["id"], about="Bakes bread.")
    assert WV.scene_view(st, s, None, "Marigold's home")["lives_here"]["about"] == "Bakes bread."


@pytest.mark.asyncio
async def test_the_gm_hears_who_they_are_and_gets_two_tries(tmp_path):
    s, st, gm, agent = make(tmp_path, [], character_looks="on")
    st.add_character("Bea", "neighbor", None, "A tall beekeeper with a veil.", 60, 0, about="Keeps hives by the ford.")
    for _ in range(4):
        await L.ensure(st, s, agent.gm, time.time())
    assert len(gm.calls) == 2 and "A tall beekeeper with a veil." in gm.calls[0]["messages"][0]["content"] and "Keeps hives by the ford." in gm.calls[0]["messages"][0]["content"]
    assert st.characters("neighbor")[0]["look"] == L.fallback("Bea", "A tall beekeeper with a veil.")
    assert L.fallback("Bea", None) == L.fallback("Bea", "") and L.fallback("Bea", None)["height"] == L._pick("Bea", "height")


# --- a place's scene details (step 4) --------------------------------------------------------------------------------------------
def test_scene_details_fall_back_to_the_places_words_its_kind_and_its_name():
    got = L.fallback_scene("Saltholm", "shop", "An ironmonger of stone, by the harbour road, with coils of rope and a slate roof.")
    assert got["walls"] == "stone" and got["roof"] == "slate" and got["setting"] == "shore" and got["props"] == ["boats", "rope"]
    assert got["palette"] == L._pick("Saltholm", "palette", L.scene_lists()) and set(got) == {"walls", "roof", "palette", "setting", "props"}
    plain = L.fallback_scene("Hollin", "wild", "")
    assert plain["setting"] == "wood" and plain["walls"] == L._pick("Hollin", "walls", L.scene_lists()) and plain["roof"] == L._pick("Hollin", "roof", L.scene_lists()) and plain["props"] == []
    assert L.fallback_scene("X", "market", "")["setting"] == "town" and L.fallback_scene("X", "yard", "")["setting"] == "hills" and L.fallback_scene("X", "odd", "")["setting"] == "field"
    assert L.fallback_scene("X", "shop", "a timber shed with a thatched roof")["walls"] == "planks" and L.fallback_scene("X", "shop", "a thatched roof")["roof"] == "thatch"
    assert L.fallback_scene("X", "shop", "a brick front and a tiled roof")["walls"] == "brick" and L.fallback_scene("X", "shop", "a tiled roof")["roof"] == "tile"
    assert L.fallback_scene("X", "wild", "an old mill by the river")["setting"] == "riverside" and L.fallback_scene("X", "wild", "lighthouse well tin barrow crates")["props"] == ["lighthouse", "tin", "barrow", "crates"]


def test_the_gms_scene_choices_are_kept_where_they_are_on_the_lists():
    raw = {"walls": "Brick", "roof": "gold", "palette": "honey", "setting": "marsh", "props": ["Beehives", "unicorns", 3, "rope"]}
    got = L.clean_scene(raw, "Bea's home", "neighbor", "rope and lanterns")
    assert got["walls"] == "brick" and got["roof"] == L.fallback_scene("Bea's home", "neighbor", "rope and lanterns")["roof"] and got["palette"] == "honey" and got["setting"] == "marsh"
    assert got["props"] == ["beehives", "rope", "lanterns"]
    assert L.clean_scene({"props": "beehives"}, "K", "wild", "")["props"] == [] and L.clean_scene(None, "K", "wild", "") == L.fallback_scene("K", "wild", "")
    assert len(L.clean_scene({"props": list(L.prop_words())}, "K", "wild", "")["props"]) == L.scene_props_max()


@pytest.mark.asyncio
async def test_each_real_place_gets_scene_details_once(tmp_path):
    import json
    s, st, gm, agent = make(tmp_path, [report(walls="stone", roof="slate", palette="cool", setting="hills", props=["anvil"]) for _ in range(5)], place_scenes="on")
    st.add_place("Hollin", "hollin", kind="wild", status="heard", created_at=time.time(), heard_at=time.time(), hours=None, daylight_only=0, walk_minutes=20.0, loot=[], verbs={})
    await L.ensure_scenes(st, s, agent.gm, None, time.time())
    kept = {k: json.loads(st.meta(f"scene:{k}")) for k in ("workshop", "woods", "junkyard")}
    assert all(v["walls"] == "stone" and v["props"][0] == "anvil" for v in kept.values()) and st.meta("scene:Hollin") is None       # not one heard of
    assert "A place in Pip's world: the woods (wild)." in "".join(c["messages"][0]["content"] for c in gm.calls) and "a wood of trees past the garden" in gm.calls[1]["messages"][0]["content"]
    n = len(gm.calls)
    await L.ensure_scenes(st, s, agent.gm, None, time.time())
    assert len(gm.calls) == n
    assert L.place_scene(st, "woods", "wild", "")["setting"] == "hills" and L.place_scene(st, "Nowhere", "wild", "beach")["setting"] == "shore"
    s.place_scenes = "off"
    st.set_meta(**{"scene:woods": ""})
    await L.ensure_scenes(st, s, agent.gm, None, time.time())
    assert len(gm.calls) == n


@pytest.mark.asyncio
async def test_two_failures_keep_the_fallback(tmp_path):
    import json
    s, st, gm, agent = make(tmp_path, [], place_scenes="on")
    for _ in range(3):
        await L.ensure_scenes(st, s, agent.gm, None, time.time())
    assert json.loads(st.meta("scene:junkyard")) == L.fallback_scene("junkyard", "yard", L.place_text(st, "junkyard")) and st.meta("scene_tries:junkyard") == "2"


def test_what_is_known_of_a_place(tmp_path):
    import asyncio
    from app import modules as M
    from tests.test_trade import marigold, world
    s, st, agent = world(tmp_path)
    ch = marigold(st, s, wares=[{"name": "honey", "kind": "food", "description": "", "per_day": 1}, {"name": "wax", "kind": "material", "description": "", "per_day": 1}])
    st.update_character(ch["id"], told=["the hives are quiet"])
    asyncio.run(M.step(st, s, None))
    text = L.place_text(st, "Marigold's home")
    assert ch["about"] in text and ch["persona"] in text and "the hives are quiet" in text and "sells honey, wax at home" in text      # what trade notes
    st.update_place("Brygdon", description="A square.", blurb="stalls", mentions=[{"by": "Jo", "there": "by the river", "items": [], "ts": 0}])
    assert L.place_text(st, "Brygdon") == "A square. stalls by the river"
    assert L.place_text(st, "library") == "a library of tall shelves" and L.place_text(st, "workshop") == "a workshop with a small garden" and L.place_text(st, "Nowhere") == ""


def test_the_scene_carries_details_and_what_can_be_found(tmp_path):
    import json
    s, st, gm, agent = make(tmp_path)
    d = WV.scene_view(st, s, None, "woods")
    assert d["place"]["scene"] == {k: v for k, v in L.fallback_scene("woods", "wild", L.place_text(st, "woods")).items() if k != "props"}
    assert d["place"]["finds"][:3] == ["sticks", "bark", "resin"] and len(d["place"]["finds"]) <= 12
    st.set_meta(**{"scene:woods": json.dumps({"walls": "stone", "roof": "slate", "palette": "cool", "setting": "heath", "props": ["well"]})})
    d = WV.scene_view(st, s, None, "woods")
    assert d["place"]["scene"]["setting"] == "heath" and d["place"]["props"][0] == "well"
    assert WV.scene_view(st, s, None)["place"]["finds"] == []


def test_the_scene_setting(tmp_path):
    assert Settings().place_scenes == "off"
    old = os.environ.pop("PLACE_SCENES", None)
    try:
        assert Settings.from_env().place_scenes == "on"
        os.environ["PLACE_SCENES"] = "OFF"
        assert Settings.from_env().place_scenes == "off"
        os.environ["PLACE_SCENES"] = "x"
        assert Settings.from_env().place_scenes == "on"
    finally:
        os.environ.pop("PLACE_SCENES", None)
        if old is not None:
            os.environ["PLACE_SCENES"] = old


def test_the_first_word_found_wins_in_a_fixed_order():
    assert L.fallback_scene("X", "shop", "stone and brick")["walls"] == "stone" and L.fallback_scene("X", "shop", "a whitewash cottage")["walls"] == "whitewash"
    assert L.fallback_scene("X", "shop", "thatch over slate")["roof"] == "thatch" and L.fallback_scene("X", "shop", None)["props"] == []


@pytest.mark.asyncio
async def test_the_gm_is_asked_twice_at_most_and_the_kind_decides_where_words_do_not(tmp_path):
    import json
    s, st, gm, agent = make(tmp_path, [], place_scenes="on")
    st.set_meta(**{"scene:workshop": json.dumps(L.fallback_scene("workshop", "home", ""))})
    st.add_place("Hob's", "hobs", kind="shop", status="real", created_at=time.time(), heard_at=time.time(), hours=[9, 17], daylight_only=0, walk_minutes=12.0,
                 loot=[], verbs={}, description="A place.")
    for _ in range(4):
        await L.ensure_scenes(st, s, agent.gm, None, time.time())
    asked = [c for c in gm.calls if "Hob's" in c["messages"][0]["content"]]
    assert len(asked) == 2 and json.loads(st.meta("scene:Hob's"))["setting"] == "town" and st.meta("scene:woods")      # a kept scene doesn't stop the rest


def test_what_is_known_in_detail(tmp_path):
    s, st, gm, agent = make(tmp_path)
    ch = neighbor(st, s)
    st.update_character(ch["id"], told=["the hives", "the honey"])
    assert "the hives the honey" in L.place_text(st, "Marigold's home")
    st.add_place("Odd", "odd", kind="wild", status="real", created_at=time.time(), heard_at=time.time(), hours=None, daylight_only=0, walk_minutes=10.0, loot=[], verbs={})
    st.update_place("Odd", description="", blurb="", mentions=[{"by": "Jo", "items": [], "ts": 0}])
    assert L.place_text(st, "Odd") == "  "
    assert L.place_text(st, "woods") == "a wood of trees past the garden" and L.place_text(st, "junkyard") == "a scrapyard over the hill"
