# Small events from the world (docs/DESIGN-happenings.md), as a module: the awake day is cut into slots; each slot gets one roll, and a
# hit picks a category the world allows (a garden needs a crop growing, a mishap something to stop...), not one that came up in the last
# twelve hours, weighted by the season; then a tone (good, bad or neutral, bad much less likely after two bad ones), a size, and what kind
# of thing changes. Slots slept through are rolled on waking, and a hit is something that happened in the night. The engine sets every
# amount, checks it all, keeps the day's limits, writes the words, and Pip takes it as it takes any happening.
import random

COOLDOWN, WINDOW, NIGHT_STALE = 12 * 3600, 30 * 60, 2 * 3600
TONES = {"good": 35, "bad": 25, "neutral": 40}
PITY = 0.3
SEVERITIES = ("minor", "medium", "major")
CATEGORIES = {  # name: (tones, can happen in the night)
    "garden": (("good", "bad", "neutral"), True), "creature": (("good", "bad", "neutral"), True), "pantry": (("bad", "neutral"), True),
    "found": (("good", "bad", "neutral"), True), "body": (("good", "bad", "neutral"), True), "market": (("good", "bad", "neutral"), False),
    "mishap": (("bad", "neutral"), True), "neighbor": (("good", "bad", "neutral"), False), "memory": (("good", "bad", "neutral"), True),
    "kindness": (("good",), True), "atmosphere": (("neutral",), True)}
SEASON_CATEGORY = {
    "winter": {"garden": 0.5, "creature": 1.2, "pantry": 1.3, "body": 1.3, "mishap": 1.2, "atmosphere": 1.4, "found": 0.8},
    "spring": {"garden": 1.5, "creature": 1.3, "found": 1.2, "kindness": 1.1, "atmosphere": 1.1},
    "summer": {"garden": 1.2, "pantry": 1.5, "creature": 1.1, "market": 1.2, "body": 0.9},
    "autumn": {"found": 1.4, "creature": 1.2, "memory": 1.5, "market": 1.2, "atmosphere": 1.2, "garden": 0.9}}
SEASON_TONE = {
    "winter": {("body", "bad"): 1.5, ("garden", "bad"): 1.3, ("body", "good"): 0.8},
    "spring": {("garden", "good"): 1.4, ("body", "good"): 1.3},
    "summer": {("pantry", "bad"): 1.4, ("garden", "good"): 1.1},
    "autumn": {("memory", "bad"): 1.4, ("found", "good"): 1.2}}
SHIFT = {"minor": 0.05, "medium": 0.15, "major": 0.30}
FALLBACK = {  # (category, tone): the words when the writer's don't pass the checks
    ("garden", "good"): ("A kind spell", "The light is kind to the garden this morning."),
    ("garden", "bad"): ("A bad turn", "Something is off in the garden: a chill, a pest, a wind."),
    ("garden", "neutral"): ("The garden shifts", "The air in the garden changes, and then settles again."),
    ("creature", "good"): ("A small visitor", "A small creature comes by and leaves something behind."),
    ("creature", "bad"): ("Nibbling", "Something has been at the pantry in the night."),
    ("creature", "neutral"): ("Watched", "A small creature watches you from the fence, then wanders off."),
    ("pantry", "bad"): ("Turned", "Some of what you stored has turned."),
    ("pantry", "neutral"): ("The shelves", "You look over the shelves and find everything as it was."),
    ("found", "good"): ("A small find", "You come across something small and useful."),
    ("found", "bad"): ("A hole in a pocket", "You find a hole in your pocket where something should be."),
    ("found", "neutral"): ("An odd thing", "You notice an odd little thing and turn it over."),
    ("body", "good"): ("Rested", "You wake with a lightness you hadn't expected."),
    ("body", "bad"): ("A rough day", "Your body is slow and heavy today."),
    ("body", "neutral"): ("A yawn", "A great yawn takes you by surprise."),
    ("market", "good"): ("Good word", "You hear that things are selling well."),
    ("market", "bad"): ("Bad word", "You hear the shelves are full and buyers are few."),
    ("market", "neutral"): ("Market talk", "You hear some idle talk about the market."),
    ("mishap", "bad"): ("Something slips", "Something in the workshop slips, jars or gives way."),
    ("mishap", "neutral"): ("A squeak", "Something in the workshop squeaks, and nothing is wrong."),
    ("neighbor", "good"): ("Good news", "Word comes from a neighbor that things are going well."),
    ("neighbor", "bad"): ("A small worry", "Word comes from a neighbor of a small worry."),
    ("neighbor", "neutral"): ("Neighbourly talk", "You hear a little idle talk about a neighbor."),
    ("memory", "good"): ("A fond thought", "An old thought of your own comes back to you."),
    ("memory", "bad"): ("A wistful thought", "An old thought of your own comes back, and lingers."),
    ("memory", "neutral"): ("A thought returns", "An old thought of your own comes back and puzzles you."),
    ("kindness", "good"): ("Left for you", "Someone has left something for you and gone."),
    ("atmosphere", "neutral"): ("In the air", "You notice a sound, a light, a smell, and then it is gone."),
}



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


def _low(pip):
    return pip["hunger"] >= 0.8 or pip["energy"] <= 0.25


def _plan(ctx, cat, tone, severity, rng):
    """What kind of thing changes ({effects, names}), or None if this category can't happen like this now."""
    pip, garden = ctx["agent"], [g for g in ctx["garden"] if g["state"] == "growing"]
    foods = sorted((i for i in ctx["items"] if i["kind"] == "food"), key=lambda i: -i["qty"])
    neighbors = [p["name"] for p in ctx["people"] if p["kind"] == "neighbor"]
    tools = [i["name"] for i in ctx["items"] if i["kind"] == "tool"]
    booths = [p["key"] for p in ctx["places"] if p["kind"] in ("shop", "market")]
    stoppable = [c["name"] for c in ctx["creations"] if c["tended"] and c["running"]]
    if cat == "garden":
        g = rng.choice(garden)
        if tone == "neutral":
            return {"names": [g["crop"]]}
        if tone == "bad" and severity == "major" and rng.random() < 0.5:
            return {"effects": [{"kind": "crop", "plot": g["plot"], "how": "ruin"}]}
        if rng.random() < 0.5:
            return {"effects": [{"kind": "crop", "plot": g["plot"], "how": "time"}]} if g["ready_in_min"] * SHIFT[severity] >= 1 else None
        return {"effects": [{"kind": "crop", "plot": g["plot"], "how": "yield"}]} if tone == "good" else None
    if cat in ("creature", "pantry"):
        if tone == "neutral":
            return {}
        if tone == "good":
            return {"effects": [{"kind": "item"}]}
        return {"effects": [{"kind": "food_loss"}]} if not _low(pip) and foods and foods[0]["qty"] >= 5 else None
    if cat == "found":
        if tone == "neutral":
            return {}
        if tone == "bad":
            return {"effects": [{"kind": "coins"}]} if pip["coins"] >= 10 else None
        return {"effects": [{"kind": "item" if rng.random() < 0.5 else "coins"}]}
    if cat == "body":
        if tone == "neutral":
            return {}
        if tone == "bad" and _low(pip):
            return None
        return {"effects": [{"kind": rng.choice(("energy", "hunger"))}]}
    if cat == "market":
        booth = rng.choice(booths)
        if tone == "neutral":
            return {"names": [booth]}
        return {"effects": [{"kind": "price", "place": booth, **({"item": foods[0]["name"]} if foods else {})}]}
    if cat == "mishap":
        if tone == "neutral":
            return {"names": tools[:1]}
        if severity == "minor":
            return None if _low(pip) else {"effects": [{"kind": "energy"}], "names": tools[:1]}
        if not stoppable:
            return None
        return {"effects": [{"kind": "stop", "creation": rng.choice(stoppable), "mend": severity == "major"}]}
    if cat == "neighbor":
        name = rng.choice(neighbors)
        return {"names": [name]} if tone == "neutral" else {"effects": [{"kind": "news", "name": name}]}
    if cat == "memory":
        return {"effects": [{"kind": "memory"}]}
    if cat == "kindness":
        return {"effects": [{"kind": "item" if rng.random() < 0.5 else "coins", "gift": True}], "names": [rng.choice(neighbors)]}
    return {}                                                 # atmosphere


def _possible(ctx, cat):
    garden = [g for g in ctx["garden"] if g["state"] == "growing"]
    return {"garden": bool(garden), "market": any(p["kind"] in ("shop", "market") for p in ctx["places"]),
            "mishap": any(c["tended"] and c["running"] for c in ctx["creations"]) or any(i["kind"] == "tool" for i in ctx["items"]),
            "neighbor": any(p["kind"] == "neighbor" for p in ctx["people"]), "kindness": any(p["kind"] == "neighbor" for p in ctx["people"]),
            "memory": ctx["happenings"]["can_remember"]}.get(cat, True)


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
    st, pip, now, p = dict(ctx["state"]), ctx["agent"], ctx["now"], ctx["params"]
    st.setdefault("rolled", [])
    out = {}
    if pip["asleep"]:
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
        if slot and now - slot[1] <= WINDOW and slot[0] not in st["rolled"] and not pip["walking"] and not ctx["happenings"]["room"]:
            st["rolled"] = (st["rolled"] + [slot[0]])[-12:]
            if random.Random(f"{st.get('salt')}:{slot[0]}").random() < p["chance"]:
                h = _choose(ctx, random.Random(f"{st.get('salt')}:{slot[0]}:build"), False)
                if h:
                    out["happen"] = h
    if st != ctx["state"]:
        out["state"] = st
    return out
