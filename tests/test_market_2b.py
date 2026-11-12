"""Market phase 2b (docs/DESIGN-market.md): neighbors sell their own wares at home and at the market one day a week, their letters offer them,
and Pip can sell its creations (once) and copies of its works."""
import os
import time

import pytest

import app.neighbors as nb
from app import market as M
from app import places
from app import tools as T
from app.config import Settings
from tests.test_neighbor import neighbor
from tests.test_projects import FixedRng, call, make, report
from tests.test_stall import LOOT

WARES = [{"name": "cork floats", "kind": "material", "description": "floats off the flats", "per_day": 2},
         {"name": "carrot seeds", "kind": "seed", "description": "from her tin", "per_day": 1},
         {"name": "driftwood", "kind": "material", "description": "grey and smooth", "per_day": 3}]


def world(tmp_path, gm_script=None, market=True, **kw):
    kw.setdefault("character_booths", "on")
    s, st, gm, agent = make(tmp_path, gm_script, **kw)
    if market:
        st.add_place("Brygdon", "brygdon", kind="market", status="real", created_at=0, heard_at=0, hours=[0, 24], daylight_only=0,
                     walk_minutes=10.0, loot=LOOT, verbs={"browse": ["see", None]})
    agent.tools.update({n: T.REGISTRY[n] for n in ("sell", "buy", "pay", "browse")})
    ch = neighbor(st, s)
    st.update_character(ch["id"], wares=nb.clean_wares(WARES))
    st.add_coins("pip", 50)
    return s, st, gm, agent, st.characters("neighbor")[0]


def today_is(monkeypatch, theirs: bool):
    wday = time.localtime().tm_wday
    monkeypatch.setattr(M, "market_day", lambda ch: wday if theirs else (wday + 3) % 7)


# --- wares --------------------------------------------------------------------------------------------------------------------------
def test_wares_are_cleaned_and_known_things_keep_their_nature():
    got = nb.clean_wares(WARES + [{"name": "a spell", "kind": "magic"}, {"name": "Cork Floats", "kind": "material"},
                                  {"name": "awl", "kind": "tool"}, {"name": "hammer", "kind": "tool"}, {"name": "", "kind": "food"}])
    assert [w["name"] for w in got] == ["cork floats", "carrot seeds", "driftwood", "awl"]
    seeds = got[1]
    assert seeds["kind"] == "seed" and seeds["attrs"]["crop"] and seeds["weight"] and seeds["per_day"] == 1   # as the gather table has them
    assert got[0]["weight"] is None and got[0]["attrs"] == {} and got[0]["description"] == "floats off the flats"
    assert [w["per_day"] for w in nb.clean_wares([{"name": "a", "kind": "food", "per_day": 9}, {"name": "b", "kind": "food", "per_day": True},
                                                  {"name": "c", "kind": "food", "per_day": 0}])] == [3, 1, 1]
    assert nb.clean_wares([{"name": "lonely", "kind": "food"}]) == [] and nb.clean_wares("nope") == [] and nb.clean_wares([3, None]) == []
    assert len(nb.clean_wares([{"name": f"thing {i}", "kind": "food"} for i in range(9)])) == nb.WARES_MAX


@pytest.mark.asyncio
async def test_a_neighbor_gets_wares_once_and_tries_again_later_if_it_fails(tmp_path):
    s, st, gm, agent = make(tmp_path, [report(wares=[]), report(wares=WARES)], character_booths="on")
    ch = neighbor(st, s)
    now = time.time()
    await nb.ensure_wares(st, s, agent.gm, now)
    assert st.characters("neighbor")[0]["wares"] == [] and len(gm.calls) == 1
    await nb.ensure_wares(st, s, agent.gm, now + 60)
    assert len(gm.calls) == 1                                                          # waits an hour
    await nb.ensure_wares(st, s, agent.gm, now + 3601)
    assert [w["name"] for w in st.characters("neighbor")[0]["wares"]] == ["cork floats", "carrot seeds", "driftwood"]
    assert "Who Marigold is:" in gm.calls[-1]["messages"][0]["content"]
    assert [e["data"] for e in st.events(5) if e["kind"] == "wares"][0] == {"name": "Marigold", "wares": ["cork floats", "carrot seeds", "driftwood"]}
    await nb.ensure_wares(st, s, agent.gm, now + 9999)
    assert len(gm.calls) == 2
    s.character_booths = "off"
    st.update_character(ch["id"], wares=[])
    await nb.ensure_wares(st, s, agent.gm, now + 99999)
    assert len(gm.calls) == 2


# --- at her home -------------------------------------------------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_at_her_home_pip_can_see_buy_and_sell(tmp_path, monkeypatch):
    today_is(monkeypatch, False)
    s, st, gm, agent, ch = world(tmp_path)
    home = places.home_of(ch)
    st.update_agent(location=home)
    r = await call(agent, "browse")
    price = M.sell_price(st, home, M._entry(M.wares_table(ch), "cork floats"), time.time())
    assert r.text.startswith(f"Marigold has for sale: cork floats ({price} coins), carrot seeds (") and "You have 60 coins" in r.text
    r = await call(agent, "buy", item="cork floats", quantity=5)
    assert r.text.startswith("you bought 4 cork floats")                               # she can spare 2 x 2 a day
    assert st.find_item("cork floats")[0]["qty"] == 4
    assert "out of cork floats" in (await call(agent, "buy", item="cork floats")).text
    assert "Marigold has for sale: carrot seeds" in agent._perception("timer", [])
    st.add_item("tomatoes", 40, "food", "", {"food_value": 0.5})
    r = await call(agent, "sell", item="tomatoes", quantity=40)
    assert "that's all the till could pay" in r.text and M.till(st, home, time.time()) < 3          # her 20 a day, plus what Pip just paid her


@pytest.mark.asyncio
async def test_a_neighbor_with_nothing_for_sale_says_so(tmp_path):
    s, st, gm, agent, ch = world(tmp_path)
    st.update_character(ch["id"], wares=[])
    st.update_agent(location=places.home_of(ch))
    assert (await call(agent, "browse")).text == "there's nothing for sale at Marigold's home"
    assert "doesn't keep" in (await call(agent, "buy", item="cork floats")).text


# --- market day ---------------------------------------------------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_on_her_market_day_she_is_at_her_stall_not_at_home(tmp_path, monkeypatch):
    today_is(monkeypatch, True)
    s, st, gm, agent, ch = world(tmp_path)
    assert M.away_at(st, ch, time.time()) == "Brygdon" and places.place_of(st, ch) == "Brygdon"
    assert [c["name"] for c in places.company_at(st, "Brygdon")] == ["Marigold"]
    st.update_agent(location=places.home_of(ch))
    assert (await call(agent, "browse")).text == "Marigold is at a stall in Brygdon today, with their wares"
    st.update_agent(location="Brygdon")
    r = await call(agent, "browse")
    assert "Marigold, at a stall here today, has for sale: cork floats" in r.text
    r = await call(agent, "buy", item="driftwood", quantity=2)
    assert r.text.startswith("you bought 2 driftwood") and M.till(st, "Marigold" + M.STALL_SUFFIX, time.time()) > M.TILL_PER_DAY["stall"]
    r = await call(agent, "buy", item="brass wire")
    assert r.text.startswith("you bought 1 brass wire")                                 # the market's own booth still trades
    assert "Marigold (at a stall here today) has for sale:" in agent._perception("timer", [])


def test_she_is_home_on_other_days_out_of_hours_and_without_wares_or_a_market(tmp_path, monkeypatch):
    today_is(monkeypatch, False)
    s, st, gm, agent, ch = world(tmp_path)
    assert M.away_at(st, ch, time.time()) is None and places.place_of(st, ch) == places.home_of(ch)
    today_is(monkeypatch, True)
    st.update_place("Brygdon", hours=[0, 0])
    assert M.away_at(st, ch, time.time()) is None
    st.update_place("Brygdon", hours=[0, 24])
    assert M.away_at(st, {**ch, "wares": []}, time.time()) is None and M.away_at(st, {**ch, "kind": "resident"}, time.time()) is None
    (tmp_path / "b").mkdir()
    s2, st2, gm2, agent2, ch2 = world(tmp_path / "b", market=False)
    assert M.away_at(st2, ch2, time.time()) is None and M.the_market(st2) is None


def test_the_market_day_is_fixed_by_name_and_her_trade_reads_plainly(tmp_path):
    s, st, gm, agent, ch = world(tmp_path)
    assert M.market_day(ch) == M.market_day({"name": "Marigold"}) and 0 <= M.market_day(ch) < 7
    assert len({M.market_day({"name": n}) for n in ("Ada", "Bea", "Cy", "Dot", "Eli", "Flo", "Gus", "Hal")}) > 1
    day = M.WEEKDAYS[M.market_day(ch)]
    assert M.selling_where(st, ch) == f"sells cork floats, carrot seeds, driftwood at home, and at Brygdon on {day}s"
    assert M.selling_where(st, {**ch, "wares": []}) == ""
    assert f"- Marigold: {ch['about']} (sells cork floats, carrot seeds, driftwood at home, and at Brygdon on {day}s)" in "\n".join(nb.perception(st))


@pytest.mark.asyncio
async def test_meeting_her_at_the_market_she_greets_pip_there(tmp_path, monkeypatch):
    today_is(monkeypatch, True)
    s, st, gm, agent, ch = world(tmp_path, [report(text="Pip! Buying or selling?")])
    st.update_agent(location="Brygdon")
    st.set_meta(arrived_at=str(time.time()))
    await nb.step(st, s, agent.gm, FixedRng(), time.time())
    task = gm.calls[0]["messages"][0]["content"]
    assert "who Pip meets at Brygdon" in task and "Marigold is minding a stall at Brygdon today (sells cork floats" in task
    assert ch["life"] == st.characters("neighbor")[0]["life"]                         # her life moves on in letters, not here


# --- letters -----------------------------------------------------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_her_letters_know_her_trade_and_offer_what_pip_wished_for(tmp_path, monkeypatch):
    today_is(monkeypatch, False)
    s, st, gm, agent, ch = world(tmp_path, [report(text="Dear Pip, the floats are piling up.", gist="g")])
    st.add_memory("Some driftwood for a frame.", "wishlist", "thing")
    assert await nb._write(st, s, agent.gm, FixedRng(), ch, time.time(), None) is True
    task = gm.calls[0]["messages"][0]["content"]
    price = M.sell_price(st, places.home_of(ch), M._entry(M.wares_table(ch), "driftwood"), time.time())
    assert "Pip can walk over to visit Marigold at home (you can invite it), and Marigold sells cork floats" in task
    assert f"Pip has wished for something like driftwood; Marigold could offer it ({price} coins each)." in task
    assert [e["data"] for e in st.events(5) if e["kind"] == "offered"][0] == {"name": "Marigold", "item": "driftwood", "price": price, "wished": True}


def test_without_a_wish_an_offer_is_now_and_then(tmp_path):
    s, st, gm, agent, ch = world(tmp_path)
    assert "could offer Pip" in nb.trade_note(st, ch, FixedRng(0.1), time.time())
    assert "offer" not in nb.trade_note(st, ch, FixedRng(nb.OFFER_CHANCE), time.time())
    assert nb.trade_note(st, {**ch, "wares": []}, FixedRng(0.1), time.time()) == ""


@pytest.mark.asyncio
async def test_a_neighbor_without_wares_writes_as_before(tmp_path):
    s, st, gm, agent, ch = world(tmp_path, [report(text="Dear Pip, hello.", gist="g")])
    st.update_character(ch["id"], wares=[])
    await nb._write(st, s, agent.gm, FixedRng(), st.characters("neighbor")[0], time.time(), None)
    assert "but Marigold doesn't go out visiting" in gm.calls[0]["messages"][0]["content"]


# --- creations and works ---------------------------------------------------------------------------------------------------------
def creation(st, quality="fine", name="Brass Walker"):
    from tests.test_happenings import UPKEEP
    from app import creations as cr
    return st.add_creation(name, "it walks", None, quality, UPKEEP, cr.initial_runtime(UPKEEP, time.time()))


def test_what_made_things_are_worth():
    assert M.base_price("x", "creation", {"quality": "masterwork"}) == 40 and M.base_price("x", "creation", {"quality": "rough"}) == 8
    assert M.base_price("x", "creation", {}) == 8 and M.base_price("x", "work", {"work": "drawing"}) == 4 and M.base_price("x", "work", {}) == 3


@pytest.mark.asyncio
async def test_a_creation_sold_to_a_keeper_is_theirs(tmp_path):
    s, st, gm, agent, ch = world(tmp_path)
    c = creation(st, "sound")
    st.update_agent(location="Brygdon")
    pay = max(1, int(M._price(st, "Brygdon", "Brass Walker", "creation", {"quality": "sound"}, None, time.time()) * M.BUY_RATE))
    r = await call(agent, "sell", item="Brass Walker")
    assert r.text == f"you sold Brass Walker for {M.coins_text(pay)} ({60 + pay} now); it is theirs now"
    assert st.creation(c["id"])["given_to"] == "the keeper at Brygdon" and not st.creations()
    assert [e["data"] for e in st.events(5) if e["kind"] == "sold_creation"][0] == {"name": "Brass Walker", "place": "Brygdon", "coins": pay, "stall": False}
    assert f"- you sold Brass Walker at Brygdon for {M.coins_text(pay)}" in agent._perception("timer", [])


@pytest.mark.asyncio
async def test_a_keeper_who_cannot_pay_keeps_the_till_and_pip_keeps_the_creation(tmp_path, monkeypatch):
    today_is(monkeypatch, False)
    s, st, gm, agent, ch = world(tmp_path)
    c = creation(st, "masterwork")
    st.update_agent(location=places.home_of(ch))
    r = await call(agent, "sell", item="Brass Walker")
    assert "till can't pay for Brass Walker today" in r.text and st.creations()
    cheap = creation(st, "rough", "Tin Mouse")
    r = await call(agent, "sell", item="Tin Mouse")
    assert r.text.startswith("you sold Tin Mouse") and st.creation(cheap["id"])["given_to"] == "Marigold"


@pytest.mark.asyncio
async def test_a_creation_on_a_stall_sells_once_and_stays_pips_until_then(tmp_path):
    s, st, gm, agent, ch = world(tmp_path)
    c = creation(st)
    st.update_agent(location="Brygdon")
    r = await call(agent, "sell", item="Brass Walker", ask=30, quantity=4)
    assert r.text.startswith("you set out Brass Walker at 30 coins each") and st.creations()
    assert st.stall_rows("Brygdon")[0]["qty"] == 1
    sale = M.sell_units(st, "Brygdon", st.stall_rows("Brygdon")[0], 1, time.time())
    assert sale == {"place": "Brygdon", "item": "Brass Walker", "qty": 1, "coins": 30, "left": 0, "what": "creation"}
    assert st.creation(c["id"])["given_to"] == "a buyer at Brygdon" and st.stall_rows("Brygdon") == []


@pytest.mark.asyncio
async def test_taking_a_creation_back_or_giving_it_away_meanwhile(tmp_path):
    s, st, gm, agent, ch = world(tmp_path)
    c = creation(st)
    st.update_agent(location="Brygdon")
    await call(agent, "sell", item="Brass Walker", ask=30)
    r = await call(agent, "sell", item="Brass Walker", ask=0)
    assert r.text == "you take 1 Brass Walker back off the stall" and st.creations() and st.find_item("Brass Walker")[0] is None
    await call(agent, "sell", item="Brass Walker", ask=30)
    st.give_creation(c["id"], "Travis")
    M.prune(st)
    assert st.stall_rows("Brygdon") == []                                                     # given away meanwhile: off the stall


@pytest.mark.asyncio
async def test_copies_of_a_work_sell_at_a_stall_and_the_original_stays(tmp_path):
    s, st, gm, agent, ch = world(tmp_path)
    w = st.add_work("drawing", "The Marsh at Dusk", "<svg/>", "reeds and a low sun", "workshop")
    st.update_agent(location="Brygdon")
    assert "keepers don't buy copies of your drawings" in (await call(agent, "sell", item="The Marsh at Dusk")).text
    r = await call(agent, "sell", item="the marsh at dusk", ask=5)
    assert r.text.startswith("you set out 1 copy of The Marsh at Dusk at 5 coins each")
    r = await call(agent, "sell", item="The Marsh at Dusk", ask=5, quantity=9)
    assert r.text.startswith(f"you set out {M.WORK_COPIES_MAX} copies") and st.stall_rows("Brygdon")[0]["qty"] == M.WORK_COPIES_MAX
    sale = M.sell_units(st, "Brygdon", st.stall_rows("Brygdon")[0], 2, time.time())
    assert sale["what"] == "work" and sale["qty"] == 2 and st.works()[0]["id"] == w
    await call(agent, "sell", item="The Marsh at Dusk", ask=0)
    assert st.find_item("The Marsh at Dusk")[0] is None


def test_the_setting():
    assert Settings().character_booths == "off"
    old = os.environ.pop("CHARACTER_BOOTHS", None)
    try:
        assert Settings.from_env().character_booths == "on"
        os.environ["CHARACTER_BOOTHS"] = "OFF"
        assert Settings.from_env().character_booths == "off"
        os.environ["CHARACTER_BOOTHS"] = "x"
        assert Settings.from_env().character_booths == "on"
    finally:
        os.environ.pop("CHARACTER_BOOTHS", None)
        if old is not None:
            os.environ["CHARACTER_BOOTHS"] = old



# --- edges ---------------------------------------------------------------------------------------------------------------------------
def test_cleaning_wares_in_detail():
    from app import finds as gathering
    from app.state import name_key
    known = next(e for t in gathering.loot().values() for e in t if name_key(e[0]) == "carrot seed")
    got = nb.clean_wares(["junk", {"name": "kelp seeds", "kind": "seed", "description": "d" * 200}, {"name": "carrot seeds", "kind": "food"},
                          {"name": "x" * 60, "kind": "Food "}])
    assert got[0]["attrs"]["crop"] == "kelp" and got[0]["description"] == "d" * 120 + "..." and got[0]["weight"] is None
    assert got[1] == {"name": known[0], "kind": known[1], "weight": known[2], "description": known[4], "attrs": dict(known[5]), "per_day": 1}
    assert got[2]["name"] == "x" * 40 + "..."
    assert len(nb.clean_wares([{"name": "a", "kind": "food"}, {"name": "b", "kind": "food"}])) == 2


@pytest.mark.asyncio
async def test_each_neighbor_is_given_wares_from_who_they_are(tmp_path):
    s, st, gm, agent = make(tmp_path, [report(wares=[]), report(wares=WARES)], character_booths="on")
    a = st.add_character("Ada", "neighbor", None, "A potter by the ford.", 60, 0, about="a potter")
    st.update_character(a["id"], life=["Her kiln cracked."], told=["Ada glazes in blue"])
    b = st.add_character("Bea", "neighbor", None, "A beekeeper.", 60, 0, about="bees")
    now = time.time()
    await nb.ensure_wares(st, s, agent.gm, now)
    first = gm.calls[0]["messages"][0]["content"]
    assert "A potter by the ford." in first and "Her kiln cracked." in first and "Ada glazes in blue" in first
    assert [c["name"] for c in st.characters("neighbor") if c["wares"]] == ["Bea"]
    assert st.meta(f"wares_retry_at:{a['id']}") == str(now + nb.RETRY_AFTER)
    gm.script = [report(wares=WARES)]
    await nb.ensure_wares(st, s, agent.gm, now + nb.RETRY_AFTER)                       # exactly when it may try again
    assert all(c["wares"] for c in st.characters("neighbor"))


def test_only_open_wishes_bring_an_offer(tmp_path):
    s, st, gm, agent, ch = world(tmp_path)
    st.set_memory_status(st.add_memory("Some driftwood.", "wishlist", "thing"), "done")
    st.add_memory("Ask about driftwood.", "todo")
    assert "Pip has wished" not in nb.trade_note(st, ch, FixedRng(0.9), time.time())


@pytest.mark.asyncio
async def test_a_till_that_can_pay_exactly_buys_the_creation(tmp_path, monkeypatch):
    s, st, gm, agent, ch = world(tmp_path)
    creation(st, "rough")
    st.update_agent(location="Brygdon")
    pay = max(1, int(M._price(st, "Brygdon", "Brass Walker", "creation", {"quality": "rough"}, None, time.time()) * M.BUY_RATE))
    st.set_till("Brygdon", pay, M.day_of(time.time()))
    assert (await call(agent, "sell", item="Brass Walker")).text.startswith("you sold Brass Walker")
    assert M.till(st, "Brygdon", time.time()) == 0
    creation(st, "rough", "Tin Mouse")
    mouse = max(1, int(M._price(st, "Brygdon", "Tin Mouse", "creation", {"quality": "rough"}, None, time.time()) * M.BUY_RATE))   # its own day's price
    r = await call(agent, "sell", item="Tin Mouse")
    assert r.text == (f"error: Brygdon's till can't pay for Tin Mouse today (it would fetch {M.coins_text(mouse)}; 0 coins left); "
                      "try a stall with an ask, or come back tomorrow")


@pytest.mark.asyncio
async def test_stall_lines_for_made_things_in_detail(tmp_path):
    s, st, gm, agent, ch = world(tmp_path)
    creation(st, "fine")
    st.add_work("writing", "Tide Song", "The tide comes in.", "", "workshop")
    st.update_agent(location="Brygdon")
    fair = M.fair_price(st, "Brygdon", "Brass Walker", "creation", {"quality": "fine"}, time.time())
    r = await call(agent, "sell", item="Brass Walker", ask=999)
    assert r.text == f"you set out Brass Walker at 999 coins each; the going price here is {fair}; at that price nobody will stop"
    await call(agent, "sell", item="Brass Walker", ask=fair)
    row = [r for r in st.stall_rows("Brygdon") if r["kind"] == "creation"][0]
    assert row["qty"] == 1 and row["ask"] == fair and row["description"] == "it walks"
    await call(agent, "sell", item="Tide Song", ask=3, quantity=2)
    r = await call(agent, "sell", item="Tide Song", ask=3, quantity=2)
    assert r.text.startswith("you set out 4 copies of Tide Song at 3 coins each; the going price here is ") and not r.text.endswith("stop")
    assert "error:" in (await call(agent, "sell", item="Tide Song")).text


def test_market_hours_bound_the_stall_and_only_a_real_market_counts(tmp_path, monkeypatch):
    today_is(monkeypatch, True)
    s, st, gm, agent, ch = world(tmp_path)
    h = time.localtime().tm_hour
    st.update_place("Brygdon", hours=[h, h + 1])
    assert M.away_at(st, ch, time.time()) == "Brygdon"
    st.update_place("Brygdon", hours=[h - 1, h])
    assert M.away_at(st, ch, time.time()) is None
    st.update_place("Brygdon", status="heard")
    st.add_place("Saltholm", "saltholm", kind="shop", status="real", created_at=0, heard_at=0, hours=[0, 24], daylight_only=0,
                 walk_minutes=10.0, loot=LOOT, verbs={})
    assert M.the_market(st) is None


def test_booths_name_their_owner_and_lists_say_when_sold_out(tmp_path, monkeypatch):
    today_is(monkeypatch, False)
    s, st, gm, agent, ch = world(tmp_path)
    assert [(k, who) for k, who, _ in M.booths(st, "Brygdon", time.time())] == [("Brygdon", "")]
    assert [(k, who) for k, who, _ in M.booths(st, places.home_of(ch), time.time())] == [(places.home_of(ch), "Marigold")]
    assert M.booths(st, "woods", time.time()) == []
    assert M.wares_line(st, "k", "Jo", [], time.time()) == "Jo has sold out of everything today."
    assert M.wares_line(st, "k", "Jo", M.wares_table(ch)[:1], time.time()).endswith(" coins).")
    assert M.till(st, "Jo" + M.STALL_SUFFIX, time.time()) == M.TILL_PER_DAY["stall"]
    many = {**ch, "wares": nb.clean_wares([{"name": f"thing {i}", "kind": "food"} for i in range(5)])}
    assert M.selling_where(st, many).startswith("sells thing 0, thing 1, thing 2, thing 3 at home")
    (tmp_path / "b").mkdir()
    s2, st2, gm2, agent2, ch2 = world(tmp_path / "b", market=False)
    assert M.selling_where(st2, ch2) == "sells cork floats, carrot seeds, driftwood at home"


def test_pruning_takes_off_only_creations_pip_no_longer_has(tmp_path):
    s, st, gm, agent, ch = world(tmp_path)
    kept, gone = creation(st), st.add_creation("Tin Bird", "a bird", None, "sound", {"capabilities": {}, "quirks": []}, {})
    st.set_stall("Brygdon", "brass walker", name="Brass Walker", kind="creation", qty=1, ask=30, attrs={"creation_id": kept["id"]})
    st.set_stall("Brygdon", "tin bird", name="Tin Bird", kind="creation", qty=1, ask=30, attrs={"creation_id": gone["id"]})
    st.set_stall("Brygdon", "tomatoes", name="tomatoes", kind="food", qty=3, ask=2, attrs={})
    st.give_creation(gone["id"], "Oriel")
    assert M.prune(st) == 1 and sorted(r["item"] for r in st.stall_rows("Brygdon")) == ["brass walker", "tomatoes"]
    assert M.prune(st) == 0
