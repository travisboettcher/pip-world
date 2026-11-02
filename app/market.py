"""Markets and coins, phase 1 (docs/DESIGN-market.md).

A booth is a shop or market place with a keeper. Everything here is engine-owned arithmetic; the model only chooses what to buy and sell.
`price = base(item) * local(booth, item) * mood(booth, item, day)`: the base comes from the item, `local` moves 4% per unit traded and
drifts back by 10% a day, `mood` is a small deterministic daily wobble. A booth pays 60% of what it charges and only has a day's coins
(its till) to pay out, which is what keeps a surplus from being worth unlimited coins.
"""
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
    entry = _entry(gathering.loot_for(state, place) or [], item)
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
    table = gathering.loot_for(state, place) or []
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
    table = gathering.loot_for(state, place) or []
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
    table = gathering.loot_for(state, place) or []
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
