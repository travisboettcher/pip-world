# Trade (docs/DESIGN-world-packs.md, phase 5c): booths, prices, tills, the agent's stall and its customers, accounts, and the neighbours'
# wares and market days. A booth is a trading place's own (its goods: `here`), a neighbour's at home, or a neighbour's stall at the
# market on their day. `price = base(item) * local(booth, item) * mood(booth, item, day)`: the base comes from the item, `local` moves 4% a
# unit traded and drifts back 10% a day, `mood` is a small daily wobble. A booth pays 60% of what it charges and only has a day's coins
# (its till) to pay out. Coins, belongings and the agent's creations are the engine's; it checks every change this proposes.
import math
import random
from datetime import date

PRICE_STEP = 0.04
LOCAL_MIN, LOCAL_MAX = 0.6, 1.6
DRIFT_PER_DAY = 0.9
MOOD_RANGE = 8
BUY_RATE = 0.6
TILL = {"shop": 40, "market": 80, "neighbor": 20, "stall": 30}
STALL_DAILY_UNITS = 8
STALL_MAX_KINDS = 3
STOCK_FLOOR = 2
UNKNOWN_PRICE = 3
QUALITY_PRICE = {"rough": 8, "sound": 15, "fine": 25, "masterwork": 40}
WORK_PRICE = {"drawing": 4, "writing": 3}
WORK_COPIES_MAX = 5
STALL_SUFFIX = "'s stall"
HOME_SUFFIX = "'s home"
WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
GLIMPSE = 4
DEMAND_PER_HOUR, MOST_SECONDS = 2.0, 3600
PRICE_UNITS = {"minor": 1, "medium": 3, "major": 6}
WARES_MAX, WARE_KINDS = 5, ("material", "food", "seed", "tool")
OWE_LINES, OWE_MOST = 8, 50
MOST = 20                # the most of one thing a sale or a stall line takes (the engine's limit on giving and taking)
HOUR = 3600


# --- small things -----------------------------------------------------------------------------------------------------------------------
def _crc_table():
    out = []
    for n in range(256):
        c = n
        for _ in range(8):
            c = (0xEDB88320 ^ (c >> 1)) if c & 1 else c >> 1
        out.append(c)
    return out


CRC = _crc_table()


def crc32(text):
    """zlib's crc32 (market days and the daily wobble were reckoned with it before trade was a module)."""
    c = 0xFFFFFFFF
    for b in text.encode():
        c = CRC[(c ^ b) & 0xFF] ^ (c >> 8)
    return c ^ 0xFFFFFFFF


def _singular(word):
    if word.endswith("ies") and len(word) > 4:
        return word[:-3] + "y"
    if word.endswith("oes") and len(word) > 4:
        return word[:-2]
    if word.endswith("s") and not word.endswith("ss") and len(word) > 3:
        return word[:-1]
    return word


def key(name):
    return " ".join(_singular(w) for w in str(name).lower().split())


def slot(*parts):
    """A store key for something named (a booth, an item): short, and safe whatever the names are."""
    return "%08x" % crc32("|".join(parts))


def fit(text, most=200):
    """A line within what the engine takes (status lines, logs and whereabouts are at most 200 characters)."""
    return text if len(text) <= most else text[:most - 3].rstrip() + "..."


def coins_text(n):
    return str(n) + " coin" + ("" if n == 1 else "s")


def local_days(now, offset):
    return (now + offset) / 86400


def day_of(now, offset=0):
    return date.fromordinal(719163 + int(local_days(now, offset) // 1)).isoformat()


def weekday_hour(now, offset):
    days = local_days(now, offset)
    return (int(days // 1) + 3) % 7, int((days % 1) * 24)


def label(k):
    return k if k.endswith(HOME_SUFFIX) or k[:1].isupper() else "the " + k


def base_price(name, kind, attrs, weight=None):
    attrs = attrs or {}
    if kind == "food":
        return max(1, round(float(attrs.get("food_value", 0.3)) * 10))
    if kind == "seed":
        return max(1, round(float(attrs.get("yield", 3)) * float(attrs.get("food_value", 0.4)) * 2))
    if kind == "tool":
        return 12
    if kind == "material":
        return max(1, min(12, round(30 / weight))) if weight else UNKNOWN_PRICE
    if kind == "creation":
        return QUALITY_PRICE.get(attrs.get("quality"), QUALITY_PRICE["rough"])
    if kind == "work":
        return WORK_PRICE.get(attrs.get("work"), WORK_PRICE["writing"])
    return UNKNOWN_PRICE


def mood(booth, item, day):
    return 1 + (crc32(booth + "|" + key(item) + "|" + day) % (2 * MOOD_RANGE + 1) - MOOD_RANGE) / 100


def entry_of(table, query):
    q = key(query)
    exact = [e for e in table if key(e[0]) == q]
    part = [e for e in table if q and (q in key(e[0]) or key(e[0]) in q)]
    return (exact or part or [None])[0]


def poisson(rng, mu):
    if mu <= 0:
        return 0
    limit, k, p = math.exp(-mu), 0, 1.0
    while True:
        p *= rng.random()
        if p <= limit:
            return k
        k += 1


def stall_factor(ratio):
    return max(0.0, min(1.25, round((1.6 - ratio) / 0.6, 9)))


# --- trade as one call sees it --------------------------------------------------------------------------------------------------------------
class Market:
    COLLECTIONS = ("prices", "tills", "stall", "accounts", "wares")

    def __init__(self, ctx):
        self.ctx, self.now = ctx, ctx["now"]
        self.offset = ctx["time"]["utc_offset"]
        self.day = day_of(self.now, self.offset)
        store = ctx["store"]
        self.data = {c: dict(store.get(c, {})) for c in self.COLLECTIONS}
        self.changed = {c: set() for c in self.COLLECTIONS}
        self.coins = 0
        self.out = {}

    def put(self, coll, k, value):
        self.data[coll][k] = value
        self.changed[coll].add(k)

    def drop(self, coll, k):
        self.data[coll].pop(k, None)
        self.changed[coll].add(k)

    def store(self):
        return {c: {k: self.data[c].get(k) for k in ks} for c, ks in self.changed.items() if ks}

    def places(self):
        return self.ctx.get("places") or []

    def the_market(self):
        return next((p["key"] for p in self.places() if p["stalls"]), None)

    def market_hours(self):
        p = next((p for p in self.places() if p["stalls"]), None)
        return (p.get("hours") or [9, 17]) if p else None

    def neighbours(self):
        return [p for p in self.ctx["people"] if p["kind"] == "neighbor"]

    def wares(self, name):
        return (self.data["wares"].get(slot(name)) or {}).get("wares") or []

    def market_day(self, name):
        return crc32(name) % 7

    def away_at(self, name):
        """The market where a neighbour with wares keeps a stall right now (their day, while it is open), or None."""
        where, hours = self.the_market(), self.market_hours()
        if not self.wares(name) or not where:
            return None
        weekday, hour = weekday_hour(self.now, self.offset)
        return where if weekday == self.market_day(name) and hours[0] <= hour < hours[1] else None

    def wares_table(self, name):
        return [[w["name"], w["kind"], w.get("weight"), [1, w["per_day"]], w["description"], w.get("attrs") or {}] for w in self.wares(name)]

    def own_table(self, place):
        """What a trading place itself keeps: [name, kind, weight, span, description, attrs] each (where the agent is, the place's own words)."""
        here = self.ctx["here"]
        if here and here["key"] == place:
            return here["finds"] if here["trades"] else []
        p = next((p for p in self.places() if p["key"] == place and p["trades"]), None)
        return [[g["name"], g["kind"], g["weight"], g["span"], "", g["attrs"]] for g in p["goods"]] if p else []

    def booths(self, place):
        """The booths at a place: (booth key, whose, table) for a trading place's own and every neighbour selling there now."""
        own = self.own_table(place)
        out = [(place, "", own)] if own else []
        for n in self.neighbours():
            if not self.wares(n["name"]):
                continue
            away = self.away_at(n["name"])
            if n["home"] == place and not away:
                out.append((place, n["name"], self.wares_table(n["name"])))
            elif away == place:
                out.append((n["name"] + STALL_SUFFIX, n["name"], self.wares_table(n["name"])))
        return out

    def till_kind(self, booth):
        if booth.endswith(STALL_SUFFIX):
            return "stall"
        if booth.endswith(HOME_SUFFIX):
            return "neighbor"
        here = self.ctx["here"]
        if here and here["key"] == booth:
            return here["kind"]
        return next((p["kind"] for p in self.places() if p["key"] == booth), "shop")

    def local(self, booth, item):
        row = self.data["prices"].get(slot(booth, key(item)))
        if not row:
            return 1.0
        days = max(0.0, self.now - row["at"]) / 86400
        return 1 + (row["local"] - 1) * DRIFT_PER_DAY ** days

    def nudge(self, booth, item, units):
        k = slot(booth, key(item))
        row = self.data["prices"].get(k) or {}
        value = self.local(booth, item)
        value *= (1 + PRICE_STEP) ** units if units >= 0 else (1 - PRICE_STEP) ** -units
        sold = row.get("sold", 0) if row.get("day") == self.day else 0
        self.put("prices", k, {"booth": booth, "item": key(item), "local": max(LOCAL_MIN, min(LOCAL_MAX, value)), "at": self.now, "day": self.day,
                               "sold": sold})

    def weight(self, name, table=None):
        e = entry_of(table or [], name)
        return (e[2] if e else None) or ((self.ctx["here"] or {}).get("weights") or {}).get(key(name))

    def price(self, booth, name, kind, attrs, weight=None):
        return max(1, round(base_price(name, kind, attrs, weight) * self.local(booth, name) * mood(booth, name, self.day)))

    def sell_price(self, booth, e):
        return self.price(booth, e[0], e[1], e[5], e[2] or self.weight(e[0]))

    def fair(self, booth, name, kind, attrs, table=None):
        return self.price(booth, name, kind, attrs, self.weight(name, table))

    def stock_left(self, booth, e):
        row = self.data["prices"].get(slot(booth, key(e[0]))) or {}
        sold = row.get("sold", 0) if row.get("day") == self.day else 0
        return max(0, max(STOCK_FLOOR, e[3][1] * 2) - sold)

    def record_sold(self, booth, name, units):
        self.nudge(booth, name, units)
        self.data["prices"][slot(booth, key(name))]["sold"] += units

    def quote(self, booth, e, qty):
        name, kind, weight, _, _, attrs = e
        weight = weight or self.weight(name)
        total, value = 0, self.local(booth, name)
        for _ in range(qty):
            total += max(1, round(base_price(name, kind, attrs, weight) * value * mood(booth, name, self.day)))
            value = min(LOCAL_MAX, value * (1 + PRICE_STEP))
        return total

    def till(self, booth):
        row = self.data["tills"].get(slot(booth))
        if not row or row["day"] != self.day:
            full = TILL.get(self.till_kind(booth), TILL["shop"])
            self.put("tills", slot(booth), {"booth": booth, "day": self.day, "coins": full})
            return full
        return row["coins"]

    def set_till(self, booth, coins):
        self.put("tills", slot(booth), {"booth": booth, "day": self.day, "coins": coins})

    def coins_now(self):
        return self.ctx["agent"]["coins"] + self.coins

    def stall_lines(self, place):
        return [r for r in self.data["stall"].values() if r and r["place"] == place]

    def stall_text(self, place):
        return ["Your stall here: " + str(r["qty"]) + " " + r["name"] + " at " + coins_text(r["ask"]) + " each ("
                + ("nothing sold yet" if not r["sold"] else "sold " + str(r["sold"]) + " for " + coins_text(r["earned"]) + " so far") + ")."
                for r in self.stall_lines(place)]

    def account(self, place):
        return (self.data["accounts"].get(slot(place)) or {}).get("items") or {}

    def owed(self, place, table):
        total = 0
        for name, qty in self.account(place).items():
            e = entry_of(table, name)
            total += qty * (self.sell_price(place, e) if e else UNKNOWN_PRICE)
        return total

    def wares_line(self, booth, whose, table):
        there = [e[0] + " (" + str(self.sell_price(booth, e)) + " coins)" for e in table if self.stock_left(booth, e)]
        return (whose + " has for sale: " + ", ".join(there) + "." if there else whose + " has sold out of everything today.")

    def selling_where(self, name):
        if not self.wares(name):
            return ""
        names = ", ".join(w["name"] for w in self.wares(name)[:4])
        where = self.the_market()
        return "sells " + names + " at home" + (", and at " + where + " on " + WEEKDAYS[self.market_day(name)] + "s" if where else "")

    def finish(self, out=None):
        """What every call leaves behind: what the agent sees of trade where it is, where the neighbours are and what they sell, the facts
        the scene and the agent's wishes read, and the changes to the store and the purse."""
        out = dict(out or {})
        here = self.ctx["here"]
        lines = []
        if here:
            lines += self.stall_text(here["key"])
            for b, who, table in self.booths(here["key"]):
                if who:
                    lines.append(self.wares_line(b, who + (" (at a stall here today)" if b.endswith(STALL_SUFFIX) else ""), table))
        out["status"] = {"title": "Trade here", "lines": [fit(x) for x in lines[:8]]} if lines else {}
        where, notes = {}, {}
        for n in self.neighbours():
            sells = self.selling_where(n["name"])
            if sells:
                notes[n["name"]] = fit(sells + "; " + self.ctx["agent"]["name"] + " can buy there.", 300)
            away = self.away_at(n["name"])
            if away:
                where[n["name"]] = {"at": away, "doing": fit("minding a stall at " + label(away) + " today (" + sells + ")")}
        out["whereabouts"], out["notes"] = where, notes
        out["publish"] = self.facts()
        if self.coins:
            out["coins"] = self.coins
        store = self.store()
        if store:
            out["store"] = store
        if "schedule" not in out:
            out["schedule"] = self.now + HOUR
        return out

    def facts(self):
        """What the scenes show of trade, by place (every place that trades, and every neighbour's home with wares), what is for sale where
        ([place, item, price, whose], for the agent's wishes and the neighbours' letters), and the agent's stall (for its pictures)."""
        scene, for_sale = {}, []
        keys = [p["key"] for p in self.places() if p["trades"]] + [n["home"] for n in self.neighbours() if self.wares(n["name"])]
        for key in dict.fromkeys(keys + [r["place"] for r in self.data["stall"].values() if r]):
            booths = [{"booth": b, "whose": who, "items": [{"name": e[0], "kind": e[1], "price": self.sell_price(b, e), "left": self.stock_left(b, e)}
                                                           for e in table]} for b, who, table in self.booths(key)]
            stall = [{"item": r["name"], "qty": r["qty"], "ask": r["ask"], "kind": r["kind"]} for r in self.stall_lines(key)]
            scene[key] = {"booths": booths, "stall": stall}
            for_sale += [[key, i["name"], i["price"], b["whose"]] for b in booths for i in b["items"]]
        for n in self.neighbours():
            if self.wares(n["name"]):
                scene.setdefault(n["home"], {})["lives_here"] = {
                    "wares": [w["name"] for w in self.wares(n["name"])], "away_at": self.away_at(n["name"]),
                    "market_day": WEEKDAYS[self.market_day(n["name"])] if self.the_market() else None}
        stall = [{"place": r["place"], "item": r["name"], "kind": r["kind"], "qty": r["qty"], **({"work": r["attrs"]["work"]} if r["attrs"].get("work") else {})}
                 for _, r in sorted(self.data["stall"].items()) if r]
        return {"scene": scene, "for_sale": for_sale[:60], "stall": stall}


# --- the tools --------------------------------------------------------------------------------------------------------------------------------
def _qty(args):
    q = args.get("quantity", 1)
    return q if isinstance(q, int) and not isinstance(q, bool) and q >= 1 else None


def _own_thing(ctx, query):
    q = key(query)
    c = next((c for c in ctx["creations"] if key(c["name"]) == q), None)
    if c:
        return {"name": c["name"], "kind": "creation", "qty": 1, "description": c["description"], "attrs": {"quality": c["quality"]}}
    w = next((w for w in ctx["made"] if q and key(w["title"]) == q), None)
    if w:
        return {"name": w["title"], "kind": "work", "qty": WORK_COPIES_MAX, "description": "a copy of your " + w["kind"], "attrs": {"work": w["kind"]}}
    return None


def _have(ctx, query):
    q = str(query).strip().lower()
    items = ctx["items"]
    exact = [i for i in items if key(i["name"]) == key(q)]
    part = [i for i in items if q and (q in i["name"].lower() or i["name"].lower() in q)]
    if exact or len(part) == 1:
        return (exact or part)[0], ""
    if not part:
        return None, "you don't have " + repr(str(query))
    return None, "which one? " + ", ".join(i["name"] for i in part)


def browse(m, args):
    here = m.ctx["here"]
    theirs = [b for b in m.booths(here["key"]) if b[1]]
    if here["key"].endswith(HOME_SUFFIX):
        if not theirs:
            name = here["key"][:-len(HOME_SUFFIX)]
            away = m.away_at(name)
            return (name + " is at a stall in " + label(away) + " today, with their wares") if away else \
                "there's nothing for sale at " + here["key"], {}
        b, who, table = theirs[0]
        return m.wares_line(b, who, table) + " You have " + str(m.coins_now()) + " coins. buy what you want, or sell them some of yours.", {}
    return "\n".join([shop_stock(m, here)] + [m.wares_line(b, who + ", at a stall here today,", table) for b, who, table in theirs]), {}


def shop_stock(m, here):
    """At a shop or market: what's in today, with its price (fewer things as the stock runs down), and what's on account."""
    table, place = here["finds"], here["key"]
    n = round(GLIMPSE * min(1.0, here["stock"] / here["full_at"])) if here["full_at"] else GLIMPSE
    names = [e[0] for e in table]
    picked = random.Random(m.ctx["seed"]).sample(names, min(n, len(names)))
    seen = [e for e in table if e[0] in picked and m.stock_left(place, e)]
    if seen:
        line = ("In stock at " + label(place) + " today: " + ", ".join(e[0] + " (" + str(m.sell_price(place, e)) + " coins)" for e in seen)
                + ". You have " + str(m.coins_now()) + " coins. buy what you need; "
                + ("sell what you have, or set out a stall with an ask." if here["stalls"] else "gather to pick through the drawers on account."))
    else:
        line = "The shelves at " + label(place) + " are bare today; they restock slowly, so come back in a day or so."
    lines = [line] + m.stall_text(place)
    if m.account(place):
        lines.append("On account here: " + ", ".join(str(q) + " " + name for name, q in m.account(place).items())
                     + " (" + str(m.owed(place, table)) + " coins at today's prices; pay settles it).")
    return "\n".join(lines)


def buy(m, args):
    qty = _qty(args)
    if qty is None:
        return "error: quantity must be a whole number, at least 1", {}
    place, item = m.ctx["here"]["key"], str(args.get("item") or "")
    found = next(((b, e) for b, _, table in m.booths(place) for e in [entry_of(table, item)] if e), None)
    if not found:
        return "error: " + label(place) + " doesn't keep " + repr(item), {}
    booth, e = found
    name, left = e[0], m.stock_left(booth, e)
    if left <= 0:
        return "error: " + label(booth) + " is out of " + name + " today; they'll have more tomorrow", {}
    qty = min(qty, left)
    total = m.quote(booth, e, qty)
    if total > m.coins_now():
        return ("error: you can't afford " + name + ": it's " + str(m.quote(booth, e, 1)) + " coins each and you have " + str(m.coins_now())
                + " coins"), {}
    m.coins -= total
    m.set_till(booth, m.till(booth) + total)
    m.record_sold(booth, name, qty)
    return ("you bought " + str(qty) + " " + name + " for " + coins_text(total) + " (" + str(m.coins_now()) + " left)",
            {"give": [{"item": name, "qty": qty, "kind": e[1], "description": e[4], "attrs": e[5]}]})


def sell(m, args):
    place, item = m.ctx["here"]["key"], str(args.get("item") or "")
    if args.get("ask") is not None:
        if args["ask"] == 0:
            return take_back(m, place, item)
        have, _ = _have(m.ctx, item)
        qty = _qty(args) if "quantity" in args else (have["qty"] if have else 1)
        if qty is None:
            return "error: quantity must be a whole number, at least 1", {}
        return list_on_stall(m, place, item, qty, args["ask"])
    qty = _qty(args)
    if qty is None:
        return "error: quantity must be a whole number, at least 1", {}
    have, err = _have(m.ctx, item)
    table = next((t for b, who, t in m.booths(place) if b == place), [])
    if not have and (thing := _own_thing(m.ctx, item)):
        if thing["kind"] == "work":
            return "error: keepers don't buy copies of your " + thing["attrs"]["work"] + "s; set copies out on a stall at a market, with an ask", {}
        pay = max(1, int(m.price(place, thing["name"], "creation", thing["attrs"]) * BUY_RATE))
        left = m.till(place)
        if pay > left:
            return ("error: " + label(place) + "'s till can't pay for " + thing["name"] + " today (it would fetch " + coins_text(pay) + "; "
                    + coins_text(left) + " left); try a stall with an ask, or come back tomorrow"), {}
        m.set_till(place, left - pay)
        m.coins += pay
        keeper = place[:-len(HOME_SUFFIX)] if place.endswith(HOME_SUFFIX) else "the keeper at " + label(place)
        return ("you sold " + thing["name"] + " for " + coins_text(pay) + " (" + str(m.coins_now()) + " now); it is theirs now",
                {"part_with": {"creation": thing["name"], "to": keeper},
                 "log": {"text": fit("You sold " + thing["name"] + " at " + label(place) + " for " + coins_text(pay) + "."), "kind": "sold_creation",
                         "feel": {"joy": 3}}})
    if not have:
        return "error: " + err, {}
    qty = min(qty, have["qty"], MOST)
    weight = m.weight(have["name"], table)
    sold, earned, left = 0, 0, m.till(place)
    while sold < qty:
        pay = max(1, int(m.price(place, have["name"], have["kind"], have["attrs"], weight) * BUY_RATE))
        if pay > left:
            break
        left, earned, sold = left - pay, earned + pay, sold + 1
        m.nudge(place, have["name"], -1)
    if not sold:
        return "error: " + label(place) + "'s till is empty for today; try tomorrow", {}
    m.coins += earned
    m.set_till(place, left)
    short = " (that's all the till could pay; " + str(qty - sold) + " left over)" if sold < qty else ""
    stall = ("; a customer at a stall of your own here would pay about " + coins_text(m.fair(place, have["name"], have["kind"], have["attrs"], table))
             + " each (sell with an ask)") if m.ctx["here"]["stalls"] else ""
    return ("you sold " + str(sold) + " " + have["name"] + " for " + coins_text(earned) + short + " (" + str(m.coins_now()) + " now)" + stall,
            {"take": [{"item": have["name"], "qty": sold}]})


def list_on_stall(m, place, item, qty, ask):
    here = m.ctx["here"]
    if not here["stalls"]:
        return ("error: " + label(place) + " is a shop: sell to its keeper (leave out the ask); stalls are for markets" if here["trades"]
                else "error: there is no stall to be had at " + label(place)), {}
    if not isinstance(ask, int) or isinstance(ask, bool) or ask < 1:
        return "error: an ask is a whole number of coins, at least 1", {}
    have, err = _have(m.ctx, item)
    have = have or _own_thing(m.ctx, item)
    if not have:
        return "error: " + err, {}
    qty = min(qty, have["qty"])
    k = slot(place, key(have["name"]))
    there = m.data["stall"].get(k)
    if not there and len(m.stall_lines(place)) >= STALL_MAX_KINDS:
        return "error: your stall has room for " + str(STALL_MAX_KINDS) + " kinds of thing; take something back first", {}
    fair = m.fair(place, have["name"], have["kind"], have["attrs"], here["finds"])
    row = {"place": place, "item": key(have["name"]), "name": have["name"], "kind": have["kind"], "description": have.get("description", ""),
           "attrs": have.get("attrs") or {}, "ask": ask, "sold": (there or {}).get("sold", 0), "earned": (there or {}).get("earned", 0),
           "sold_today": (there or {}).get("sold_today", 0), "day": (there or {}).get("day", m.day)}
    extra = {}
    if have["kind"] in ("creation", "work"):                    # it stays the agent's until it sells: a creation once, copies of a work
        row["qty"] = min(have["qty"], qty + (there["qty"] if there else 0)) if have["kind"] == "work" else 1
        what = (str(row["qty"]) + " cop" + ("y" if row["qty"] == 1 else "ies") + " of " + have["name"]) if have["kind"] == "work" else have["name"]
    else:
        qty = min(qty, MOST - (there["qty"] if there else 0))
        if qty < 1:
            return "error: your stall holds at most " + str(MOST) + " " + have["name"], {}
        row["qty"] = (there["qty"] if there else 0) + qty
        extra = {"take": [{"item": have["name"], "qty": qty}]}
        what = str(qty) + " " + have["name"]
    m.put("stall", k, row)
    return ("you set out " + what + " at " + coins_text(ask) + " each; the going price here is " + str(fair)
            + ("; at that price nobody will stop" if stall_factor(ask / fair) == 0 else "")), extra


def take_back(m, place, item):
    k = slot(place, key(item))
    there = m.data["stall"].get(k)
    if not there:
        return "error: you have no " + item + " on the stall", {}
    m.drop("stall", k)
    give = [] if there["kind"] in ("creation", "work") else [{"item": there["name"], "qty": there["qty"], "kind": there["kind"],
                                                               "description": there["description"], "attrs": there["attrs"]}]
    return "you take " + str(there["qty"]) + " " + there["name"] + " back off the stall", ({"give": give} if give else {})


def pay(m, args):
    place = m.ctx["here"]["key"]
    debt = m.owed(place, m.ctx["here"]["finds"])
    if not debt:
        return "error: you owe " + label(place) + " nothing", {}
    if debt > m.coins_now():
        return "error: you owe " + label(place) + " " + str(debt) + " coins and have " + str(m.coins_now()) + " coins", {}
    m.coins -= debt
    m.set_till(place, m.till(place) + debt)
    m.drop("accounts", slot(place))
    return "you paid " + str(debt) + " coins for what was on account at " + label(place) + " (" + str(m.coins_now()) + " left)", {}


TOOLS = {"browse": browse, "buy": buy, "sell": sell, "pay": pay}


def on_action(ctx):
    m = Market(ctx)
    text, extra = TOOLS[ctx["tool"]](m, ctx["args"])
    m.out.update(extra)
    out = m.finish(m.out)
    out["reply"] = text
    return out


# --- customers, wares, and the rest of the day --------------------------------------------------------------------------------------------
def _customers(m):
    """While the agent is at an open market, awake, people stop at its stall now and then and buy at its ask, fewer the dearer it is."""
    ctx, st = m.ctx, m.ctx["state"]
    last = st.get("at")
    m.out["state"] = {**st, "at": m.now}
    here, a = ctx["here"], ctx["agent"]
    if last is None or not here or not here["stalls"] or not here["open"] or a["asleep"] or a["walking"]:
        return
    seconds, rng = min(m.now - last, MOST_SECONDS), random.Random(ctx["seed"])
    sales, gone = [], []
    names = {c["name"] for c in ctx["creations"]}
    for k, r in sorted(m.data["stall"].items()):
        if not r or r["place"] != here["key"]:
            continue
        if r["kind"] == "creation" and r["name"] not in names:          # sold or given away elsewhere meanwhile
            m.drop("stall", k)
            continue
        fair = m.fair(here["key"], r["name"], r["kind"], r["attrs"], here["finds"])
        sold_today = r["sold_today"] if r["day"] == m.day else 0
        units = min(poisson(rng, DEMAND_PER_HOUR * stall_factor(r["ask"] / fair) * seconds / 3600), r["qty"], STALL_DAILY_UNITS - sold_today)
        if units <= 0:
            continue
        coins = units * r["ask"]
        m.coins += coins
        m.nudge(here["key"], r["name"], -units)
        left = r["qty"] - units
        if r["kind"] == "creation":
            gone.append(r["name"])
        if left:
            m.put("stall", k, {**r, "qty": left, "sold": r["sold"] + units, "earned": r["earned"] + coins, "sold_today": sold_today + units, "day": m.day})
        else:
            m.drop("stall", k)
        sales.append((units, r["name"], coins))
    if sales:
        m.out["log"] = {"text": fit("At your stall you sold " + "; ".join(str(u) + " " + n + " for " + coins_text(c) for u, n, c in sales) + "."),
                        "kind": "stall_sale", "feel": {"joy": 2}, "items": [{"name": n, "qty": u} for u, n, _ in sales]}
    if gone:
        m.out["part_with"] = {"creation": gone[0], "to": "a buyer at " + label(here["key"])}


def _clean_wares(m, raw):
    out, seen = [], set()
    weights = (m.ctx["here"] or {}).get("weights") or {}
    for w in raw or []:
        if not isinstance(w, dict):
            continue
        name, kind = " ".join(str(w.get("name") or "").split())[:40], str(w.get("kind") or "").strip().lower()
        if not name or kind not in WARE_KINDS or key(name) in seen or (kind == "tool" and any(o["kind"] == "tool" for o in out)):
            continue
        out.append({"name": name, "kind": kind, "weight": weights.get(key(name)), "description": " ".join(str(w.get("description") or "").split())[:120],
                    "attrs": {}, "per_day": max(1, min(3, w["per_day"])) if isinstance(w.get("per_day"), int) and not isinstance(w["per_day"], bool) else 1})
        seen.add(key(name))
        if len(out) == WARES_MAX:
            break
    return out if len(out) >= 2 else []


def _ask_wares(m):
    """A neighbour without wares gets a few things to sell, invented once from who they are (one at a time; tried again hourly)."""
    if m.ctx["params"]["wares"] not in (True, "on") or m.ctx["asking"] or "ask" in m.out:
        return
    n = next((n for n in m.neighbours() if not m.wares(n["name"]) and m.now >= (m.data["wares"].get(slot(n["name"])) or {}).get("retry", 0)), None)
    if not n:
        return
    m.put("wares", slot(n["name"]), {"name": n["name"], "wares": [], "retry": m.now + HOUR})
    ware = {"type": "object", "properties": {"name": {"type": "string"}, "kind": {"type": "string"}, "description": {"type": "string"},
                                              "per_day": {"type": "integer"}}, "required": ["name", "kind"]}
    m.out["ask"] = {"purpose": "wares:" + n["name"], "most": 600, "schema": {"properties": {"wares": {"type": "array", "items": ware}}, "required": ["wares"]},
                    "prompt": (n["name"] + " is " + m.ctx["agent"]["name"] + "'s neighbor. Who " + n["name"] + " is: " + (n.get("about") or "")
                               + "\n\n" + n["name"] + " has a few things to spare and sells them, at home and from a stall at the market one day a week. List 2-5 plain, physical things that fit their life and work (what "
                               "they find, grow, make or keep), as `wares`, each with:\n- `name`: a few words, as you'd write it on a label (\"cork floats\","
                               " \"carrot seeds\")\n- `kind`: material, food, seed or tool (at most one tool)\n- `description`: one short line\n- `per_day`: "
                               "how many they can spare in a day, 1-3\nNo services, nothing alive, nothing magical or rare beyond what this small world has.")}


def on_install(ctx):
    return Market(ctx).finish()


def on_tick(ctx):
    m = Market(ctx)
    _customers(m)
    _ask_wares(m)
    return m.finish(m.out)


def on_time(ctx):
    m = Market(ctx)
    _ask_wares(m)
    return m.finish(m.out)


def on_event(ctx):                                          # the agent arrived somewhere: what's on sale there
    return Market(ctx).finish()


def on_answer(ctx):
    m = Market(ctx)
    got = ctx["answer"]
    if got["purpose"].startswith("wares:"):
        name = got["purpose"][len("wares:"):]
        wares = _clean_wares(m, (got.get("data") or {}).get("wares"))
        if wares:
            m.put("wares", slot(name), {"name": name, "wares": wares})
            m.out["log"] = {"text": fit(name + " has things for sale: " + ", ".join(w["name"] for w in wares) + "."), "kind": "wares"}
    return m.finish(m.out)


def on_request(ctx):
    m = Market(ctx)
    r = ctx["request"]
    if r["what"] == "owe":                                  # taken from a shop to settle up later (gathering at a shop)
        place, items = r["args"].get("place"), r["args"].get("items")
        if not isinstance(place, str) or not place or not isinstance(items, dict) or not 1 <= len(items) <= OWE_LINES or not all(
                isinstance(k, str) and k.strip() and isinstance(n, int) and not isinstance(n, bool) and 1 <= n <= OWE_MOST for k, n in items.items()):
            return {"refuse": "`owe` is {place, items: {name: qty}}: up to " + str(OWE_LINES) + " things, 1 to " + str(OWE_MOST) + " each"}
        if not any(p["key"] == place and p["trades"] for p in m.places()):
            return {"refuse": "`owe.place` is a place that trades"}
        owed = dict(m.account(place))
        for n, q in items.items():
            owed[n] = owed.get(n, 0) + q
        m.put("accounts", slot(place), {"place": place, "items": owed})
        out = m.finish()
        out["reply"] = "on account at " + label(place)
        return out
    sign = 1 if r.get("tone") == "good" else -1             # price: a happening's turn for one thing at one booth
    units = sign * PRICE_UNITS.get(r.get("severity", "minor"), 1)
    booth = next((p for p in m.places() if p["trades"] and p["key"] == r["args"].get("place")), None)
    if not booth:
        return {"refuse": "`place` is the key of a place that sells"}
    pool = [i["name"] for i in ctx["items"] if i["kind"] == "food"] + [g["name"] for g in booth["goods"]]
    item = str(r["args"].get("item") or "").strip().lower() or (random.Random(ctx["seed"]).choice(pool).lower() if pool else "")
    if not item or item not in {p.lower() for p in pool}:
        return {"refuse": "`item` is something sold at " + booth["key"] + " or that " + ctx["agent"]["name"] + " has"}
    pct = round(abs((1 + PRICE_STEP) ** units - 1 if units > 0 else 1 - (1 - PRICE_STEP) ** -units) * 100)
    line = item[:1].upper() + item[1:] + " fetches about " + str(pct) + "% " + ("more" if units > 0 else "less") + " at " + booth["key"] + " for now."
    if not r["apply"]:
        return {"reply": line}
    m.nudge(booth["key"], item, units)
    out = m.finish()
    out["reply"] = line
    return out
