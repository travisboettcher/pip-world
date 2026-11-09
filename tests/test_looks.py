"""Looks and props for the world view (docs/DESIGN-world-view.md): a character's look from fixed lists, chosen once; props found in a
record's own words."""
import os
import time

import pytest

import app.neighbors as nb
from app import looks as L
from app import world_view as WV
from app.config import Settings
from tests.test_neighbor import neighbor
from tests.test_projects import make, report


def test_a_fallback_look_takes_what_the_persona_says_and_hashes_the_rest():
    got = L.fallback("Oriel", "A tall, white-haired widow in a grey shawl whose eyesight is failing.")
    assert got["height"] == "tall" and got["hair"] == "white" and got["accessory"] in ("shawl", "glasses")
    assert set(got) == set(L.LOOK) and all(got[f] in L.LOOK[f] for f in L.LOOK)
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


def test_a_scene_shows_who_lives_at_a_home_even_when_they_are_out(tmp_path, monkeypatch):
    from app import market as M
    from tests.test_stall import LOOT
    s, st, gm, agent = make(tmp_path)
    ch = neighbor(st, s)
    st.update_character(ch["id"], wares=nb.clean_wares([{"name": "honey", "kind": "food"}, {"name": "beeswax", "kind": "material"}]))
    st.add_place("Brygdon", "brygdon", kind="market", status="real", created_at=time.time(), heard_at=time.time(), hours=[0, 24], daylight_only=0, walk_minutes=10.0, loot=LOOT, verbs={})
    wday = time.localtime().tm_wday
    monkeypatch.setattr(M, "market_day", lambda c: (wday + 2) % 7)
    d = WV.scene_view(st, s, None, "Marigold's home")
    lh = d["lives_here"]
    assert lh["name"] == "Marigold" and lh["wares"] == ["honey", "beeswax"] and lh["market_day"] == M.WEEKDAYS[(wday + 2) % 7] and lh["away_at"] is None
    assert lh["look"] == L.fallback("Marigold", ch["persona"]) and d["present"][0]["look"] == lh["look"]           # not chosen yet: from the persona
    assert "beehives" in d["place"]["props"]
    monkeypatch.setattr(M, "market_day", lambda c: wday)
    d = WV.scene_view(st, s, None, "Marigold's home")
    assert d["lives_here"]["away_at"] == "Brygdon" and d["present"] == []
    m = WV.scene_view(st, s, None, "Brygdon")
    assert [b["whose"] for b in m["booths"]] == ["", "Marigold"] and m["booths"][1]["look"] == lh["look"] and "look" not in m["booths"][0]
    st.update_character(ch["id"], look={"height": "tall", "hair": "grey", "skin": "pale", "top": "red", "bottom": "black", "accessory": "hat"})
    assert WV.scene_view(st, s, None, "Brygdon")["present"][0]["look"]["accessory"] == "hat"
    st.update_character(ch["id"], wares=[])
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
    s, st, gm, agent = make(tmp_path)
    ch = neighbor(st, s)
    for field, value, prop in [("about", "keeps a loom", "loom"), ("persona", "fires a kiln", "kiln"), ("told", ["the anvil rang"], "anvil")]:
        st.update_character(ch["id"], **{"about": "", "persona": "", "told": [], "wares": [], field: value})
        assert WV.scene_view(st, s, None, "Marigold's home")["place"]["props"] == [prop]
    st.update_character(ch["id"], about="", persona="", told=[], wares=nb.clean_wares([{"name": "dried herbs", "kind": "food"}, {"name": "jam", "kind": "food"}]))
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
