A module is one Python file (plain Python; you may import math, random, json, re, datetime, itertools, functools, collections,
statistics, heapq, bisect; nothing else, no files, no network, no attributes starting with "_", no .format). Define any of:
- on_install(ctx): once, when it goes live. on_time(ctx): at the time it asked for with "schedule". on_event(ctx): when one of the
  event kinds you list happens (ctx["event"] = {"kind", "data"}). on_tick(ctx): every few minutes (costly: prefer on_time).
Each gets ctx and returns a dict (or nothing). ctx holds:
- now (seconds since the epoch, local clock), seed (for random.Random(ctx["seed"])), state (the dict you returned last time as "state").
- time: {hour, minute, weekday ("Monday"...), season}. weather: {condition, temp, unit, daylight} or None.
- pip: {where (a place key; Pip's own home is "workshop"), at_home, activity, asleep}. items: Pip's belongings [{name, qty, kind}].
- places: the real places [{key, label, kind}] (kinds: home, wild, yard, sight, library, neighbor, shop, market).
- works: Pip's newest pixel drawings [{id, title, subject, rows, palette}]. stalls: Pip's stall lines [{place, item, kind, qty}].
- facts: what other modules published, by module name.
Return any of:
- "state": a dict to keep. "publish": facts other modules may read. "schedule": when to call on_time next (a time, like ctx["now"] + 3600).
- "perceive": one line Pip will notice (rare: a few a day at most). "log": one line for the day's record. "wake": true to wake Pip (rarer).
- "show": up to 8 pixel pictures in scenes: [{"id": "bell", "sprite": {"rows": ["..kk..", ...], "palette": {"k": "#3a2a1c"}},
  "size": 0.6, "frame": false, "at": {"type": "wall"|"surface"|"floor"|"ground", "place": "home" or a place key, "tags": [...]},
  "motion": "bob"|"sway"|"spin", "tip": {"title": "...", "text": "..."}}]. Rows are 4 to 32 letters long, all the same length, 4 to 32
  rows; "." is empty; each letter is a colour in the palette. "place" is "home" (Pip's workshop) or a place's key. Ask only for anchors
  that exist; tags must all match (leave them out to take any of that type). A "show" stays until you send another; [] clears it.
  The anchors, by kind of place:
ANCHORS
Event kinds you can listen for: EVENT_KINDS.
An example, only to show how the pieces fit (it is not an idea to propose; think of your own):

    def _next(ctx):
        return ctx["now"] + 3600 - ctx["now"] % 3600

    def on_install(ctx):
        return {"schedule": _next(ctx)}

    def on_time(ctx):
        out = {"schedule": _next(ctx)}
        t = ctx["time"]
        if t["weekday"] == "Saturday" and t["hour"] == 9:
            out["log"] = "The bell in the square rings for market day."
            if ctx["pip"]["where"] == "Brygdon":                 # a place's key, from ctx["places"]
                out["perceive"] = "The bell in the square rings: the market is open."
        return out
