"""Markets and coins, phase 1 (docs/DESIGN-market.md).

A booth is a shop or market place with a keeper. Everything here is engine-owned arithmetic; the model only chooses what to buy and sell.
`price = base(item) * local(booth, item) * mood(booth, item, day)`: the base comes from the item, `local` moves 4% per unit traded and
drifts back by 10% a day, `mood` is a small deterministic daily wobble. A booth pays 60% of what it charges and only has a day's coins
(its till) to pay out, which is what keeps a surplus from being worth unlimited coins.
"""
import math
import time
import zlib

from . import gathering
from .state import name_key

PRICE_STEP = 0.04        # a unit bought from the booth raises its price this much, a unit sold to it lowers it
LOCAL_MIN, LOCAL_MAX = 0.6, 1.6
DRIFT_PER_DAY = 0.9      # the part of a price's distance from normal that is still there a day later
MOOD_RANGE = 8           # percent, either way
BUY_RATE = 0.6           # a booth pays this share of what it charges
TILL_PER_DAY = {"shop": 40, "market": 80}
STALL_DEMAND_PER_HOUR = 2.0   # customers an hour at a fair ask
STALL_DAILY_UNITS = 8         # the most of one thing a market takes off a stall in a day
STALL_MAX_KINDS = 3
STALL_STEP_CAP = 3600         # seconds of selling credited in one look
STOCK_FLOOR = 2          # the least a booth keeps of anything for a day
UNKNOWN_KIND_PRICE = 3


def day_of(now: float) -> str:
    return time.strftime("%Y-%m-%d", time.localtime(now))


def base_price(name: str, kind: str, attrs: dict | None, weight: float | None = None) -> int:
    """What an item is worth before the market has a say, always at least 1."""
    attrs = attrs or {}
    if kind == "food":
        return max(1, round(float(attrs.get("food_value", 0.3)) * 10))
    if kind == "seed":
        return max(1, round(float(attrs.get("yield", 3)) * float(attrs.get("food_value", 0.4)) * 2))
    if kind == "tool":
        return 12
    if kind == "material":
        return max(1, min(12, round(30 / weight))) if weight else UNKNOWN_KIND_PRICE
    return UNKNOWN_KIND_PRICE


def mood(place: str, item: str, day: str) -> float:
    """A small wobble, +-8%, the same all day for the same booth and item."""
    return 1 + (zlib.crc32(f"{place}|{name_key(item)}|{day}".encode()) % (2 * MOOD_RANGE + 1) - MOOD_RANGE) / 100


def _weights() -> dict[str, float]:
    return {name_key(e[0]): e[2] for table in gathering.LOOT.values() for e in table}


def local(state, place: str, item: str, now: float) -> float:
    row = state.price_row(place, name_key(item))
    if not row:
        return 1.0
    days = max(0.0, now - row["local_at"]) / 86400
    return 1 + (row["local"] - 1) * DRIFT_PER_DAY ** days


def nudge(state, place: str, item: str, units: int, now: float) -> None:
    """Trade moves a price: +units raises it (the booth sold them), -units lowers it (the booth bought them)."""
    key = name_key(item)
    value = local(state, place, key, now)
    value *= (1 + PRICE_STEP) ** units if units >= 0 else (1 - PRICE_STEP) ** -units
    row = state.price_row(place, key)
    today = day_of(now)
    sold = row["sold_today"] if row and row["day"] == today else 0
    state.set_price_row(place, key, max(LOCAL_MIN, min(LOCAL_MAX, value)), now, today, sold)


def _entry(table: list, query: str):
    q = name_key(query)
    exact = [e for e in table if name_key(e[0]) == q]
    part = [e for e in table if q and (q in name_key(e[0]) or name_key(e[0]) in q)]
    return (exact or part or [None])[0]


def _price(state, place: str, name: str, kind: str, attrs: dict, weight: float | None, now: float) -> int:
    return max(1, round(base_price(name, kind, attrs, weight) * local(state, place, name, now) * mood(place, name, day_of(now))))


def sell_price(state, place: str, entry, now: float) -> int:
    """What the booth charges for one unit of a thing from its own table."""
    name, kind, weight, _, _, attrs = entry
    return _price(state, place, name, kind, attrs, weight, now)


def stock_table(state, place: str) -> list:
    """What a booth here keeps: the place's gather table, or (a market has no gathering) the stock of a real trading place."""
    from . import place_kinds
    found = gathering.loot_for(state, place)
    if found:
        return found
    rec = state.place_row(place)
    if rec and rec["status"] == "real" and place_kinds.KINDS[rec["kind"]].trades:
        return [(n, k, w, tuple(q), d, a) for n, k, w, q, d, a in rec["loot"]]
    return []


def _kind_of(state, place: str) -> str | None:
    row = state.place_row(place)
    return row["kind"] if row else None


def till(state, place: str, now: float) -> int:
    """The coins the keeper can pay out today; it fills up again each morning."""
    row = state.till_row(place)
    full = TILL_PER_DAY.get(_kind_of(state, place), TILL_PER_DAY["shop"])
    if not row or row["day"] != day_of(now):
        state.set_till(place, full, day_of(now))
        return full
    return row["coins"]


def _set_till(state, place: str, coins: int, now: float) -> None:
    state.set_till(place, coins, day_of(now))


def stock_target(entry) -> int:
    return max(STOCK_FLOOR, entry[3][1] * 2)


def stock_left(state, place: str, entry, now: float) -> int:
    row = state.price_row(place, name_key(entry[0]))
    sold = row["sold_today"] if row and row["day"] == day_of(now) else 0
    return max(0, stock_target(entry) - sold)


def _record_sold(state, place: str, name: str, units: int, now: float) -> None:
    key = name_key(name)
    nudge(state, place, key, units, now)
    row = state.price_row(place, key)
    state.set_price_row(place, key, row["local"], row["local_at"], row["day"], row["sold_today"] + units)


def quote_buy(state, place: str, item: str, qty: int, now: float) -> int | None:
    """The total for `qty` units at the booth, each dearer than the last (None: it doesn't keep that)."""
    entry = _entry(stock_table(state, place), item)
    if not entry:
        return None
    name, kind, weight, _, _, attrs = entry
    total, value = 0, local(state, place, name, now)
    for i in range(qty):
        total += max(1, round(base_price(name, kind, attrs, weight) * value * mood(place, name, day_of(now))))
        value = min(LOCAL_MAX, value * (1 + PRICE_STEP))
    return total


def coins_text(n: int) -> str:
    return f"{n} coin{'s' if n != 1 else ''}"


def buy(state, place: str, item: str, qty: int, now: float) -> tuple[bool, str]:
    table = stock_table(state, place)
    entry = _entry(table, item)
    if not entry:
        return False, f"{place} doesn't keep {item!r}"
    name = entry[0]
    left = stock_left(state, place, entry, now)
    if left <= 0:
        return False, f"{place} is out of {name} today; they'll have more tomorrow"
    qty = min(qty, left)
    total = quote_buy(state, place, name, qty, now)
    coins = state.coins()
    if total > coins:
        one = quote_buy(state, place, name, 1, now)
        return False, f"you can't afford {name}: it's {one} coins each and you have {coins} coins"
    state.add_coins("pip", -total)
    _set_till(state, place, till(state, place, now) + total, now)
    _record_sold(state, place, name, qty, now)
    state.add_item(name, qty, entry[1], entry[4], entry[5])
    return True, f"you bought {qty} {name} for {coins_text(total)} ({state.coins()} left)"


def sell(state, place: str, item: str, qty: int, now: float) -> tuple[bool, str]:
    have, err = state.find_item(item)
    if not have:
        return False, f"you don't have {item!r}"
    qty = min(qty, have["qty"])
    table = stock_table(state, place)
    weight = (_entry(table, have["name"]) or [None, None, None])[2] or _weights().get(name_key(have["name"]))
    key = name_key(have["name"])
    sold, earned = 0, 0
    left = till(state, place, now)
    while sold < qty:
        pay = max(1, int(_price(state, place, have["name"], have["kind"], have["attrs"], weight, now) * BUY_RATE))
        if pay > left:
            break
        left -= pay
        earned += pay
        sold += 1
        nudge(state, place, key, -1, now)
    if not sold:
        return False, f"{place}'s till is empty for today; try tomorrow"
    state.take_item(have["id"], sold)
    state.add_coins("pip", earned)
    _set_till(state, place, left, now)
    short = f" (that's all the till could pay; {qty - sold} left over)" if sold < qty else ""
    return True, f"you sold {sold} {have['name']} for {coins_text(earned)}{short} ({state.coins()} now)"


def owed(state, place: str, now: float) -> int:
    row = state.place_row(place) or {}
    table = stock_table(state, place)
    total = 0
    for name, qty in (row.get("on_account") or {}).items():
        entry = _entry(table, name)
        total += qty * (sell_price(state, place, entry, now) if entry else UNKNOWN_KIND_PRICE)
    return total


def pay(state, place: str, now: float) -> tuple[bool, str]:
    debt = owed(state, place, now)
    if not debt:
        return False, f"you owe {place} nothing"
    if debt > state.coins():
        return False, f"you owe {place} {debt} coins and have {state.coins()} coins"
    state.add_coins("pip", -debt)
    _set_till(state, place, till(state, place, now) + debt, now)
    state.update_place(place, on_account={})
    return True, f"you paid {debt} coins for what was on account at {place} ({state.coins()} left)"


# --- Pip's own stall (docs/DESIGN-market.md, phase 2) ---------------------------------------------------------------
# Goods are set out at an ask. Customers stop only while Pip is at the market, awake and it is open: about two an hour at the going price, fewer as the ask
# climbs above it (none beyond 1.6 times), and the market takes at most STALL_DAILY_UNITS of one thing a day. Each sale pays the ask and slips the local price.
def stall_factor(ratio: float) -> float:
    """How many customers stop at an ask this many times the going price: more for a cheap one, none for a silly one."""
    return max(0.0, min(1.25, round((1.6 - ratio) / 0.6, 9)))


def poisson(rng, mu: float) -> int:
    """A count of customers with mean `mu` (Knuth's method; fine for the small means here)."""
    if mu <= 0:
        return 0
    limit, k, p = math.exp(-mu), 0, 1.0
    while True:
        p *= rng.random()
        if p <= limit:
            return k
        k += 1


def fair_price(state, place: str, name: str, kind: str, attrs: dict, now: float) -> int:
    """What a booth here would charge for one of these today: the going price a stall is measured against."""
    table = stock_table(state, place)
    weight = (_entry(table, name) or [None, None, None])[2] or _weights().get(name_key(name))
    return _price(state, place, name, kind, attrs, weight, now)


def list_on_stall(state, place: str, item: str, qty: int, ask: int, now: float) -> tuple[bool, str]:
    """Set goods out at an ask (they leave Pip's belongings until sold or taken back). A line already there takes the new quantity and ask."""
    from . import place_kinds
    row = state.place_row(place)
    if not row:
        return False, f"there is no stall to be had at {place}"
    if not place_kinds.KINDS[row["kind"]].stalls:
        return False, (f"{place} is a shop: sell to its keeper (leave out the ask); stalls are for markets" if place_kinds.KINDS[row["kind"]].trades
                       else f"there is no stall to be had at {place}")
    if ask < 1:
        return False, "an ask is at least 1 coin"
    have, err = state.find_item(item)
    if not have:
        return False, err
    if qty < 1:
        return False, "set out at least 1"
    qty = min(qty, have["qty"])
    key = name_key(have["name"])
    lines = state.stall_rows(place)
    if not any(r["item"] == key for r in lines) and len(lines) >= STALL_MAX_KINDS:
        return False, f"your stall has room for {STALL_MAX_KINDS} kinds of thing; take something back first"
    state.take_item(have["id"], qty)
    there = next((r for r in lines if r["item"] == key), None)
    if there:
        state.set_stall(place, key, qty=there["qty"] + qty, ask=ask)
    else:
        state.set_stall(place, key, name=have["name"], kind=have["kind"], description=have["description"], attrs=have["attrs"], qty=qty, ask=ask)
    fair = fair_price(state, place, have["name"], have["kind"], have["attrs"], now)
    return True, (f"you set out {qty} {have['name']} at {coins_text(ask)} each; the going price here is {fair}"
                  + ("; at that price nobody will stop" if stall_factor(ask / fair) == 0 else ""))


def take_back(state, place: str, item: str) -> tuple[bool, str]:
    key = name_key(item)
    there = next((r for r in state.stall_rows(place) if r["item"] == key), None)
    if not there:
        return False, f"you have no {item} on the stall"
    state.add_item(there["name"], there["qty"], there["kind"], there["description"], there["attrs"])
    state.delete_stall(place, key)
    return True, f"you take {there['qty']} {there['name']} back off the stall"


def stall_tick(state, place: str, now: float, seconds: float, rng) -> list[dict]:
    """Let customers stop at Pip's stall for `seconds`: returns what sold (one entry per line) and pays Pip, logs and slips the prices."""
    sales = []
    if seconds <= 0:
        return sales
    today = day_of(now)
    for row in state.stall_rows(place):
        sold_today = row["sold_today"] if row["day"] == today else 0
        fair = fair_price(state, place, row["name"], row["kind"], row["attrs"], now)
        customers = poisson(rng, STALL_DEMAND_PER_HOUR * stall_factor(row["ask"] / fair) * seconds / 3600)
        units = min(customers, row["qty"], STALL_DAILY_UNITS - sold_today)
        if units <= 0:
            continue
        coins = units * row["ask"]
        left = row["qty"] - units
        state.add_coins("pip", coins)
        nudge(state, place, row["item"], -units, now)
        if left:
            state.set_stall(place, row["item"], qty=left, sold=row["sold"] + units, earned=row["earned"] + coins, sold_today=sold_today + units, day=today)
        else:
            state.delete_stall(place, row["item"])
        sale = {"place": place, "item": row["name"], "qty": units, "coins": coins, "left": left}
        state.log("stall_sale", **sale)
        sales.append(sale)
    return sales


def stall_step(state, settings, rng, now: float | None = None) -> list[dict]:
    """The monitor's look at the stall: customers stop only while Pip is at a market, awake, not walking, and it is open. The first look only starts the clock."""
    from . import places, place_kinds
    from . import sleep as sleepmod
    now = now or time.time()
    last = state.meta("stall_at")
    state.set_meta(stall_at=now)
    here = state.agent()["location"]
    rec = state.place_row(here)
    if last is None or sleepmod.asleep(state) or (state.session() or {}).get("kind") == "walk":
        return []
    if not rec or not place_kinds.KINDS[rec["kind"]].stalls or not places.open_now(places.invented_place(rec), settings, now):
        return []
    return stall_tick(state, here, now, min(now - float(last), STALL_STEP_CAP), rng)


def stall_lines(state, place: str, now: float) -> list[str]:
    return [f"Your stall here: {r['qty']} {r['name']} at {coins_text(r['ask'])} each ("
            + ("nothing sold yet" if not r["sold"] else f"sold {r['sold']} for {coins_text(r['earned'])} so far") + ")."
            for r in state.stall_rows(place)]
