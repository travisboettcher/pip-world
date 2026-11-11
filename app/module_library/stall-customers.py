# Customers at Pip's stall: while Pip is at a market, awake, and it is open, people stop at the stall now and then: about two an hour for
# a line at the going price, more if it is cheaper, none if it is far dearer. A market takes at most eight of one thing a day. The engine
# checks every sale (only Pip's goods, at Pip's ask) and pays Pip; this decides how many people stop.
import math
import random

DEMAND_PER_HOUR, MOST_SECONDS, DAILY_UNITS = 2.0, 3600, 8


def factor(ratio):
    """How many stop at an ask this many times the going price: more for a cheap one, none for a silly one."""
    return max(0.0, min(1.25, round((1.6 - ratio) / 0.6, 9)))


def poisson(rng, mu):
    if mu <= 0:
        return 0
    limit, k, p = math.exp(-mu), 0, 1.0
    while True:
        p *= rng.random()
        if p <= limit:
            return k
        k += 1


def on_tick(ctx):
    now, last = ctx["now"], ctx["state"].get("at")
    out = {"state": {"at": now}}
    if last is None:                                         # the first look only starts the clock
        return out
    seconds, rng, sales = min(now - last, MOST_SECONDS), random.Random(ctx["seed"]), []
    for row in ctx["stalls"]:
        if not row["selling"]:
            continue
        stop = poisson(rng, DEMAND_PER_HOUR * factor(row["ask"] / row["fair"]) * seconds / 3600)
        units = min(stop, row["qty"], DAILY_UNITS - row["sold_today"])
        if units > 0:
            sales.append({"place": row["place"], "item": row["item"], "qty": units})
    if sales:
        out["sell"] = sales
    return out
