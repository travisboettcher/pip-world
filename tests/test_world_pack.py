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
    assert gm.system.startswith("A dead city under a grey sky.\nKeep the world consistent") and gm.system.endswith("the `report` tool.")
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
