"""Agents meeting (docs/DESIGN-multi-agent.md, release 3): they see each other where they are and meet the first time, hear each other
in person, write to each other by the world's post, and modules can see where everyone is (never what anyone thinks)."""
import json
import os
import time

import pytest

from app import loop, modules as M, others, tools, world_pack as W
from app.config import Settings
from app.llm.fake import FakeBackend
from tests.test_agents import two
from tests.test_modules import live, rule


@pytest.fixture
def world(tmp_path):
    os.makedirs(tmp_path / "data")
    s = Settings(world_pack=str(two(tmp_path)), db_path=str(tmp_path / "data" / "agent.db"), persona_path="/x", pacing="manual",
                 tools=["say", "write_letter", "go_to"])
    w = loop.build(s, FakeBackend())
    yield w
    W.set_active(W.load(Settings()))


async def use(agent, name, **args):
    with agent.acting():
        return await tools.REGISTRY[name][1](agent.ctx, args)


def at(agent, place):
    agent.state.update_agent(location=place)


def woke(agent):
    return agent._wake.is_set()


def test_everyone_and_the_others(world):
    wren, ivo = world.agents
    assert others.everyone() == [wren, ivo]
    with wren.acting():
        assert others.others() == [ivo] and others.named("IVO") is ivo and others.named("Ivo") is ivo and others.named("Wren") is None
    with ivo.acting():
        assert others.others() == [wren] and others.named("wren") is wren and others.named("") is None


def test_agents_at_the_same_place_see_each_other_and_meet_once(world):
    wren, ivo = world.agents
    at(wren, "ruins")
    at(ivo, "lockup")
    with wren.acting():
        assert others.seen(wren.state) == [] and not others.met(wren.state, ivo)
    at(ivo, "ruins")
    ivo.state.update_agent(activity="digging")
    with wren.acting():
        first = others.seen(wren.state)
        assert first == ['Ivo is here (a scavenger, digging): you haven\'t met before. They hear you if you say(to="Ivo").']
        again = others.seen(wren.state)
    assert again == ['Ivo is here (a scavenger, digging). They hear you if you say(to="Ivo").']
    with wren.acting():
        assert others.met(wren.state, ivo)
    with ivo.acting():
        assert others.met(ivo.state, wren)
    met = [e["data"] for e in wren.state.events(5) if e["kind"] == "met"]
    assert met == [{"name": "Ivo", "about": "a scavenger", "place": "ruins"}] and woke(ivo)
    assert [e["data"]["name"] for e in ivo.state.events(5) if e["kind"] == "met"] == ["Wren"]
    with wren.acting():
        perception = wren._perception("timer", [])
    assert "Ivo is here (a scavenger, digging)." in perception


@pytest.mark.asyncio
async def test_agents_hear_each_other_only_in_person(world):
    wren, ivo = world.agents
    at(wren, "ruins")
    at(ivo, "lockup")
    r = await use(wren, "say", text="Anyone there?", to="Ivo")
    assert r.text == "Ivo can't hear you from here" and ivo.state.pending_inbox() == []
    at(ivo, "ruins")
    r = await use(wren, "say", text="Found any wire?", to="Ivo")
    assert r.text == "said it to Ivo; he heard you" and woke(ivo)
    (msg,) = ivo.state.pending_inbox()
    assert (msg["sender"], msg["text"], msg["source"]) == ("Wren", "Found any wire?", "agent")
    with ivo.acting():
        seen = ivo._perception("event", ivo.state.pending_inbox())
    assert '- Wren (here with you) said: Found any wire? (answer with say(to="Wren"))' in seen
    assert [e["data"]["to_name"] for e in wren.state.events(5) if e["kind"] == "say"] == ["Ivo"]
    at(ivo, "lockup")
    r = await use(wren, "say", text="Ivo?", to="Ivo")
    assert r.text == "Ivo can't hear you from here; write_letter to reach them (they're at home)"


@pytest.mark.asyncio
async def test_agents_who_have_met_write_by_the_worlds_post(world, monkeypatch):
    wren, ivo = world.agents
    wren.state.add_item("copper wire", 3, "material", "a coil")
    r = await use(wren, "write_letter", to="Ivo", text="Hello?")
    assert r.text.startswith("error: you don't write to anyone called 'Ivo'")              # they haven't met
    at(wren, "ruins")
    at(ivo, "ruins")
    with wren.acting():
        others.seen(wren.state)
    r = await use(wren, "write_letter", to="Ivo", text="Here's the wire I promised.", enclose="copper wire")
    assert r.text == "your letter to Ivo is on its way, with copper wire tucked inside; it'll take a few hours to arrive"
    assert wren.state.find_item("copper wire")[0]["qty"] == 2
    assert (await use(wren, "write_letter", to="Ivo", text="")).text == "error: the letter is empty"
    gear = wren.state.add_creation("Gear Clock", "a clock", None, "sound", {"capabilities": {}, "quirks": []}, {})
    r = await use(wren, "write_letter", to="Ivo", text="A clock for you", enclose="Gear Clock")
    assert r.text == "error: Gear Clock is yours to keep: only things fit in a letter (nothing was sent)" and gear
    assert others.deliver() == 0 and ivo.state.pending_inbox() == []                          # not yet
    assert others.deliver(time.time() + others.POST_HOURS[1] * 3600 + 1) == 1
    (letter,) = ivo.state.pending_inbox()
    assert (letter["sender"], letter["source"]) == ("Wren", "letter")
    assert letter["text"] == "Here's the wire I promised.\n(Tucked inside: 1 x copper wire.)" and ivo.state.find_item("copper wire")[0]["qty"] == 1
    assert others.deliver(time.time() + 99 * 3600) == 0                                        # once
    with ivo.acting():
        seen = ivo._perception("event", ivo.state.pending_inbox())
    assert "- a letter from Wren: Here's the wire I promised." in seen and "(write_letter to answer)" in seen
    sent = [{k: e["data"][k] for k in ("to", "text", "enclosed")} for e in wren.state.events(10) if e["kind"] == "letter_sent"]
    assert sent == [{"to": "Ivo", "text": "Here's the wire I promised.", "enclosed": "copper wire"}]
    monkeypatch.setattr(wren.s, "letters_per_day", 1)
    assert (await use(wren, "write_letter", to="Ivo", text="More?")).text.startswith("you've written plenty of letters today")


@pytest.mark.asyncio
async def test_the_worlds_step_delivers_the_post(world):
    wren, ivo = world.agents
    with wren.acting():
        wren.state.set_meta(**{"met:ivo": "1"})
        others.post(wren.state, ivo, "See you at the gate.", None, now=time.time() - 7 * 3600)
    await world.step()
    assert [m["text"] for m in ivo.state.pending_inbox()] == ["See you at the gate."] and woke(ivo)


def test_modules_see_where_everyone_is(world):
    wren, ivo = world.agents
    at(ivo, "ruins")
    ivo.state.update_agent(activity="sleeping")
    m = live(wren.state, rule(name="census", reads=["agents"], api=2), "x")
    with wren.acting():
        got = M.context(wren.state, wren.s, m, time.time())["agents"]
    assert got == [{"key": "wren", "name": "Wren", "where": "shelter", "activity": "idle", "asleep": False},
                   {"key": "ivo", "name": "Ivo", "where": "ruins", "activity": "sleeping", "asleep": True}]


def test_meeting_at_its_edges(world, monkeypatch):
    import random
    from app.text import clip
    wren, ivo = world.agents
    at(wren, "ruins")
    at(ivo, "ruins")
    with wren.acting():
        assert others.seen(wren.state, now=123.0)[0] == 'Ivo is here (a scavenger): you haven\'t met before. They hear you if you say(to="Ivo").'
    assert wren.state.meta("met:ivo") == "123.0" == ivo.state.meta("met:wren")
    assert [e["data"] for e in ivo.state.events(5) if e["kind"] == "met"] == [{"name": "Wren", "about": "a survivor", "place": "ruins"}]
    ivo.state.update_agent(activity="")
    with wren.acting():
        assert others.seen(wren.state)[0].startswith("Ivo is here (a scavenger).")
        at(ivo, "ruins")
        ivo.state.start_session(0, 0, 10, time.time() + 600, kind="walk", target="lockup")        # on his way: not here, not anywhere
        assert others.seen(wren.state) == [] and others.say(wren.state, ivo, "x") == "Ivo can't hear you from here; write_letter to reach them"
        ivo.state.end_session()
        at(wren, "shelter")
        assert others.say(wren.state, ivo, "x") == "Ivo can't hear you from here; write_letter to reach them (they're at the ruins)"
        at(wren, "ruins")
        others.say(wren.state, ivo, "Wire?")
    said = next(e["data"] for e in wren.state.events(5) if e["kind"] == "say")
    assert {k: said[k] for k in ("text", "to", "to_name")} == {"text": "Wire?", "to": [], "to_name": "Ivo"}
    with wren.acting():
        others.post(wren.state, ivo, "y" * 500, None, random.Random(1), now=1000.0)
    row = wren.state.db.execute("SELECT * FROM agent_post ORDER BY id DESC LIMIT 1").fetchone()
    assert (row["sent_at"], row["deliver_at"], row["enclosed"]) == (1000.0, 1000.0 + random.Random(1).uniform(*others.POST_HOURS) * 3600, "")
    sent = next(e["data"] for e in wren.state.events(5) if e["kind"] == "letter_sent")
    assert sent["text"] == clip("y" * 500, 400) and sent["enclosed"] == ""


def test_the_post_at_its_edges(world, monkeypatch):
    wren, ivo = world.agents
    st = wren.state
    for sender, to, text in (("kit", "ivo", "From Kit."), ("wren", "nobody", "Lost."), ("wren", "ivo", "From Wren.")):
        st.db.execute("INSERT INTO agent_post (sender, recipient, text, enclosed, sent_at, deliver_at) VALUES (?, ?, ?, ?, 0, 0)",
                      (sender, to, text, '{"name": "brass key", "qty": 1, "kind": "tool", "description": "old", "attrs": {"x": 1}}'
                       if sender == "wren" and to == "ivo" else ""))
    st.db.commit()
    assert others.deliver() == 2                                                       # one waits for an agent not running here
    assert [(m["sender"], m["text"]) for m in ivo.state.pending_inbox()] == [("kit", "From Kit."), ("Wren", "From Wren.\n(Tucked inside: 1 x brass key.)")]
    key = ivo.state.find_item("brass key")[0]
    assert (key["description"], key["attrs"]) == ("old", {"x": 1})
    saved = list(others._world)
    others._world.clear()
    try:
        assert others.everyone() == [] and others.deliver() == 0
    finally:
        others._world[:] = saved


@pytest.mark.asyncio
async def test_a_letter_to_an_agent_at_its_edges(world, monkeypatch):
    wren, ivo = world.agents
    wren.state.set_meta(**{"met:ivo": "1"})
    r = await use(wren, "write_letter", to="Ivo", text="Just a note.")
    assert r.text == "your letter to Ivo is on its way; it'll take a few hours to arrive"
    for bad in ({"text": ""}, {"text": "x", "enclose": "moonstone"}):
        assert (await use(wren, "write_letter", to="Ivo", **bad)).followup is True
    wren.state.add_character("Marta", "villager", None, "x", 60, 0, place="ruins", writes=True)
    wren.state.add_letter("Wren", "Marta", "Hello Marta", time.time())
    monkeypatch.setattr(wren.s, "letters_per_day", 2)                                  # one to Marta, one to Ivo: the day's two
    r = await use(wren, "write_letter", to="Ivo", text="Another.")
    assert r.text.startswith("you've written plenty of letters today") and r.followup is True


@pytest.mark.asyncio
async def test_each_place_is_laid_out_by_one_agent_and_not_again_every_beat(world):
    """Found on Ashfall (2026-11-17): the kind layouts were rebuilt every beat, each agent's view of a place (its home is "home" to one,
    "the lock-up" to the other) making them stale for the next. Shared places are the world's to lay out; an agent's home, its own."""
    import shutil
    wren, ivo = world.agents
    shutil.copy(W.DEFAULT.parent / "ashfall" / "scene.json", W.active().dir / "scene.json")
    W._data.cache_clear()
    world.runner = M.LocalRunner()
    src = 'def on_build(ctx):\n    return {"shapes": [{"shape": "box", "size": [1, 1, 1], "at": [0, 0, 0], "material": {"color": "#000"}}]}\n'
    live(wren.state, {"name": "everywhere", "kind": "place", "api": 1, "hooks": ["on_build"], "kinds": ["yard", "home"]}, src)
    look = {"setting": "town", "walls": "stone", "roof": "slate", "palette": "slate", "props": ["tin"]}
    wren.state.set_meta(**{"scene:ruins": json.dumps(look)})
    ivo.state.set_meta(**{"scene:ruins": json.dumps({**look, "props": ["rope"]}), "scene:lockup": json.dumps({**look, "walls": "brick"})})
    from app import looks
    looks.gather_scenes(world.agents)                                              # as a start does: what only one agent had, the world keeps
    assert json.loads(wren.state.meta("scene:lockup"))["walls"] == "brick" and json.loads(wren.state.meta("scene:ruins"))["props"] == ["tin"]
    for _ in range(3):
        await world.step()
    built = {a.identity.name: sorted(e["data"]["place"] for e in a.state.events(50) if e["kind"] == "layout_built") for a in world.agents}
    assert built == {"Wren": ["ruins", "shelter"], "Ivo": ["lockup"]}
    from app import world_view
    for a in world.agents:                                                          # everyone sees the world's look of a place
        with a.acting():
            assert world_view.place_details(a.state, a.s, "ruins", "yard")["props"] == ["tin"]


@pytest.mark.asyncio
async def test_once_they_have_met_each_knows_where_the_other_lives(world):
    """Found on Ashfall (2026-11-18): Sela promised to come and look at Wren's vent, but no agent knew where another lived, so she
    couldn't. Meeting someone, you learn where they live: their home is a place you can go, by its name or theirs."""
    from app import places
    wren, ivo = world.agents
    with wren.acting():
        assert "lockup" not in places.available(wren.state, None) and places.find(wren.state, None, "Ivo's") is None
    at(wren, "ruins")
    at(ivo, "ruins")
    with wren.acting():
        others.seen(wren.state)
        known = places.available(wren.state, None)
        assert known["lockup"] == "where Ivo lives: a steel-shuttered lock-up crammed with salvage"
        assert [places.find(wren.state, None, q) for q in ("Ivo's", "ivo", "Ivo's lock-up", "lockup", "home")] == ["lockup"] * 4 + ["shelter"]
        assert places.kind_of(wren.state, "lockup") == "home" and places.kind_of(wren.state, "shelter") == "home"
    with ivo.acting():
        assert places.find(ivo.state, None, "Wren's") == "shelter" and places.find(ivo.state, None, "home") == "lockup"
        assert places.available(ivo.state, None)["shelter"] == "where Wren lives"                       # her world's home says no more
    at(ivo, "lockup")
    r = await use(wren, "go_to", place="Ivo's")
    assert r.text.startswith("you set off for the lockup")
    with wren.acting():
        await places.arrive(wren.state, wren.s, None, None)
        assert others.seen(wren.state) == ['Ivo is here (a scavenger). They hear you if you say(to="Ivo").']


@pytest.mark.asyncio
async def test_handing_things_over_in_person(world):
    """Found on Ashfall (2026-11-18): Ivo and Hester agreed a price for his wire and scrap in a talk, and then had no way to hand
    anything over (trade is with booths; a letter carries one thing). `give` hands things you carry, or coins, to someone here."""
    wren, ivo = world.agents
    at(wren, "ruins")
    at(ivo, "ruins")
    wren.state.add_item("copper wire", 11, "material", "stripped bright")
    gear = wren.state.add_creation("Gear Clock", "a clock", None, "sound", {"capabilities": {}, "quirks": []}, {})
    r = await use(wren, "give", to="Ivo", item="copper wire", quantity=4)
    assert r.text == "you hand Ivo 4 x copper wire" and not r.followup
    assert wren.state.find_item("copper wire")[0]["qty"] == 7 and ivo.state.find_item("copper wire")[0]["qty"] == 4
    assert ivo.state.find_item("copper wire")[0]["description"] == "stripped bright"
    r = await use(ivo, "give", to="Wren", coins=6)
    assert r.text == "you hand Wren 6 coins"
    assert (wren.state.coins(), ivo.state.coins()) == (16, 4)                                     # a purse each
    r = await use(wren, "give", to="Ivo", item="copper wire", quantity=2, coins=3)
    assert r.text == "you hand Ivo 2 x copper wire and 3 coins"
    gave = [{k: e["data"][k] for k in ("to_name", "item", "qty", "coins")} for e in reversed(wren.state.events(30)) if e["kind"] == "gave"]
    assert gave == [{"to_name": "Ivo", "item": "copper wire", "qty": 4, "coins": 0}, {"to_name": "Ivo", "item": "copper wire", "qty": 2, "coins": 3}]
    got = [{k: e["data"][k] for k in ("sender", "item", "qty", "coins")} for e in reversed(ivo.state.events(30)) if e["kind"] == "gift"]
    assert got == [{"sender": "Wren", "item": "copper wire", "qty": 4, "coins": 0}, {"sender": "Wren", "item": "copper wire", "qty": 2, "coins": 3}]
    assert woke(ivo)
    for args, why in (({"to": "Ivo"}, "error: give something (an item, or coins)"),
                      ({"to": "Ivo", "item": "moonstone"}, "error: you don't have 'moonstone'"),
                      ({"to": "Ivo", "item": "copper wire", "quantity": 99}, "error: you have only 5 x copper wire"),
                      ({"to": "Ivo", "item": "copper wire", "quantity": 0}, "error: give at least one"),
                      ({"to": "Ivo", "coins": 999}, "error: you have only 13 coins"),
                      ({"to": "Ivo", "coins": -5}, "error: give at least one"),
                      ({"to": "Ivo", "item": "Gear Clock"}, "error: Gear Clock is yours to keep: only things you carry change hands"),
                      ({"to": "Nobody", "item": "copper wire"}, "error: there's no one called 'Nobody' here to give it to")):
        r = await use(wren, "give", **args)
        assert (r.text, r.followup) == (why, True), args
    at(ivo, "lockup")
    assert (await use(wren, "give", to="Ivo", coins=1)).text == "error: there's no one called 'Ivo' here to give it to"
    assert wren.state.coins() == 13 and gear


def test_the_world_view_shows_the_other_agents_who_are_here(world):
    import shutil
    from app import world_view
    shutil.copy(W.DEFAULT.parent / "ashfall" / "scene.json", W.active().dir / "scene.json")
    W._data.cache_clear()
    wren, ivo = world.agents
    at(wren, "ruins")
    at(ivo, "ruins")
    ivo.state.update_agent(activity="digging")
    with wren.acting():
        present = world_view.scene_view(wren.state, wren.s, None)["present"]
    (him,) = [p for p in present if p["name"] == "Ivo"]
    assert him["kind"] == "agent" and him["about"] == "a scavenger, digging" and set(him["look"]) >= {"hair", "top"}
    assert him["look"]["accessory"] == "satchel"                                                   # his own look, from world.json
    ivo.state.start_session(0, 0, 10, time.time() + 600, kind="walk", target="lockup")                # passing through: not here
    with wren.acting():
        assert not [p for p in world_view.scene_view(wren.state, wren.s, None)["present"] if p["name"] == "Ivo"]


@pytest.mark.asyncio
async def test_handing_over_at_its_edges(world):
    from app import conversation as conv
    wren, ivo = world.agents
    at(wren, "ruins")
    at(ivo, "ruins")
    wren.state.add_item("old cell", 2, "material", "", {"charge": 3})
    assert (await use(wren, "give", to="Ivo", item="old cell")).text == "you hand Ivo 1 x old cell"
    assert ivo.state.find_item("old cell")[0]["attrs"] == {"charge": 3} and ivo.state.find_item("old cell")[0]["description"] == ""
    assert (await use(wren, "give", to="Ivo", coins=1)).text == "you hand Ivo 1 coin"
    gave = next(e["data"] for e in wren.state.events(5) if e["kind"] == "gave")
    got = next(e["data"] for e in ivo.state.events(5) if e["kind"] == "gift")
    assert (gave["item"], gave["qty"], gave["coins"]) == ("", 0, 1) and (got["item"], got["qty"], got["item_kind"], got["coins"]) == ("", 0, "", 1)
    assert wren.state.coins("Marta") == 0 and ivo.state.coins() == 11                         # a character's purse starts empty
    wren.state.log("gave", to_name="Marta", item="x", qty=1, coins=0, text="1 x x")              # to someone else
    wren.state.log("gift", sender="Ivo", item="y", qty=1, item_kind="", coins=0, text="1 x y")   # not by hand (a visitor's gift)
    wren.state.log("gift", sender="Marta", item="z", qty=1, item_kind="", coins=0, text="1 x z", source="agent")
    lines = conv.visit_lines(wren.state, "Ivo", 0)
    assert lines == ["You: (hand Ivo 1 x old cell)", "You: (hand Ivo 1 coin)"]


def test_the_land_is_the_worlds_and_looks_the_same_to_everyone(world):
    """Found on Ashfall (2026-11-20): each agent's map drew different land (mountains on one, none on another). Its seed was each
    agent's own, and the land was shaped by the places that agent knew. The land is the world's: its seed and every place's spot."""
    from app import world_view
    wren, ivo = world.agents
    world.check()                                                                           # as the world does: every place gets its spot
    with ivo.acting():
        ivo.state.set_meta(world_seed="777")                                                # a seed of his own, from before
        his = world_view.map_view(ivo.state, ivo.s, None)
    with wren.acting():
        hers = world_view.map_view(wren.state, wren.s, None)
    assert hers["land"] == his["land"] and hers["seed"] == his["seed"] == hers["land"]["seed"] != 777
    assert {s["key"] for s in hers["land"]["spots"]} == {"shelter", "ruins", "lockup"}       # every place in the world, known or not
    assert {p["key"] for p in hers["places"]} == {"shelter", "ruins"}                       # what she knows is still what she's shown
    assert sorted(hers["land"]["homes"]) == ["lockup", "shelter"]


def test_one_agents_land_is_its_own_places_as_before(tmp_path):
    from app import world_view
    from tests.test_projects import make
    s, st, gm, agent = make(tmp_path)
    m = world_view.map_view(st, s, None)
    assert [(p["key"], p["x"], p["y"], p["coastal"]) for p in m["places"]] == [(p["key"], p["x"], p["y"], p["coastal"]) for p in m["land"]["spots"]]
    assert m["land"]["homes"] == [m["home"]] and m["land"]["seed"] == m["seed"]
