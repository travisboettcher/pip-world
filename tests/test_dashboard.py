"""The engine's dashboard (docs/DESIGN-dashboard.md): one page for every world, made of panels a pack chooses and adds to, saying the
agent's name, stats and item kinds from the world; and a view of the whole world: everyone at a glance, what happens between them, and
the world's own doings."""
import json
import os
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import others, world_pack as W
from app.config import Settings
from app.llm.fake import FakeBackend
from app.main import create_app
from tests.test_agents import two
from tests.test_modules import live, rule


ASHFALL = Path(__file__).resolve().parent.parent / "worlds" / "ashfall"


def pack(tmp_path):
    d = two(tmp_path)
    stats = json.loads((ASHFALL / "stats.json").read_text())
    (d / "stats.json").write_text(json.dumps({k: stats[k] for k in ("hunger", "energy")}))
    return d


@pytest.fixture
def app(tmp_path):
    os.makedirs(tmp_path / "data")
    s = Settings(world_pack=str(pack(tmp_path)), db_path=str(tmp_path / "data" / "agent.db"), persona_path="/x", pacing="manual")
    with TestClient(create_app(s, FakeBackend())) as c:
        yield c
    W.set_active(W.load(Settings()))


def agents(c):
    return c.app.state.world.agents


def test_the_state_says_who_the_agent_is_its_stats_and_the_worlds_item_kinds(app):
    got = app.get("/state?agent=ivo").json()
    assert got["identity"] == {"key": "ivo", "name": "Ivo", "they": "he", "kind": "a scavenger", "home": "lockup"}
    assert [(s["name"], s["label"], s["good"]) for s in got["stats"]] == [("hunger", "hunger", "low"), ("energy", "energy", "high")]
    assert all(0 <= s["value"] <= 1 for s in got["stats"]) and got["item_kinds"] == ["tool", "material", "food"]
    assert app.get("/state").json()["identity"]["name"] == "Wren"


def test_everyone_at_a_glance_and_nothing_of_anyones_mind(app):
    wren, ivo = agents(app)
    ivo.state.update_agent(location="ruins", activity="digging", description="for wire", mood="curious")
    ivo.state.add_usage(1200, 300)
    got = app.get("/world/agents").json()
    assert [a["key"] for a in got] == ["wren", "ivo"]
    him = got[1]
    assert (him["name"], him["kind"], him["where"], him["place"], him["activity"], him["description"], him["mood"]) == \
        ("Ivo", "a scavenger", "ruins", "the ruins", "digging", "for wire", "curious")
    assert him["usage"]["total_tokens"] == 1500 and him["usage"]["budget"] == ivo.s.daily_token_budget
    assert [s["name"] for s in him["stats"]] == ["hunger", "energy"] and him["asleep"] is False and him["condition"] is None
    assert got[0]["place"] == "home" and got[0]["session"] is None
    assert not {"notes", "memories", "diary", "emotions", "persona"} & set(him)


def test_what_happens_between_them_meetings_once_words_and_the_post(app):
    wren, ivo = agents(app)
    for a in (wren, ivo):
        a.state.update_agent(location="ruins")
    with wren.acting():
        others.seen(wren.state, now=1000.0)
        others.say(wren.state, ivo, "Found any wire?")
    with ivo.acting():
        others.say(ivo.state, wren, "Some.")
        others.post(ivo.state, wren, "Here's the wire.", {"name": "copper wire", "qty": 1, "kind": "material"}, now=time.time())
    wren.state.log("say", text="to myself", to=[], to_name="")                  # not between them
    got = app.get("/world/between").json()
    lines = [(x["kind"], x["who"], x["to"], x["text"]) for x in got["happened"]]
    assert lines == [("letter", "Ivo", "Wren", "Here's the wire."), ("said", "Ivo", "Wren", "Some."),
                     ("said", "Wren", "Ivo", "Found any wire?"), ("met", "Wren", "Ivo", "")]
    assert got["happened"][0]["enclosed"] == "copper wire" and got["happened"][-1]["place"] == "ruins"
    (way,) = got["on_the_way"]
    assert (way["who"], way["to"], way["text"], way["enclosed"]) == ("Ivo", "Wren", "Here's the wire.", "copper wire")
    assert way["arrives"] > time.time()
    assert app.get("/world/between?limit=1").json()["happened"] == got["happened"][:1]


def test_the_worlds_doings_the_builders_nights_modules_and_people(app):
    wren, ivo = agents(app)
    st = wren.state
    st.log("builder", outcome="nothing", why="covered already")
    st.log("module_live", name="radio", version=2, author="world")
    ivo.state.log("character", name="Marta", role="trader", about="keeps the gate", place="village")
    m = live(st, rule(name="weather"), "x")
    st.add_module_call(m["id"], 1.0, "on_tick", False, 12, "error: boom")
    st.add_module_call(m["id"], 2.0, "on_tick", True, 10, "nothing")
    st.add_module_call(m["id"], 3.0, "on_tick", False, 11, "error: boom again")
    got = app.get("/world/doings").json()
    assert [(x["kind"], x["text"]) for x in got["happened"][:3]] == [
        ("character", "Marta (trader) came into the world: keeps the gate"), ("module_live", "radio v2 (by the world) is live"),
        ("builder", "The builder added nothing: covered already")]
    (bad,) = got["failing"]
    assert (bad["name"], bad["fails"], bad["calls"], bad["last"]) == (m["name"], 2, 3, "error: boom again")


def test_none_of_the_world_view_is_public(tmp_path):
    os.makedirs(tmp_path / "data")
    s = Settings(world_pack=str(two(tmp_path)), db_path=str(tmp_path / "data" / "agent.db"), persona_path="/x", pacing="manual",
                 public_hosts=("w.example",))
    with TestClient(create_app(s, FakeBackend())) as c:
        for path in ("/world/agents", "/world/between", "/world/doings"):
            assert c.get(path, headers={"host": "w.example"}).status_code == 404, path
    W.set_active(W.load(Settings()))


def test_the_dashboard_is_the_engines_and_a_pack_adds_to_it(tmp_path):
    d = two(tmp_path)
    (d / "web" / "panels").mkdir(parents=True)
    (d / "web" / "dashboard.json").write_text(json.dumps({"tabs": [{"key": "now", "title": "Now", "panels": ["feed", "pack:radio"]}]}))
    (d / "web" / "panels" / "radio.js").write_text("export default {};")
    (d / "web" / "index.html").write_text("<p>a pack can't replace the page</p>")
    os.makedirs(tmp_path / "data")
    s = Settings(world_pack=str(d), db_path=str(tmp_path / "data" / "agent.db"), persona_path="/x", pacing="manual")
    with TestClient(create_app(s, FakeBackend())) as c:
        page = c.get("/ui/").text
        assert "dashboard.js" in page and "a pack can't" not in page
        assert c.get("/ui/dashboard.js").status_code == 200 and c.get("/ui/world/scene.js").status_code == 200
        assert c.get("/ui/pack/dashboard.json").json()["tabs"][0]["panels"] == ["feed", "pack:radio"]
        assert c.get("/ui/pack/panels/radio.js").text == "export default {};"
        assert c.get("/ui/plain.js").status_code == 404                              # the plain page is gone
    W.set_active(W.load(Settings()))


def test_a_pack_without_a_page_gets_the_whole_dashboard(app):
    assert "dashboard.js" in app.get("/ui/").text and app.get("/ui/pack/dashboard.json").status_code == 404


def test_the_world_view_at_its_edges(app):
    wren, ivo = agents(app)
    ivo.state.update_agent(activity="sleeping")
    wren.state.update_agent(activity="Sleeping")
    seen = app.get("/world/agents").json()
    assert (seen[0]["asleep"], seen[1]["asleep"]) == (False, True)
    assert [s["label"] for s in seen[1]["stats"]] == ["hunger", "energy"]
    st = wren.state
    for outcome, data in (("proposed", {"name": "lamp-oil", "revised": True}), ("proposed", {"name": "chain"}),
                          ("dropped", {"name": "bell", "why": "copies the radio"}), ("failed", {"why": "no answer"})):
        st.log("builder", outcome=outcome, **data)
    st.log("module_disabled", name="raids", author="library", why="", subject="")
    st.log("module_disabled", name="radio", author="world", why="too loud", subject="")
    st.log("module_rejected", name="bell", author="world", version=1, note="", subject="")
    st.log("module_rejected", name="horn", author="world", version=2, note="no", subject="")
    ivo.state.log("module_live", name="ledger", author="agent", version=1, subject="")
    st.log("module_live", name="stall", author="library", version=3, subject="")
    for a in (wren, ivo):
        a.state.log("character", name="Ezra", role="villager", about="minds the pumps", place="village")
    got = app.get("/world/doings").json()["happened"]
    assert [(x["text"], x["who"]) for x in got] == [
        ("Ezra (villager) came into the world: minds the pumps", "Wren"), ("stall v3 (shipped) is live", "Wren"),
        ("ledger v1 (by Ivo) is live", "Ivo"), ("horn v2 was turned down: no", "Wren"), ("bell v1 was turned down", "Wren"),
        ("radio was switched off: too loud", "Wren"), ("raids was switched off", "Wren"),
        ("The builder could not propose anything: no answer", "Wren"), ("The builder dropped an idea (bell): copies the radio", "Wren"),
        ("The builder proposed chain", "Wren"), ("The builder proposed lamp-oil (a new version)", "Wren")]
    assert len(app.get("/world/doings?limit=3").json()["happened"]) == 3


def test_what_passes_between_them_at_its_edges(app):
    wren, ivo = agents(app)
    now = time.time()
    with wren.acting():
        others.post(wren.state, ivo, "Just a note.", None, now=now)
    st = wren.state
    st.db.execute("INSERT INTO agent_post (sender, recipient, text, enclosed, sent_at, deliver_at) VALUES ('kit', 'wren', 'From Kit.', '', 5, ?)",
                  (now + 9e9,))
    st.db.execute("INSERT INTO agent_post (sender, recipient, text, enclosed, sent_at, deliver_at, delivered_at) VALUES ('ivo', 'wren', 'Old.', '', 1, 2, 3)")
    st.db.commit()
    way = app.get("/world/between").json()["on_the_way"]
    assert [(w["who"], w["to"], w["text"], w["enclosed"], w["sent"]) for w in way] == [("Wren", "Ivo", "Just a note.", "", now), ("kit", "Wren", "From Kit.", "", 5)]
    for i in range(5):
        wren.state.log("say", text=f"to myself {i}", to=[], to_name="")
    wren.state.log("say", text="Hello, Ivo.", to=[], to_name="Ivo")
    for i in range(5):
        wren.state.log("say", text=f"again {i}", to=[], to_name="")
    assert [x["text"] for x in app.get("/world/between?limit=3").json()["happened"]] == ["Hello, Ivo.", "Just a note."]   # says to no one don't crowd them out
    ivo.state.log("met", name="Wren", about="a survivor", place="ruins")                              # remembered by the second of the two
    assert [x["kind"] for x in app.get("/world/between").json()["happened"]] == ["said", "letter"]


def test_two_nights_alike_both_show_and_the_newest_failure_comes_first(app):
    wren, _ = agents(app)
    st = wren.state
    for _ in range(2):
        st.log("builder", outcome="nothing", why="covered")
        st.db.execute("UPDATE events SET ts = ts + ? WHERE id = (SELECT MAX(id) FROM events)", (len(st.events(100)),))
    st.db.commit()
    assert [x["text"] for x in app.get("/world/doings").json()["happened"]] == ["The builder added nothing: covered"] * 2
    old, new = live(st, rule(name="old"), "x"), live(st, rule(name="new"), "x")
    st.add_module_call(new["id"], 5.0, "on_tick", False, 1, "new broke")
    st.add_module_call(old["id"], 9.0, "on_tick", False, 1, "old broke")
    st.add_module_call(new["id"], 6.0, "on_tick", True, 1, "fine")
    got = app.get("/world/doings").json()["failing"]
    assert [(m["name"], m["version"], m["calls"], m["fails"], m["last"], m["last_ts"]) for m in got] == [
        ("old", old["version"], 1, 1, "old broke", 9.0), ("new", new["version"], 2, 1, "new broke", 5.0)]


def test_an_agent_alone_keeps_its_own_looks(tmp_path):
    from app import looks
    from app.state import State
    st = State(Settings(db_path=str(tmp_path / "a.db"), persona_path="/x"))
    saved = list(others._world)
    others._world.clear()
    try:
        st.set_meta(**{"scene:yard": json.dumps({"walls": "brick"})})
        assert looks.keeper(st) is st and looks.place_scene(st, "yard", "yard", "")["walls"] == "brick"
    finally:
        others._world[:] = saved
