"""Markets and coins, phase 1 (docs/DESIGN-market.md): purses, engine-owned prices that move a little, a keeper's till, and buy/sell/pay."""
import time

import pytest

from app import market as M
from app import place_kinds as K
from app import places as P
from app import tools as T
from tests.test_invented_places import real_shop
from tests.test_projects import call, make

TRADE_TOOLS = ("buy", "sell", "pay", "browse", "eat")
DAY = 86400


def shop(tmp_path, **kw):
    """A fresh world with Pip standing in an open Saltholm (a real shop: wire, hooks, pliers, an awl, biscuits, kelp seeds)."""
    s, st, gm, agent = make(tmp_path, **kw)
    s.invented_places_per_day = 3
    real_shop(st)
    st.update_place("Saltholm", hours=[0, 24])
    agent.tools.update({n: T.REGISTRY[n] for n in TRADE_TOOLS})
    st.update_agent(location="Saltholm")
    return s, st, agent


# --- purses --------------------------------------------------------------------------------------------------------
def test_pip_starts_with_ten_coins_and_coins_never_go_negative(tmp_path):
    s, st, *_ = make(tmp_path)
    assert st.coins() == 10
    st.add_coins("pip", 5)
    assert st.coins() == 15 and st.coins("Mr Teague") == 0
    with pytest.raises(ValueError):
        st.add_coins("pip", -16)
    assert st.coins() == 15
    st.add_coins("pip", -15)
    assert st.coins() == 0


# --- base prices ---------------------------------------------------------------------------------------------------
def test_base_prices_come_from_the_item_and_never_below_one():
    assert M.base_price("tomatoes", "food", {"food_value": 0.5}) == 5
    assert M.base_price("carrots", "food", {"food_value": 0.4}) == 4
    assert M.base_price("peas", "food", {"food_value": 0.01}) == 1
    assert M.base_price("tomato seeds", "seed", {"yield": 3, "food_value": 0.5}) == 3
    assert M.base_price("needle file", "tool", {}) == 12
    assert M.base_price("sticks", "material", {}, weight=30) == 1
    assert M.base_price("fine brass gears", "material", {}, weight=5) == 6
    assert M.base_price("mystery", "material", {}) == 3
    assert M.base_price("mystery", "material", {}, weight=1) == 12            # the dearest a find can be
    assert M.base_price("junk", "creature", {}) == 3                           # an unknown kind still has a price


def test_the_daily_mood_is_deterministic_and_small():
    assert M.mood("Saltholm", "awl", "2026-11-02") == M.mood("Saltholm", "awl", "2026-11-02")
    moods = {M.mood("Saltholm", f"item{i}", f"2026-11-{d:02d}") for i in range(10) for d in range(1, 29)}
    assert min(moods) >= 0.92 and max(moods) <= 1.08 and len(moods) > 5


# --- prices move with trade ----------------------------------------------------------------------------------------
def test_local_price_rises_when_the_booth_sells_falls_when_it_buys_and_drifts_back(tmp_path):
    s, st, agent = shop(tmp_path)
    now = time.time()
    assert M.local(st, "Saltholm", "awl", now) == 1.0
    M.nudge(st, "Saltholm", "awl", +3, now)
    assert M.local(st, "Saltholm", "awl", now) == pytest.approx(1.04 ** 3)
    M.nudge(st, "Saltholm", "awl", -10, now)
    assert M.local(st, "Saltholm", "awl", now) == pytest.approx(1.04 ** 3 * 0.96 ** 10)
    M.nudge(st, "Saltholm", "awl", +200, now)
    assert M.local(st, "Saltholm", "awl", now) == 1.6                             # never above 1.6...
    M.nudge(st, "Saltholm", "awl", -400, now)
    assert M.local(st, "Saltholm", "awl", now) == 0.6                             # ...or below 0.6
    assert M.local(st, "Saltholm", "awl", now + DAY) == pytest.approx(1 - 0.4 * 0.9)
    assert M.local(st, "Saltholm", "awl", now + 30 * DAY) == pytest.approx(1, abs=0.02)


def test_buying_costs_the_price_moves_it_and_fills_the_till(tmp_path):
    s, st, agent = shop(tmp_path)
    now = time.time()
    table = {e[0]: e for e in __import__("app.finds", fromlist=["x"]).loot_for(st, "Saltholm")}
    unit = M.sell_price(st, "Saltholm", table["brass wire"], now)
    till_before = M.till(st, "Saltholm", now)
    ok, text = M.buy(st, "Saltholm", "brass wire", 1, now)
    assert ok and f"{unit} coin" in text
    assert st.coins() == 10 - unit and st.find_item("brass wire")[0]["qty"] == 1
    assert M.till(st, "Saltholm", now) == till_before + unit
    assert M.local(st, "Saltholm", "brass wire", now) == pytest.approx(1.04)


def test_you_cannot_buy_what_the_booth_does_not_keep_or_more_than_you_can_afford(tmp_path):
    s, st, agent = shop(tmp_path)
    now = time.time()
    ok, text = M.buy(st, "Saltholm", "a unicorn", 1, now)
    assert not ok and "doesn't keep" in text
    st.add_coins("pip", -10)
    ok, text = M.buy(st, "Saltholm", "awl", 1, now)
    assert not ok and "0 coins" in text and st.find_item("awl")[0] is None
    st.add_coins("pip", 9)
    ok, text = M.buy(st, "Saltholm", "awl", 1, now)
    assert not ok and "can't afford" in text                                       # an awl costs more than 9


def test_a_booth_runs_out_for_the_day_and_restocks_tomorrow(tmp_path):
    s, st, agent = shop(tmp_path)
    now = time.time()
    st.add_coins("pip", 10_000)
    sold = 0
    while True:
        ok, text = M.buy(st, "Saltholm", "awl", 1, now)
        if not ok:
            break
        sold += 1
    assert 1 <= sold <= 4 and "out of" in text                                    # rare things: only a few a day
    ok, _ = M.buy(st, "Saltholm", "awl", 1, now + DAY)
    assert ok


def test_buying_several_raises_the_price_as_you_go(tmp_path):
    s, st, agent = shop(tmp_path)
    now = time.time()
    st.add_coins("pip", 1000)
    one = M.quote_buy(st, "Saltholm", "brass wire", 1, now)
    many = M.quote_buy(st, "Saltholm", "brass wire", 6, now)
    assert many >= 6 * one                                                           # never cheaper than a unit at a time


def test_selling_pays_less_than_buying_costs_lowers_the_price_and_empties_the_till(tmp_path):
    s, st, agent = shop(tmp_path)
    now = time.time()
    st.add_item("tomatoes", 100, "food", "", {"food_value": 0.5})
    ok, text = M.sell(st, "Saltholm", "tomatoes", 2, now)
    assert ok and "6 coins" in text and st.coins() == 10 + 6 and st.find_item("tomatoes")[0]["qty"] == 98
    assert M.local(st, "Saltholm", "tomatoes", now) == pytest.approx(0.96 ** 2)
    assert M.till(st, "Saltholm", now) == M.TILL_PER_DAY["shop"] - 6
    ok, text = M.sell(st, "Saltholm", "tomatoes", 100, now)                          # the till runs dry well before 98
    assert ok and 0 < st.find_item("tomatoes")[0]["qty"] < 98 and "till" in text
    assert M.till(st, "Saltholm", now) < 3
    ok, text = M.sell(st, "Saltholm", "tomatoes", 1, now)
    assert not ok and "till" in text
    assert M.till(st, "Saltholm", now + DAY) == M.TILL_PER_DAY["shop"]               # a new day, a full till


def test_a_buy_then_a_sell_back_loses_money(tmp_path):
    s, st, agent = shop(tmp_path)
    now = time.time()
    st.add_coins("pip", 100)
    before = st.coins()
    assert M.buy(st, "Saltholm", "brass wire", 5, now)[0]
    assert M.sell(st, "Saltholm", "brass wire", 5, now)[0]
    assert st.coins() < before


def test_you_cannot_sell_what_you_do_not_have(tmp_path):
    s, st, agent = shop(tmp_path)
    ok, text = M.sell(st, "Saltholm", "tomatoes", 1, time.time())
    assert not ok and "don't have" in text


# --- what is owed on account ---------------------------------------------------------------------------------------
def test_pay_settles_what_is_on_account_at_todays_prices(tmp_path):
    s, st, agent = shop(tmp_path)
    now = time.time()
    ok, text = M.pay(st, "Saltholm", now)
    assert not ok and "nothing" in text
    st.update_place("Saltholm", on_account={"brass wire": 2})
    unit = M.sell_price(st, "Saltholm", next(e for e in __import__("app.finds", fromlist=["x"]).loot_for(st, "Saltholm")
                                                  if e[0] == "brass wire"), now)
    assert M.owed(st, "Saltholm", now) == 2 * unit
    st.add_coins("pip", -9)
    ok, text = M.pay(st, "Saltholm", now)
    assert not ok and "owe" in text and st.place_row("Saltholm")["on_account"] == {"brass wire": 2}
    st.add_coins("pip", 20)
    coins = st.coins()
    ok, text = M.pay(st, "Saltholm", now)
    assert ok and st.coins() == coins - 2 * unit and st.place_row("Saltholm")["on_account"] == {}


# --- the tools, offered only where there is a booth ----------------------------------------------------------------
@pytest.mark.asyncio
async def test_the_trade_tools_work_at_a_shop_through_the_registry(tmp_path):
    s, st, agent = shop(tmp_path)
    r = await call(agent, "buy", item="brass wire", quantity=1)
    assert "bought" in r.text and st.find_item("brass wire")[0]["qty"] == 1
    st.add_item("tomatoes", 3, "food", "", {"food_value": 0.5})
    r = await call(agent, "sell", item="tomatoes", quantity=3)
    assert "sold" in r.text
    r = await call(agent, "pay")
    assert "nothing" in r.text
    r = await call(agent, "buy", item="brass wire", quantity=0)
    assert r.text.startswith("error")
    r = await call(agent, "sell", item="tomatoes")
    assert r.text.startswith("error") or "don't have" in r.text


@pytest.mark.asyncio
async def test_trade_tools_are_refused_away_from_a_booth_and_listed_at_one(tmp_path):
    s, st, agent = shop(tmp_path)
    tools = {n: T.REGISTRY[n] for n in ("buy", "sell", "pay", "say", "tend")}
    listed = lambda key: sorted(x.name for x in T.specs_for(tools, key, P.registry(st, s, None)[key], True))  # noqa: E731
    assert listed("Saltholm") == ["buy", "pay", "say", "sell"]
    assert "buy" not in listed("workshop")
    st.update_agent(location="workshop")
    r = await call(agent, "buy", item="awl")
    assert "go_to" in r.text


def test_shops_and_markets_trade_and_other_kinds_do_not():
    assert K.KINDS["shop"].trades and K.KINDS["market"].trades
    assert not any(K.KINDS[k].trades for k in ("wild", "yard", "sight"))
    assert K.guess("a bazaar by the quay") == "market"
    assert K.KINDS["market"].shop_hours and set(K.KINDS["market"].verbs) == {"browse"}
    assert set(M.TILL_PER_DAY) == {"shop", "market", "neighbor", "stall"} and M.TILL_PER_DAY["market"] > M.TILL_PER_DAY["shop"] > M.TILL_PER_DAY["stall"] > M.TILL_PER_DAY["neighbor"]


def test_browse_at_a_shop_shows_todays_prices_and_your_purse(tmp_path):
    import asyncio
    s, st, agent = shop(tmp_path)
    st.set_meta(**{"stock:Saltholm": 40, "stock_at:Saltholm": time.time()})
    r = asyncio.run(call(agent, "browse"))
    assert "coins" in r.text and "brass wire" in r.text and "buy" in r.text


# --- Pip is told ---------------------------------------------------------------------------------------------------
def test_perception_shows_the_purse_once_trade_tools_are_enabled(tmp_path):
    s, st, agent = shop(tmp_path)
    assert "Coins: 10" in "\n".join(agent._belongings())
    del agent.tools["buy"], agent.tools["sell"], agent.tools["pay"]
    assert "Coins" not in "\n".join(agent._belongings())


# --- exact arithmetic, on a fixed day and a small table ---------------------------------------------------------------
NOW = time.mktime((2026, 3, 5, 12, 0, 0, 0, 0, -1))
TODAY = "2026-03-05"
TABLE = [["brass wire", "material", 5, [1, 2], "wire", {}],
         ["kelp seeds", "seed", 8, [1, 3], "kelp", {"crop": "kelp", "grow_minutes": 999, "yield": 2, "food_value": 0.3}],
         ["awl", "tool", 3, [1, 1], "an awl", {}]]


def booth(tmp_path):
    s, st, agent = shop(tmp_path)
    st.update_place("Saltholm", loot=TABLE)
    return st


def priced(base, place="Saltholm", item="brass wire", local=1.0, day=TODAY):
    return max(1, round(base * local * M.mood(place, item, day)))


def test_a_day_is_named_year_month_day_in_local_time():
    assert M.day_of(NOW) == TODAY


def test_base_prices_in_detail():
    assert M.base_price("x", "food", {}) == 3 and M.base_price("x", "food", {"food_value": 0.9}) == 9
    assert M.base_price("x", "seed", {}) == 2 and M.base_price("x", "seed", {"yield": 5, "food_value": 0.5}) == 5
    assert M.base_price("x", "seed", {"yield": 0, "food_value": 0}) == 1
    assert M.base_price("x", "material", {}, weight=12) == 2 and M.base_price("x", "material", {}, weight=20) == 2
    assert M.base_price("x", "material", {}, weight=4) == 8


def test_the_mood_is_the_documented_hash_and_ignores_plurals():
    import zlib
    want = 1 + (zlib.crc32(b"Saltholm|awl|2026-03-05") % 17 - 8) / 100
    assert M.mood("Saltholm", "awl", TODAY) == want == M.mood("Saltholm", "awls", TODAY)
    assert M.mood("Saltholm", "awl", TODAY) != M.mood("Elsewhere", "awl", TODAY) or M.mood("Saltholm", "hook", TODAY) != want


def test_a_thing_not_in_the_booths_table_is_priced_by_where_it_is_found(tmp_path):
    st = booth(tmp_path)
    st.add_item("sticks", 40, "material", "")
    ok, text = M.sell(st, "Saltholm", "sticks", 1, NOW)                          # woods sticks have weight 30: 1 coin to the booth
    assert ok and "for 1 coin " in text
    st.add_item("mystery", 1, "material", "")
    ok, text = M.sell(st, "Saltholm", "mystery", 1, NOW)                         # unknown: 3 coins base, 60% of that
    assert ok and "for 1 coin " in text


def test_prices_use_the_booths_own_table_weight(tmp_path):
    st = booth(tmp_path)
    st.add_item("brass wire", 1, "material", "")                                  # junkyard weight 20 -> 2; this booth says 5 -> 6
    ok, text = M.sell(st, "Saltholm", "brass wire", 1, NOW)
    assert ok and f"for {M.coins_text(max(1, int(priced(6) * 0.6)))} " in text


def test_a_name_matches_exactly_before_partly(tmp_path):
    table = [("brass wire", "material", 5, (1, 2), "w", {}), ("wire", "material", 5, (1, 2), "w", {})]
    assert M._entry(table, "wire")[0] == "wire" and M._entry(table, "brass wires")[0] == "brass wire"
    assert M._entry(table[:1], "wire")[0] == "brass wire"                        # part of a name
    assert M._entry(table[:1], "some brass wire please")[0] == "brass wire"      # a name inside the words
    assert M._entry(table, "") is None and M._entry(table, "unicorn") is None


def test_the_till_depends_on_the_kind_of_place_and_a_missing_place_is_a_shop(tmp_path):
    s, st, agent = shop(tmp_path)
    st.add_place("Quay", "the quay", kind="market", status="real", created_at=NOW, heard_at=NOW)
    assert M.till(st, "Quay", NOW) == 80 and M.till(st, "Saltholm", NOW) == 40 and M.till(st, "Nowhere", NOW) == 40
    assert st.till_row("Quay")["day"] == TODAY
    st.set_till("Quay", 7, "2026-03-04")
    assert M.till(st, "Quay", NOW) == 80                                           # yesterday's coins are gone
    st.set_till("Quay", 7, TODAY)
    assert M.till(st, "Quay", NOW) == 7


def test_stock_is_a_day_of_twice_the_biggest_haul_and_resets_each_day(tmp_path):
    st = booth(tmp_path)
    wire, kelp, awl = TABLE
    assert [M.stock_target(e) for e in (wire, kelp, awl)] == [4, 6, 2]
    st.add_coins("pip", 1000)
    assert M.stock_left(st, "Saltholm", awl, NOW) == 2
    assert M.buy(st, "Saltholm", "awl", 1, NOW)[0]
    assert M.stock_left(st, "Saltholm", awl, NOW) == 1
    assert M.buy(st, "Saltholm", "awl", 1, NOW)[0]                                 # the last one can still be bought
    assert M.stock_left(st, "Saltholm", awl, NOW) == 0
    assert M.stock_left(st, "Saltholm", awl, NOW + DAY) == 2
    assert M.nudge(st, "Saltholm", "awl", 1, NOW + DAY) is None and st.price_row("Saltholm", "awl")["sold_today"] == 0
    assert st.price_row("Saltholm", "awl")["day"] == "2026-03-06"


def test_buying_in_detail(tmp_path):
    st = booth(tmp_path)
    one = priced(6)
    assert M.quote_buy(st, "Saltholm", "brass wire", 1, NOW) == one
    st.add_coins("pip", 5)                                                           # 15 coins in all
    ok, text = M.buy(st, "Saltholm", "brass wire", 1, NOW)
    assert ok and text == f"you bought 1 brass wire for {M.coins_text(one)} ({15 - one} left)"
    assert st.find_item("brass wire")[0]["qty"] == 1 and st.coins() == 15 - one
    assert M.till(st, "Saltholm", NOW) == 40 + one and st.till_row("Saltholm")["day"] == TODAY


def test_buying_exactly_what_you_can_afford_works_and_one_more_does_not(tmp_path):
    st = booth(tmp_path)
    price = M.quote_buy(st, "Saltholm", "awl", 1, NOW)
    st.add_coins("pip", price - 10)                                                # leaves exactly `price`
    ok, text = M.buy(st, "Saltholm", "awl", 1, NOW)
    assert ok and st.coins() == 0 and text == f"you bought 1 awl for {M.coins_text(price)} (0 left)"
    st.add_coins("pip", 5)
    ok, text = M.buy(st, "Saltholm", "awl", 1, NOW)
    assert not ok and text == f"you can't afford awl: it's {M.quote_buy(st, 'Saltholm', 'awl', 1, NOW)} coins each and you have 5 coins"


def test_the_bought_thing_keeps_the_booths_description_and_attributes(tmp_path):
    st = booth(tmp_path)
    assert M.buy(st, "Saltholm", "kelp seeds", 2, NOW)[0]
    item = st.find_item("kelp seeds")[0]
    assert item["kind"] == "seed" and item["description"] == "kelp" and item["attrs"]["grow_minutes"] == 999


def test_quotes_for_several_units_climb_four_percent_a_unit(tmp_path):
    st = booth(tmp_path)
    want = sum(priced(6, local=1.04 ** i) for i in range(4))
    assert M.quote_buy(st, "Saltholm", "brass wire", 4, NOW) == want
    assert M.quote_buy(st, "Saltholm", "unicorn", 1, NOW) is None
    st.set_price_row("Saltholm", "brass wire", 1.55, NOW, TODAY, 0)                # near the ceiling: the climb stops at 1.6
    assert M.quote_buy(st, "Saltholm", "brass wire", 3, NOW) == sum(priced(6, local=v) for v in (1.55, 1.6, 1.6))


def test_a_buy_wants_a_whole_day_of_stock_when_asked_for_more_it_sells_what_is_left(tmp_path):
    st = booth(tmp_path)
    st.add_coins("pip", 1000)
    ok, text = M.buy(st, "Saltholm", "awl", 5, NOW)
    assert ok and "bought 2 awl" in text


def test_selling_in_detail(tmp_path):
    st = booth(tmp_path)
    st.add_item("tomatoes", 10, "food", "", {"food_value": 0.5})
    ok, text = M.sell(st, "Saltholm", "tomatoes", 3, NOW)                          # on this day the units pay 3, 2 and 2: each sale lowers the next
    assert ok and text == "you sold 3 tomatoes for 7 coins (17 now)"
    assert st.price_row("Saltholm", "tomato")["local"] == pytest.approx(0.96 ** 3)
    assert M.till(st, "Saltholm", NOW) == 33 and st.find_item("tomatoes")[0]["qty"] == 7


def test_a_till_of_exactly_one_units_pay_still_pays_it(tmp_path):
    st = booth(tmp_path)
    st.add_item("tomatoes", 10, "food", "", {"food_value": 0.5})
    st.set_till("Saltholm", 3, TODAY)
    ok, text = M.sell(st, "Saltholm", "tomatoes", 1, NOW)
    assert ok and text == "you sold 1 tomatoes for 3 coins (13 now)" and M.till(st, "Saltholm", NOW) == 0


def test_the_till_pays_what_it_can_and_says_what_is_left_over(tmp_path):
    st = booth(tmp_path)
    st.add_item("tomatoes", 10, "food", "", {"food_value": 0.5})
    st.set_till("Saltholm", 7, TODAY)
    ok, text = M.sell(st, "Saltholm", "tomatoes", 4, NOW)                          # the units pay 3, 2, 2, 2: the till covers three
    assert ok and text == "you sold 3 tomatoes for 7 coins (that's all the till could pay; 1 left over) (17 now)"
    assert M.till(st, "Saltholm", NOW) == 0 and st.find_item("tomatoes")[0]["qty"] == 7
    ok, text = M.sell(st, "Saltholm", "tomatoes", 1, NOW)
    assert not ok and text == "Saltholm's till is empty for today; try tomorrow"


def test_what_is_owed_adds_up_and_unlisted_things_cost_three(tmp_path):
    st = booth(tmp_path)
    st.update_place("Saltholm", on_account={"brass wire": 2, "awl": 1, "mystery": 2})
    assert M.owed(st, "Saltholm", NOW) == 2 * priced(6) + priced(12, item="awl") + 2 * 3
    assert M.owed(st, "Elsewhere", NOW) == 0


def test_paying_in_detail(tmp_path):
    st = booth(tmp_path)
    st.update_place("Saltholm", on_account={"awl": 1})
    price = priced(12, item="awl")
    st.add_coins("pip", price - 10)                                                # exactly enough
    ok, text = M.pay(st, "Saltholm", NOW)
    assert ok and text == f"you paid {price} coins for what was on account at Saltholm (0 left)"
    assert M.till(st, "Saltholm", NOW) == 40 + price and st.place_row("Saltholm")["on_account"] == {}
    st.update_place("Saltholm", on_account={"awl": 1})
    ok, text = M.pay(st, "Saltholm", NOW)
    assert not ok and text == f"you owe Saltholm {price} coins and have 0 coins"
    assert M.pay(st, "Elsewhere", NOW) == (False, "you owe Elsewhere nothing")


def test_coins_are_counted_in_the_singular_too():
    assert [M.coins_text(n) for n in (0, 1, 2)] == ["0 coins", "1 coin", "2 coins"]


def test_a_junkyard_thing_sold_at_a_shop_is_priced_by_its_junkyard_weight(tmp_path):
    st = booth(tmp_path)
    st.add_item("clock parts", 1, "material", "")                                  # weight 4 at the junkyard: base 8
    ok, text = M.sell(st, "Saltholm", "clock parts", 1, NOW)
    pay = int(priced(8, item="clock parts") * 0.6)
    assert ok and text == f"you sold 1 clock parts for {M.coins_text(pay)} ({10 + pay} now)"


def test_the_cheapest_price_is_one_coin_and_a_things_attributes_set_its_price(tmp_path):
    st = booth(tmp_path)
    sticks = ("sticks", "material", 30, (1, 2), "s", {})
    assert M.sell_price(st, "Saltholm", sticks, NOW) == 1
    cake = ("cake", "food", 5, (1, 2), "c", {"food_value": 0.9})
    assert M.sell_price(st, "Saltholm", cake, NOW) == priced(9, item="cake")
    st.update_place("Saltholm", loot=[list(sticks[:3]) + [[1, 2], "s", {}], list(cake[:3]) + [[1, 2], "c", {"food_value": 0.9}]])
    assert M.quote_buy(st, "Saltholm", "sticks", 1, NOW) == 1
    assert M.quote_buy(st, "Saltholm", "cake", 1, NOW) == priced(9, item="cake")


def test_what_a_sale_buy_or_payment_puts_in_the_till_is_added_to_what_is_already_there(tmp_path):
    st = booth(tmp_path)
    st.add_item("tomatoes", 10, "food", "", {"food_value": 0.5})
    assert M.sell(st, "Saltholm", "tomatoes", 3, NOW)[0]                            # the till pays out 7: 33 left
    st.add_coins("pip", 100)
    one = M.quote_buy(st, "Saltholm", "awl", 1, NOW)
    assert M.buy(st, "Saltholm", "awl", 1, NOW)[0]
    assert M.till(st, "Saltholm", NOW) == 33 + one
    st.update_place("Saltholm", on_account={"awl": 1})
    debt = M.owed(st, "Saltholm", NOW)
    assert M.pay(st, "Saltholm", NOW)[0]
    assert M.till(st, "Saltholm", NOW) == 33 + one + debt
