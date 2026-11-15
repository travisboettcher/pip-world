"""The dashboard is the world pack's (docs/DESIGN-engine-audit.md, B5): the engine serves the pack's `web/` at /ui with its own renderer
underneath, a plain page for a pack without one, and generic reads (`/published`, `/characters`, `/abilities`) in place of one
feature's endpoints; a module's standing is a chat command of its own."""
import asyncio
import json
import shutil
import time
from pathlib import Path

from fastapi.testclient import TestClient

from app import commands, world_pack
from app.config import Settings
from app.llm.fake import FakeBackend
from app.main import create_app
from tests.test_projects import given, make

ROOT = Path(__file__).resolve().parent.parent


def client(tmp_path, **kw):
    s = Settings(db_path=str(tmp_path / "t.db"), persona_path="/x", pacing="manual", **kw)
    return TestClient(create_app(s, FakeBackend()))


def test_published_is_what_each_live_module_publishes(tmp_path):
    with client(tmp_path) as c:
        st = c.app.state.agent.state
        asyncio.run(given(st, {"name": "kite", "craft": "sewing", "stages": [{"name": "cut", "minutes": 30, "progress": 15.0}]},
                          skills={"sewing": 120}))
        got = c.get("/published").json()
        assert got["crafting"]["projects"][0]["name"] == "kite" and got["crafting"]["skills"] == {"sewing": {"xp": 120, "level": 1}}
        mid = next(m["id"] for m in st.modules("live") if m["name"] == "crafting")
        st.update_module(mid, status="disabled")
        assert "crafting" not in c.get("/published").json()                        # only what's live


def test_abilities_are_the_agents_practice_with_its_level(tmp_path):
    with client(tmp_path) as c:
        c.app.state.agent.state.add_ability_xp({"handiness": 240})
        assert c.get("/abilities").json()["handiness"] == {"xp": 240, "level": 2}


def test_characters_are_everyone_the_agent_knows_of_whatever_their_role(tmp_path):
    from app import neighbors as nb
    with client(tmp_path) as c:
        st = c.app.state.agent.state
        st.add_character("Marigold", "neighbor", None, "a weaver", 60, time.time() + 600, about="weaves", place="Marigold's home")
        st.add_character("Oswin", "resident", None, "a ferryman", 60, nb.NOT_YET, about="ferries", place="the quay")
        got = {ch["name"]: ch for ch in c.get("/characters").json()}
        assert got["Marigold"]["kind"] == "neighbor" and got["Marigold"]["about"] == "weaves" and got["Marigold"]["place"] == "Marigold's home"
        assert got["Marigold"]["next_chatter_at"] > time.time() and got["Oswin"]["next_chatter_at"] is None    # None: when a module asks
        assert set(got["Oswin"]) == {"name", "kind", "about", "life", "place", "next_chatter_at"}             # never their persona
        st.add_letter("Marigold", "Pip", "hello", deliver_at=0)
        assert [lt["text"] for lt in c.get("/letters").json()["letters"]] == ["hello"] and "neighbors" not in c.get("/letters").json()


def test_one_features_endpoints_are_gone_and_the_state_says_what_the_agent_is_busy_with(tmp_path):
    with client(tmp_path) as c:
        assert c.get("/projects").status_code == 404 and c.get("/library/bookmarks").status_code == 404
        assert c.get("/state").json()["session"] is None
        c.app.state.agent.state.start_session(0, 0, 30, 9e9, kind="module", target="crafting", expect="working on the kite", about="kite")
        got = c.get("/state").json()["session"]
        assert got["kind"] == "module" and got["about"] == "kite" and got["label"] == "working on the kite" and got["ends_at"] == 9e9
        assert got["target"] == "crafting" and time.time() - 5 < got["started_at"] <= time.time()


def test_the_public_may_read_what_modules_publish_but_not_who_the_characters_are(tmp_path):
    with client(tmp_path, public_hosts=("pip.example",)) as c:
        h = {"host": "pip.example"}
        assert c.get("/published", headers=h).status_code == 200 and c.get("/abilities", headers=h).status_code == 200
        assert c.get("/state", headers=h).json()["session"] is None
        st = c.app.state.agent.state
        st.start_session(0, 0, 30, 9e9, kind="walk", target="Brygdon")
        st.set_meta(stakes=json.dumps({"outcome": "weak", "stat": "energy", "label": "energy", "since": 1.0}))
        public = c.get("/state", headers=h).json()
        assert public["session"]["target"] == "Brygdon" and public["condition"]["outcome"] == "weak"
        assert c.get("/characters", headers=h).status_code == 404 and c.get("/letters", headers=h).status_code == 404


def pack_with_page(tmp_path, files: dict | None) -> Path:
    d = tmp_path / "ashfall"                                  # the pack's own modules are named after its directory
    shutil.copytree(ROOT / "worlds" / "ashfall", d)
    if files is not None:
        (d / "web").mkdir()
        for name, text in files.items():
            (d / "web" / name).parent.mkdir(parents=True, exist_ok=True)
            (d / "web" / name).write_text(text)
    return d


def test_the_page_is_the_packs_and_the_renderer_is_the_engines(tmp_path):
    d = pack_with_page(tmp_path, {"index.html": "<title>Wren</title>", "app.js": "// the pack's", "world/scene.js": "// a pack's own scene"})
    with client(tmp_path, world_pack=str(d)) as c:
        assert "<title>Wren</title>" in c.get("/ui/").text and c.get("/ui/app.js").text == "// the pack's"
        assert "export class SceneView" in c.get("/ui/world/scene.js").text           # the engine's renderer can't be replaced
        assert c.get("/ui/vendor/three/three.min.js").status_code == 200 and c.get("/ui/fonts/OFL.txt").status_code == 200
        assert c.get("/ui/app.js").headers["cache-control"] == "no-cache"


def test_a_pack_without_a_page_gets_the_engines_plain_one(tmp_path):
    with client(tmp_path, world_pack=str(pack_with_page(tmp_path, None))) as c:
        page = c.get("/ui/").text
        assert c.get("/ui/").status_code == 200 and 'src="plain.js"' in page and "Pip" not in page
        js = c.get("/ui/plain.js").text
        for path in ("/standing", "/events", "/mode", "/inbox", "/stream"):                   # what every world has (and the scene)
            assert f"'{path}" in js, path
        assert "./world/scene.js" in js and c.get("/ui/plain.css").status_code == 200


def test_pips_world_ships_its_own_page(tmp_path):
    with client(tmp_path) as c:
        assert "<title>Pip</title>" in c.get("/ui/").text and "plain.js" not in c.get("/ui/").text
    assert (ROOT / "worlds" / "pip" / "web" / "index.html").is_file() and not (ROOT / "web" / "index.html").exists()


def test_a_module_is_a_command_showing_its_standing(tmp_path):
    from tests.test_garden import garden
    s, st, *_ = make(tmp_path)
    m = garden(st)
    st.update_module(m["id"], standing={"title": "Your garden", "lines": ["plot 1: tomatoes growing, ready in about {in:%d}" % (time.time() + 600)],
                                        "ready": False})
    assert commands.answer(st, s, "/garden") == "Your garden\nplot 1: tomatoes growing, ready in about 10 min"
    assert "/garden: your garden" in commands.answer(st, s, "/help")
    other = garden(st)
    st.update_module(other["id"], name="orchard", standing={"title": "The orchard", "lines": [], "ready": False})
    assert commands.answer(st, s, "/help").endswith("\n/garden: your garden\n/orchard: the orchard")
    assert commands.answer(st, s, "/projects").startswith("I don't know /projects.")           # crafting's command is /crafting now
    st.update_module(m["id"], standing={"title": "Plots", "lines": [], "ready": False})
    assert commands.answer(st, s, "/garden") == "Plots\nNothing to show right now."


def test_a_modules_command_never_hides_the_engines_own(tmp_path):
    from tests.test_garden import garden
    s, st, *_ = make(tmp_path)
    m = garden(st)
    st.update_module(m["id"], name="status", standing={"title": "Shadow", "lines": ["x"], "ready": False})
    assert commands.answer(st, s, "/status").startswith("Status\n") and commands.answer(st, s, "/help").count("/status:") == 1


def test_a_module_command_may_have_digits_and_dashes(tmp_path):
    from tests.test_garden import garden
    s, st, *_ = make(tmp_path)
    m = garden(st)
    st.update_module(m["id"], name="stall-2", standing={"title": "The stall", "lines": ["3 jars"], "ready": False})
    assert commands.answer(st, s, "/stall-2") == "The stall\n3 jars"
    assert commands.answer(st, s, "/-x") is None and commands.answer(st, s, "/2x") is None


def test_the_world_json_sprite_and_look_reach_the_scene(tmp_path):
    d = pack_with_page(tmp_path, None)
    w = json.loads((d / "world.json").read_text())
    w["agents"][0]["look"] = {"hair": "auburn", "top": "ochre", "height": "towering"}
    (d / "world.json").write_text(json.dumps(w))
    with client(tmp_path, world_pack=str(d)) as c:
        a = c.get("/world/scene").json()["agent"]
        assert a["look"]["hair"] == "auburn" and a["look"]["top"] == "ochre" and a["look"]["height"] in ("short", "medium", "tall")
        assert "sprite" not in a and world_pack.active().sprite() is None


def test_pipchat_reads_what_modules_publish(tmp_path, monkeypatch, capsys):
    """Pip's command line reads the same generic endpoints as the page: projects, the garden, letters and the reading."""
    from argparse import Namespace
    from tests.test_defaults import load_pipchat
    from tests.test_garden import garden
    pipchat = load_pipchat(monkeypatch)
    with client(tmp_path) as c:
        st = c.app.state.agent.state
        asyncio.run(given(st, {"name": "kite", "craft": "sewing", "stages": [{"name": "cut", "minutes": 30, "progress": 15.0}]}))
        st.start_session(0, 0, 30, time.time() + 600, kind="module", target="crafting", about="kite")
        st.add_ability_xp({"handiness": 240})
        st.add_character("Marigold", "neighbor", None, "a weaver", 60, time.time() + 600, about="weaves", place="Marigold's home")
        st.add_letter("Marigold", "Pip", "the loom is fixed", deliver_at=0)
        g = garden(st)
        st.update_module(g["id"], standing={"title": "Your garden", "lines": ["plot 1: empty"], "ready": False})
        mid = next(m["id"] for m in st.modules("live") if m["name"] == "crafting")
        st.update_module(mid, facts={**st.module(mid)["facts"], "bookmarks": [{"book_id": 7, "title": "Moby", "finished": False, "unreadable": False,
                                                                               "percent": 40, "sessions": 2, "last_read": None}]})
        pip = type("P", (), {"call": lambda self, path, body=None, method=None: c.get(path).json()})()
        pipchat.cmd_projects(pip, Namespace(status=None))
        pipchat.cmd_letters(pip, Namespace(n=10))
        pipchat.cmd_library(pip, Namespace(query=[]))
        pipchat.cmd_garden(pip, Namespace())
    out = capsys.readouterr().out
    assert "#1 kite" in out and "working, ~10 min left" in out and "handiness: level 2" in out
    assert "Marigold" in out and "the loom is fixed" in out and "#7 Moby" in out and "40%" in out and "plot 1: empty" in out


def test_a_packs_sprite_and_look_are_checked_when_it_loads(tmp_path):
    import pytest
    d = pack_with_page(tmp_path, None)
    good = json.loads((ROOT / "worlds" / "pip" / "sprite.json").read_text())
    assert len(good["frames"]) == world_pack.SPRITE_FRAMES
    for sprite, why in [({**good, "frames": good["frames"][:9]}, "`frames` is a list of 10 pixel pictures: 0-1 standing, 2-5 walking, 6 asleep, 7-8 working, 9 sitting"),
                        ({**good, "frames": good["frames"][:3] + [["zz" * 8] * 22] + good["frames"][4:]}, "frame 3: "),
                        ({**good, "frames": good["frames"][:9] + [[r[:12] for r in good["frames"][9]]]}, "every frame is the same size")]:
        (d / "sprite.json").write_text(json.dumps(sprite))
        world_pack._sprite.cache_clear(), world_pack._data.cache_clear()
        with pytest.raises(world_pack.PackError) as e:
            world_pack.load(Settings(world_pack=str(d)))
        assert f"sprite.json: {why}" in str(e.value)
    (d / "sprite.json").write_text(json.dumps(good))
    world_pack._sprite.cache_clear(), world_pack._data.cache_clear()
    p = world_pack.load(Settings(world_pack=str(d)))
    assert p.sprite()["frames"] == good["frames"] and (p.sprite()["w"], p.sprite()["h"]) == (16, 22)
    w = json.loads((d / "world.json").read_text())
    w["agents"][0]["look"] = ["auburn"]
    (d / "world.json").write_text(json.dumps(w))
    with pytest.raises(world_pack.PackError) as e:
        world_pack._load.cache_clear() or world_pack.load(Settings(world_pack=str(d)))
    assert "the agent's `look` maps a look's fields to words" in str(e.value)


def test_the_scene_lists_the_worlds_stats_by_their_labels(tmp_path):
    from app import world_view as WV
    from app.state import State
    s = Settings(db_path=str(tmp_path / "t.db"), persona_path="/x", stats={"energy": {"label": "vigour"}, "focus": {"start": 0.7}})
    st = State(s)
    st.update_agent(energy=0.45678, hunger=0.5)
    got = WV.scene_view(st, s, None)["agent"]["stats"]
    assert got == [{"name": "hunger", "label": "hunger", "value": 0.5}, {"name": "energy", "label": "vigour", "value": 0.46},
                   {"name": "focus", "label": "focus", "value": 0.7}]                       # no label of its own: its name


def test_a_look_the_pack_leaves_partly_open_is_filled_from_the_agents_name_and_persona(tmp_path):
    from app import looks, world_view as WV
    d = pack_with_page(tmp_path, None)
    w = json.loads((d / "world.json").read_text())
    w["agents"][0]["look"] = {"hair": "auburn"}
    (d / "world.json").write_text(json.dumps(w))
    (d / "persona.md").write_text("You are Wren. You wear glasses and a grey coat.")
    world_pack.set_active(world_pack.load(Settings(world_pack=str(d))))
    try:
        look = WV.agent_look()["look"]
        assert look == looks.clean({"hair": "auburn"}, "Wren", world_pack.active().persona()) and look["hair"] == "auburn"
        assert look["accessory"] == "glasses"                                               # from the persona's words
        assert look != looks.clean({"hair": "auburn"}, "Someone else", "")
    finally:
        world_pack.set_active(world_pack.load(Settings()))
