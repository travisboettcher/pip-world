"""Trade (docs/DESIGN-world-packs.md, phase 5c): the shipped `trade` module (module_library/trade.py): booths and prices, a keeper's
till, buy/sell/pay, the agent's stall and its customers, things on account, and the neighbours' wares and market days."""
import asyncio
import random
import time
import zlib
from datetime import datetime

import pytest

from app import modules as M
from app import places as P
from app import tools as T
from app import world_view as WV
from app.llm.base import ToolCall
from tests.test_projects import FixedRng, make

NOW = time.mktime((2026, 3, 5, 12, 0, 0, 0, 0, -1))      # a Thursday, at noon
TODAY, DAY, HOUR = "2026-03-05", 86400, 3600
LOOT = [["brass wire", "material", 5, [1, 2], "wire", {}], ["tomatoes", "food", 12, [2, 4], "ripe tomatoes", {"food_value": 0.5}],
        ["awl", "tool", 3, [1, 1], "an awl", {}]]
WARES = [{"name": "cork floats", "kind": "material", "description": "floats off the flats", "per_day": 2},
         {"name": "carrot seeds", "kind": "seed", "description": "from her tin", "per_day": 1},
         {"name": "driftwood", "kind": "material", "description": "grey and smooth", "per_day": 3}]


def code():
    out = {}
    exec(M.library("trade")[1], out)
    return out


G = code()


def slot(*parts):
    return G["slot"](*parts)


def module(st, **params):
    from tests.test_modules import live
    man, src = M.library("trade")
    man.pop("reason", None)
    return live(st, {**man, "params": {**man["params"], "wares": "off", **params}}, src, author=M.SHIPPED)


def world(tmp_path, where="Brygdon", **kw):
    """Pip at an open market, Brygdon (with a shop, Saltholm, to compare: both keep LOOT), with trade live."""
    s, st, gm, agent = make(tmp_path, modules="on", module_runner="local", **kw)
    for key, kind in (("Brygdon", "market"), ("Saltholm", "shop")):
        st.add_place(key, key.lower(), kind=kind, status="real", created_at=NOW, heard_at=NOW, hours=[0, 24], daylight_only=0, walk_minutes=10.0,
                     loot=LOOT, verbs={"browse": ["see", None]})
    st.update_agent(location=where)
    module(st)
    return s, st, agent


def trade(st):
    return M.live_named(st, "trade")


async def use(st, s, tool, now=NOW, **args):
    """The agent uses one of trade's tools (at a fixed time)."""
    m = trade(st)
    return (await M.use_tool(st, s, None, m, next(t for t in m["manifest"]["tools"] if t["name"] == tool), args, now))[0]


async def run(agent, name, **args):
    """A tool as the agent uses it (the engine's, or a module's where one applies): what it says."""
    return (await agent._run_tool(ToolCall(id="1", name=name, arguments=args), 0))["content"]


def view(st, s, now=NOW):
    """Trade as one call sees it: its Market over the context the engine hands it."""
    return G["Market"](M.context(st, s, trade(st), now))


def priced(base, place="Brygdon", item="brass wire", local=1.0, day=TODAY):
    return max(1, round(base * local * G["mood"](place, item, day)))


def account(st, place):
    return ((st.store("trade").get("accounts") or {}).get(slot(place)) or {}).get("items") or {}


def stall(st, place="Brygdon"):
    return sorted((r for r in (st.store("trade").get("stall") or {}).values() if r["place"] == place), key=lambda r: r["item"])


async def tick(st, s, now=NOW):
    await M.step(st, s, None, now)


def moments(st, moment):
    return [e["data"] for e in st.events(300) if e["kind"] == "module" and e["data"].get("moment") == moment]


# --- the small things ---------------------------------------------------------------------------------------------------------------
def test_its_crc32_is_zlibs_and_its_days_are_local():
    assert all(G["crc32"](t) == zlib.crc32(t.encode()) for t in ("", "Marigold", "Saltholm|awl|2026-11-02", "é ü"))
    for now in (NOW, NOW + 13 * HOUR, 1e9, time.time()):
        t = datetime.fromtimestamp(now)
        off = round(t.astimezone().utcoffset().total_seconds())
        assert G["day_of"](now, off) == t.strftime("%Y-%m-%d") and G["weekday_hour"](now, off) == (t.weekday(), t.hour)
    assert G["day_of"](0) == "1970-01-01" and G["slot"]("a", "b") == "%08x" % zlib.crc32(b"a|b")


def test_base_prices_come_from_the_thing():
    bp = G["base_price"]
    assert bp("x", "food", {}) == 3 and bp("x", "food", {"food_value": 0.9}) == 9 and bp("peas", "food", {"food_value": 0.01}) == 1
    assert bp("x", "seed", {}) == 2 and bp("x", "seed", {"yield": 5, "food_value": 0.5}) == 5 and bp("x", "seed", {"yield": 0, "food_value": 0}) == 1
    assert bp("x", "tool", {}) == 12 and bp("x", "material", {}) == 3 and bp("x", "material", {}, weight=1) == 12
    assert bp("x", "material", {}, weight=30) == 1 and bp("x", "material", {}, weight=12) == 2 and bp("x", "material", {}, weight=4) == 8
    assert bp("x", "creation", {"quality": "masterwork"}) == 40 and bp("x", "creation", {}) == 8
    assert bp("x", "work", {"work": "drawing"}) == 4 and bp("x", "work", {}) == 3 and bp("x", "creature", {}) == 3


def test_the_daily_mood_is_the_documented_hash_and_ignores_plurals():
    want = 1 + (zlib.crc32(b"Saltholm|awl|2026-03-05") % 17 - 8) / 100
    assert G["mood"]("Saltholm", "awl", TODAY) == want == G["mood"]("Saltholm", "awls", TODAY)
    moods = {G["mood"]("Saltholm", f"item{i}", f"2026-11-{d:02d}") for i in range(10) for d in range(1, 29)}
    assert min(moods) >= 0.92 and max(moods) <= 1.08 and len(moods) > 5


def test_a_name_matches_exactly_before_partly():
    table = [("brass wire", "material", 5, (1, 2), "w", {}), ("wire", "material", 5, (1, 2), "w", {})]
    e = G["entry_of"]
    assert e(table, "wire")[0] == "wire" and e(table, "brass wires")[0] == "brass wire" and e(table[:1], "wire")[0] == "brass wire"
    assert e(table[:1], "some brass wire please")[0] == "brass wire" and e(table, "") is None and e(table, "unicorn") is None


@pytest.mark.parametrize("ratio,factor", [(0.5, 1.25), (1.0, 1.0), (1.3, 0.5), (1.6, 0.0), (3.0, 0.0)])
def test_the_dearer_the_ask_the_fewer_customers_stop(ratio, factor):
    assert G["stall_factor"](ratio) == pytest.approx(factor)


def test_a_poisson_count_has_the_right_mean():
    rng = random.Random(4)
    assert sum(G["poisson"](rng, 2.0) for _ in range(4000)) / 4000 == pytest.approx(2.0, rel=0.05)
    assert G["poisson"](rng, 0) == 0 and G["poisson"](rng, -1) == 0


def test_coins_are_counted_in_the_singular_too():
    from app.text import coins_text
    assert [G["coins_text"](n) for n in (0, 1, 2)] == [coins_text(n) for n in (0, 1, 2)] == ["0 coins", "1 coin", "2 coins"]


# --- the module as shipped -----------------------------------------------------------------------------------------------------------
def test_it_ships_with_the_setting_as_its_param_and_replaces_the_engines_market():
    from app.config import Settings
    man, _ = M.library("trade")
    assert M.settings_params(Settings(character_booths="on"), "trade", man["params"]) == {"wares": "on"}
    assert "trade" in M.RULES and "stall-customers" not in M.RULES and M.RULES.index("trade") < M.RULES.index("happenings")
    assert {t["name"] for t in man["tools"]} == {"browse", "buy", "sell", "pay"} and set(man["answers"]) == {"owe", "price"}
    assert not {"buy", "sell", "pay"} & set(T.SCOPES) and not {"sell", "owe"} & set(M.PROPOSES) and "stalls" not in M.READS


async def test_its_tools_are_offered_at_shops_markets_and_neighbours_and_nowhere_else(tmp_path):
    from tests.test_neighbor import neighbor
    s, st, agent = world(tmp_path)
    neighbor(st, s)
    names = lambda key: sorted(sp.name for sp in T.module_specs(st, key, P.registry(st, s, None)[key], True))  # noqa: E731
    assert names("Brygdon") == ["browse", "buy", "pay", "sell"] and names("Saltholm") == ["browse", "buy", "pay", "sell"]
    assert names("Marigold's home") == ["browse", "buy", "sell"] and names("woods") == [] and names(P.HOME) == []
    st.update_agent(location="woods")
    r = (await agent._run_tool(ToolCall(id="1", name="buy", arguments={"item": "awl"}), 0))["content"]
    assert r == "there's nothing to buy at the woods"


# --- buying ----------------------------------------------------------------------------------------------------------------------------
async def test_buying_in_detail(tmp_path):
    s, st, agent = world(tmp_path, where="Saltholm")
    one = priced(6, "Saltholm")
    st.add_coins("pip", 5)                                                           # 15 coins in all
    assert await use(st, s, "buy", item="brass wire") == f"you bought 1 brass wire for {G['coins_text'](one)} ({15 - one} left)"
    assert st.find_item("brass wire")[0]["qty"] == 1 and st.coins() == 15 - one
    v = view(st, s)
    assert v.till("Saltholm") == 40 + one and v.local("Saltholm", "brass wire") == pytest.approx(1.04)
    assert st.store("trade")["tills"][slot("Saltholm")]["day"] == TODAY


async def test_you_cannot_buy_what_isnt_kept_more_than_you_can_afford_or_none(tmp_path):
    s, st, agent = world(tmp_path, where="Saltholm")
    assert await use(st, s, "buy", item="a unicorn") == "error: Saltholm doesn't keep 'a unicorn'"
    price = view(st, s).quote("Saltholm", G["entry_of"](LOOT, "awl"), 1)
    st.add_coins("pip", price - 10)                                                 # exactly enough
    assert await use(st, s, "buy", item="awl") == f"you bought 1 awl for {G['coins_text'](price)} (0 left)" and st.coins() == 0
    st.add_coins("pip", 5)
    again = view(st, s).quote("Saltholm", G["entry_of"](LOOT, "awl"), 1)
    assert await use(st, s, "buy", item="awl") == f"error: you can't afford awl: it's {again} coins each and you have 5 coins"
    assert await use(st, s, "buy", item="awl", quantity=0) == "error: quantity must be a whole number, at least 1"


async def test_a_booth_runs_out_for_the_day_and_restocks_tomorrow(tmp_path):
    s, st, agent = world(tmp_path, where="Saltholm")
    st.add_coins("pip", 1000)
    assert (await use(st, s, "buy", item="awl", quantity=5)).startswith("you bought 2 awl")      # a day's stock: twice the biggest haul
    assert await use(st, s, "buy", item="awl") == "error: Saltholm is out of awl today; they'll have more tomorrow"
    assert (await use(st, s, "buy", item="awl", now=NOW + DAY)).startswith("you bought 1 awl")
    v = view(st, s, NOW + DAY)
    assert [v.stock_left("Saltholm", e) for e in LOOT] == [4, 8, 1]


async def test_quotes_for_several_climb_four_percent_a_unit_up_to_the_ceiling(tmp_path):
    s, st, agent = world(tmp_path, where="Saltholm")
    wire = G["entry_of"](LOOT, "brass wire")
    assert view(st, s).quote("Saltholm", wire, 4) == sum(priced(6, "Saltholm", local=1.04 ** i) for i in range(4))
    st.merge_store("trade", {"prices": {slot("Saltholm", "brass wire"): {"booth": "Saltholm", "item": "brass wire", "local": 1.55, "at": NOW,
                                                                          "day": TODAY, "sold": 0}}})
    assert view(st, s).quote("Saltholm", wire, 3) == sum(priced(6, "Saltholm", local=x) for x in (1.55, 1.6, 1.6))


async def test_the_bought_thing_keeps_the_booths_description_and_attributes(tmp_path):
    s, st, agent = world(tmp_path, where="Saltholm")
    st.add_coins("pip", 50)
    await use(st, s, "buy", item="tomatoes", quantity=2)
    item = st.find_item("tomatoes")[0]
    assert item["kind"] == "food" and item["description"] == "ripe tomatoes" and item["attrs"] == {"food_value": 0.5}


# --- prices --------------------------------------------------------------------------------------------------------------------------
def test_a_local_price_moves_with_trade_stays_in_bounds_and_drifts_back(tmp_path):
    s, st, agent = world(tmp_path)
    v = view(st, s)
    assert v.local("Saltholm", "awl") == 1.0
    v.nudge("Saltholm", "awl", 3)
    assert v.local("Saltholm", "awl") == pytest.approx(1.04 ** 3)
    v.nudge("Saltholm", "awl", -10)
    assert v.local("Saltholm", "awl") == pytest.approx(1.04 ** 3 * 0.96 ** 10)
    v.nudge("Saltholm", "awl", 200)
    assert v.local("Saltholm", "awl") == 1.6
    v.nudge("Saltholm", "awl", -400)
    assert v.local("Saltholm", "awl") == 0.6
    v.now += DAY
    assert v.local("Saltholm", "awl") == pytest.approx(1 - 0.4 * 0.9)
    v.now += 29 * DAY
    assert v.local("Saltholm", "awl") == pytest.approx(1, abs=0.02)


def test_the_going_price_uses_the_booths_weight_then_the_worlds(tmp_path):
    s, st, agent = world(tmp_path)
    v = view(st, s)
    assert v.fair("Brygdon", "brass wire", "material", {}, LOOT) == priced(6)                                 # the booth's own weight: 30 / 5
    assert v.fair("Brygdon", "clock parts", "material", {}, LOOT) == priced(8, item="clock parts")            # the junkyard's
    assert v.fair("Brygdon", "mystery", "material", {}, LOOT) == priced(3, item="mystery")
    assert v.fair("Brygdon", "peas", "seed", {"yield": 4, "food_value": 0.4}, LOOT) == priced(3, item="peas")
    assert v.fair("Saltholm", "tomatoes", "food", {"food_value": 0.5}) == priced(5, "Saltholm", "tomatoes")
    assert v.sell_price("Brygdon", ["sticks", "material", 30, [1, 2], "s", {}]) == 1


def test_a_till_is_a_days_coins_by_the_kind_of_booth(tmp_path):
    s, st, agent = world(tmp_path)
    v = view(st, s)
    assert G["TILL"] == {"shop": 40, "market": 80, "neighbor": 20, "stall": 30}
    assert v.till("Brygdon") == 80 and v.till("Saltholm") == 40 and v.till("Nowhere") == 40
    assert v.till("Marigold's home") == 20 and v.till("Marigold's stall") == 30
    v.set_till("Brygdon", 7)
    assert v.till("Brygdon") == 7
    v.day = "2026-03-06"
    assert v.till("Brygdon") == 80                                                   # yesterday's coins are gone


# --- selling ---------------------------------------------------------------------------------------------------------------------------
async def test_selling_in_detail(tmp_path):
    s, st, agent = world(tmp_path, where="Saltholm")
    st.add_item("tomatoes", 10, "food", "", {"food_value": 0.5})
    assert await use(st, s, "sell", item="tomatoes", quantity=3) == "you sold 3 tomatoes for 7 coins (17 now)"     # 3, 2 and 2: each lowers the next
    v = view(st, s)
    assert v.local("Saltholm", "tomatoes") == pytest.approx(0.96 ** 3) and v.till("Saltholm") == 33 and st.find_item("tomatoes")[0]["qty"] == 7
    st.merge_store("trade", {"tills": {slot("Saltholm"): {"booth": "Saltholm", "day": TODAY, "coins": 5}}})
    assert await use(st, s, "sell", item="tomatoes", quantity=4) == "you sold 2 tomatoes for 4 coins (that's all the till could pay; 2 left over) (21 now)"
    assert await use(st, s, "sell", item="tomatoes") == "error: Saltholm's till is empty for today; try tomorrow"
    assert (await use(st, s, "sell", item="tomatoes", now=NOW + DAY)).startswith("you sold 1 tomatoes")


async def test_what_you_dont_have_cant_be_sold_and_a_vague_name_asks_which(tmp_path):
    s, st, agent = world(tmp_path, where="Saltholm")
    assert await use(st, s, "sell", item="tomatoes") == "error: you don't have 'tomatoes'"
    st.add_item("red wire", 1, "material", "")
    st.add_item("blue wire", 1, "material", "")
    assert await use(st, s, "sell", item="wire") == "error: which one? red wire, blue wire"


async def test_a_thing_not_kept_here_is_priced_by_where_it_is_found(tmp_path):
    s, st, agent = world(tmp_path, where="Saltholm")
    st.add_item("clock parts", 1, "material", "")                                  # weight 4 at the junkyard: base 8
    pay = int(priced(8, "Saltholm", "clock parts") * 0.6)
    assert await use(st, s, "sell", item="clock parts") == f"you sold 1 clock parts for {G['coins_text'](pay)} ({10 + pay} now)"


async def test_a_quick_sale_at_a_market_says_what_a_stall_would_fetch(tmp_path):
    s, st, agent = world(tmp_path)
    st.add_item("tomatoes", 5, "food", "", {"food_value": 0.5})
    fair = view(st, s).fair("Brygdon", "tomatoes", "food", {"food_value": 0.5}, LOOT)
    text = await use(st, s, "sell", item="tomatoes")
    assert text.endswith(f"; a customer at a stall of your own here would pay about {G['coins_text'](fair)} each (sell with an ask)")


async def test_a_buy_then_a_sell_back_loses_money(tmp_path):
    s, st, agent = world(tmp_path, where="Saltholm")
    st.add_coins("pip", 100)
    await use(st, s, "buy", item="brass wire", quantity=4)
    await use(st, s, "sell", item="brass wire", quantity=4)
    assert st.coins() < 110 and st.find_item("brass wire")[0] is None


# --- on account ------------------------------------------------------------------------------------------------------------------------
async def test_owe_puts_things_on_account_and_pay_settles_at_todays_prices(tmp_path):
    s, st, agent = world(tmp_path, where="Saltholm")
    assert await use(st, s, "pay") == "error: you owe Saltholm nothing"
    assert await M.ask_module(st, s, None, "trade", "owe", {"place": "Saltholm", "items": {"awl": 1}}, True, NOW) == "on account at Saltholm"
    await M.ask_module(st, s, None, "trade", "owe", {"place": "Saltholm", "items": {"awl": 1, "mystery": 2}}, True, NOW)
    assert account(st, "Saltholm") == {"awl": 2, "mystery": 2}
    debt = 2 * priced(12, "Saltholm", "awl") + 2 * 3
    assert view(st, s).owed("Saltholm", LOOT) == debt
    assert await use(st, s, "pay") == f"error: you owe Saltholm {debt} coins and have 10 coins"
    st.add_coins("pip", debt - 10)
    assert await use(st, s, "pay") == f"you paid {debt} coins for what was on account at Saltholm (0 left)"
    assert account(st, "Saltholm") == {} and view(st, s).till("Saltholm") == 40 + debt


@pytest.mark.parametrize("args", [{"items": {"w": 1}}, {"place": "Saltholm"}, {"place": "Saltholm", "items": {}}, {"place": "Saltholm", "items": {"w": 0}},
                                  {"place": "Saltholm", "items": {"w": 51}}, {"place": "Saltholm", "items": {"w": True}}, {"place": "Saltholm", "items": {" ": 1}},
                                  {"place": "Saltholm", "items": {f"t{i}": 1 for i in range(9)}}, {"place": "Saltholm", "items": ["w"]},
                                  {"place": "woods", "items": {"w": 1}}])
async def test_what_cant_be_owed(tmp_path, args):
    s, st, agent = world(tmp_path, where="Saltholm")
    with pytest.raises(M.Refused) as e:
        await M.ask_module(st, s, None, "trade", "owe", args, True, NOW)
    assert str(e.value) == ("`owe.place` is a place that trades" if args.get("place") == "woods" else "`owe` is {place, items: {name: qty}}: up to 8 things, 1 to 50 each")
    assert account(st, "Saltholm") == {}


# --- browsing --------------------------------------------------------------------------------------------------------------------------
async def test_browsing_a_shop_shows_some_of_its_stock_with_prices_and_whats_on_account(tmp_path):
    s, st, agent = world(tmp_path, where="Saltholm")
    await M.ask_module(st, s, None, "trade", "owe", {"place": "Saltholm", "items": {"awl": 1}}, True, NOW)
    first, owed = (await use(st, s, "browse")).split("\n")
    assert first.startswith("In stock at Saltholm today: ") and first.endswith(". You have 10 coins. buy what you need; gather to pick through the drawers on account.")
    assert owed == f"On account here: 1 awl ({priced(12, 'Saltholm', 'awl')} coins at today's prices; pay settles it)."
    st.update_agent(location="Brygdon")
    assert (await use(st, s, "browse")).endswith("sell what you have, or set out a stall with an ask.")


async def test_a_bare_shop_says_come_back(tmp_path):
    s, st, agent = world(tmp_path, where="Saltholm")
    st.add_coins("pip", 1000)
    for e in LOOT:
        await use(st, s, "buy", item=e[0], quantity=20)
    assert await use(st, s, "browse") == "The shelves at Saltholm are bare today; they restock slowly, so come back in a day or so."


# --- the agent's stall -----------------------------------------------------------------------------------------------------------------
async def test_goods_are_set_out_at_an_ask_and_leave_the_belongings(tmp_path):
    s, st, agent = world(tmp_path)
    st.add_item("tomatoes", 10, "food", "ripe", {"food_value": 0.5})
    fair = view(st, s).fair("Brygdon", "tomatoes", "food", {"food_value": 0.5}, LOOT)
    assert await use(st, s, "sell", item="tomatoes", quantity=6, ask=fair) == f"you set out 6 tomatoes at {G['coins_text'](fair)} each; the going price here is {fair}"
    assert st.find_item("tomatoes")[0]["qty"] == 4
    (row,) = stall(st)
    assert (row["name"], row["kind"], row["qty"], row["ask"], row["sold"], row["earned"], row["attrs"], row["description"]) == \
        ("tomatoes", "food", 6, fair, 0, 0, {"food_value": 0.5}, "ripe")
    assert (await use(st, s, "sell", item="tomatoes", quantity=3, ask=fair + 1)).startswith("you set out 3 tomatoes")
    assert (stall(st)[0]["qty"], stall(st)[0]["ask"]) == (9, fair + 1)
    assert (await use(st, s, "sell", item="tomatoes", ask=999)).endswith("; at that price nobody will stop") and st.find_item("tomatoes")[0] is None


async def test_what_cannot_be_set_out_says_why(tmp_path):
    s, st, agent = world(tmp_path)
    st.add_item("tomatoes", 3, "food", "", {"food_value": 0.5})
    assert await use(st, s, "sell", item="pears", ask=3) == "error: you don't have 'pears'"
    assert await use(st, s, "sell", item="tomatoes", ask=-4) == "error: an ask is a whole number of coins, at least 1"
    assert await use(st, s, "sell", item="tomatoes", ask=3, quantity=0) == "error: quantity must be a whole number, at least 1"
    st.update_agent(location="Saltholm")
    assert await use(st, s, "sell", item="tomatoes", ask=3) == "error: Saltholm is a shop: sell to its keeper (leave out the ask); stalls are for markets"
    assert st.find_item("tomatoes")[0]["qty"] == 3 and stall(st) == []
    st.update_agent(location="Brygdon")
    for n in ("alpha", "bravo", "charlie", "delta"):
        st.add_item(n, 1, "material", "")
    for n in ("alpha", "bravo", "charlie"):
        assert (await use(st, s, "sell", item=n, ask=3)).startswith("you set out")
    assert await use(st, s, "sell", item="delta", ask=3) == "error: your stall has room for 3 kinds of thing; take something back first"


async def test_a_zero_ask_takes_goods_back_whole(tmp_path):
    s, st, agent = world(tmp_path)
    st.add_item("tomatoes", 5, "food", "ripe", {"food_value": 0.5})
    await use(st, s, "sell", item="tomatoes", ask=4)
    assert await use(st, s, "sell", item="tomatoes", ask=0) == "you take 5 tomatoes back off the stall"
    item = st.find_item("tomatoes")[0]
    assert (item["qty"], item["kind"], item["attrs"], item["description"]) == (5, "food", {"food_value": 0.5}, "ripe") and stall(st) == []
    assert await use(st, s, "sell", item="tomatoes", ask=0) == "error: you have no tomatoes on the stall"


async def test_customers_stop_while_pip_is_there_and_pay_the_ask(tmp_path):
    s, st, agent = world(tmp_path)
    st.add_item("tomatoes", 10, "food", "", {"food_value": 0.5})
    fair = view(st, s).fair("Brygdon", "tomatoes", "food", {"food_value": 0.5}, LOOT)
    await use(st, s, "sell", item="tomatoes", ask=fair)
    await tick(st, s, NOW)                                                         # the first look only starts the clock
    assert stall(st)[0]["qty"] == 10
    for h in range(1, 11):
        await tick(st, s, NOW + h * HOUR)
    sold = sum(sum(i["qty"] for i in e["items"]) for e in moments(st, "stall_sale"))
    assert 1 <= sold <= G["STALL_DAILY_UNITS"] and st.coins() == 10 + sold * fair
    row = stall(st)[0]
    assert (row["qty"], row["sold"], row["earned"], row["sold_today"], row["day"]) == (10 - sold, sold, sold * fair, sold, TODAY)
    assert all(e["text"].startswith("At your stall you sold ") for e in moments(st, "stall_sale"))
    assert view(st, s, NOW + 10 * HOUR).local("Brygdon", "tomatoes") < 1


async def test_nobody_stops_at_a_silly_price_or_while_pip_is_away(tmp_path):
    s, st, agent = world(tmp_path)
    st.add_item("tomatoes", 10, "food", "", {"food_value": 0.5})
    await use(st, s, "sell", item="tomatoes", ask=999)
    for h in range(0, 6):
        await tick(st, s, NOW + h * HOUR)
    assert stall(st)[0]["qty"] == 10
    st.update_agent(location="woods")
    for h in range(6, 12):
        await tick(st, s, NOW + h * HOUR)
    assert stall(st)[0]["qty"] == 10 and trade(st)["fails"] == 0 and moments(st, "stall_sale") == []


async def test_the_market_only_takes_so_many_of_one_thing_a_day(tmp_path, monkeypatch):
    s, st, agent = world(tmp_path)
    st.add_item("tomatoes", 20, "food", "", {"food_value": 0.5})
    await use(st, s, "sell", item="tomatoes", ask=1)
    for h in range(0, 11):
        await tick(st, s, NOW + h * HOUR)
    assert stall(st)[0]["sold_today"] == stall(st)[0]["sold"] == G["STALL_DAILY_UNITS"]
    await tick(st, s, NOW + DAY)
    await tick(st, s, NOW + DAY + HOUR)
    assert stall(st)[0]["day"] == "2026-03-06" and stall(st)[0]["sold"] > G["STALL_DAILY_UNITS"]


async def test_a_creation_sold_to_a_keeper_is_theirs_and_one_the_till_cant_pay_for_stays(tmp_path):
    s, st, agent = world(tmp_path)
    c = st.add_creation("Brass Walker", "it walks", None, "fine", {"capabilities": {}}, {})
    pay = int(priced(25, item="Brass Walker") * 0.6)
    assert await use(st, s, "sell", item="Brass Walker") == f"you sold Brass Walker for {G['coins_text'](pay)} ({10 + pay} now); it is theirs now"
    assert st.creation(c["id"])["given_to"] == "the keeper at Brygdon" and not st.creations()
    assert moments(st, "sold_creation")[0]["text"] == f"You sold Brass Walker at Brygdon for {G['coins_text'](pay)}."
    st.add_creation("Gold Bird", "it sings", None, "masterwork", {"capabilities": {}}, {})
    st.merge_store("trade", {"tills": {slot("Brygdon"): {"booth": "Brygdon", "day": TODAY, "coins": 3}}})
    assert (await use(st, s, "sell", item="Gold Bird")).startswith("error: Brygdon's till can't pay for Gold Bird today") and st.creations()


async def test_a_creation_on_a_stall_sells_once_and_stays_pips_until_then(tmp_path):
    s, st, agent = world(tmp_path)
    c = st.add_creation("Brass Walker", "it walks", None, "fine", {"capabilities": {}}, {})
    assert (await use(st, s, "sell", item="Brass Walker", ask=1)).startswith("you set out Brass Walker at 1 coin each") and st.creations()
    assert stall(st)[0]["qty"] == 1
    for h in range(0, 30):
        await tick(st, s, NOW + h * HOUR)
        if not stall(st):
            break
    assert stall(st) == [] and st.creation(c["id"])["given_to"] == "a buyer at Brygdon"


async def test_a_creation_given_away_meanwhile_comes_off_the_stall(tmp_path):
    s, st, agent = world(tmp_path)
    c = st.add_creation("Brass Walker", "it walks", None, "fine", {"capabilities": {}}, {})
    await use(st, s, "sell", item="Brass Walker", ask=999)
    st.give_creation(c["id"], "Oriel")
    await tick(st, s, NOW)
    await tick(st, s, NOW + HOUR)
    assert stall(st) == []


async def test_copies_of_a_work_sell_at_a_stall_and_keepers_dont_buy_them(tmp_path):
    s, st, agent = world(tmp_path)
    st.add_work("drawing", "The Marsh at Dusk", "<svg/>")
    assert await use(st, s, "sell", item="The Marsh at Dusk") == \
        "error: keepers don't buy copies of your drawings; set copies out on a stall at a market, with an ask"
    assert (await use(st, s, "sell", item="The Marsh at Dusk", ask=5, quantity=1)).startswith("you set out 1 copy of The Marsh at Dusk at 5 coins each")
    assert (await use(st, s, "sell", item="The Marsh at Dusk", ask=5, quantity=9)).startswith(f"you set out {G['WORK_COPIES_MAX']} copies")
    assert stall(st)[0]["qty"] == G["WORK_COPIES_MAX"] and stall(st)[0]["kind"] == "work"
    assert trade(st)["facts"]["stall"] == [{"place": "Brygdon", "item": "The Marsh at Dusk", "kind": "work", "qty": 5, "work": "drawing"}]


async def test_the_stall_shows_where_pip_stands(tmp_path):
    s, st, agent = world(tmp_path)
    st.add_item("tomatoes", 5, "food", "", {"food_value": 0.5})
    await use(st, s, "sell", item="tomatoes", ask=6)
    assert trade(st)["standing"]["lines"] == ["Your stall here: 5 tomatoes at 6 coins each (nothing sold yet)."]
    assert "Your stall here: 5 tomatoes at 6 coins each (nothing sold yet)." in (await use(st, s, "browse")).split("\n")
    st.update_agent(location="Saltholm")
    await tick(st, s)
    assert trade(st)["standing"] == {}
    assert trade(st)["facts"]["stall"] == [{"place": "Brygdon", "item": "tomatoes", "kind": "food", "qty": 5}]


# --- neighbours and their wares ---------------------------------------------------------------------------------------------------------
def marigold(st, s, wares=WARES):
    from tests.test_neighbor import neighbor
    ch = neighbor(st, s)
    if wares:
        st.merge_store("trade", {"wares": {slot("Marigold"): {"name": "Marigold", "wares": [{**w, "weight": None, "attrs": {}} for w in wares]}}})
    return ch


def her_day(hers=True):
    """Noon on Marigold's market day (or the day after)."""
    wday = datetime.fromtimestamp(NOW).weekday()
    return NOW + (((G["crc32"]("Marigold") % 7) - wday) % 7 + (0 if hers else 1)) * DAY


def selling(day_name):
    return f"sells cork floats, carrot seeds, driftwood at home, and at Brygdon on {day_name}s"


async def test_at_her_home_pip_can_see_buy_and_sell(tmp_path):
    s, st, agent = world(tmp_path, where="Marigold's home")
    marigold(st, s)
    st.add_coins("pip", 50)
    now = her_day(hers=False)
    r = await use(st, s, "browse", now=now)
    assert r.startswith("Marigold has for sale: cork floats (") and r.endswith("You have 60 coins. buy what you want, or sell them some of yours.")
    assert (await use(st, s, "buy", item="cork floats", quantity=9, now=now)).startswith("you bought 4 cork floats")      # she spares 2 x 2 a day
    assert await use(st, s, "buy", item="cork floats", now=now) == "error: Marigold's home is out of cork floats today; they'll have more tomorrow"
    floats = st.find_item("cork floats")[0]
    assert floats["kind"] == "material" and floats["description"] == "floats off the flats"
    await use(st, s, "buy", item="carrot seeds", now=now)
    from app import finds
    known = next(e for t in finds.loot().values() for e in t if e[0] == "carrot seeds")
    from app.world import normalize_attrs
    assert st.find_item("carrot seeds")[0]["attrs"] == normalize_attrs("carrot seeds", "seed", dict(known[5]))      # the world's own carrot seeds
    st.add_item("tomatoes", 50, "food", "", {"food_value": 0.5})
    sold = await use(st, s, "sell", item="tomatoes", quantity=50, now=now)
    assert sold.startswith("you sold ") and st.find_item("tomatoes")[0]["qty"] >= 30                    # 20 at most at once
    assert "till" in await use(st, s, "sell", item="tomatoes", quantity=20, now=now)


async def test_a_stall_line_holds_twenty_at_most(tmp_path):
    s, st, agent = world(tmp_path)
    st.add_item("tomatoes", 30, "food", "", {"food_value": 0.5})
    assert (await use(st, s, "sell", item="tomatoes", ask=4)).startswith("you set out 20 tomatoes")
    assert await use(st, s, "sell", item="tomatoes", ask=4) == "error: your stall holds at most 20 tomatoes"
    assert st.find_item("tomatoes")[0]["qty"] == 10 and await use(st, s, "sell", item="tomatoes", ask=0) == "you take 20 tomatoes back off the stall"


async def test_a_neighbour_with_nothing_for_sale_says_so(tmp_path):
    s, st, agent = world(tmp_path, where="Marigold's home")
    marigold(st, s, wares=None)
    assert await use(st, s, "browse") == "there's nothing for sale at Marigold's home"
    assert await use(st, s, "buy", item="cork floats") == "error: Marigold's home doesn't keep 'cork floats'"


async def test_on_her_market_day_she_keeps_a_stall_at_the_market(tmp_path):
    s, st, agent = world(tmp_path, where="Marigold's home")
    ch = marigold(st, s)
    st.add_coins("pip", 50)
    now, day = her_day(), G["WEEKDAYS"][G["crc32"]("Marigold") % 7]
    assert await use(st, s, "browse", now=now) == "Marigold is at a stall in Brygdon today, with their wares"
    assert M.whereabouts(st, "Marigold") == {"at": "Brygdon", "doing": f"minding a stall at Brygdon today ({selling(day)})"}
    assert P.place_of(st, ch) == "Brygdon" and [c["name"] for c in P.company_at(st, "Brygdon")] == ["Marigold"]
    st.update_agent(location="Brygdon")
    assert "Marigold, at a stall here today, has for sale: cork floats" in await use(st, s, "browse", now=now)
    assert (await use(st, s, "buy", item="driftwood", quantity=2, now=now)).startswith("you bought 2 driftwood")
    assert view(st, s, now).till("Marigold's stall") > 30
    assert (await use(st, s, "buy", item="brass wire", now=now)).startswith("you bought 1 brass wire")    # the market's own booth still trades
    assert "Marigold (at a stall here today) has for sale:" in "\n".join(trade(st)["standing"]["lines"])
    await tick(st, s, now + 6 * HOUR)
    assert M.whereabouts(st, "Marigold") is not None                                           # Brygdon keeps the hours we gave it: all day
    st.update_place("Brygdon", hours=[9, 17])
    await tick(st, s, now + 6 * HOUR)                                                          # six o'clock: shut
    assert M.whereabouts(st, "Marigold") is None and P.place_of(st, ch) == "Marigold's home"
    await tick(st, s, now + DAY)
    assert M.whereabouts(st, "Marigold") is None                                               # another day: at home


def test_her_trade_reads_plainly_in_her_notes_and_the_neighbours_list(tmp_path):
    import app.neighbors as nb
    s, st, agent = world(tmp_path)
    ch = marigold(st, s)
    asyncio.run(tick(st, s))
    day = G["WEEKDAYS"][G["crc32"]("Marigold") % 7]
    assert M.notes_on(st, "Marigold") == [f"{selling(day)}; Pip can buy there."]
    assert f"- Marigold: {ch['about']} ({selling(day)}; Pip can buy there.)" in "\n".join(nb.perception(st))


def test_her_letters_offer_what_pip_wished_for_and_now_and_then_something_else(tmp_path):
    import app.neighbors as nb
    s, st, agent = world(tmp_path)
    ch = marigold(st, s)
    asyncio.run(tick(st, s))
    price = next(p for _, item, p, who in M.for_sale(st) if item == "driftwood" and who == "Marigold")
    st.add_memory("some driftwood for a frame", "wishlist")
    note = nb.trade_note(st, ch, FixedRng(0.9))
    assert note.startswith("Marigold sells cork floats") and note.endswith(f"Pip has wished for something like driftwood; Marigold could offer it ({price} coins each).")
    assert [e["data"] for e in st.events(5) if e["kind"] == "offered"][0] == {"name": "Marigold", "item": "driftwood", "price": price, "wished": True}
    st.db.execute("DELETE FROM memories")
    assert "could offer Pip" in nb.trade_note(st, ch, FixedRng(0.1)) and "offer" not in nb.trade_note(st, ch, FixedRng(nb.OFFER_CHANCE))
    assert nb.trade_note(st, {**ch, "name": "Nobody"}, FixedRng(0.1)) == ""


async def test_a_neighbour_without_wares_is_asked_for_some_once_at_a_time(tmp_path):
    s, st, agent = world(tmp_path)
    marigold(st, s, wares=None)
    m = trade(st)
    st.update_module(m["id"], manifest={**m["manifest"], "params": {"wares": "on"}})
    await tick(st, s)
    (ask,) = trade(st)["asks"]
    assert ask["purpose"] == "wares:Marigold" and "Who Marigold is: " in ask["prompt"] and ask["schema"]["properties"]["wares"]["type"] == "array"
    await tick(st, s, NOW + 60)
    assert len(trade(st)["asks"]) == 1                                                   # one question at a time


async def test_wares_come_of_the_answer(tmp_path):
    s, st, agent = world(tmp_path)
    marigold(st, s, wares=None)
    m = trade(st)
    out = await M.call(st, s, M.LocalRunner(), m, "on_answer", NOW, answer={"purpose": "wares:Marigold", "text": "", "data": {"wares": WARES}})
    assert out["ok"] and [w["name"] for w in G["Market"](M.context(st, s, trade(st), NOW)).wares("Marigold")] == ["cork floats", "carrot seeds", "driftwood"]
    assert moments(st, "wares")[0]["text"] == "Marigold has things for sale: cork floats, carrot seeds, driftwood."


def test_cleaning_wares():
    m = G["Market"]({"now": NOW, "time": {"utc_offset": 0}, "store": {}, "here": None, "people": [], "places": [], "agent": {"name": "Pip"}})
    got = G["_clean_wares"](m, [{"name": "  cork   floats ", "kind": "Material", "per_day": 9}, {"name": "awl", "kind": "tool"},
                                {"name": "file", "kind": "tool"}, {"name": "newt", "kind": "creature"}, "x", {"name": "Cork floats", "kind": "food"},
                                {"name": "n" * 50, "kind": "food", "per_day": True, "description": "d" * 200}])
    assert [w["name"] for w in got] == ["cork floats", "awl", "n" * 40] and [w["per_day"] for w in got] == [3, 1, 1]
    assert got[2]["description"] == "d" * 120 and got[0]["attrs"] == {} and got[0]["weight"] is None
    assert G["_clean_wares"](m, [{"name": "lonely", "kind": "food"}]) == [] and G["_clean_wares"](m, "nope") == []
    assert len(G["_clean_wares"](m, [{"name": f"thing {i}", "kind": "food"} for i in range(9)])) == G["WARES_MAX"]


# --- a happening's turn in a price --------------------------------------------------------------------------------------------------
async def test_a_happening_moves_one_price_and_says_so(tmp_path):
    s, st, agent = world(tmp_path)
    line = await M.ask_module(st, s, None, "trade", "price", {"place": "Saltholm", "item": "awl"}, False, NOW, tone="good", severity="medium")
    assert line == "Awl fetches about 12% more at Saltholm for now." and view(st, s).local("Saltholm", "awl") == 1.0
    await M.ask_module(st, s, None, "trade", "price", {"place": "Saltholm", "item": "awl"}, True, NOW, tone="good", severity="medium")
    assert view(st, s).local("Saltholm", "awl") == pytest.approx(1.04 ** 3)
    st.add_item("pears", 2, "food", "", {})
    assert (await M.ask_module(st, s, None, "trade", "price", {"place": "Brygdon"}, False, NOW, tone="bad", severity="major")).endswith(
        "fetches about 22% less at Brygdon for now.")
    for tone, severity, line in (("good", "major", "27% more"), ("good", "minor", "4% more"), ("bad", "major", "22% less"), ("bad", "minor", "4% less")):
        assert await M.ask_module(st, s, None, "trade", "price", {"place": "Saltholm", "item": "tomatoes"}, False, NOW, tone=tone, severity=severity) == \
            f"Tomatoes fetches about {line} at Saltholm for now."
    for args, why in (({"place": "woods", "item": "awl"}, "`place` is the key of a place that sells"),
                      ({"place": "Saltholm", "item": "unicorn"}, "`item` is something sold at Saltholm or that Pip has")):
        with pytest.raises(M.Refused) as e:
            await M.ask_module(st, s, None, "trade", "price", args, False, NOW, tone="good", severity="minor")
        assert str(e.value) == why


# --- what others read of it ---------------------------------------------------------------------------------------------------------
async def test_scenes_wishes_and_pictures_read_what_it_publishes(tmp_path):
    s, st, agent = world(tmp_path)
    marigold(st, s)
    st.add_item("tomatoes", 4, "food", "", {"food_value": 0.5})
    now = her_day(hers=False)
    await use(st, s, "sell", item="tomatoes", ask=6, now=now)
    facts = trade(st)["facts"]
    assert set(facts) == {"scene", "for_sale", "stall"} and set(facts["scene"]) == {"Brygdon", "Saltholm", "Marigold's home"}
    assert facts["scene"]["Brygdon"]["stall"] == [{"item": "tomatoes", "qty": 4, "ask": 6, "kind": "food"}]
    assert facts["scene"]["Marigold's home"]["lives_here"] == {"wares": ["cork floats", "carrot seeds", "driftwood"], "away_at": None,
                                                               "market_day": G["WEEKDAYS"][G["crc32"]("Marigold") % 7]}
    v = WV.scene_view(st, s, None, "Brygdon")
    assert [b["booth"] for b in v["booths"]] == ["Brygdon"] and v["stall"] == facts["scene"]["Brygdon"]["stall"]
    assert [i["name"] for i in v["booths"][0]["items"]] == ["brass wire", "tomatoes", "awl"]
    home = WV.scene_view(st, s, None, "Marigold's home")
    assert home["lives_here"]["wares"] == ["cork floats", "carrot seeds", "driftwood"] and home["booths"][0]["whose"] == "Marigold"
    assert "look" in home["booths"][0]
    wire = view(st, s, now).sell_price("Saltholm", G["entry_of"](LOOT, "brass wire"))
    assert ("Saltholm", "brass wire", wire, "") in M.for_sale(st)
    from app import wishes as W
    assert W.sources(st, "some brass wire", now) == [f"Brygdon sells brass wire ({view(st, s, now).sell_price('Brygdon', G['entry_of'](LOOT, 'brass wire'))} coins)",
                                                     f"Saltholm sells brass wire ({wire} coins)"]
    assert W.sources(st, "driftwood", now)[0].startswith("Marigold sells driftwood (") and W.sources(st, "driftwood", now)[0].endswith(" at Marigold's home")


# --- the market before it was a module ------------------------------------------------------------------------------------------------
def test_an_older_install_keeps_its_prices_tills_stall_accounts_and_wares(tmp_path):
    from app.config import Settings
    from app.state import State
    path = str(tmp_path / "old.db")
    st = State(Settings(), path)
    st.db.executescript("""
        CREATE TABLE market_prices (place TEXT, item TEXT, local REAL, local_at REAL, day TEXT, sold_today INTEGER, PRIMARY KEY (place, item));
        CREATE TABLE stalls (place TEXT, item TEXT, name TEXT, kind TEXT, description TEXT, attrs TEXT, qty INTEGER, ask INTEGER, sold INTEGER,
                             earned INTEGER, sold_today INTEGER, day TEXT, PRIMARY KEY (place, item));
        CREATE TABLE tills (place TEXT PRIMARY KEY, coins INTEGER, day TEXT);
        ALTER TABLE characters ADD COLUMN wares TEXT NOT NULL DEFAULT '[]';
        INSERT INTO market_prices VALUES ('Brygdon', 'tomato', 1.2, 100.0, '2026-11-10', 2);
        INSERT INTO stalls VALUES ('Brygdon', 'tomato', 'tomatoes', 'food', 'ripe', '{"food_value": 0.5}', 6, 3, 1, 3, 0, '');
        INSERT INTO tills VALUES ('Brygdon', 73, '2026-11-10');
    """)
    st.add_place("Saltholm", "saltholm", kind="shop", status="real", created_at=NOW, heard_at=NOW, loot=LOOT, verbs={})
    st.update_place("Saltholm", on_account={"brass wire": 7})
    ch = st.add_character("Oriel", "neighbor", None, "x", 60, NOW)
    st.db.execute("UPDATE characters SET wares = ? WHERE id = ?", ('[{"name": "sea glass", "kind": "material", "per_day": 3}]', ch["id"]))
    st.db.commit()
    st = State(Settings(), path)
    got = st.store("trade")
    assert got["prices"] == {slot("Brygdon", "tomato"): {"booth": "Brygdon", "item": "tomato", "local": 1.2, "at": 100.0, "day": "2026-11-10", "sold": 2}}
    assert got["tills"] == {slot("Brygdon"): {"booth": "Brygdon", "day": "2026-11-10", "coins": 73}}
    assert got["stall"] == {slot("Brygdon", "tomato"): {"place": "Brygdon", "item": "tomato", "name": "tomatoes", "kind": "food", "description": "ripe",
                                                         "qty": 6, "ask": 3, "sold": 1, "earned": 3, "sold_today": 0, "day": "", "attrs": {"food_value": 0.5}}}
    assert got["accounts"] == {slot("Saltholm"): {"place": "Saltholm", "items": {"brass wire": 7}}}
    assert got["wares"] == {slot("Oriel"): {"name": "Oriel", "wares": [{"name": "sea glass", "kind": "material", "per_day": 3}]}}
    tables = {r["name"] for r in st.db.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert not {"market_prices", "stalls", "tills"} & tables and st.place_row("Saltholm")["on_account"] == {}
    assert State(Settings(), path).store("trade") == got                              # once


def test_the_guide_tells_of_trade_while_its_tools_are_offered(tmp_path):
    s, st, agent = world(tmp_path)
    page = "Some places have booths: a shop, or a market with several."
    assert not {"buy", "sell", "pay"} & set(agent.tools) and {"buy", "sell", "pay"} <= agent.tool_names()
    assert page in agent._system_prompt()
    M.disable(st, trade(st)["id"])
    assert page not in agent._system_prompt() and not {"buy", "sell", "pay"} & agent.tool_names()


async def test_long_names_are_clipped_to_what_the_engine_takes(tmp_path):
    s, st, agent = world(tmp_path, where="Marigold's home")
    long = [{"name": f"{c * 30} things", "kind": "material", "description": "", "per_day": 1} for c in "abcde"]
    marigold(st, s, wares=long)
    assert (await use(st, s, "browse", now=her_day())).startswith("Marigold is at a stall")
    assert len(M.whereabouts(st, "Marigold")["doing"]) == 200 and M.whereabouts(st, "Marigold")["doing"].endswith("...")
    st.update_agent(location="Brygdon")
    await use(st, s, "browse", now=her_day())
    assert all(len(x) <= 200 for x in trade(st)["standing"]["lines"]) and trade(st)["fails"] == 0
    assert G["fit"]("x" * 200) == "x" * 200 and G["fit"]("x" * 201) == "x" * 197 + "..." and G["fit"]("ab  cd", 5) == "ab..."


def test_a_till_away_from_the_booth_is_by_the_places_kind(tmp_path):
    s, st, agent = world(tmp_path, where="Saltholm")
    assert view(st, s).till("Brygdon") == 80 and view(st, s).till("Saltholm") == 40
