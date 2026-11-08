"""Wishes of every kind (a thing, an activity, an ability, an idea): filed with a kind, hinted at where they could be met, noticed in the night's reflection,
and shared with Pip's friend without being asked (docs/DESIGN-wishes.md)."""
import asyncio
import time

import pytest

from app import wishes as W
from app.config import Settings
from app.state import State
from tests.test_projects import call, make

NOW = time.mktime((2026, 3, 5, 12, 0, 0, 0, 0, -1))
HOUR = 3600


def run(coro):
    return asyncio.run(coro)


def at(h, m=0, d=5):
    return time.mktime((2026, 3, d, h, m, 0, 0, 0, -1))


# --- storing a kind ----------------------------------------------------------------------------------------------------
def test_a_note_keeps_its_kind_and_the_old_notes_have_none(tmp_path):
    s = Settings(db_path=str(tmp_path / "t.db"))
    st = State(s)
    a = st.add_memory("a plain note")
    b = st.add_memory("to sit at a real market stall", "wishlist", "activity")
    rows = {m["id"]: m for m in st.memories()}
    assert rows[a]["kind"] == "" and rows[b]["kind"] == "activity"


def test_a_database_from_before_kinds_gains_the_column(tmp_path):
    import sqlite3
    path = str(tmp_path / "old.db")
    db = sqlite3.connect(path)
    db.execute("CREATE TABLE memories (id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL, text TEXT NOT NULL, section TEXT NOT NULL DEFAULT 'diary', "
               "status TEXT NOT NULL DEFAULT 'open', outcome TEXT NOT NULL DEFAULT '', edited_at REAL)")
    db.execute("INSERT INTO memories (ts, text, section) VALUES (1, 'an old wish', 'wishlist')")
    db.commit()
    db.close()
    st = State(Settings(db_path=path))
    assert st.memories("wishlist")[0]["kind"] == ""
    st.add_memory("a new wish", "wishlist", "idea")
    assert [m["kind"] for m in st.memories("wishlist")] == ["", "idea"]


@pytest.mark.asyncio
async def test_pip_files_a_wish_with_its_kind(tmp_path):
    s, st, gm, agent = make(tmp_path)
    r = await call(agent, "note_to_self", section="wishlist", text="To understand how a clock keeps its time.", kind="idea")
    assert r.text == "wrote in wishlist" and st.memories("wishlist")[0]["kind"] == "idea"
    r = await call(agent, "note_to_self", section="wishlist", text="A better set of needle files for fine work.")
    assert r.text == "wrote in wishlist" and st.memories("wishlist")[1]["kind"] == "thing"                 # a wish with no kind is a thing
    r = await call(agent, "note_to_self", section="wishlist", text="Fly over the marsh at dawn, just once.", kind="Ability")
    assert st.memories("wishlist")[2]["kind"] == "ability"
    r = await call(agent, "note_to_self", section="wishlist", text="Something quite different from all of those.", kind="dream")
    assert r.text == f"error: a wish's kind is one of {', '.join(W.KINDS)}" and r.followup is True and len(st.memories("wishlist")) == 3
    r = await call(agent, "note_to_self", section="todo", text="Check the plots after lunch.", kind="activity")
    assert st.memories("todo")[0]["kind"] == ""                                                           # a kind is for wishes only


def test_the_tool_describes_wishes_broadly_and_offers_the_kinds():
    from app import tools as T
    spec, _ = T.REGISTRY["note_to_self"]
    assert "anything you wish for" in spec.description and "something you wish you could do but can't" in spec.description
    kind = spec.parameters["properties"]["kind"]
    assert kind["enum"] == list(W.KINDS) and "wishlist" in kind["description"]
    assert spec.parameters["required"] == ["section", "text"]


def test_the_guide_says_what_a_wishlist_is_for_and_that_it_is_shared():
    from app import guide
    text = guide.render(["note_to_self"], Settings(wish_share="on"), False)
    assert "Your wishlist is for anything you wish for" in text and "something you wish you could do but can't yet" in text
    assert "what you write there is shared with your friend" in text
    off = guide.render(["note_to_self"], Settings(wish_share="off"), False)
    assert "Your wishlist is for anything you wish for" in off and "shared with your friend" not in off
    assert "Your wishlist is for anything" not in guide.render(["say"], Settings(), False)


# --- where a thing could be had ------------------------------------------------------------------------------------------
def world(tmp_path):
    s, st, gm, agent = make(tmp_path)
    st.add_place("Brygdon", "brygdon", kind="market", status="real", created_at=NOW, heard_at=NOW, hours=[0, 24], daylight_only=0, walk_minutes=10.0,
                 loot=[["needle file", "tool", 3, [1, 1], "a slim needle file", {}], ["sticks", "material", 30, [2, 5], "sticks", {}]], verbs={"browse": ["see", None]})
    st.add_place("Fen", "fen", kind="market", status="heard", created_at=NOW, heard_at=NOW, loot=[["needle file", "tool", 3, [1, 1], "x", {}]])
    return s, st, agent


def test_a_wish_for_a_thing_says_where_it_is_sold_and_for_how_much(tmp_path):
    s, st, agent = world(tmp_path)
    got = W.sources(st, "A finer set of needle files for the gears", NOW)
    price = W.market_price(st, "Brygdon", "needle file", NOW)
    assert got == [f"Brygdon sells needle file ({price} coins)"] and price >= 1
    assert W.sources(st, "A set of fine brass gears", NOW) == []                                          # nothing sells that
    assert W.sources(st, "to see the sea", NOW) == []


def test_it_names_places_pip_has_been_that_have_it_and_not_ones_it_has_not(tmp_path):
    s, st, agent = world(tmp_path)
    assert W.sources(st, "a needle file", NOW) == [f"Brygdon sells needle file ({W.market_price(st, 'Brygdon', 'needle file', NOW)} coins)"]
    st.log("arrived", place="junkyard", label="the junkyard", first_time=True, description="")
    got = W.sources(st, "a needle file", NOW)
    assert got[1:] == ["the junkyard has turned up needle file"]
    assert W.sources(st, "tweezers", NOW) == ["the junkyard has turned up tweezers"]                      # the junkyard's table lists them
    assert W.sources(st, "sticks and string", NOW)[0] == f"Brygdon sells sticks ({W.market_price(st, 'Brygdon', 'sticks', NOW)} coins)"


def test_no_more_than_two_places_are_named(tmp_path):
    s, st, agent = world(tmp_path)
    st.add_place("Quay", "quay", kind="market", status="real", created_at=NOW, heard_at=NOW, hours=[0, 24], daylight_only=0, walk_minutes=10.0,
                 loot=[["needle file", "tool", 3, [1, 1], "x", {}]], verbs={"browse": ["see", None]})
    st.add_place("Saltholm", "saltholm", kind="shop", status="real", created_at=NOW, heard_at=NOW, hours=[0, 24], daylight_only=0, walk_minutes=10.0,
                 loot=[["needle file", "tool", 3, [1, 1], "x", {}]], verbs={"browse": ["see", None]})
    st.log("arrived", place="junkyard", label="the junkyard", first_time=True, description="")
    got = W.sources(st, "a needle file", NOW)
    assert len(got) == W.MAX_SOURCES == 2 and all("sells" in g for g in got)                              # markets and shops come before a place that merely turned something up


def test_a_wish_in_the_prompt_carries_the_hint_only_for_things(tmp_path):
    s, st, agent = world(tmp_path)
    st.add_memory("A finer set of needle files for the gears.", "wishlist", "thing")
    st.add_memory("To understand why the needle files I have chatter.", "wishlist", "idea")
    st.add_memory("To work the lathe like a master.", "wishlist", "ability")
    lines = [l for l in agent._journal() if l.startswith("- #")]
    price = W.market_price(st, "Brygdon", "needle file", time.time())
    assert lines[0].endswith(f"  [you could try: Brygdon sells needle file ({price} coins)]")
    assert "you could try" not in lines[1] and "you could try" not in lines[2]
    st.add_memory("Some needle file stock.", "wishlist")                                                  # an older note with no kind is a thing
    assert any("you could try" in l for l in agent._journal() if "Some needle file stock" in l)


# --- the night's wishes ---------------------------------------------------------------------------------------------------
def test_a_reflection_may_add_a_couple_of_wishes_of_the_right_kinds(tmp_path):
    s, st, gm, agent = make(tmp_path)
    added = W.add_reflected(st, [{"kind": "ability", "text": "To run my own stall at the market."}, {"kind": "idea", "text": "How the tide keeps its hours."},
                                 {"kind": "activity", "text": "A third wish that must not fit."}], NOW)
    assert [a["kind"] for a in added] == ["ability", "idea"] and len(added) == W.REFLECTED_MAX == 2
    rows = st.memories("wishlist")
    assert [(m["kind"], m["text"]) for m in rows] == [("ability", "To run my own stall at the market."), ("idea", "How the tide keeps its hours.")]
    ev = [e["data"] for e in st.events(10) if e["kind"] == "wished"]
    assert ev == [{"id": rows[1]["id"], "wish": "idea", "text": "How the tide keeps its hours.", "source": "reflection"},
                  {"id": rows[0]["id"], "wish": "ability", "text": "To run my own stall at the market.", "source": "reflection"}]       # newest first


@pytest.mark.parametrize("raw", [None, "wish", 7, [], [None], ["a"], [{"kind": "dream", "text": "x" * 30}], [{"kind": "idea"}], [{"kind": "idea", "text": "  "}],
                                 [{"text": "To fly."}], [{"kind": "idea", "text": 5}]])
def test_a_reflection_with_nothing_usable_adds_nothing(tmp_path, raw):
    s, st, gm, agent = make(tmp_path)
    assert W.add_reflected(st, raw, NOW) == [] and st.memories("wishlist") == []


def test_a_reflected_wish_is_clipped_and_not_a_repeat(tmp_path):
    s, st, gm, agent = make(tmp_path)
    st.add_memory("To run my own stall at the market in Brygdon someday.", "wishlist", "ability")
    assert W.add_reflected(st, [{"kind": "ability", "text": "To run my own market stall in Brygdon someday."}], NOW) == []       # the same wish, reworded
    long = "To learn how a clock keeps its time. " * 10
    (one,) = W.add_reflected(st, [{"kind": "idea", "text": long}], NOW)
    assert len(one["text"]) <= W.WISH_CHARS + 3 and one["text"].startswith("To learn how a clock")
    st.resolve_memory(st.memories("wishlist")[0]["id"], "done")
    (again,) = W.add_reflected(st, [{"kind": "ability", "text": "To run my own market stall in Brygdon someday."}], NOW)     # the old one is closed: fine


@pytest.mark.asyncio
async def test_the_nightly_reflection_asks_for_wishes_and_files_them(tmp_path):
    from tests.test_memory import REFLECTION, visit
    from tests.test_projects import report
    s, st, gm, agent = make(tmp_path, [report(**{**REFLECTION, "wishes": [{"kind": "ability", "text": "To run my own stall."}]})])
    visit(st, "How is the clock?")
    await agent.reflect()
    prompt = gm.calls[0]["messages"][0]["content"]
    assert "- `wishes`: at most two things you found yourself wishing for" in prompt and "something you wish you could do but can't" in prompt
    assert [(m["kind"], m["text"]) for m in st.memories("wishlist")] == [("ability", "To run my own stall.")]


# --- telling the friend ------------------------------------------------------------------------------------------------
class StubOutreach:
    def __init__(self, can=True, ok=True):
        self.can, self.ok, self.sent = can, ok, []

    def can_send(self, now=None):
        self.asked = now
        return self.can

    async def send_postcard(self, text, now=None, images=()):
        self.sent.append((text, now))
        return self.ok, "sent" if self.ok else "the channel is down"


def share_world(tmp_path, **kw):
    kw.setdefault("wish_share", "on")
    s, st, gm, agent = make(tmp_path, **kw)
    return s, st


def share(s, st, out, now=NOW):
    return run(W.share_step(st, s, out, now))


def test_a_wish_that_is_not_a_thing_is_told_to_the_friend_once(tmp_path):
    s, st = share_world(tmp_path)
    st.add_memory("A finer set of needle files.", "wishlist", "thing")
    a = st.add_memory("To run my own stall at the market.", "wishlist", "ability")
    out = StubOutreach()
    assert share(s, st, out) is True
    assert out.sent == [("A wish of mine: To run my own stall at the market.", NOW)]
    ev = [e["data"] for e in st.events(5) if e["kind"] == "wish_shared"]
    assert ev == [{"ids": [a], "text": "A wish of mine: To run my own stall at the market."}]
    assert share(s, st, out, NOW + 5 * HOUR) is False and len(out.sent) == 1                       # nothing new, and not twice in a day
    b = st.add_memory("To understand why a clock drifts.", "wishlist", "idea")
    assert share(s, st, out, NOW + 6 * HOUR) is False                                              # the same day
    assert share(s, st, out, NOW + 24 * HOUR) is True and out.sent[1][0] == "A wish of mine: To understand why a clock drifts."


def test_it_tells_about_the_newest_wishes_up_to_what_a_postcard_holds(tmp_path):
    s, st = share_world(tmp_path)
    st.add_memory("To sit by the sea and count the waves until I lose the number.", "wishlist", "activity")
    st.add_memory("To work a lathe.", "wishlist", "ability")
    st.add_memory("To know why the tide turns when it does.", "wishlist", "idea")
    out = StubOutreach()
    assert share(s, st, out)
    text = out.sent[0][0]
    assert text == "A wish of mine: To know why the tide turns when it does. Also: To work a lathe. Also: To sit by the sea and count the waves until I lose the number."
    assert len(text) <= W.SHARE_TEXT_MAX
    assert [e["data"]["ids"] for e in st.events(5) if e["kind"] == "wish_shared"] == [[3, 2, 1]]


def test_a_postcard_is_never_longer_than_it_may_be(tmp_path):
    s, st = share_world(tmp_path)
    st.add_memory("To understand " + "the slow turning of the gears in a clock " * 8, "wishlist", "idea")
    out = StubOutreach()
    assert share(s, st, out) and len(out.sent[0][0]) <= W.SHARE_TEXT_MAX and out.sent[0][0].startswith("A wish of mine: To understand")
    (tmp_path / "b").mkdir()
    s2, st2 = share_world(tmp_path / "b")
    st2.add_memory("To work a lathe.", "wishlist", "ability")
    st2.add_memory("x" * 400, "wishlist", "idea")
    out2 = StubOutreach()
    assert share(s2, st2, out2) and out2.sent[0][0].startswith("A wish of mine: x") and out2.sent[0][0].count("Also:") <= 1


def test_nothing_is_shared_when_it_is_off_or_postcards_may_not_go_or_pip_sleeps(tmp_path):
    s, st = share_world(tmp_path)
    st.add_memory("To run my own stall.", "wishlist", "ability")
    out = StubOutreach()
    assert share(settings_off(s), st, out) is False and out.sent == []
    assert share(s, st, StubOutreach(can=False)) is False
    st.update_agent(activity="sleeping")
    assert share(s, st, out) is False and out.sent == []
    st.update_agent(activity="idle")
    assert share(s, st, out) is True


def settings_off(s):
    from dataclasses import replace
    return replace(s, wish_share="off")


def test_a_postcard_that_fails_is_tried_again_in_an_hour_and_not_marked_shared(tmp_path):
    s, st = share_world(tmp_path)
    st.add_memory("To run my own stall.", "wishlist", "ability")
    out = StubOutreach(ok=False)
    assert share(s, st, out) is False and len(out.sent) == 1 and [e for e in st.events(5) if e["kind"] == "wish_shared"] == []
    assert share(s, st, out, NOW + 59 * 60) is False and len(out.sent) == 1                        # not straight away
    out.ok = True
    assert share(s, st, out, NOW + 60 * 60) is True and len(out.sent) == 2                         # an hour on, again


def test_resolved_wishes_and_things_are_not_shared(tmp_path):
    s, st = share_world(tmp_path)
    a = st.add_memory("To run my own stall.", "wishlist", "ability")
    st.add_memory("A set of fine needle files.", "wishlist", "thing")
    st.add_memory("An old wish with no kind.", "wishlist")
    st.resolve_memory(a, "done")
    out = StubOutreach()
    assert share(s, st, out) is False and out.sent == []


def test_the_shared_list_stays_short(tmp_path):
    s, st = share_world(tmp_path)
    st.set_meta(wish_shared_ids="[" + ",".join(str(i) for i in range(1000, 1000 + W.SHARED_KEPT + 20)) + "]")
    st.add_memory("To run my own stall.", "wishlist", "ability")
    assert share(s, st, StubOutreach())
    import json
    kept = json.loads(st.meta("wish_shared_ids"))
    assert len(kept) == W.SHARED_KEPT and kept[-1] > 1000


@pytest.mark.asyncio
async def test_the_loop_offers_the_wishes_to_the_friend(tmp_path, monkeypatch):
    s, st, gm, agent = make(tmp_path)
    seen = []

    async def spy(state, settings, outreach, now=None):
        seen.append(outreach)
        return False
    monkeypatch.setattr(W, "share_step", spy)
    await agent.resolve_world()
    assert seen == [agent.outreach]


def test_the_settings_for_sharing():
    assert Settings().wish_share == "off"
    import os
    old = os.environ.pop("WISH_SHARE", None)
    try:
        assert Settings.from_env().wish_share == "on"
        os.environ["WISH_SHARE"] = "OFF"
        assert Settings.from_env().wish_share == "off"
        os.environ["WISH_SHARE"] = "sometimes"
        assert Settings.from_env().wish_share == "on"
    finally:
        os.environ.pop("WISH_SHARE", None)
        if old is not None:
            os.environ["WISH_SHARE"] = old


def test_a_wish_is_public_and_its_sharing_is_not(tmp_path):
    from app import public_view as pv
    assert pv.EVENT_FIELDS["wished"] == ("id", "wish", "text") and "wish_shared" not in pv.EVENT_FIELDS
    assert pv.public_event({"id": 3, "ts": 1.0, "kind": "wished", "data": {"id": 9, "wish": "idea", "text": "To know.", "source": "reflection"}}) == \
        {"id": 3, "ts": 1.0, "kind": "wished", "importance": None, "data": {"id": 9, "wish": "idea", "text": "To know."}}
    assert pv.public_event({"id": 4, "ts": 1.0, "kind": "wish_shared", "data": {"ids": [1], "text": "x"}}) is None


def test_the_notes_carry_their_kind_to_the_owner_and_the_public(tmp_path):
    from fastapi.testclient import TestClient
    from app.llm.fake import FakeBackend
    from app.main import create_app
    s = Settings(db_path=str(tmp_path / "t.db"), persona_path="/x", pacing="manual", public_hosts=["pip.example.org"])
    with TestClient(create_app(s, FakeBackend())) as c:
        c.app.state.agent.state.add_memory("To run my own stall.", "wishlist", "ability")
        assert c.get("/notes").json()["wishlist"][0]["kind"] == "ability"
        assert c.get("/notes", headers={"host": "pip.example.org"}).json()["wishlist"][0]["kind"] == "ability"


# --- details found by the mutation run ----------------------------------------------------------------------------------------
def test_a_priced_hint_uses_the_things_own_attributes_and_the_time_given(tmp_path):
    s, st, agent = world(tmp_path)
    st.update_place("Brygdon", loot=[["cake", "food", 5, [1, 2], "a cake", {"food_value": 0.9}]])
    st.set_price_row("Brygdon", "cake", 1.4, NOW - 86400, "x", 0)
    from tests.test_market import priced
    want = priced(9, "Brygdon", "cake", local=1 + 0.4 * 0.9)                                               # a day of drift from the time given
    assert W.sources(st, "a lovely cake", NOW) == [f"Brygdon sells cake ({want} coins)"] and W.market_price(st, "Brygdon", "cake", NOW) == want


def test_the_clock_and_the_day_a_postcard_goes_by(tmp_path):
    assert W._today(NOW) == "2026-03-05"
    s, st = share_world(tmp_path)
    st.add_memory("To run my own stall.", "wishlist", "ability")
    out = StubOutreach()
    share(s, st, out)
    assert out.asked == NOW


def test_a_wish_reworded_a_little_is_a_repeat_whatever_its_case(tmp_path):
    s, st, gm, agent = make(tmp_path)
    st.add_memory("To fly high", "wishlist", "idea")
    assert W.add_reflected(st, [{"kind": "idea", "text": "To fly high."}], NOW) == []                       # nearly the same words
    assert W.add_reflected(st, [{"kind": "idea", "text": "TO FLY HIGH"}], NOW) == []                        # and the same in capitals
    assert len(W.add_reflected(st, [{"kind": "idea", "text": "To count the stars one by one."}], NOW)) == 1


def test_only_open_wishes_count_as_repeats_and_all_of_them_are_looked_at(tmp_path):
    s, st, gm, agent = make(tmp_path)
    st.add_memory("To sit by the sea until the light goes.", "todo")
    assert len(W.add_reflected(st, [{"kind": "activity", "text": "To sit by the sea until the light goes."}], NOW)) == 1      # a to-do is not a wish
    (tmp_path / "b").mkdir()
    s2, st2, gm2, agent2 = make(tmp_path / "b")
    first = st2.add_memory("To fly over the grey marsh at the first light.", "wishlist", "idea")
    for i in range(14):
        st2.add_memory(f"Unrelated wish number {i} about {['rope', 'honey', 'tin', 'glass', 'oak', 'wool', 'salt', 'ink', 'clay', 'lime', 'ash', 'tar', 'fig', 'yew'][i]} entirely.", "wishlist")
    assert W.add_reflected(st2, [{"kind": "idea", "text": "To fly over the grey marsh at the first light."}], NOW) == []     # the oldest open wish is still seen


def test_a_bad_wish_does_not_stop_the_good_ones_after_it(tmp_path):
    s, st, gm, agent = make(tmp_path)
    added = W.add_reflected(st, [{"kind": "dream", "text": "x" * 20}, "nonsense", {"kind": "idea", "text": "To know why the tide turns."}], NOW)
    assert [(a["kind"], a["text"]) for a in added] == [("idea", "To know why the tide turns.")] and isinstance(added[0]["id"], int)


def test_only_open_shareable_wishes_are_looked_at_even_among_many(tmp_path):
    s, st = share_world(tmp_path)
    old = st.add_memory("To run my own stall at the market.", "wishlist", "ability")
    for i in range(14):
        st.add_memory(f"A wish for {['rope', 'honey', 'tin', 'glass', 'oak', 'wool', 'salt', 'ink', 'clay', 'lime', 'ash', 'tar', 'fig', 'yew'][i]}.", "wishlist", "thing")
    st.add_memory("a todo that mentions a stall", "todo", "")
    out = StubOutreach()
    assert share(s, st, out) and out.sent[0][0] == "A wish of mine: To run my own stall at the market."


def test_a_second_wish_is_clipped_shorter_and_the_card_may_be_exactly_full(tmp_path):
    from app.text import clip
    s, st = share_world(tmp_path)
    st.add_memory("w" * 100 + " and then it goes on and on " * 4, "wishlist", "idea")
    st.add_memory("To work a lathe.", "wishlist", "ability")                                                 # newest: it goes first
    out = StubOutreach()
    share(s, st, out)
    second = "w" * 100 + " and then it goes on and on " * 4
    assert out.sent[0][0] == f"A wish of mine: To work a lathe. Also: {clip(second, 100).strip()}"
    (tmp_path / "b").mkdir()
    s2, st2 = share_world(tmp_path / "b")
    st2.add_memory("B" * 87, "wishlist", "idea")
    st2.add_memory("A" * 120, "wishlist", "idea")                                                            # newest
    out2 = StubOutreach()
    share(s2, st2, out2)
    assert len(out2.sent[0][0]) == W.SHARE_TEXT_MAX == 230 and out2.sent[0][0].endswith("B" * 87) and "Also:" in out2.sent[0][0]


# --- 0.8.1: wishes to do something, tied to what the world offers -------------------------------------------------------------------
def test_a_wish_to_do_something_is_shown_where_it_can_be_done(tmp_path):
    s, st, agent = world(tmp_path)
    tools = {"sell": 1, "start_project": 1}
    got = W.doings(st, s, None, "I'd love to sit at a real market stall in Brygdon and watch people choose.", tools)
    assert got == ["at Brygdon: sell something you have to a booth here, or set out a stall of your own (sell with an ask)"]
    assert W.doings(st, s, None, "I'd love to sit at a real market stall.", {"start_project": 1}) == []           # no sell tool, no hint
    assert W.doings(st, s, None, "I wish I could make a second walking creature.", tools) == ["start_project could make a start on it"]
    assert W.doings(st, s, None, "I wish I could make a stall for the market.", tools) == [
        "at Brygdon: sell something you have to a booth here, or set out a stall of your own (sell with an ask)", "start_project could make a start on it"]
    assert W.doings(st, s, None, "I wish I could make a second walking creature.", {"sell": 1}) == []
    assert W.doings(st, s, None, "To understand the tides.", tools) == []


def test_the_prompt_shows_a_doing_wish_with_its_hint(tmp_path):
    s, st, agent = world(tmp_path)
    agent.tools.update({n: __import__("app.tools", fromlist=["x"]).REGISTRY[n] for n in ("sell", "start_project")})
    st.add_memory("I'd love to sit at a real market stall in Brygdon.", "wishlist", "activity")
    line = [l for l in agent._journal() if "market stall" in l][0]
    assert line.endswith("  [you could try: at Brygdon: sell something you have to a booth here, or set out a stall of your own (sell with an ask)]")
