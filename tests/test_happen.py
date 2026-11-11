"""Happenings a module proposes (0.28.0): the generic `happen` effect. A module says what kind of thing happens and what changes; the engine
sets every amount, checks every target, keeps the day's limits, writes the words and lets Pip take it as it takes any happening."""
import random
import time

import pytest

from app import happenings as H
from app import modules as M
from tests.test_happenings import plot, food, w
from tests.test_modules import NOW, live, modular, rule


def decide(p, world=None, seed=1, **kw):
    """H.decide against a stand-in world (no state)."""
    from unittest import mock
    with mock.patch.object(H, "world", lambda state, settings, now: world or w(**kw)):
        return H.decide(None, None, p, NOW, random.Random(seed))


def refused(p, **kw):
    with pytest.raises(ValueError) as e:
        decide(p, **kw)
    return str(e.value)


# --- the engine makes intents real -------------------------------------------------------------------------------------------
def test_a_good_turn_gives_by_its_size():
    d = decide({"category": "kindness", "tone": "good", "severity": "medium", "effects": [{"kind": "coins", "gift": True}],
                "about": "Oriel leaves a twist of paper on the step.", "names": ["Oriel Vantosh"]})
    (e,) = d["effects"]
    assert e["kind"] == "coins" and H.FOUND_COINS["medium"][0] <= e["delta"] <= H.FOUND_COINS["medium"][1] and e["gift"]
    assert d["tone"] == "good" and d["severity"] == "medium" and d["lens"] in H.LENS_USUAL["good"] + H.LENS_CROSS["good"]
    assert d["facts"] == {"about": "Oriel leaves a twist of paper on the step."} and d["names"] == ["Oriel Vantosh"]
    assert d["line"].startswith("(You are given ") and d["category"] == "kindness"
    item = decide({"category": "found", "tone": "good", "severity": "minor", "effects": [{"kind": "item", "name": "Bark"}]})["effects"][0]
    assert (item["name"], item["qty"], item["item_kind"]) == ("bark", 1, "material")
    any_item = decide({"category": "found", "tone": "good", "effects": [{"kind": "item"}]})["effects"][0]
    assert any_item["kind"] == "item" and any_item["item_kind"] in ("food", "seed", "material")


def test_a_bad_turn_takes_and_the_engine_picks_how_much():
    loss = decide({"category": "found", "tone": "bad", "severity": "major", "effects": [{"kind": "coins"}]})["effects"][0]
    assert loss == {"kind": "coins", "delta": -H.coin_loss(78, "major")}
    stop = decide({"category": "mishap", "tone": "bad", "severity": "major", "effects": [{"kind": "stop", "creation": "gear clock", "mend": True}]})
    assert stop["effects"][0]["name"] == "Gear Clock" and stop["effects"][0]["part"]["qty"] >= 1 and "Gear Clock" in stop["names"]
    medium = decide({"category": "mishap", "tone": "bad", "severity": "medium", "effects": [{"kind": "stop", "creation": "Gear Clock", "mend": True}]})
    assert medium["effects"][0]["part"] is None                                                   # only a major one needs mending
    crop = decide({"category": "garden", "tone": "bad", "severity": "medium", "effects": [{"kind": "crop", "plot": 1, "how": "time"}]})["effects"][0]
    assert crop["kind"] == "crop_time" and crop["minutes"] == -round(600 * H.SHIFT["medium"]) and crop["factor"] == 1 + H.SHIFT["medium"]
    ruin = decide({"category": "garden", "tone": "bad", "severity": "major", "effects": [{"kind": "crop", "plot": 1, "how": "ruin"}]})["effects"][0]
    assert ruin == {"kind": "crop_ruin", "plot": 1, "crop": "tomatoes"}
    yield_ = decide({"category": "garden", "tone": "good", "severity": "major", "effects": [{"kind": "crop", "plot": 1, "how": "yield"}]})["effects"][0]
    assert yield_["delta"] == H.YIELD_GOOD["major"]
    price = decide({"category": "market", "tone": "bad", "severity": "minor", "effects": [{"kind": "price", "place": "Saltholm", "item": "Tomatoes"}]})
    assert price["effects"][0] == {"kind": "price", "place": "Saltholm", "item": "tomatoes", "units": -H.PRICE_UNITS["minor"]}
    assert decide({"category": "body", "tone": "bad", "severity": "minor", "effects": [{"kind": "energy"}]})["effects"][0] == {"kind": "energy", "delta": -H.ENERGY["minor"]}
    assert decide({"category": "body", "tone": "good", "severity": "minor", "effects": [{"kind": "hunger"}]})["effects"][0] == {"kind": "hunger", "delta": -H.ENERGY["minor"]}
    assert decide({"category": "pantry", "tone": "bad", "severity": "medium", "effects": [{"kind": "food_loss"}]})["effects"][0]["name"] == "tomatoes"
    news = decide({"category": "neighbor", "tone": "good", "effects": [{"kind": "news", "name": "oriel vantosh"}]})
    assert news["effects"] == [{"kind": "news", "name": "Oriel Vantosh", "tone": "good"}]


def test_a_neutral_moment_changes_nothing_but_may_bring_back_a_memory():
    d = decide({"category": "atmosphere", "tone": "neutral", "severity": "major"})
    assert d["severity"] == "minor" and d["effects"] == [] and d["line"] == ""
    m = decide({"category": "memory", "tone": "neutral", "effects": [{"kind": "memory"}]})
    assert m["facts"]["memory"].startswith("Oriel taught me") and "Oriel" in m["names"]


@pytest.mark.parametrize("p,why", [
    ({"category": "x", "tone": "good"}, "`happen` is {category"),
    ({"category": "Kindness", "tone": "good"}, "`happen` is {category"),
    ({"category": "kindness", "tone": "great"}, "`happen` is {category"),
    ({"category": "kindness", "tone": "good", "severity": "huge"}, "`happen` is {category"),
    ("kindness", "`happen` is {category"),
    ({"category": "found", "tone": "good", "effects": [{"kind": "coins"}] * 3}, "`effects` is a list of up to 2"),
    ({"category": "found", "tone": "good", "effects": {"kind": "coins"}}, "`effects` is a list of up to 2"),
    ({"category": "found", "tone": "good", "about": "x" * 301}, "`about` is a line of up to 300"),
    ({"category": "found", "tone": "good", "names": "Oriel"}, "`about` is a line of up to 300"),
    ({"category": "found", "tone": "good", "names": ["Bartholomew"]}, "no one and nothing called Bartholomew is in Pip's world"),
    ({"category": "found", "tone": "good", "effects": [{"kind": "gold"}]}, "an effect's kind is one of coins, item"),
    ({"category": "found", "tone": "neutral", "effects": [{"kind": "coins"}]}, "a neutral happening changes nothing"),
    ({"category": "found", "tone": "good", "effects": [{"kind": "stop", "creation": "Gear Clock"}]}, "a good turn can't bring stop"),
    ({"category": "found", "tone": "bad", "effects": [{"kind": "item"}]}, "a bad turn can't bring item"),
    ({"category": "found", "tone": "good", "effects": [{"kind": "item", "name": "a diamond"}]}, "nothing called a diamond is found in this world"),
    ({"category": "found", "tone": "good", "effects": [{"kind": "coins"}, {"kind": "coins"}]}, "one effect of each kind"),
    ({"category": "garden", "tone": "good", "effects": [{"kind": "crop", "plot": 7}]}, "`plot` is the number of a plot with something growing"),
    ({"category": "garden", "tone": "good", "effects": [{"kind": "crop", "plot": 1, "how": "ruin"}]}, "only a major bad turn ruins a crop"),
    ({"category": "garden", "tone": "good", "effects": [{"kind": "crop", "plot": 1, "how": "grow"}]}, "`how` is time, yield or ruin"),
    ({"category": "market", "tone": "good", "effects": [{"kind": "price", "place": "Atlantis"}]}, "`place` is the key of a place that sells"),
    ({"category": "market", "tone": "good", "effects": [{"kind": "price", "place": "Saltholm", "item": "gold"}]}, "`item` is something sold at Saltholm"),
    ({"category": "mishap", "tone": "bad", "severity": "minor", "effects": [{"kind": "stop", "creation": "Gear Clock"}]}, "`creation` is one of Pip's running"),
    ({"category": "mishap", "tone": "bad", "severity": "major", "effects": [{"kind": "stop", "creation": "Vase"}]}, "`creation` is one of Pip's running"),
    ({"category": "neighbor", "tone": "good", "effects": [{"kind": "news", "name": "Nobody"}]}, "`name` is one of Pip's neighbors"),
])
def test_what_a_happening_cant_be_is_named(p, why):
    assert refused(p).startswith(why)


def test_the_world_as_it_is_limits_what_can_happen():
    assert refused({"category": "found", "tone": "bad", "effects": [{"kind": "coins"}]}, coins=0) == "Pip has no coins to lose"
    assert refused({"category": "body", "tone": "bad", "effects": [{"kind": "energy"}]}, low=True) == "Pip is too low already"
    assert refused({"category": "pantry", "tone": "bad", "effects": [{"kind": "food_loss"}]}, foods=[]).startswith("there is nothing to lose")
    assert refused({"category": "garden", "tone": "good", "effects": [{"kind": "crop", "plot": 1}]}, plots=[plot(left_min=0)]) == "that crop is as good as ripe"
    assert refused({"category": "garden", "tone": "bad", "effects": [{"kind": "crop", "plot": 1, "how": "yield"}]}, plots=[plot(yield_=1)]) == "that crop can't give any less"
    assert refused({"category": "memory", "tone": "good", "effects": [{"kind": "memory"}]}, diary_count=2) == "Pip has no old thought to come back to it"
    assert refused({"category": "market", "tone": "good", "effects": [{"kind": "price", "place": "Saltholm"}]}, foods=[],
                   booths=[{"key": "Saltholm", "loot": []}]).startswith("`item` is something sold")


# --- through a module ------------------------------------------------------------------------------------------------------------
class Writer:
    def __init__(self, title="A twist of paper", text="Someone has left a twist of paper on the step for you."):
        self.title, self.text, self.calls = title, text, []

    async def write_happening(self, category, tone, severity, lens, line, facts, recent):
        self.calls.append((category, tone, severity, line, facts))
        return {"title": self.title, "text": self.text}


GIFT = {"category": "kindness", "tone": "good", "severity": "minor", "effects": [{"kind": "coins", "gift": True}],
        "about": "A neighbor leaves something on the step.", "fallback": {"title": "Left for you", "text": "Something was left on the step for you."}}


def happy(tmp_path):
    s, st, agent = modular(tmp_path, happenings="on")
    m = live(st, rule(name="porch", proposes=["happen"]), "x")
    return s, st, agent, m


@pytest.mark.asyncio
async def test_a_module_proposes_a_happening_and_the_engine_writes_and_records_it(tmp_path):
    s, st, agent, m = happy(tmp_path)
    coins = st.coins()
    M.apply(st, m, M.plan(st, m, {"happen": GIFT}, NOW, "on_tick", s), NOW)
    assert st.module(m["id"])["happen"][0]["category"] == "kindness" and st.coins() == coins            # nothing yet: it's written first
    with pytest.raises(M.Refused) as e:
        M.plan(st, st.module(m["id"]), {"happen": GIFT}, NOW, "on_tick", s)
    assert str(e.value) == "its last happening is still being written"
    gm = Writer()
    assert await H.from_modules(st, s, gm, time.time()) is True
    h = st.happenings(1)[0]
    assert (h["category"], h["tone"], h["severity"], h["title"], h["status"]) == ("kindness", "good", "minor", "A twist of paper", "applied")
    assert gm.calls[0][4]["about"] == "A neighbor leaves something on the step." and st.coins() > coins
    assert next(e["data"] for e in st.events(5) if e["kind"] == "happening")["by"] == "porch" and st.module(m["id"])["happen"] == []
    assert M._budget(st.module(m["id"]), NOW)["happen"] == 1


@pytest.mark.asyncio
async def test_the_days_limits_and_pips_state_hold_for_module_happenings_too(tmp_path):
    s, st, agent, m = happy(tmp_path)
    M.apply(st, m, M.plan(st, m, {"happen": GIFT}, time.time(), "on_tick", s), time.time())
    await H.from_modules(st, s, Writer(), time.time())
    with pytest.raises(M.Refused) as e:
        M.plan(st, st.module(m["id"]), {"happen": GIFT}, time.time(), "on_tick", s)
    assert str(e.value) == "nothing can happen now: Pip hasn't taken in the last one yet"
    H.resolve(st, st.happenings(1)[0], "joy")
    st.update_agent(activity="sleeping")
    with pytest.raises(M.Refused) as e:
        M.plan(st, st.module(m["id"]), {"happen": GIFT}, time.time(), "on_tick", s)
    assert str(e.value) == "nothing can happen now: Pip is asleep or out walking"
    st.update_agent(activity="idle")
    s.happenings_max_per_day = 1
    assert H.room_for(st, s, time.time()) == "there have been 1 today already"
    s.happenings = "off"
    assert H.room_for(st, s, time.time()) == "happenings are off"
    with pytest.raises(M.Refused) as e:
        M.plan(st, st.module(m["id"]), {"happen": GIFT}, time.time(), "on_tick")
    assert str(e.value) == "nothing can happen now: happenings can't be checked here"
    assert "happen" not in M.PIP_PROPOSES


@pytest.mark.asyncio
async def test_a_happening_that_no_longer_fits_is_dropped_and_a_failed_text_falls_back(tmp_path):
    s, st, agent, m = happy(tmp_path)
    st.add_coins("pip", -st.coins())
    st.update_module(m["id"], happen=[{"category": "found", "tone": "bad", "effects": [{"kind": "coins"}]}])
    assert await H.from_modules(st, s, Writer(), time.time()) is False
    assert next(e["data"] for e in st.events(3) if e["kind"] == "happening_dropped") == {"module": "porch", "category": "found", "reason": "Pip has no coins to lose"}
    st.update_module(m["id"], happen=[GIFT])
    assert await H.from_modules(st, s, Writer(text="It was Bartholomew!"), time.time()) is True               # a name not offered: fallback
    h = st.happenings(1)[0]
    assert h["title"] == "Left for you" and h["text"].startswith("Something was left on the step for you.") and h["author"] == "template"
    H.resolve(st, h, "joy")
    st.update_module(m["id"], happen=[{"category": "odd sky", "tone": "neutral"}])
    await H.from_modules(st, s, None, time.time())
    assert st.happenings(1)[0]["title"] == "A moment"                                                        # no fallback given: by tone


def test_the_reads_a_happenings_module_needs(tmp_path):
    s, st, agent = modular(tmp_path, happenings="on")
    st.add_character("Oriel Vantosh", "neighbor", None, "a weaver", 60, NOW)
    from tests.test_world_view import clock
    clock(st)
    m = live(st, rule(reads=["people", "creations", "happenings", "pip"], params={"chance": 0.1, "severity": [50, 45, 5]}), "x")
    ctx = M.context(st, s, m, time.time())
    assert ctx["people"] == [{"name": "Oriel Vantosh", "kind": "neighbor"}] and ctx["params"] == {"chance": 0.1, "severity": [50, 45, 5]}
    assert ctx["creations"] == [{"name": "Gear Clock", "running": True, "tended": True}] and ctx["pip"]["coins"] == st.coins()
    assert ctx["happenings"] == {"recent": [], "today": 0, "room": "", "can_remember": False}
    with pytest.raises(M.Refused):
        M.check_manifest(rule(params={"a": [[1]]}), "world")
    with pytest.raises(M.Refused):
        M.check_manifest(rule(params={"a": list(range(9))}), "world")


# --- word for word -----------------------------------------------------------------------------------------------------------
def test_intents_word_for_word_at_their_limits():
    named = decide({"category": "kindness", "tone": "good", "severity": "minor", "effects": [{"kind": "item", "name": "bark", "gift": True}]})
    assert named["effects"] == [{"kind": "item", "name": "bark", "qty": 1, "item_kind": "material", "description": "curls of birch bark", "attrs": {},
                                 "gift": True}] and named["names"] == ["bark"]
    plain = decide({"category": "found", "tone": "good", "effects": [{"kind": "item", "name": "bark"}, {"kind": "coins"}]})
    assert "gift" not in plain["effects"][0] and "gift" not in plain["effects"][1]
    found = decide({"category": "found", "tone": "good", "effects": [{"kind": "item"}]}, seed=3)["effects"][0]
    assert set(found) == {"kind", "name", "qty", "item_kind", "description", "attrs"} and found["description"]
    kinds = {decide({"category": "found", "tone": "good", "effects": [{"kind": "item"}]}, seed=i)["effects"][0]["item_kind"] for i in range(80)}
    assert kinds == {"food", "seed", "material"}
    assert decide({"category": "found", "tone": "bad", "severity": "minor", "effects": [{"kind": "coins"}]}, coins=10)["effects"] == \
        [{"kind": "coins", "delta": -H.coin_loss(10, "minor")}] and H.coin_loss(10, "minor") == 1          # one coin is something to lose
    assert decide({"category": "pantry", "tone": "bad", "severity": "minor", "effects": [{"kind": "food_loss"}]}, foods=[food(qty=5)])["effects"][0]["name"] == "tomatoes"
    assert refused({"category": "pantry", "tone": "bad", "effects": [{"kind": "food_loss"}]}, foods=[food(qty=4)]).startswith("there is nothing")
    assert decide({"category": "body", "tone": "bad", "severity": "major", "effects": [{"kind": "hunger"}]})["effects"] == [{"kind": "hunger", "delta": H.ENERGY["major"]}]
    assert decide({"category": "body", "tone": "good", "severity": "medium", "effects": [{"kind": "energy"}]})["effects"] == [{"kind": "energy", "delta": H.ENERGY["medium"]}]
    assert refused({"category": "garden", "tone": "bad", "severity": "medium", "effects": [{"kind": "crop", "plot": 1, "how": "ruin"}]}) == "only a major bad turn ruins a crop"
    ruin = decide({"category": "garden", "tone": "bad", "severity": "major", "effects": [{"kind": "crop", "plot": 1, "how": "ruin"}]})
    assert ruin["names"] == ["tomatoes"]
    one = decide({"category": "garden", "tone": "good", "severity": "minor", "effects": [{"kind": "crop", "plot": 1}]}, plots=[plot(left_min=20)])
    assert one["effects"][0]["minutes"] == 1 and one["names"] == ["tomatoes"]                       # 5% of 20 minutes: one minute sooner
    assert refused({"category": "garden", "tone": "good", "severity": "minor", "effects": [{"kind": "crop", "plot": 1}]}, plots=[plot(left_min=9)]) == "that crop is as good as ripe"
    least = decide({"category": "garden", "tone": "bad", "severity": "major", "effects": [{"kind": "crop", "plot": 1, "how": "yield"}]}, plots=[plot(yield_=2)])
    assert least["effects"][0]["delta"] == -1 and least["names"] == ["tomatoes"]
    price = decide({"category": "market", "tone": "good", "severity": "medium", "effects": [{"kind": "price", "place": "Saltholm"}]}, foods=[])
    assert price["effects"] == [{"kind": "price", "place": "Saltholm", "item": "brass wire", "units": H.PRICE_UNITS["medium"]}] and price["names"] == ["Saltholm", "brass wire"]
    stop = decide({"category": "mishap", "tone": "bad", "severity": "medium", "effects": [{"kind": "stop", "creation": "Gear Clock"}]})
    assert stop["effects"] == [{"kind": "creation_stop", "id": 1, "name": "Gear Clock", "part": None}] and stop["names"] == ["Gear Clock"]
    assert decide({"category": "neighbor", "tone": "bad", "effects": [{"kind": "news", "name": "Oriel Vantosh"}]})["names"] == ["Oriel Vantosh"]
    assert decide({"category": "memory", "tone": "good", "effects": [{"kind": "memory"}]}, diary_count=H.MIN_DIARY)["effects"] == []
    assert refused({"category": "found", "tone": "bad", "effects": [{"kind": "item"}]}) == "a bad turn can't bring item"
    assert refused({"category": "found", "tone": "good", "effects": [{"kind": "food_loss"}]}) == "a good turn can't bring food loss"
    assert refused({"category": "found", "tone": "good", "effects": [{"kind": "x"}]}) == "an effect's kind is one of " + ", ".join(H.INTENTS)


@pytest.mark.asyncio
async def test_room_and_recording_word_for_word(tmp_path):
    s, st, agent, m = happy(tmp_path)
    t = time.time()
    st.start_session(0, 0, 10, t + 99999, kind="walk", target="woods")
    assert H.room_for(st, s, t) == "Pip is asleep or out walking"
    st.end_session()
    st.start_session(0, 0, 10, t + 99999, kind="work", target="x")
    assert H.room_for(st, s, t) == ""                                                               # working is fine
    st.end_session()
    s.happenings_max_per_day = 2
    st.add_happening(ts=H._today_start(t), slot="x", category="x", tone="good", severity="minor", lens="joy", seed="x", context={}, effects=[],
                     effects_line="", meaning={}, text="t", title="t", author="test", status="resolved")
    assert H.room_for(st, s, t) == ""                                                               # one at midnight counts: one of two
    st.update_module(m["id"], happen=[{**GIFT, "night": True}])
    gm = Writer()
    assert await H.from_modules(st, s, gm, t) is True
    h = st.happenings(1)[0]
    assert h["slot"] == f"module:porch:{int(t)}" and h["context"]["night"] is True and h["effects"][0]["gift"] is True
    assert H.room_for(st, s, t) == "Pip hasn't taken in the last one yet"
    two = live(st, rule(name="porch2", proposes=["happen"]), "x")
    H.resolve(st, h, "joy")
    s.happenings_max_per_day = 5
    st.update_module(two["id"], happen=[{"category": "odd sky", "tone": "neutral"}])
    st.update_module(m["id"], happen=[{"category": "odd sky", "tone": "neutral", "about": "x" * 400}])
    assert await H.from_modules(st, s, gm, t + 1) is True                                           # one dropped, one made: still true
    dropped = next(e["data"] for e in st.events(5) if e["kind"] == "happening_dropped")
    assert dropped["module"] == "porch" and dropped["reason"].startswith("`about` is a line") and len(dropped["category"]) <= 24
    st.update_module(m["id"], happen=[{"category": "c" * 30, "tone": "neutral"}])
    await H.from_modules(st, s, gm, t + 2)
    assert next(e["data"] for e in st.events(3) if e["kind"] == "happening_dropped")["category"] == "c" * 24
