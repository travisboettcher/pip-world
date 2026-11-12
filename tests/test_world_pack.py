"""World packs, phase 1a (docs/DESIGN-world-packs.md): a world's persona, narrator, bible and guide come from its pack, chosen with
WORLD_PACK; Pip's world is the default pack, and nothing about Pip's world changes."""
import json

import pytest

from app import world_pack as W
from app.config import Settings


def pack_dir(tmp_path, **world):
    d = tmp_path / "ashfall"
    (d / "guide").mkdir(parents=True)
    (d / "world.json").write_text(json.dumps({"name": "Ashfall", "api": 1, "agent": {"name": "Wren", "pronoun": "she", "kind": "a survivor"}, **world}))
    (d / "persona.md").write_text("You are Wren, who keeps the shelter.\n")
    (d / "narrator.md").write_text("A dead city under a grey sky.\n")
    (d / "bible.md").write_text("Hardship is ordinary here.\n")
    (d / "guide" / "world.md").write_text("You act on your own.\n")
    return d


def test_pips_world_is_the_default_pack():
    p = W.load(Settings())
    assert (p.name, p.agent.name, p.agent.pronoun, p.agent.kind) == ("Pip's world", "Pip", "it", "a small creature")
    assert p.dir == W.DEFAULT and p.dir.name == "pip"
    assert p.persona().startswith("You are Pip, a small creature") and p.bible().startswith("This is a small, slow world")
    assert p.narrator().startswith("You are the quiet narrator and game master of a small world where a curious creature named Pip lives")
    assert p.guide("world").startswith("You act on your own: nobody has to prompt you.") and p.guide("nonexistent") == ""
    assert W.load(Settings()) is p                                                               # loaded once per pack


def test_a_pack_is_chosen_with_world_pack(tmp_path):
    p = W.load(Settings(world_pack=str(pack_dir(tmp_path))))
    assert (p.name, p.agent.name, p.agent.pronoun, p.agent.kind) == ("Ashfall", "Wren", "she", "a survivor")
    assert p.persona() == "You are Wren, who keeps the shelter." and p.narrator() == "A dead city under a grey sky."
    assert p.bible() == "Hardship is ordinary here." and p.guide("world") == "You act on your own." and p.guide("market") == ""
    import os
    os.environ["WORLD_PACK"] = str(pack_dir(tmp_path / "e"))
    try:
        assert Settings.from_env().world_pack.endswith("ashfall")
    finally:
        del os.environ["WORLD_PACK"]


def test_what_a_pack_can_leave_out(tmp_path):
    d = pack_dir(tmp_path)
    for f in ("persona.md", "narrator.md", "bible.md"):
        (d / f).unlink()
    p = W.load(Settings(world_pack=str(d)))
    assert p.persona() == "You are Wren." and p.narrator() == "" and p.bible() == ""
    (d / "world.json").write_text(json.dumps({"name": "Bare", "api": 1, "agent": {"name": "Ox"}}))
    p = W.load(Settings(world_pack=str(d)))
    assert (p.agent.pronoun, p.agent.kind) == ("they", "")


@pytest.mark.parametrize("world, why", [
    ({"name": "X", "api": 2, "agent": {"name": "A"}}, "this engine reads world packs of api 1"),
    ({"name": "X", "api": 1}, "world.json needs an agent with a name"),
    ({"name": "X", "api": 1, "agent": {"name": ""}}, "world.json needs an agent with a name"),
    ({"name": "X", "api": 1, "agent": {"name": "A", "pronoun": "zie"}}, "the agent's pronoun is one of it, she, he, they"),
])
def test_a_broken_pack_says_what_is_wrong(tmp_path, world, why):
    d = pack_dir(tmp_path)
    (d / "world.json").write_text(json.dumps(world))
    with pytest.raises(W.PackError) as e:
        W.load(Settings(world_pack=str(d)))
    assert str(e.value) == f"world pack {d}: {why}"


def test_a_missing_pack_says_so(tmp_path):
    with pytest.raises(W.PackError) as e:
        W.load(Settings(world_pack=str(tmp_path / "nowhere")))
    assert str(e.value) == f"world pack {tmp_path / 'nowhere'}: no world.json"


def test_the_persona_file_still_overrides_the_packs(tmp_path):
    from tests.test_projects import make
    own = tmp_path / "me.md"
    own.write_text("You are Pip, but grumpy.")
    s, st, gm, agent = make(tmp_path)
    s.persona_path = str(own)
    assert agent._persona() == "You are Pip, but grumpy."
    own.unlink()
    assert agent._persona().startswith("You are Pip, a small creature")                     # no file: the pack's persona
    (tmp_path / "w").mkdir()
    d = pack_dir(tmp_path / "w")
    (d / "persona.md").unlink()
    s2, st2, gm2, agent2 = make(tmp_path / "w", world_pack=str(d))
    s2.persona_path = str(tmp_path / "none.md")
    assert agent2._persona() == "You are Wren."


def test_the_guide_the_narrator_and_the_bible_come_from_the_pack(tmp_path):
    from app import builder as B
    from app import guide
    from app.gm import GameMaster
    d = pack_dir(tmp_path)
    s = Settings(world_pack=str(d))
    assert guide.render(["say"], s, False) == "You act on your own."                                  # only the pages the pack has
    assert "You act on your own" in guide.render(["say"], Settings(), False) and "visitor" in guide.render(["say"], Settings(), False)
    assert B.bible(s) == "Hardship is ordinary here."
    gm = GameMaster(None, None, system=W.load(s).narrator_system())
    assert gm.system.startswith("A dead city under a grey sky.\nKeep the world consistent") and gm.system.endswith("the `report` tool.\n" + W.FLOOR_RULES)
    from app import gm as G
    assert G.SYSTEM == W.load(Settings()).narrator_system()                                        # Pip's world: word for word as before
    assert G.SYSTEM.startswith("You are the quiet narrator and game master of a small world where a curious creature named Pip lives,\n")


@pytest.mark.parametrize("pronoun, forms", [("it", ("it", "its", "itself")), ("she", ("her", "her", "herself")),
                                            ("he", ("him", "his", "himself")), ("they", ("them", "their", "themself"))])
def test_the_agent_has_the_forms_prompts_need(pronoun, forms):
    a = W.Agent("Wren", pronoun)
    assert (a.them, a.their, a.themself) == forms and a.possessive == "Wren's"


def test_modules_read_the_agent_and_the_old_name_still_works(tmp_path):
    from app import modules as M
    from tests.test_modules import NOW, live, modular, rule
    s, st, agent = modular(tmp_path)
    new = M.context(st, s, live(st, rule(name="new-reader", reads=["agent"]), "x"), NOW)
    old = M.context(st, s, live(st, rule(name="old-reader", reads=["pip"]), "x"), NOW)
    assert new["agent"] == old["pip"] and "pip" not in new and "agent" not in old and new["agent"]["where"] == "workshop"
    m = live(st, rule(name="talker", proposes=["voices", "speak"]), "x")
    st.update_module(m["id"], voices=[{"name": "Bo", "at": "home", "about": ""}])
    m = st.module(m["id"])
    assert M.plan(st, m, {"speak": {"as": "Bo", "text": "hi", "to_pip": True}}, NOW, "on_tick")[0][1]["to_agent"] is True
    assert M.plan(st, m, {"speak": {"as": "Bo", "text": "hi", "to_agent": True}}, NOW, "on_tick")[0][1]["to_agent"] is True
    assert M.plan(st, m, {"speak": {"as": "Bo", "text": "hi", "to_agent": False, "to_pip": True}}, NOW, "on_tick")[0][1]["to_agent"] is False


def test_until_a_world_is_set_the_active_one_is_pips_and_they_agree_with_their_verbs(tmp_path, monkeypatch):
    from app import commands
    monkeypatch.setattr(W, "_active", [])
    assert W.active().agent.name == "Pip" and W.active().dir == W.DEFAULT
    d = pack_dir(tmp_path)
    (d / "world.json").write_text(json.dumps({"name": "Bare", "api": 1, "agent": {"name": "Ox", "pronoun": "they"}}))
    W.set_active(W.load(Settings(world_pack=str(d))))
    assert W.active().agent.name == "Ox" and "what Ox is doing and how they are" in commands.answer(None, Settings(), "/help")


# --- phase 2: a world's content is its pack's -----------------------------------------------------------------------------------
def ashfall(tmp_path):
    d = pack_dir(tmp_path)
    (d / "items.json").write_text(json.dumps({"kinds": ["scrap", "food", "medicine"], "food_default": 0.2, "seeds_per_food": 0,
        "start": [{"name": "tinned beans", "qty": 4, "kind": "food", "description": "dented tins", "attrs": {"food_value": 0.5}}],
        "finds": {"ruins": [["scrap metal", "scrap", 30, [1, 3], "bent sheet", {}]]}, "gerunds": {"ruins": "scavenging"}}))
    (d / "places.json").write_text(json.dumps({
        "home": {"key": "shelter", "description": "your shelter", "offers": ["sleep"], "about": "a bunker", "aliases": ["home", "shelter", "bunker"], "called": "shelter"},
        "start": [{"key": "ruins", "description": "a collapsed mall", "walk": 12, "offers": ["gather"], "verbs": {"gather": ["scavenge", None]},
                   "kind": "yard", "tag": "salvage", "about": "a collapsed mall"}],
        "kinds": {"camp": {"help": "a survivors' camp", "words": ["camp", "village"], "trades": True, "loot_kinds": ["food"]},
                  "ruin": {"help": "somewhere to look at", "words": []}},
        "fallback_kind": "ruin", "words": {"trade": ["camp"], "reserved": ["home", "shelter", "ruins"], "features": ["ruins?", "camp"]}}))
    (d / "scene.json").write_text(json.dumps({"look": {"height": ["short", "tall"]}, "props": {"barricade": ["barricade"]},
        "scene": {"walls": ["concrete"], "roof": ["tin"], "palette": ["ash"], "setting": ["wasteland"]}, "coastal_words": ["reservoir"]}))
    (d / "content.json").write_text(json.dumps({"world_effects": {"wall": {"help": "a wall", "words": ["wall"], "does": "add_project_slot", "note": "{n} benches"}},
        "abilities": {"radio": {"help": "a receiver", "words": ["radio"], "per_day": 1}}, "crafting": {"abilities": ["grit"], "default_abilities": ["grit"]},
        "happening_firsts": {"raid": "had a raid"}}))
    return W.load(Settings(world_pack=str(d)))


def test_a_worlds_content_is_its_packs(tmp_path):
    from app import abilities, firsts, gathering, looks, place_kinds, places, projects, world, world_effects, world_view
    from app import invented_places as IP
    try:
        W.set_active(ashfall(tmp_path))
        assert world.KINDS == ("scrap", "food", "medicine") and world.starter_items()[0]["name"] == "tinned beans" and world.food_default() == 0.2
        assert world.normalize_attrs("beans", "food", {}) == {"food_value": 0.2}
        assert gathering.loot() == {"ruins": [("scrap metal", "scrap", 30, (1, 3), "bent sheet", {})]} and gathering.VERB == {"ruins": "scavenging"}
        assert places.HOME == "shelter" and places._data()["home"]["called"] == "shelter"
        assert list(place_kinds.KINDS) == ["camp", "ruin"] and place_kinds.KINDS["camp"].trades and place_kinds.guess("an old camp") == "camp"
        assert place_kinds.guess("a hill") == "ruin" and place_kinds.hours_for("camp") is None
        assert looks.scene_lists()["walls"] == ["concrete"] and looks.props("a barricade of tyres") == ["barricade"]
        assert world_view.coastal().search("by the reservoir") and not world_view.coastal().search("by the sea")
        assert list(world_effects.EFFECTS) == ["wall"] and list(abilities.ABILITIES) == ["radio"] and projects.abilities() == ("grit",)
        assert firsts.happening_firsts() == {"raid": "had a raid"} and "shelter" in IP.reserved() and "camp" in IP.trade_words()
        assert IP.chat_mentions("go to the old ruins") and not IP.chat_mentions("go to the old marsh")
        nobody = type("S", (), {"place_row": lambda self, k: None, "characters": lambda self, kind=None: []})()
        assert looks.place_text(nobody, "ruins") == "a collapsed mall"
        assert places.find(nobody, None, "bunker") == "shelter"
    finally:
        W.set_active(W.load(Settings()))
    assert places.HOME == "workshop" and "woods" in gathering.loot()


def test_a_pack_with_no_content_gets_plain_defaults(tmp_path):
    from app import abilities, firsts, gathering, looks, place_kinds, places, projects, world, world_effects, world_view
    from app import invented_places as IP
    d = tmp_path / "bare"
    d.mkdir()
    (d / "world.json").write_text(json.dumps({"name": "Bare", "api": 1, "agent": {"name": "Ox"}}))
    try:
        W.set_active(W.load(Settings(world_pack=str(d))))
        assert (world.kinds(), world.seed_defaults(), world.food_default(), world.starter_items(), world.seeds_per_food()) == ((), {}, 0.3, [], 2)
        assert (world.finds(), world.gerunds(), gathering.loot(), world.normalize_attrs("x", "seed", None)) == ({}, {}, {}, {"crop": "x"})
        assert world.normalize_attrs("bread", "food", None) == {"food_value": 0.3}
        assert (place_kinds.registry(), place_kinds.fallback(), place_kinds.SHOP_DEFAULT_HOURS, place_kinds.OPENS, place_kinds.CLOSES) == ({}, "sight", (9, 17), (7, 10), (16, 19))
        assert place_kinds.guess("a mill") == "sight" and place_kinds.check("shop", "a shop") == "sight"
        assert places.home_key() == "home" and places.HOME == "home"
        reg = places.registry(type("S", (), {"characters": lambda self, kind=None: [], "place_rows": lambda self: []})(), Settings(), None)
        assert list(reg) == ["home"] and (reg["home"].blurb, reg["home"].offers) == ("your home", ("sleep",))
        assert (looks.look_lists(), looks.prop_words(), looks.scene_lists(), looks.scene_props_max(), looks.props("a lighthouse")) == ({}, {}, {}, 4, [])
        assert world_view.coastal().search("the sea") and not world_view.coastal().search("the marsh")
        assert (abilities.registry(), world_effects.registry(), projects.abilities(), projects.default_abilities(), firsts.happening_firsts()) == ({}, {}, (), [], {})
        assert (IP.reserved(), IP.trade_words()) == (set(), set())
        for mod, name in ((world, "NOPE"), (place_kinds, "NOPE"), (places, "NOPE"), (gathering, "NOPE"), (abilities, "NOPE"), (world_effects, "NOPE"),
                          (projects, "NOPE"), (firsts, "NOPE")):
            with pytest.raises(AttributeError):
                getattr(mod, name)
    finally:
        W.set_active(W.load(Settings()))


def test_registries_fill_in_what_an_entry_leaves_out(tmp_path):
    from app import abilities, place_kinds, world_effects
    d = pack_dir(tmp_path)
    (d / "content.json").write_text(json.dumps({"world_effects": {"wall": {"help": "a wall", "does": "add_project_slot", "note": "now {n} benches"}},
                                                "abilities": {"radio": {"help": "a receiver"}}}))
    (d / "places.json").write_text(json.dumps({"kinds": {"camp": {"help": "a camp", "shop_hours": True}}, "opens": [5, 6], "closes": [20, 21],
                                               "shop_default_hours": [8, 18]}))
    try:
        W.set_active(W.load(Settings(world_pack=str(d))))
        a = abilities.registry()["radio"]
        assert (a.words, a.per_day, a.proposable, a.min_difficulty) == ((), 0, True, 2)
        e = world_effects.registry()["wall"]
        assert (e.words, e.min_difficulty) == ((), 2)
        st = type("S", (), {"add_project_slot": lambda self: 3})()
        assert e.apply(st) == "now 3 benches" and e.apply(type("S", (), {"add_project_slot": lambda self: None})()) is None
        k = place_kinds.registry()["camp"]
        assert (k.words, k.verbs, k.loot_kinds, k.max_tools, k.capacity, k.refill, k.session, k.trades, k.stalls) == ((), {}, (), 0, 120, 15, (15, 60), False, False)
        assert place_kinds.hours_for("camp") == (8, 18) and place_kinds.hours_for("camp", 1, 23) == (5, 21) and place_kinds.hours_for("camp", 6, 20) == (6, 20)
        assert (place_kinds.OPENS, place_kinds.CLOSES, place_kinds.SHOP_DEFAULT_HOURS) == ((5, 6), (20, 21), (8, 18))
    finally:
        W.set_active(W.load(Settings()))


def test_a_half_filled_pack_and_values_that_differ_from_the_defaults(tmp_path):
    from app import abilities, looks, place_kinds, places, world_effects
    d = pack_dir(tmp_path)
    (d / "scene.json").write_text(json.dumps({"scene": {"walls": ["plaster", "stone"], "roof": ["tin", "slate"], "palette": ["ash"], "setting": ["wasteland", "ruins"]}}))
    (d / "places.json").write_text(json.dumps({"home": {"key": "shelter"}, "kinds": {"camp": {"help": "a camp", "shop_hours": True}}}))
    (d / "content.json").write_text(json.dumps({"world_effects": {"wall": {"help": "a wall", "does": "add_plot", "note": "x", "min_difficulty": 4}},
                                                "abilities": {"radio": {"help": "r", "per_day": 3, "min_difficulty": 5, "proposable": False}}}))
    nobody = type("S", (), {"place_row": lambda self, k: None, "characters": lambda self, kind=None: [], "place_rows": lambda self: []})()
    try:
        W.set_active(W.load(Settings(world_pack=str(d))))
        got = looks.fallback_scene("Keep", "camp", "a plaster hut with a slate roof")
        assert (got["walls"], got["roof"], got["setting"]) == ("plaster", "slate", "wasteland")      # no matching order given: the lists'
        assert looks.fallback_scene("Keep", "camp", "")["setting"] == "wasteland"
        assert looks.place_text(nobody, "shelter") == "" and looks.place_text(nobody, "elsewhere") == ""
        assert places.find(nobody, None, "home") == "shelter" and places.find(nobody, None, "the bunker") is None
        reg = places.registry(nobody, Settings(), None)
        assert list(reg) == ["shelter"]
        assert place_kinds.hours_for("camp") == (9, 17) and place_kinds.hours_for("camp", 3, 23) == (7, 19) and place_kinds.hours_for("camp", 8, 17) == (8, 17)
        a = abilities.registry()["radio"]
        assert (a.per_day, a.min_difficulty, a.proposable, a.help) == (3, 5, False, "r")
        assert world_effects.registry()["wall"].min_difficulty == 4 and world_effects.registry()["wall"].help == "a wall"
    finally:
        W.set_active(W.load(Settings()))
    built = places._built_in({"key": "k", "description": "d"}, 7.0)
    assert (built.walk_minutes, built.offers, built.daylight_only, built.verbs) == (7.0, (), False, {})
    built = places._built_in({"key": "k", "description": "d", "walk": 3, "offers": ["gather"], "daylight_only": True, "verbs": {"gather": ["g", None]}}, 7.0)
    assert (built.walk_minutes, built.offers, built.daylight_only, built.verbs) == (3, ("gather",), True, {"gather": ("g", None)})
