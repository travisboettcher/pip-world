# Design: markets and coins

Status (2026-11-02): phase 1 built (`app/market.py`, `tests/test_market.py`); phases 2-3 not yet. Where the build differs from the plan below: a
booth's stock for the day is `max(2, 2 * the table's biggest quantity)` per item (no restocking mid-day), tills reset daily (not accumulate),
and `pay` settles the whole account at once. Grew out of the tomato glut (81 tomatoes after a day of scoop-seeds-and-replant):
crops had no demand. Crops now take about a day (v0.2.1); this gives the surplus somewhere to go, and gives Pip a reason to
roam, forage and want things. It replaces the ROADMAP's "Small economy" item.

## Principles (from the owner)
- A **market is a kind of place**, like Saltholm today. A place is made real by the existing invented-places path; nothing is hand-built.
- **A booth is the one trading unit.** Pip can run a booth and so can another agent (a neighbor or resident). Both use the same code:
  stock, prices, a till, a ledger. Nothing in trading knows whether the owner is Pip or a character.
- **Light supply and demand**: prices move a little with what has been bought and sold and drift back. They are never static, never wild.
- **Coins buy anything Pip can find.** Seeds, materials, food, tools: whatever the gather tables, a shop's loot table or a neighbor's
  parcel can give. Pip's own creations and works can be sold, but not bought back as stock.
- Follow CLAUDE.md: extend general verbs, keep new tools few, put sources of truth in the engine and let the GM only narrate.

## Coins
- One integer purse per **party** (`pip`, or a character's name): table `purses(party, coins)`. Pip starts with 10.
- Coins are never created by buying or selling. The only faucet is a booth keeper paying Pip from the keeper's **till**.
  A keeper's till refills a fixed amount each day (`TILL_PER_DAY`, default 40 coins for a shop, 80 for a market booth), so a
  booth can absorb only so much surplus per day. That is the natural throttle on a tomato glut: Pip can sell about a day's worth
  of one crop, not 81 at once.
- The only sinks are what Pip buys (the keeper's till takes the coins; stock leaves the booth).

## Prices
`price(booth, item) = base(item) * local(booth, item) * day_mood(place, item, day)`
- **base(item)**: engine-owned, from the item, never the LLM. Foraged finds: `max(1, round(K / weight))` from the gather table
  weights (rare is dear; common sticks cost 1). Food: `round(food_value * 10)`. Seeds: by the crop's yield and grow time. Tools: a fixed
  band by `kind`. Creations: quality. Unknown items: kind default. All integers >= 1.
- **local(booth, item)**, in `[0.6, 1.6]`: starts at 1. Each unit the booth *buys* from a seller lowers it 4% (it has plenty); each
  unit it *sells* raises it 4% (it is running low). It drifts back toward 1 by 10% of the gap per day. Per booth, per item, so one
  market glutted with tomatoes still pays fair prices at the next one.
- **day_mood**: a deterministic hash of (place, item, day) giving +-8%, so prices change a little every day with no state.
- **Spread**: a booth pays 60% of what it charges, so there is no arbitrage loop (buy then sell back costs 40%).
- Weather may nudge food prices (rain raises produce 5%); optional, off in the first version.

## Booths and places
- **Place kind `market`** (new entry in `place_kinds.py`; words: market, fair, bazaar, quay, stalls). Opening hours like a shop, several
  booths, each with a keeper.
- **Saltholm (kind `shop`) becomes a one-booth market.** Its keeper is its resident. Its loot table is its stock; its `on_account`
  list (things Pip picked through but owes for) becomes a coin debt at current prices, paid with `pay`.
- A booth row: `booths(id, place, owner, kind, till, stock JSON, ask JSON)` where `owner` is a party. A character-run booth is stocked
  by the engine from the place's loot table, restocked at the place's `refill` rate (today's gather mechanics), so a keeper's
  stock needs no LLM.
- **Pip's booth** (phase 2): at a market with a free stand, Pip `sell`s items to its own booth with an asking price (default the
  computed price). While Pip is *at* the market, simulated customers buy from it at an hourly rate that falls as the ask rises above
  the computed price; coins go into Pip's till and are collected with `pay`/`take`. Pip away: no sales, so being there matters.
- **Other agents run booths the same way**: a resident or neighbor with a trade gets a booth in their own place (or a market stand).
  Pip buys from them with `buy` exactly as from Saltholm. Letters may carry offers ("I have brass wire at 3 coins"), which are
  just text until Pip goes there.

## Verbs
Existing `browse`, `gather` stay. New (the economy is a genuinely new action, so it earns tools; they appear only where a booth is):
- `browse` at a market/shop: lists each booth's stock with the *current* price and buy/sell quote, plus Pip's purse and debts.
- `buy(item, qty?)`: pay the booth's sell price, item joins belongings. Refused if the booth lacks stock or Pip lacks coins (it says what
  it costs).
- `sell(item, qty?, ask?)`: at a booth that buys, instant sale at its buy price (limited by its till); phase 2 `ask` stocks Pip's own booth.
- `pay(booth?)`: settle what is owed on account (and, phase 2, collect Pip's own till).
`gather` in a shop stays "on account": it now records a coin debt rather than a bare item list.

## What Pip sees
Perception gains one line: `Coins: 14` and, at a market, the day's best prices ("Saltholm pays 4 for tomatoes today, 6 for carrots").
The guide gets a short `market.md`. The to-do/dedup logic is untouched. Because prices differ by booth and day, Pip has a real reason to
compare, travel and time its sales; there is no fixed "best action".

## Public view
Add `coins` and the market tab data (prices, Pip's till) to the public allowlist; `buy`/`sell`/`pay` tool *results* are public
(they are Pip's own affairs), with arguments still dropped. Names of other keepers go through the existing redaction.

## Plan
1. **Engine, phase 1 (TDD, ~1 release):** `purses`, base prices, local index and mood, `market` place kind, booth rows for shops,
   `browse`/`buy`/`sell`/`pay` against a keeper's till; Saltholm `on_account` converted to debt; perception line; public view.
2. **Phase 2:** Pip's own booth and customers; character booths beyond shopkeepers; letters that offer goods.
3. **Phase 3 (maybe):** weather and event effects on prices, a price history in the UI, a market tab.

## Open questions
- `TILL_PER_DAY` and the base-price constants need playing with. Aim: one day of Pip's garden (about 9 tomatoes) sells for roughly the
  cost of a few materials, so surplus matters but nothing is trivial.
- Should a booth ever refuse to deal with Pip (reputation)? Left out of v1.
- Do keepers keep coins between days (a rich merchant) or reset? Fixed refill keeps it simple; v1 resets to `TILL_PER_DAY`.
- Existing worlds: Pip's purse starts at 10 when the table is first created; Saltholm's debt is priced at the day it is converted.
