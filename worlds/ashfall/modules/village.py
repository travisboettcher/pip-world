# The village by the reservoir, as voices: the radio in the shelter reads the evening notices (the model writes them, a few lines, once a
# day around `broadcast_hour`), and Marta keeps the village gate and answers whoever comes to talk to her there.
RADIO, GATE = "the radio", "Marta"
HEARD = 6


def _next_broadcast(ctx):
    t, now = ctx["time"], ctx["now"]
    since = t["hour"] * 3600 + t["minute"] * 60 + int(now) % 60
    at = now - since + ctx["params"]["broadcast_hour"] * 3600
    return at if at > now + 60 else at + 86400


def on_install(ctx):
    return {"voices": [{"name": RADIO, "at": "home", "about": "a crackling receiver tuned to the village's evening broadcast"},
                       {"name": GATE, "at": "village", "about": "keeps the village gate; blunt, fair, and knows everyone's business"}],
            "state": {"heard": []}, "schedule": _next_broadcast(ctx)}


def on_time(ctx):
    me = ctx["agent"]
    prompt = ("Write tonight's broadcast from a walled village of survivors by a reservoir in a dead city, twenty years after the ash: "
              "two or three short notices read over the radio (the water ration, a work party, a warning about dogs in the east blocks, a "
              "birth, a trade). Plain and calm, in the voice of whoever reads them. It is " + ctx["time"]["season"] + ". "
              + me["name"] + " is listening in her shelter.")
    return {"ask": {"prompt": prompt, "purpose": "broadcast", "most": 400}, "schedule": _next_broadcast(ctx)}


def on_message(ctx):
    m, st = ctx["message"], dict(ctx["state"])
    if m["to"].lower() != GATE.lower():
        return {}
    st["heard"] = (st.get("heard", []) + [{"who": m["from"], "text": m["text"]}])[-HEARD:]
    lines = "\n".join(h["who"] + ": " + h["text"] for h in st["heard"])
    prompt = ("You are Marta, who keeps the gate of a walled village of survivors by a reservoir, twenty years after the ash. You are "
              "blunt, fair and tired, and you know everyone's business. Answer in a sentence or two, as Marta, to what was just said.\n" + lines)
    return {"state": st, "ask": {"prompt": prompt, "purpose": "reply", "most": 300}}


def on_answer(ctx):
    a, st = ctx["answer"], dict(ctx["state"])
    if not a["text"]:
        return {}
    if a["purpose"] == "broadcast":
        return {"speak": {"as": RADIO, "text": a["text"]}}
    st["heard"] = (st.get("heard", []) + [{"who": GATE, "text": a["text"]}])[-HEARD:]
    return {"state": st, "speak": {"as": GATE, "text": a["text"], "to_agent": True}}
