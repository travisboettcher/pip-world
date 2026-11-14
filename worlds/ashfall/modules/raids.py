# What happens out here (Ashfall's happenings): the awake day is cut into slots; each slot gets one roll, and a hit picks a category the
# world allows (a raid, salvage, an ash day, a kindness from the village, a quiet moment, how she feels, an old thought), not one that came
# up in the last twelve hours; then a tone, a size and what changes. Out in the open a raid hurts her (`harm`); at home behind the door
# it costs food. Slots slept through are rolled on waking. The engine sets every amount, checks it all and writes the words.
import random

COOLDOWN, WINDOW = 12 * 3600, 30 * 60
TONES = {"good": 30, "bad": 35, "neutral": 35}
PITY = 0.3
SEVERITIES = ("minor", "medium", "major")
CATEGORIES = {  # name: (tones, can happen in the night)
    "raid": (("bad", "neutral"), True), "salvage": (("good", "neutral"), False), "ashfall": (("bad", "neutral"), True),
    "kindness": (("good",), False), "quiet": (("neutral",), True), "body": (("good", "bad", "neutral"), True), "memory": (("good", "bad", "neutral"), True)}
SEASON_CATEGORY, SEASON_TONE = {}, {}
FALLBACK = {
    ("raid", "bad"): ("Dogs", "A dog pack comes out of the rubble, and you get away, but not clean."),
    ("raid", "neutral"): ("Tracks", "Fresh tracks in the ash: something big passed here in the night."),
    ("salvage", "good"): ("Worth having", "Under a fallen shelf, something worth having."),
    ("salvage", "neutral"): ("Picked clean", "Someone has been through here before you, and recently."),
    ("ashfall", "bad"): ("Ash", "The sky goes the colour of old tin and the ash comes down."),
    ("ashfall", "neutral"): ("Grey", "A grey haze sits over the city all afternoon."),
    ("kindness", "good"): ("From the village", "Someone from the village left something by your door."),
    ("quiet", "neutral"): ("Quiet", "For a while the city is perfectly quiet."),
    ("body", "good"): ("A good day", "You feel stronger today than you have in a while."),
    ("body", "bad"): ("Heavy", "Everything is heavy today."),
    ("body", "neutral"): ("A cough", "A dry cough, and then it passes."),
    ("memory", "good"): ("A fond thought", "An old thought of your own comes back to you."),
    ("memory", "bad"): ("A thought that lingers", "An old thought of your own comes back, and lingers."),
    ("memory", "neutral"): ("A thought returns", "An old thought of your own comes back and puzzles you."),
}


def _plan(ctx, cat, tone, severity, rng):
    """What changes ({effects}), or None if this category can't happen like this now."""
    me = ctx["agent"]
    foods = sorted((i for i in ctx["items"] if i["kind"] == "food"), key=lambda i: -i["qty"])
    if tone == "neutral":
        return {"effects": [{"kind": "memory"}]} if cat == "memory" else {}
    if cat == "raid":
        if not me["at_home"]:
            return {"effects": [{"kind": "harm", "stat": "health"}]}
        return {"effects": [{"kind": "food_loss"}]} if foods and foods[0]["qty"] >= 5 else None
    if cat == "salvage":
        return {"effects": [{"kind": "item"}]}
    if cat == "ashfall":
        return {"effects": [{"kind": "radiation"}]}
    if cat == "kindness":
        return {"effects": [{"kind": "item", "gift": True}]}
    if cat == "body":
        return {"effects": [{"kind": "energy"}]}
    if cat == "memory":
        return {"effects": [{"kind": "memory"}]}
    return None


def _possible(ctx, cat):
    return {"memory": ctx["happenings"]["can_remember"]}.get(cat, True)

def on_install(ctx):
    return {"state": {"salt": random.Random(ctx["seed"]).getrandbits(48), "rolled": []}}


def _slots(ctx):
    """(key, start) for the current awake day's slots, from the wake hour, `slot_hours` apart."""
    p, t, now = ctx["params"], ctx["time"], ctx["now"]
    since_midnight = t["hour"] * 3600 + t["minute"] * 60 + int(now) % 60
    midnight = now - since_midnight
    wake, bed = p["wake_hour"], p["bedtime_hour"]
    length = (bed - wake) % 24 or 24
    out = []
    for back in (1, 0):                                      # yesterday's awake day may run past midnight
        day = midnight - back * 86400
        k = 0
        while k * p["slot_hours"] < length:
            start = day + (wake + k * p["slot_hours"]) * 3600
            out.append((f"{int(day)}#{k}", start))
            k += 1
    started = [s for s in out if s[1] <= now]
    return max(started, key=lambda s: s[1]) if started else None



def _choose(ctx, rng, night):
    """A category, tone, size and what changes, for the world as it is; None when nothing fits."""
    p, now, recent = ctx["params"], ctx["now"], ctx["happenings"]["recent"]
    season = ctx["time"]["season"] if p["seasons"] else None
    cooling = {h["category"] for h in recent if now - h["ts"] < COOLDOWN and h["status"] != "skipped"}
    tones_seen = [h["tone"] for h in recent]
    options = [c for c, (tones, at_night) in CATEGORIES.items() if c not in cooling and _possible(ctx, c) and (at_night or not night)]
    while options:
        cat = rng.choices(options, weights=[SEASON_CATEGORY.get(season, {}).get(c, 1) for c in options])[0]
        tones = CATEGORIES[cat][0]
        weights = [TONES[t] * SEASON_TONE.get(season, {}).get((cat, t), 1) * (PITY if t == "bad" and tones_seen[:2] == ["bad", "bad"] else 1) for t in tones]
        tone = rng.choices(list(tones), weights=weights)[0]
        severity = "minor" if tone == "neutral" else rng.choices(SEVERITIES, weights=p["severity"])[0]
        plan = _plan(ctx, cat, tone, severity, rng)
        if plan is not None:
            title, text = FALLBACK.get((cat, tone), ("", ""))
            return {"category": cat, "tone": tone, "severity": severity, **plan, **({"night": True} if night else {}),
                    **({"fallback": {"title": title, "text": text}} if title else {})}
        options.remove(cat)
    return None


def on_tick(ctx):
    st, me, now, p = dict(ctx["state"]), ctx["agent"], ctx["now"], ctx["params"]
    st.setdefault("rolled", [])
    out = {}
    if me["asleep"]:
        if "slept_at" not in st:
            st["slept_at"] = now
        return {"state": st} if st != ctx["state"] else {}
    night = None
    if "slept_at" in st:                                     # just woke: roll once for each slot slept through
        slept = st.pop("slept_at")
        slots = int((now - slept) / 3600 // p["slot_hours"])
        rng = random.Random(f"{st.get('salt')}:night:{int(slept)}")
        if slots >= 1 and not ctx["happenings"]["room"] and any(rng.random() < p["chance"] for _ in range(slots)):
            night = True
    if night:
        rng = random.Random(f"{st.get('salt')}:night-build:{int(now)}")
        h = _choose(ctx, rng, True)
        if h:
            out["happen"] = h
    else:
        slot = _slots(ctx)
        if slot and now - slot[1] <= WINDOW and slot[0] not in st["rolled"] and not me["walking"] and not ctx["happenings"]["room"]:
            st["rolled"] = (st["rolled"] + [slot[0]])[-12:]
            if random.Random(f"{st.get('salt')}:{slot[0]}").random() < p["chance"]:
                h = _choose(ctx, random.Random(f"{st.get('salt')}:{slot[0]}:build"), False)
                if h:
                    out["happen"] = h
    if st != ctx["state"]:
        out["state"] = st
    return out
