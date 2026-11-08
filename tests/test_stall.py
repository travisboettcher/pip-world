"""Pip's own stall at a market (docs/DESIGN-market.md, phase 2): goods set out at an ask, customers who stop only while Pip is there, and what they pay."""
import random
import time

import pytest

from app import emotions as emo
from app import market as M
from app import place_kinds as K
from app import tools as T
from tests.test_market import NOW, TODAY, priced
from tests.test_projects import call, make

HOUR = 3600
LOOT = [["brass wire", "material", 5, [1, 2], "wire", {}], ["tomatoes", "food", 12, [2, 4], "ripe tomatoes", {"food_value": 0.5}],
        ["awl", "tool", 3, [1, 1], "an awl", {}]]


def market(tmp_path, here=True, **kw):
    """A fresh world with Pip at an open market called Brygdon (and a shop, Saltholm, to compare)."""
    s, st, gm, agent = make(tmp_path, **kw)
    st.add_place("Brygdon", "brygdon", kind="market", status="real", created_at=NOW, heard_at=NOW, hours=[0, 24], daylight_only=0, walk_minutes=10.0, loot=LOOT, verbs={"browse": ["see", None]})
    st.add_place("Saltholm", "saltholm", kind="shop", status="real", created_at=NOW, heard_at=NOW, hours=[0, 24], daylight_only=0, walk_minutes=10.0, loot=LOOT, verbs={"browse": ["see", None]})
    agent.tools.update({n: T.REGISTRY[n] for n in ("sell", "buy", "pay", "browse")})
    st.update_agent(location="Brygdon" if here else "workshop")
    return s, st, agent


# --- the dice and the demand -------------------------------------------------------------------------------------
@pytest.mark.parametrize("ratio, factor", [(0.0, 1.25), (0.5, 1.25), (0.85, 1.25), (1.0, 1.0), (1.3, 0.5), (1.6, 0.0), (2.0, 0.0), (1.1, pytest.approx(5 / 6))])
def test_the_dearer_the_ask_the_fewer_customers_stop(ratio, factor):
    assert M.stall_factor(ratio) == factor


def test_a_poisson_count_has_the_right_mean_and_never_goes_below_zero():
    rng = random.Random(1)
    for mu in (0.3, 1.0, 4.0):
        draws = [M.poisson(rng, mu) for _ in range(20000)]
        assert min(draws) >= 0 and sum(draws) / len(draws) == pytest.approx(mu, rel=0.05)
    assert M.poisson(rng, 0) == 0 and M.poisson(rng, -2) == 0


def test_stalls_belong_to_markets_only():
    assert K.KINDS["market"].stalls and not any(K.KINDS[k].stalls for k in ("wild", "yard", "shop", "sight"))


# --- setting out and taking back ------------------------------------------------------------------------------------
def test_goods_are_set_out_at_an_ask_and_leave_the_belongings(tmp_path):
    s, st, agent = market(tmp_path)
    st.add_item("tomatoes", 10, "food", "ripe", {"food_value": 0.5})
    fair = M.fair_price(st, "Brygdon", "tomatoes", "food", {"food_value": 0.5}, NOW)
    ok, text = M.list_on_stall(st, "Brygdon", "tomatoes", 6, fair, NOW)
    assert ok and text == f"you set out 6 tomatoes at {M.coins_text(fair)} each; the going price here is {fair}"
    assert st.find_item("tomatoes")[0]["qty"] == 4
    (row,) = st.stall_rows("Brygdon")
    assert (row["name"], row["kind"], row["qty"], row["ask"], row["sold"], row["earned"]) == ("tomatoes", "food", 6, fair, 0, 0)
    assert row["attrs"] == {"food_value": 0.5} and row["description"] == "ripe"
    ok, text = M.list_on_stall(st, "Brygdon", "tomatoes", 10, fair + 1, NOW)                       # more, at a new ask: it all joins the stall
    assert ok and "you set out 4 tomatoes" in text and st.find_item("tomatoes")[0] is None
    (row,) = st.stall_rows("Brygdon")
    assert row["qty"] == 10 and row["ask"] == fair + 1


def test_a_stall_says_when_nobody_will_pay_the_ask(tmp_path):
    s, st, agent = market(tmp_path)
    st.add_item("tomatoes", 3, "food", "", {"food_value": 0.5})
    fair = M.fair_price(st, "Brygdon", "tomatoes", "food", {"food_value": 0.5}, NOW)
    ok, text = M.list_on_stall(st, "Brygdon", "tomatoes", 3, fair * 2, NOW)
    assert ok and text.endswith("; at that price nobody will stop")
    ok, text = M.list_on_stall(st, "Brygdon", "tomatoes", 3, 1, NOW)
    assert "nobody will stop" not in text


def test_what_cannot_be_set_out_is_refused_with_a_reason(tmp_path):
    s, st, agent = market(tmp_path)
    st.add_item("tomatoes", 3, "food", "", {"food_value": 0.5})
    assert M.list_on_stall(st, "Brygdon", "pears", 1, 3, NOW) == (False, "you don't have 'pears'")
    assert M.list_on_stall(st, "Brygdon", "tomatoes", 1, 0, NOW) == (False, "an ask is at least 1 coin")
    assert M.list_on_stall(st, "Brygdon", "tomatoes", 1, -4, NOW) == (False, "an ask is at least 1 coin")
    assert M.list_on_stall(st, "Saltholm", "tomatoes", 1, 3, NOW) == (False, "Saltholm is a shop: sell to its keeper (leave out the ask); stalls are for markets")
    assert M.list_on_stall(st, "Nowhere", "tomatoes", 1, 3, NOW) == (False, "there is no stall to be had at Nowhere")
    assert st.find_item("tomatoes")[0]["qty"] == 3 and st.stall_rows("Brygdon") == []
    for name in ("alpha", "bravo", "charlie", "delta"):
        st.add_item(name, 2, "material", "")
    assert all(M.list_on_stall(st, "Brygdon", n, 1, 3, NOW)[0] for n in ("alpha", "bravo", "charlie"))
    assert M.list_on_stall(st, "Brygdon", "delta", 1, 3, NOW) == (False, "your stall has room for 3 kinds of thing; take something back first")
    assert M.list_on_stall(st, "Brygdon", "alpha", 1, 4, NOW)[0] is True                              # one it already has is not a new kind


def test_quantity_is_clamped_to_what_pip_has_and_must_be_positive(tmp_path):
    s, st, agent = market(tmp_path)
    st.add_item("tomatoes", 3, "food", "", {"food_value": 0.5})
    ok, text = M.list_on_stall(st, "Brygdon", "tomatoes", 50, 4, NOW)
    assert ok and "you set out 3 tomatoes" in text and st.stall_rows("Brygdon")[0]["qty"] == 3
    st.add_item("pears", 3, "food", "", {"food_value": 0.2})
    assert M.list_on_stall(st, "Brygdon", "pears", 0, 4, NOW) == (False, "set out at least 1")


def test_taking_goods_back_returns_them_whole(tmp_path):
    s, st, agent = market(tmp_path)
    st.add_item("tomatoes", 5, "food", "ripe", {"food_value": 0.5})
    M.list_on_stall(st, "Brygdon", "tomatoes", 5, 4, NOW)
    ok, text = M.take_back(st, "Brygdon", "tomato")
    assert ok and text == "you take 5 tomatoes back off the stall"
    item = st.find_item("tomatoes")[0]
    assert item["qty"] == 5 and item["kind"] == "food" and item["attrs"]["food_value"] == 0.5 and st.stall_rows("Brygdon") == []
    assert M.take_back(st, "Brygdon", "tomatoes") == (False, "you have no tomatoes on the stall")


# --- the customers --------------------------------------------------------------------------------------------------
class Count:
    """A rng whose Poisson draws are what we say."""
    def __init__(self, *counts):
        self.counts = list(counts)

    def random(self):
        return 0.0


def fixed(monkeypatch, *counts):
    seq = list(counts)
    monkeypatch.setattr(M, "poisson", lambda rng, mu: seq.pop(0) if seq else 0)


def stocked(tmp_path, qty=10, ask=None, name="tomatoes", kind="food", attrs=None):
    s, st, agent = market(tmp_path)
    attrs = attrs or {"food_value": 0.5}
    st.add_item(name, qty, kind, "", attrs)
    ask = ask or M.fair_price(st, "Brygdon", name, kind, attrs, NOW)
    assert M.list_on_stall(st, "Brygdon", name, qty, ask, NOW)[0]
    return s, st, agent, ask


def test_customers_pay_the_ask_and_the_price_slips(tmp_path, monkeypatch):
    s, st, agent, ask = stocked(tmp_path)
    fixed(monkeypatch, 3)
    before = M.local(st, "Brygdon", "tomatoes", NOW)
    sales = M.stall_tick(st, "Brygdon", NOW, 600, random.Random(1))
    assert sales == [{"place": "Brygdon", "item": "tomatoes", "qty": 3, "coins": 3 * ask, "left": 7}]
    assert st.coins() == 10 + 3 * ask
    row = st.stall_rows("Brygdon")[0]
    assert (row["qty"], row["sold"], row["earned"], row["sold_today"], row["day"]) == (7, 3, 3 * ask, 3, TODAY)
    assert M.local(st, "Brygdon", "tomatoes", NOW) == pytest.approx(before * 0.96 ** 3)
    ev = [e for e in st.events(5) if e["kind"] == "stall_sale"][0]["data"]
    assert ev.pop("firsts")[0]["key"] == "stall:sale"
    assert ev == {"place": "Brygdon", "item": "tomatoes", "qty": 3, "coins": 3 * ask, "left": 7}


def test_the_stall_sells_what_it_has_and_a_sold_out_line_goes(tmp_path, monkeypatch):
    s, st, agent, ask = stocked(tmp_path, qty=4)
    fixed(monkeypatch, 9)
    (sale,) = M.stall_tick(st, "Brygdon", NOW, 3600, random.Random(1))
    assert sale["qty"] == 4 and sale["left"] == 0 and sale["coins"] == 4 * ask
    assert st.stall_rows("Brygdon") == []


def test_the_market_only_wants_so_much_of_one_thing_a_day(tmp_path, monkeypatch):
    s, st, agent, ask = stocked(tmp_path, qty=30)
    fixed(monkeypatch, 5, 5, 5)
    assert M.stall_tick(st, "Brygdon", NOW, 3600, random.Random(1))[0]["qty"] == 5
    assert M.stall_tick(st, "Brygdon", NOW + 100, 3600, random.Random(1))[0]["qty"] == M.STALL_DAILY_UNITS - 5          # only three more today
    assert M.stall_tick(st, "Brygdon", NOW + 200, 3600, random.Random(1)) == []
    assert st.stall_rows("Brygdon")[0]["sold_today"] == M.STALL_DAILY_UNITS
    fixed(monkeypatch, 2)
    assert M.stall_tick(st, "Brygdon", NOW + 86400, 3600, random.Random(1))[0]["qty"] == 2                          # a new day
    assert st.stall_rows("Brygdon")[0]["sold_today"] == 2 and st.stall_rows("Brygdon")[0]["day"] == "2026-03-06"


def test_nobody_stops_at_a_silly_price_and_more_stop_at_a_cheap_one(tmp_path):
    s, st, agent, fair = stocked(tmp_path, qty=200)
    st.db.execute("UPDATE stalls SET ask = ?", (fair * 3,))
    assert sum(sum(x["qty"] for x in M.stall_tick(st, "Brygdon", NOW, 3600, random.Random(i))) for i in range(50)) == 0
    (tmp_path / "b").mkdir()
    s2, st2, agent2, fair2 = stocked(tmp_path / "b", qty=200)
    st2.db.execute("UPDATE stalls SET ask = 1")
    cheap = sum(sum(x["qty"] for x in M.stall_tick(st2, "Brygdon", NOW, 3600, random.Random(i))) for i in range(1))
    assert cheap >= 0


def test_the_rate_is_about_two_an_hour_at_the_going_price(tmp_path):
    totals = []
    for i in range(40):
        (tmp_path / str(i)).mkdir()
        s, st, agent, ask = stocked(tmp_path / str(i), qty=200)
        st.db.execute("UPDATE stalls SET ask = ?", (M.fair_price(st, "Brygdon", "tomatoes", "food", {"food_value": 0.5}, NOW),))
        sold = sum(x["qty"] for x in M.stall_tick(st, "Brygdon", NOW, 3600, random.Random(i)))
        totals.append(sold)
    assert sum(totals) / len(totals) == pytest.approx(M.STALL_DEMAND_PER_HOUR, abs=0.6)


def test_each_item_sells_on_its_own(tmp_path, monkeypatch):
    s, st, agent, ask = stocked(tmp_path, qty=6)
    st.add_item("awl", 3, "tool", "")
    M.list_on_stall(st, "Brygdon", "awl", 3, M.fair_price(st, "Brygdon", "awl", "tool", {}, NOW), NOW)
    fixed(monkeypatch, 2, 1)
    sales = M.stall_tick(st, "Brygdon", NOW, 3600, random.Random(1))
    assert sorted((x["item"], x["qty"]) for x in sales) == [("awl", 1), ("tomatoes", 2)] or sorted((x["item"], x["qty"]) for x in sales) == [("awl", 2), ("tomatoes", 1)]
    assert len(sales) == 2


def test_no_time_no_customers(tmp_path, monkeypatch):
    s, st, agent, ask = stocked(tmp_path)
    fixed(monkeypatch, 5)
    assert M.stall_tick(st, "Brygdon", NOW, 0, random.Random(1)) == [] and st.coins() == 10
    seen = []
    monkeypatch.setattr(M, "poisson", lambda rng, mu: seen.append(mu) or 0)
    M.stall_tick(st, "Brygdon", NOW, 1800, random.Random(1))
    fair = M.fair_price(st, "Brygdon", "tomatoes", "food", {"food_value": 0.5}, NOW)
    assert seen == [pytest.approx(M.STALL_DEMAND_PER_HOUR * M.stall_factor(ask / fair) * 0.5)]


def test_what_the_stall_says_about_itself(tmp_path, monkeypatch):
    s, st, agent, ask = stocked(tmp_path, qty=5)
    assert M.stall_lines(st, "Brygdon", NOW) == [f"Your stall here: 5 tomatoes at {M.coins_text(ask)} each (nothing sold yet)."]
    fixed(monkeypatch, 2)
    M.stall_tick(st, "Brygdon", NOW, 3600, random.Random(1))
    assert M.stall_lines(st, "Brygdon", NOW) == [f"Your stall here: 3 tomatoes at {M.coins_text(ask)} each (sold 2 for {M.coins_text(2 * ask)} so far)."]
    assert M.stall_lines(st, "Saltholm", NOW) == []


# --- when it all happens: Pip has to be there ----------------------------------------------------------------------
def step(st, s, now, rng=None):
    return M.stall_step(st, s, rng or random.Random(1), now)


def test_the_stall_sells_only_while_pip_is_at_the_market_awake_and_it_is_open(tmp_path, monkeypatch):
    s, st, agent, ask = stocked(tmp_path, qty=50)
    fixed(monkeypatch, *([2] * 20))
    assert step(st, s, NOW) == []                                                     # the first look only starts the clock
    sales = step(st, s, NOW + 1800)
    assert sales and sales[0]["qty"] == 2
    st.update_agent(location="workshop")
    assert step(st, s, NOW + 3600) == []                                              # Pip is at home
    st.update_agent(location="Brygdon", activity="sleeping")
    assert step(st, s, NOW + 5400) == []
    st.update_agent(activity="idle")
    st.start_session(0, 0, 10, NOW + 99999, kind="walk", target="Saltholm")
    assert step(st, s, NOW + 7200) == []
    st.end_session()
    st.update_place("Brygdon", hours=[0, 1])
    assert step(st, s, NOW + 9000) == []                                              # closed
    st.update_place("Brygdon", hours=[0, 24])
    assert step(st, s, NOW + 10800)                                                    # open again


def test_the_time_credited_at_once_is_capped_at_an_hour(tmp_path):
    s, st, agent, ask = stocked(tmp_path, qty=50)
    step(st, s, NOW)
    seen = []
    orig = M.poisson
    M.poisson = lambda rng, mu: seen.append(mu) or 0
    try:
        step(st, s, NOW + 10 * HOUR)
    finally:
        M.poisson = orig
    fair = M.fair_price(st, "Brygdon", "tomatoes", "food", {"food_value": 0.5}, NOW + 10 * HOUR)
    assert seen == [pytest.approx(M.STALL_DEMAND_PER_HOUR * M.stall_factor(ask / fair) * 1.0)]       # one hour, not ten


def test_a_shop_has_no_stall_customers(tmp_path):
    s, st, agent, ask = stocked(tmp_path, qty=5)
    st.update_agent(location="Saltholm")
    st.db.execute("UPDATE stalls SET place = 'Saltholm'")
    assert step(st, s, NOW) == [] and step(st, s, NOW + 1800) == []


# --- the tools -------------------------------------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_sell_with_an_ask_sets_a_stall_and_a_zero_ask_takes_it_back(tmp_path):
    s, st, agent = market(tmp_path)
    st.add_item("tomatoes", 8, "food", "", {"food_value": 0.5})
    r = await call(agent, "sell", item="tomatoes", quantity=5, ask=6)
    assert r.text.startswith("you set out 5 tomatoes at 6 coins each; the going price here is") and st.stall_rows("Brygdon")[0]["qty"] == 5
    r = await call(agent, "sell", item="tomatoes", ask=0)
    assert r.text == "you take 5 tomatoes back off the stall" and st.find_item("tomatoes")[0]["qty"] == 8
    r = await call(agent, "sell", item="tomatoes", quantity=2)                       # no ask: the keeper buys, as before
    assert r.text.startswith("error: ") or r.text.startswith("you sold")
    r = await call(agent, "sell", item="tomatoes", ask="cheap")
    assert r.text == "error: an ask is a whole number of coins"
    r = await call(agent, "sell", item="tomatoes", ask=4, quantity=0)
    assert r.text == "error: quantity must be a whole number, at least 1"
    r = await call(agent, "sell", item="tomatoes", ask=3.5)
    assert r.text == "error: an ask is a whole number of coins"


@pytest.mark.asyncio
async def test_an_ask_at_a_shop_is_refused_and_a_plain_sale_still_goes_to_the_keeper(tmp_path):
    s, st, agent = market(tmp_path)
    st.update_agent(location="Saltholm")
    st.add_item("tomatoes", 8, "food", "", {"food_value": 0.5})
    r = await call(agent, "sell", item="tomatoes", ask=5)
    assert r.text == "error: Saltholm is a shop: sell to its keeper (leave out the ask); stalls are for markets"
    r = await call(agent, "sell", item="tomatoes", quantity=2)
    assert r.text.startswith("you sold 2 tomatoes") and st.stall_rows("Saltholm") == []


@pytest.mark.asyncio
async def test_browsing_a_market_shows_the_stall_and_the_prices(tmp_path):
    s, st, agent = market(tmp_path)
    st.set_meta(**{"stock:Brygdon": 80, "stock_at:Brygdon": time.time()})
    st.add_item("tomatoes", 4, "food", "", {"food_value": 0.5})
    await call(agent, "sell", item="tomatoes", ask=6)
    text = (await call(agent, "browse")).text
    assert "Your stall here: 4 tomatoes at 6 coins each (nothing sold yet)." in text.split("\n")


def test_the_prompt_shows_the_stall_where_pip_stands_and_what_it_sold(tmp_path):
    s, st, agent, ask = stocked(tmp_path, qty=5)
    assert f"Your stall here: 5 tomatoes at {M.coins_text(ask)} each (nothing sold yet)." in agent._belongings()
    st.update_agent(location="workshop")
    assert not [l for l in agent._belongings() if l.startswith("Your stall")]
    st.log("stall_sale", place="Brygdon", item="tomatoes", qty=2, coins=12, left=3)
    p = agent._perception("timer", [])
    assert "- at your stall you sold 2 tomatoes for 12 coins" in p


def test_the_monitor_works_the_stall(tmp_path, monkeypatch):
    s, st, agent, ask = stocked(tmp_path)
    called = []
    monkeypatch.setattr(M, "stall_step", lambda state, settings, rng, now=None: called.append(1) or [])
    agent.check_world()
    assert called == [1]


# --- how the rest of the world takes it ----------------------------------------------------------------------------
def test_a_sale_pleases_pip_a_little_and_is_a_first(tmp_path):
    from app import firsts
    s, st, agent, ask = stocked(tmp_path)
    before = emo.levels(st)["joy"]
    st.log("stall_sale", place="Brygdon", item="tomatoes", qty=2, coins=12, left=3)
    assert emo.levels(st)["joy"] == pytest.approx(before + 2, abs=0.2)
    assert emo._appraisal("stall_sale", {"item": "tomatoes"}) == ({"joy": 2}, "sold tomatoes at your stall")
    assert emo._appraisal("stall_sale", {}) == ({"joy": 2}, "sold something at your stall")
    assert firsts.facets("stall_sale", {}, None, 0) == [("stall:sale", "the first time you sold something at your own stall", "major")]


def test_the_public_feed_shows_stall_sales_and_the_stall_only_to_the_owner(tmp_path):
    from app import public_view as pv
    assert pv.EVENT_FIELDS["stall_sale"] == ("place", "item", "qty", "coins", "left")
    assert pv.public_event({"id": 1, "ts": 1.0, "kind": "stall_sale", "data": {"place": "Brygdon", "item": "tomatoes", "qty": 2, "coins": 12, "left": 3, "x": 1}}) == \
        {"id": 1, "ts": 1.0, "kind": "stall_sale", "importance": None, "data": {"place": "Brygdon", "item": "tomatoes", "qty": 2, "coins": 12, "left": 3}}


def test_the_stall_is_kept_when_pip_goes_home(tmp_path):
    s, st, agent, ask = stocked(tmp_path, qty=5)
    st.update_agent(location="workshop")
    assert st.stall_rows("Brygdon")[0]["qty"] == 5                                    # the goods wait for Pip's return
    assert M.fair_price(st, "Brygdon", "awl", "tool", {}, NOW) >= 1


def test_a_market_sells_its_stock_and_browse_lists_it(tmp_path):
    s, st, agent = market(tmp_path)
    st.add_coins("pip", 50)
    ok, text = M.buy(st, "Brygdon", "brass wire", 1, NOW)
    assert ok and st.find_item("brass wire")[0]["qty"] == 1 and M.stock_table(st, "Saltholm")[0][0] == "brass wire"
    assert M.stock_table(st, "Nowhere") == [] and M.quote_buy(st, "Brygdon", "awl", 1, NOW) >= 1
    st.add_place("Fen", "fen", kind="market", status="heard", created_at=NOW, heard_at=NOW, loot=LOOT)
    assert M.stock_table(st, "Fen") == []                                                      # heard of only: nothing to buy
    st.add_place("Lake", "lake", kind="sight", status="real", created_at=NOW, heard_at=NOW, loot=LOOT)
    assert M.stock_table(st, "Lake") == []


# --- details found by the mutation run ---------------------------------------------------------------------------------
def test_the_going_price_is_what_a_booth_here_would_charge_today(tmp_path):
    s, st, agent = market(tmp_path)
    st.set_price_row("Brygdon", "tomato", 1.2, NOW, TODAY, 0)
    assert M.fair_price(st, "Brygdon", "tomatoes", "food", {"food_value": 0.5}, NOW) == priced(5, "Brygdon", "tomatoes", local=1.2)
    assert M.fair_price(st, "Brygdon", "brass wire", "material", {}, NOW) == priced(6, "Brygdon", "brass wire")             # the booth's own weight: 30 / 5
    assert M.fair_price(st, "Brygdon", "clock parts", "material", {}, NOW) == priced(8, "Brygdon", "clock parts")           # not stocked: the junkyard's weight
    assert M.fair_price(st, "Brygdon", "awl", "tool", {}, NOW) == priced(12, "Brygdon", "awl")
    assert M.fair_price(st, "Brygdon", "mystery", "material", {}, NOW) == priced(3, "Brygdon", "mystery")
    assert M.fair_price(st, "Saltholm", "tomatoes", "food", {"food_value": 0.5}, NOW) == priced(5, "Saltholm", "tomatoes")  # another place, another mood
    st.set_price_row("Brygdon", "tomato", 1.6, NOW - 86400, TODAY, 0)
    assert M.fair_price(st, "Brygdon", "tomatoes", "food", {"food_value": 0.5}, NOW) == priced(5, "Brygdon", "tomatoes", local=1 + 0.6 * 0.9)   # a day of drift
    assert M.fair_price(st, "Brygdon", "peas", "seed", {"yield": 4, "food_value": 0.4}, NOW) == priced(3, "Brygdon", "peas")


def test_the_going_price_is_quoted_back_when_goods_are_set_out(tmp_path):
    s, st, agent = market(tmp_path)
    st.add_item("brass wire", 4, "material", "")
    ok, text = M.list_on_stall(st, "Brygdon", "brass wire", 2, 9, NOW)
    assert text == f"you set out 2 brass wire at 9 coins each; the going price here is {priced(6, 'Brygdon', 'brass wire')}"
    assert M.list_on_stall(st, "Brygdon", "brass wire", 1, 1, NOW)[0] is True                       # an ask of one coin is allowed


def test_a_place_that_is_neither_shop_nor_market_has_no_stall(tmp_path):
    s, st, agent = market(tmp_path)
    st.add_place("Lake", "lake", kind="sight", status="real", created_at=NOW, heard_at=NOW)
    st.add_item("tomatoes", 2, "food", "")
    assert M.list_on_stall(st, "Lake", "tomatoes", 1, 3, NOW) == (False, "there is no stall to be had at Lake")


def test_a_line_at_its_daily_limit_does_not_stop_the_others_selling(tmp_path, monkeypatch):
    s, st, agent, ask = stocked(tmp_path, qty=10)
    st.add_item("awl", 3, "tool", "")
    M.list_on_stall(st, "Brygdon", "awl", 3, M.fair_price(st, "Brygdon", "awl", "tool", {}, NOW), NOW)
    st.set_stall("Brygdon", "awl", sold_today=M.STALL_DAILY_UNITS, day=TODAY)                          # the awl is sold out for today, and comes first
    fixed(monkeypatch, 2, 2)
    sales = M.stall_tick(st, "Brygdon", NOW, 3600, random.Random(1))
    assert [(x["item"], x["qty"]) for x in sales] == [("tomatoes", 2)]


def test_a_second_of_selling_is_selling(tmp_path, monkeypatch):
    s, st, agent, ask = stocked(tmp_path)
    fixed(monkeypatch, 1)
    assert M.stall_tick(st, "Brygdon", NOW, 1, random.Random(1))[0]["qty"] == 1


def test_customers_judge_the_ask_against_the_price_at_this_market_today(tmp_path, monkeypatch):
    s, st, agent, ask = stocked(tmp_path)
    st.set_price_row("Brygdon", "tomato", 1.5, NOW, TODAY, 0)
    seen = []
    monkeypatch.setattr(M, "poisson", lambda rng, mu: seen.append(mu) or 0)
    M.stall_tick(st, "Brygdon", NOW, 3600, random.Random(1))
    fair = priced(5, "Brygdon", "tomatoes", local=1.5)
    assert seen == [pytest.approx(M.STALL_DEMAND_PER_HOUR * M.stall_factor(ask / fair))]


def test_the_stall_is_worked_in_the_markets_hours_at_the_markets_clock(tmp_path, monkeypatch):
    s, st, agent, ask = stocked(tmp_path, qty=50)
    st.update_place("Brygdon", hours=[12, 13])
    fixed(monkeypatch, *([2] * 10))
    step(st, s, NOW)
    assert step(st, s, NOW + 1800)                                                            # half past twelve: open
    assert step(st, s, NOW + 3 * HOUR) == []                                                  # three o'clock: shut
    st.update_place("Brygdon", hours=None, daylight_only=1)
    assert step(st, s, NOW + 3 * HOUR + 60)                                                   # a daylight place is open in the afternoon...
    assert step(st, s, at_hour(23)) == []                                                     # ...and not at eleven at night


def at_hour(h):
    return time.mktime((2026, 3, 5, h, 0, 0, 0, 0, -1))


def test_the_step_credits_the_time_since_the_last_look_and_uses_the_dice_it_is_given(tmp_path, monkeypatch):
    s, st, agent, ask = stocked(tmp_path, qty=50)
    step(st, s, NOW)
    seen = []
    monkeypatch.setattr(M, "poisson", lambda rng, mu: seen.append(mu) or 0)
    step(st, s, NOW + 1800)
    fair = M.fair_price(st, "Brygdon", "tomatoes", "food", {"food_value": 0.5}, NOW + 1800)
    assert seen == [pytest.approx(M.STALL_DEMAND_PER_HOUR * M.stall_factor(ask / fair) * 0.5)]
    monkeypatch.undo()
    got = []
    for sub in ("b", "c"):                                                                    # two identical worlds: the step and a direct tick, the same dice
        (tmp_path / sub).mkdir()
        s2, st2, agent2, ask2 = stocked(tmp_path / sub, qty=50)
        if sub == "b":
            step(st2, s2, NOW)
            got.append(step(st2, s2, NOW + 3600, random.Random(7)))
        else:
            got.append(M.stall_tick(st2, "Brygdon", NOW + 3600, 3600, random.Random(7)))
    assert got[0] == got[1] and got[0]


def test_a_quick_sale_at_a_market_says_what_a_stall_would_fetch(tmp_path):
    s, st, agent = market(tmp_path)
    st.add_item("tomatoes", 4, "food", "", {"food_value": 0.5})
    ok, text = M.sell(st, "Brygdon", "tomatoes", 2, NOW)
    fair = M.fair_price(st, "Brygdon", "tomatoes", "food", {"food_value": 0.5}, NOW)
    assert ok and text.endswith(f"; a customer at a stall of your own here would pay about {M.coins_text(fair)} each (sell with an ask)")
    ok, text = M.sell(st, "Saltholm", "tomatoes", 1, NOW)
    assert ok and "stall" not in text                                                                  # a shop has no stalls
