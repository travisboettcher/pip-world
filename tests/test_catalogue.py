"""What a made thing can notice and do comes from its world (docs/DESIGN-engine-audit.md, C2): the engine's own sensors and helpers, then
the pack's catalogue (content.json), each saying what it watches or does in the engine's few words; the engine works out whether a watch
holds and whether a helper is any use, and offers the designer only what the world as it is can run."""
import time

import pytest

from app import creations as cr
from tests.test_garden import planted
from tests.test_modules import NOW, live, modular, rule


def test_the_catalogue_is_the_engines_then_the_worlds():
    assert list(cr.sensors()) == ["visitor", "dawn", "dusk", "crop_ripe", "hungry", "tired"]
    assert list(cr.helpers()) == ["find", "hurry_crops", "comfort"]
    assert cr.sensors()["crop_ripe"]["watches"] == "ready:garden" and "watches" not in cr.sensors()["visitor"]
    assert cr.helpers()["hurry_crops"] == {"help": "anything that helps the garden do better - guarding, watering, warming it - so crops ripen "
                                                   "sooner", "every": 60, "does": "request:garden:hurry", "when": "next:garden"}
    assert cr.helpers()["find"]["every"] == 360 and "does" not in cr.helpers()["find"]


def test_a_sensor_or_helper_is_offered_only_when_what_it_needs_is_in_the_world(tmp_path):
    s, st, agent = modular(tmp_path)
    assert cr.usable(st, {"help": "x"}) and cr.usable(st, {"watches": "low:energy"}) and cr.usable(st, {"does": "affect:hunger:-0.1"})
    assert not cr.usable(st, {"watches": "low:radiation"}) and not cr.usable(st, {"does": "affect:radiation:-0.1"})   # no such stat here
    assert not cr.usable(st, {"watches": "ready:garden"}) and not cr.usable(st, {"when": "next:garden"})                # no garden live
    assert not cr.usable(st, {"watches": "soon"}) and not cr.usable(st, {"does": "request:garden"}) and not cr.usable(st, {"does": "x"})
    menu = "\n".join(cr.menu(False, st))
    assert "crop_ripe" not in menu and "hurry_crops" not in menu and "hungry (Pip is hungry)" in menu and "comfort (" in menu
    planted(st, s, 1, "peas", 600)                                                      # the garden is live
    assert cr.usable(st, {"watches": "ready:garden"}) and cr.usable(st, {"does": "request:garden:hurry", "when": "next:garden"})
    assert not cr.usable(st, {"does": "request:garden:dig"})                          # something it doesn't answer
    menu = "\n".join(cr.menu(False, st))
    assert "crop_ripe (a crop in Pip's garden is ripe)" in menu and "hurry_crops (" in menu
    assert cr.menu(False, None) == cr.menu(False)                                     # no world given: everything


def test_whether_a_watch_holds_is_the_engines_to_say(tmp_path):
    s, st, agent = modular(tmp_path)
    noon = time.mktime(time.strptime("2026-11-15 12:00", "%Y-%m-%d %H:%M"))
    at = lambda h: noon + (h - 12) * 3600                                             # noqa: E731
    assert cr.watching(st, "dawn", at(6)) and not cr.watching(st, "dawn", at(7)) and cr.watching(st, "dusk", at(19))
    assert not cr.watching(st, "visitor", noon)
    st.add_inbox("hello", "Ada")
    assert cr.watching(st, "visitor", noon)
    st.update_agent(hunger=0.5, energy=0.9)
    assert not cr.watching(st, "low:hunger", noon) and not cr.watching(st, "low:energy", noon)
    st.update_agent(hunger=0.8, energy=0.25)                                         # exactly at the world's low_at counts
    assert cr.watching(st, "low:hunger", noon) and cr.watching(st, "low:energy", noon)
    assert not cr.watching(st, "low:radiation", noon) and not cr.watching(st, "nonsense", noon) and not cr.watching(st, None, noon)
    assert not cr.watching(st, "ready:garden", noon) and not cr.watching(st, "next:garden", noon)
    m = live(st, rule(name="pots"), "x")
    st.update_module(m["id"], standing={"title": "Pots", "lines": [], "ready": False, "next_at": NOW + 60})
    assert not cr.watching(st, "ready:pots", noon) and cr.watching(st, "next:pots", noon)
    st.update_module(m["id"], standing={"title": "Pots", "lines": [], "ready": True})
    assert cr.watching(st, "ready:pots", noon) and not cr.watching(st, "next:pots", noon)


def test_the_workings_read_what_the_engine_worked_out(tmp_path):
    s, st, agent = modular(tmp_path)
    st.update_agent(hunger=0.9)
    caps = {"sensor": {"condition": "hungry", "alert": "It whines."}, "helper": {"effect": "hurry_crops", "line": "It waters.", "every_minutes": 60},
            "periodic": {"lines": ["It hums."], "every_minutes": 60}}
    got = cr.at_work(st, caps, NOW)
    assert got["sensor"] == {"condition": "hungry", "alert": "It whines.", "on": True} and got["periodic"] == caps["periodic"]
    assert got["helper"] == {**caps["helper"], "does": "request:garden:hurry", "can": False}                 # nothing growing
    assert "on" not in caps["sensor"] and "can" not in caps["helper"]                                     # the spec itself is left alone
    assert cr.at_work(st, {"sensor": {"condition": "visitor", "alert": "x"}}, NOW)["sensor"]["on"] is False   # the engine's own watch
    assert cr.at_work(st, {"helper": {"effect": "gone", "line": "x", "every_minutes": 60}}, NOW)["helper"] == \
        {"effect": "gone", "line": "x", "every_minutes": 60, "does": "", "can": True}                    # no longer in the world: does nothing
    planted(st, s, 1, "peas", 600)
    assert cr.at_work(st, caps, NOW)["helper"]["can"] is True


@pytest.mark.parametrize("content,why", [
    ({"sensors": []}, "content.json `sensors` maps a name to {help, watches, ...}"),
    ({"helpers": {"purify": "cleans water"}}, "content.json helpers 'purify': needs a `help` line for the narrator"),
    ({"sensors": {"hurt": {"help": " "}}}, "content.json sensors 'hurt': needs a `help` line for the narrator"),
    ({"sensors": {"hurt": {"help": "x"}}}, "content.json sensors 'hurt': `watches` is ready:<module>, next:<module> or low:<stat>"),
    ({"sensors": {"hurt": {"help": "x", "watches": "low:Health"}}}, "content.json sensors 'hurt': `watches` is ready:<module>"),
    ({"helpers": {"purify": {"help": "x"}}}, "content.json helpers 'purify': `does` is request:<module>:<what> or affect:<stat>:<amount>"),
    ({"helpers": {"purify": {"help": "x", "does": "affect:radiation:lots"}}}, "content.json helpers 'purify': `does` is request:"),
    ({"helpers": {"purify": {"help": "x", "does": "affect:radiation:-0.1", "when": "always"}}},
     "content.json helpers 'purify': `when` is ready:<module>, next:<module> or low:<stat>"),
    ({"helpers": {"purify": {"help": "x", "does": "affect:radiation:-0.1", "every": 0}}},
     "content.json helpers 'purify': `every` is a whole number of minutes, 1 to 1440"),
    ({"helpers": {"Purify": {"help": "x", "does": "affect:radiation:-0.1"}}}, "content.json helpers 'Purify': a name is a word in lower case"),
])
def test_a_packs_catalogue_is_checked_when_it_loads(tmp_path, content, why):
    import json
    from app import world_pack as W
    from app.config import Settings
    from tests.test_world_pack import pack_dir
    d = pack_dir(tmp_path)
    (d / "content.json").write_text(json.dumps(content))
    with pytest.raises(W.PackError) as e:
        W.load(Settings(world_pack=str(d)))
    assert str(e.value).startswith(f"world pack {d}: {why}")


def test_a_pack_may_redescribe_the_engines_own_without_saying_how_they_work(tmp_path):
    import json
    from app import world_pack as W
    from app.config import Settings
    from tests.test_world_pack import pack_dir
    d = pack_dir(tmp_path)
    (d / "content.json").write_text(json.dumps({"sensors": {"visitor": {"help": "someone knocks at the hatch"}},
                                                "helpers": {"find": {"help": "it noses through the rubble", "every": 120}}}))
    assert W.load(Settings(world_pack=str(d))).name == "Ashfall"


def test_a_design_keeps_a_sensor_or_helper_only_as_the_world_has_it(monkeypatch):
    import random
    raw = lambda *caps: {"name": "Bell", "description": "a bell", "capabilities": list(caps)}          # noqa: E731
    spec = lambda *caps: cr.sanitize_spec(raw(*caps), {"name": "x"}, "sound", [], random.Random(1))[2]["capabilities"]   # noqa: E731
    assert spec({"type": "sensor", "condition": "hungry", "alert": "It whines."}) == {"sensor": {"condition": "hungry", "alert": "It whines."}}
    assert spec({"type": "sensor", "condition": "dosed", "alert": "It clicks."}) == {}                  # Ashfall's, not this world's
    assert spec({"type": "sensor", "condition": "hungry"}) == {} and spec({"type": "sensor", "alert": "It whines."}) == {}
    monkeypatch.setattr(cr, "helpers", lambda: {"hum": {"help": "it hums", "does": "affect:energy:0.01"}})   # no `every`: an hour
    assert spec({"type": "helper", "effect": "hum", "line": "It hums."}) == {"helper": {"effect": "hum", "line": "It hums.", "every_minutes": 120}}
    assert spec({"type": "helper", "effect": "hum", "line": "It hums.", "every_minutes": 5})["helper"]["every_minutes"] == 60


@pytest.mark.parametrize("entry,ok", [
    ({"watches": "low:health"}, False), ({"help": "x", "watches": "low:health", "every": 1}, True),
    ({"help": "x", "watches": "low:health", "every": 1440}, True), ({"help": "x", "watches": "low:health", "every": 1441}, False),
    ({"help": "x", "watches": "low:health", "every": 2.0}, False), ({"help": "x", "watches": "ready:garden", "when": "next:garden"}, True),
])
def test_a_catalogue_entry_at_its_edges(entry, ok):
    if ok:
        cr.check_catalogue({"sensors": {"hurt": entry}})
    else:
        with pytest.raises(ValueError, match="^content.json sensors 'hurt': "):
            cr.check_catalogue({"sensors": {"hurt": entry}})


def test_only_a_live_module_counts_and_a_sensor_the_world_dropped_never_comes_on(tmp_path):
    from app import modules as M
    s, st, agent = modular(tmp_path)
    m = live(st, rule(name="pots"), "x")
    st.update_module(m["id"], standing={"title": "Pots", "lines": [], "ready": True})
    assert cr.usable(st, {"watches": "ready:pots"}) and cr.watching(st, "ready:pots", NOW)
    M.disable(st, m["id"])
    assert not cr.usable(st, {"watches": "ready:pots"}) and not cr.watching(st, "ready:pots", NOW)
    assert cr.at_work(st, {"sensor": {"condition": "gone", "alert": "x"}}, NOW)["sensor"] == {"condition": "gone", "alert": "x", "on": False}


def test_what_mends_is_at_most_a_dozen_things_of_the_kinds_the_world_mends_with(monkeypatch):
    from app import finds
    monkeypatch.setattr(finds, "loot", lambda: {"yard": [(f"part {i:02d}", "material", 1, (1, 1), "x", {}) for i in range(14)]
                                                + [("acorn", "food", 1, (1, 1), "x", {})]})
    got = finds.mending()
    assert got == {"things": [f"part {i:02d}" for i in range(12)], "qty": [1, 3]}
