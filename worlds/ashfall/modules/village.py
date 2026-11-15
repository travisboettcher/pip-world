# The village by the reservoir: the radio in the shelter reads the evening notices (the model writes them, a few lines, once a day around
# `broadcast_hour`), and the villagers live at the village, where Wren can talk with whoever is about in person (the engine's talk
# scenes: docs/DESIGN-engine-audit.md, C1). They come into the world one a day, Marta when it starts and the rest with the broadcasts.
RADIO = "the radio"
VILLAGERS = [
    {"name": "Marta", "about": "keeps the village gate; blunt, fair, and knows everyone's business",
     "persona": "Marta keeps the gate of a walled village of survivors by a reservoir, twenty years after the ash. Blunt, fair and tired; "
                "she knows everyone's business and trades news for news, and she has no patience for waste."},
    {"name": "Ezra", "about": "minds the village's water pumps; slow-spoken and careful with every drop",
     "persona": "Ezra keeps the pumps that bring the reservoir's water into the village. Slow-spoken, patient, a little deaf from the "
                "engines; he measures everything in buckets and remembers every dry summer."},
    {"name": "Jun", "about": "scavenges the east blocks and trades salvage at the gate; quick, cheerful, owed favours everywhere",
     "persona": "Jun goes out into the east blocks for salvage and trades it at the gate. Quick, cheerful and a little reckless; she is "
                "owed favours by half the village and knows where the dogs run."},
]


def _next_broadcast(ctx):
    t, now = ctx["time"], ctx["now"]
    since = t["hour"] * 3600 + t["minute"] * 60 + int(now) % 60
    at = now - since + ctx["params"]["broadcast_hour"] * 3600
    return at if at > now + 60 else at + 86400


def _villager(v):
    return {"name": v["name"], "kind": "villager", "persona": v["persona"], "about": v["about"], "home": "village"}


def _arrivals(ctx, out, st):
    """The next villager not yet in the world (or brought already: remembered here), and the next broadcast to look again at."""
    brought = list(st.get("brought", []))
    here = {p["name"] for p in ctx["people"]} | set(brought)
    missing = [v for v in VILLAGERS if v["name"] not in here]
    if missing:
        out["character"] = _villager(missing[0])
        st["brought"] = brought + [missing[0]["name"]]
    out["schedule"] = st["next"]
    out["state"] = st
    return out


def on_install(ctx):
    st = dict(ctx["state"], next=_next_broadcast(ctx))
    return _arrivals(ctx, {"voices": [{"name": RADIO, "at": "home", "about": "a crackling receiver tuned to the village's evening broadcast"}]}, st)


def on_time(ctx):
    st, out = dict(ctx["state"]), {}
    st.setdefault("next", _next_broadcast(ctx))
    if ctx["now"] >= st["next"]:
        me = ctx["agent"]
        prompt = ("Write tonight's broadcast from a walled village of survivors by a reservoir in a dead city, twenty years after the ash: "
                  "two or three short notices read over the radio (the water ration, a work party, a warning about dogs in the east "
                  "blocks, a birth, a trade). Plain and calm, in the voice of whoever reads them. "
                  + (f"It is {ctx['time']['season']}. " if ctx["time"]["season"] else "") + me["name"] + " is listening in her shelter.")
        out["ask"] = {"prompt": prompt, "purpose": "broadcast", "most": 400}
        st["next"] = _next_broadcast(ctx)
    return _arrivals(ctx, out, st)


def on_answer(ctx):
    a = ctx["answer"]
    return {"speak": {"as": RADIO, "text": a["text"]}} if a["text"] else {}
