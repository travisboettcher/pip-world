"""Happenings at their edges: every effect applied and described word for word, the world as the dice see it, and how a module's happening
is recorded (happenings.py)."""
import random
import time

import pytest

from app import happenings as H
from app import market
from app import modules as M
from app.config import Settings
from tests.test_happen import Writer
from tests.test_modules import NOW, live, modular, rule


def make(tmp_path, **kw):
    s, st, agent = modular(tmp_path, happenings="on", **kw)
    return s, st, agent


# --- applying each effect ---------------------------------------------------------------------------------------------------------------
def test_each_effect_is_applied(tmp_path):
    s, st, agent = make(tmp_path)
    H.apply_effects(st, [{"kind": "item", "name": "acorn", "qty": 3, "item_kind": "material", "description": "a nut", "attrs": {"x": 1}}], NOW)
    a = st.find_item("acorn")[0]
    assert (a["qty"], a["kind"], a["description"], a["attrs"]) == (3, "material", "a nut", {"x": 1})
    st.add_item("plums", 5, "food", "")
    st.add_item("plum stones", 9, "material", "")
    H.apply_effects(st, [{"kind": "food_loss", "name": "plums", "qty": 3}], NOW)
    assert st.find_item("plums", kind="food")[0]["qty"] == 2
    H.apply_effects(st, [{"kind": "food_loss", "name": "plums", "qty": 9}], NOW)
    assert st.find_item("plums", kind="food")[0]["qty"] == 1                    # one always stays
    H.apply_effects(st, [{"kind": "food_loss", "name": "plums", "qty": 1}, {"kind": "food_loss", "name": "figs", "qty": 1}], NOW)
    assert st.find_item("plums", kind="food")[0]["qty"] == 1 and st.find_item("plum stones")[0]["qty"] == 9
    st.add_item("pears", 2, "food", "")
    H.apply_effects(st, [{"kind": "food_loss", "name": "pears", "qty": 1}], NOW)
    assert st.find_item("pears")[0]["qty"] == 1


def test_a_price_turn_moves_the_booths_price(tmp_path):
    s, st, agent = make(tmp_path)
    H.apply_effects(st, [{"kind": "price", "place": "Saltholm", "item": "Tomatoes", "units": -3}], NOW)
    assert market.local(st, "Saltholm", "tomatoes", NOW) == pytest.approx((1 - market.PRICE_STEP) ** 3)
    assert market.local(st, "Brygdon", "tomatoes", NOW) == 1.0


def test_a_creation_stops_only_if_it_needs_tending(tmp_path):
    from tests.test_world_view import TIMEKEEPER
    s, st, agent = make(tmp_path)
    clock = st.add_creation("Gear Clock", "a clock", None, "sound", TIMEKEEPER, {})
    vase = st.add_creation("Vase", "a vase", None, "sound", {"capabilities": {}, "quirks": []}, {})
    H.apply_effects(st, [{"kind": "creation_stop", "id": clock["id"], "part": {"name": "spring", "qty": 1}},
                         {"kind": "creation_stop", "id": vase["id"]}, {"kind": "creation_stop", "id": 999}], NOW)
    rt = {c["name"]: c["runtime"] for c in st.creations()}
    assert rt["Gear Clock"] == {"halted_at": NOW, "needs_part": {"name": "spring", "qty": 1}} and rt["Vase"] == {}
    H.apply_effects(st, [{"kind": "creation_stop", "id": clock["id"]}], NOW + 5)
    assert st.creations()[0]["runtime"] == {"halted_at": NOW + 5, "needs_part": {"name": "spring", "qty": 1}}


def test_news_of_a_neighbor_goes_into_their_life(tmp_path):
    s, st, agent = make(tmp_path)
    ch = st.add_character("Oriel", "neighbor", None, "x", 60, NOW)
    st.add_character("Oriel", "creation", None, "x", 60, NOW)
    st.update_character(ch["id"], life=[f"thing {i}" for i in range(5)])
    H.apply_effects(st, [{"kind": "news", "name": "Oriel"}], NOW, "A new roof " + "x" * 300)
    life = st.characters("neighbor")[0]["life"]
    assert len(life) == 5 and life[:4] == ["thing 1", "thing 2", "thing 3", "thing 4"] and life[4].startswith("A new roof") and len(life[4]) <= 200
    H.apply_effects(st, [{"kind": "news", "name": "Oriel"}], NOW, "")
    H.apply_effects(st, [{"kind": "news", "name": "Nobody"}], NOW, "x")
    assert st.characters("neighbor")[0]["life"] == life


# --- describing each effect ---------------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("e,text", [
    ({"kind": "coins", "delta": 3}, "You find 3 coins."),
    ({"kind": "coins", "delta": 1, "gift": True}, "You are given 1 coin."),
    ({"kind": "coins", "delta": -2}, "You lose 2 coins."),
    ({"kind": "item", "name": "acorns", "qty": 2}, "You find 2 acorns."),
    ({"kind": "item", "name": "acorns", "qty": 1, "gift": True}, "You are given 1 acorn."),
    ({"kind": "creation_stop", "name": "Gear Clock", "part": {"name": "spring", "qty": 1}}, "Your Gear Clock stops; it needs 1 spring to mend, then tending."),
    ({"kind": "creation_stop", "name": "Gear Clock", "part": None}, "Your Gear Clock stops; it needs tending."),
    ({"kind": "news", "name": "Oriel"}, "You hear news of Oriel."),
    ({"kind": "food_loss", "name": "plums", "qty": 3}, "You lose 3 plums."),
    ({"kind": "price", "item": "tomatoes", "place": "Saltholm", "units": 6}, "Tomatoes fetches about 27% more at Saltholm for now."),
    ({"kind": "price", "item": "tomatoes", "place": "Saltholm", "units": 1}, "Tomatoes fetches about 4% more at Saltholm for now."),
    ({"kind": "price", "item": "tomatoes", "place": "Saltholm", "units": -6}, "Tomatoes fetches about 22% less at Saltholm for now."),
    ({"kind": "price", "item": "tomatoes", "place": "Saltholm", "units": -1}, "Tomatoes fetches about 4% less at Saltholm for now."),
    ({"kind": "request", "module": "garden"}, ""),
])
def test_each_effect_in_words(e, text):
    assert H.describe(e) == text


def test_an_unknown_effect_is_an_error():
    with pytest.raises(ValueError, match="^unknown effect 'odd'$"):
        H.describe({"kind": "odd"})


# --- the world as the dice see it -----------------------------------------------------------------------------------------------------------
def test_the_world_as_the_dice_see_it(tmp_path):
    s, st, agent = make(tmp_path, happenings_seasons=False)
    st.add_item("plums", 2, "food", "")
    st.add_item("figs", 7, "food", "")
    st.add_item("needle file", 1, "tool", "")
    st.add_character("Oriel", "neighbor", None, "x", 60, NOW)
    st.add_character("Gear", "creation", None, "x", 60, NOW)
    now = time.time()
    st.add_place("Saltholm", "saltholm", kind="shop", status="real", created_at=now, heard_at=now, hours=[0, 24], daylight_only=0,
                 walk_minutes=10.0, loot=[["brass wire", "material", 20, [1, 2], "wire", {}]], verbs={"buy": ["buy", None]}, blurb="a shop")
    st.add_place("Hollin", "hollin", kind="wild", status="heard", created_at=now, heard_at=now, hours=None, daylight_only=0, walk_minutes=20.0,
                 loot=[], verbs={})
    a = live(st, rule(name="pots", hooks=["on_request"], answers={"grow": "x"}), "x")
    st.update_module(a["id"], facts={"names": ["beans", 3]})
    b = live(st, rule(name="gone", hooks=["on_request"], answers={"dig": "x"}), "x")
    st.update_module(b["id"], facts={"names": ["moles"]}, status="disabled")
    w = H.world(st, s, now)
    assert [f["name"] for f in w["foods"]][:2] == ["figs", "plums"] and all(f["kind"] == "food" for f in w["foods"])
    assert [b["key"] for b in w["booths"]] == ["Saltholm"] and w["neighbors"] == ["Oriel"] and "needle file" in w["tools"]
    assert "Saltholm" in w["places"] and "Hollin" not in w["places"] and all(isinstance(p, str) for p in w["places"])
    assert w["known"] == ["beans"] and w["answers"] == {"pots": ["grow"]} and w["season"] is None and w["now"] == now
    assert {"beans", "saltholm", "figs", "oriel", "needle file"} <= H.world_names(w)
    s2 = Settings(**{**s.__dict__, "happenings_seasons": True, "hemisphere": "south"})
    assert H.world(st, s2, NOW)["season"] == H.season_of(NOW, "south") != H.season_of(NOW, "north")


def test_world_names_without_the_optional_parts():
    w = {"neighbors": ["Ann"], "creations": [], "foods": [], "tools": [], "booths": []}
    assert H.world_names(w) == {"ann"}


# --- what a module can propose, at its edges -----------------------------------------------------------------------------------------------
def test_intents_at_their_edges(monkeypatch):
    from app import gathering
    from tests.test_happenings import w
    monkeypatch.setattr(gathering, "loot", lambda: {"woods": [("acorn", "material", 1, (1, 1), "a nut", {})],
                                                     "junkyard": [("cog", "material", 1, (1, 1), "a cog", {})]})
    rng = random.Random(1)
    assert H._intent(w(), "good", "minor", {"kind": "item", "name": "cog"}, rng).effects[0]["name"] == "cog"
    with pytest.raises(ValueError, match="^nothing called gold is found in this world; leave the name out, or use one of: acorn, cog$"):
        H._intent(w(), "good", "minor", {"kind": "item", "name": "gold"}, rng)
    with pytest.raises(ValueError, match=r"^`args` is an object$"):
        H._intent(w(), "good", "minor", {"kind": "request", "module": "a", "what": "b", "args": []}, rng)
    many = {"answers": {"pots": ["grow", "dig"], "bees": ["swarm"]}}
    with pytest.raises(ValueError, match="answers: pots: grow, dig; bees: swarm$"):
        H._intent(many, "good", "minor", {"kind": "request", "module": "x", "what": "y"}, rng)
    plan = H._intent({**w(), "stoppable": [{"id": 1, "name": "Gear Clock"}]}, "bad", "major", {"kind": "stop", "creation": "gear clock", "mend": True}, rng)
    assert plan.names == ["Gear Clock", plan.effects[0]["part"]["name"]]


def test_a_happenings_shape_at_its_edges():
    H.shape({"category": "fog", "tone": "good", "about": "x" * 300})
    with pytest.raises(ValueError, match="`about` is a line of up to 300"):
        H.shape({"category": "fog", "tone": "good", "about": "x" * 301})


# --- recording a module's happening -----------------------------------------------------------------------------------------------------------
TELLER = '''
def on_request(ctx):
    r = ctx["request"]
    if r["apply"]:
        return {"store": {"log": {"applied": {"severity": r["severity"]}}}, "reply": "done"}
    return {"store": {"log": {"asked": {"apply": r["apply"]}}}, "reply": r["args"].get("say", "Pot 1 grows")}
'''


async def test_a_modules_happening_is_recorded_with_what_it_carries(tmp_path):
    s, st, agent = make(tmp_path)
    live(st, rule(name="pots", hooks=["on_request"], proposes=["store"], answers={"grow": "x"}), TELLER)
    for i in range(6):
        st.add_happening(ts=time.time() - 2 * 86400 - i, slot=f"old{i}", category="fog", tone="neutral", severity="minor", lens="joy", seed="s", context={},
                         effects=[], effects_line="", meaning={}, text="t", title=f"Old {i}", author="template", status="resolved")
    asker = live(st, rule(name="porch", proposes=["happen"]), "x")
    turn = {"category": "garden", "tone": "good", "severity": "major", "names": ["Oriel"], "effects": [{"kind": "request", "module": "pots", "what": "grow"}]}
    st.add_character("Oriel", "neighbor", None, "x", 60, NOW)
    st.update_module(asker["id"], happen=[turn])
    gm = Writer()
    made = await H.from_modules(st, s, gm)
    assert made is True, [e["data"] for e in st.events(5) if e["kind"] == "happening_dropped"]
    assert len(gm.calls[0][4]["names"]) >= 1 and len(gm.calls) == 1
    h = st.happenings(1)[0]
    assert h["context"]["names"] == ["Oriel"] and "night" not in h["context"] and h["effects_line"] == "(Pot 1 grows.)"
    assert h["meaning"]["amount"] + (h["meaning"]["jolt"]) == H.lens_amount("good", "major")
    assert st.store("pots")["log"] == {"asked": {"apply": False}, "applied": {"severity": "major"}}


async def test_only_live_modules_happenings_are_written_and_each_counts(tmp_path):
    s, st, agent = make(tmp_path)
    gift = {"category": "kindness", "tone": "good", "severity": "minor", "effects": [{"kind": "coins", "gift": True}]}
    off = live(st, rule(name="off", proposes=["happen"]), "x")
    st.update_module(off["id"], happen=[gift], status="disabled")
    assert await H.from_modules(st, s, Writer()) is False and st.module(off["id"])["happen"] == [gift]
    one = live(st, rule(name="one", proposes=["happen"]), "x")
    two = live(st, rule(name="two", proposes=["happen"]), "x")
    st.update_module(one["id"], happen=[gift])
    st.update_module(two["id"], happen=[gift])                                 # the second can't: the first hasn't been taken in
    assert await H.from_modules(st, s, Writer(), time.time()) is True
    ev = next(e["data"] for e in st.events(5) if e["kind"] == "happening_dropped")
    assert ev["module"] == "two" and ev["reason"] == "Pip hasn't taken in the last one yet"


async def test_the_same_happening_comes_out_the_same(tmp_path):
    lenses = []
    for d in ("a", "b"):
        (tmp_path / d).mkdir()
        s, st, agent = make(tmp_path / d)
        st.set_meta(happenings_salt="fixed")
        m = live(st, rule(name="porch", proposes=["happen"]), "x")
        await H.from_module(st, s, Writer(), "porch", {"category": "fog", "tone": "neutral"}, NOW)
        lenses.append(st.happenings(1)[0]["lens"])
    assert lenses[0] == lenses[1]


async def test_a_request_line_is_kept_short_and_ends_a_sentence(tmp_path):
    s, st, agent = make(tmp_path)
    live(st, rule(name="pots", hooks=["on_request"], proposes=["store"], answers={"grow": "x"}), TELLER)
    c = {"tone": "good", "severity": "minor"}
    e = {"module": "pots", "what": "grow", "args": {"say": "It grows!"}}
    assert await H._ask(st, s, e, c, False) == "It grows!"
    assert await H._ask(st, s, {**e, "args": {"say": "It grows"}}, c, False) == "It grows."
    assert await H._ask(st, s, {**e, "args": {"say": "b" * 200}}, c, False) == "b" * 200 + "."       # a full line still ends a sentence


def test_world_names_include_the_real_places():
    w = {"neighbors": [], "creations": [], "foods": [], "tools": [], "booths": [], "places": ["the Old Mill"]}
    assert H.world_names(w) == {"the old mill"}
