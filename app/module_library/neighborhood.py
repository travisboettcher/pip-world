# The neighbourhood (docs/DESIGN-world-packs.md, phase 5b): someone who lives near the agent, invented once by the model, and when they write
# first. Letters themselves are the engine's (conversation at a distance: a neighbour answers the agent's letters as they answer in
# person); this module decides who the neighbour is and asks them to write now and then.
import random

JITTER = (0.7, 1.3)
RETRY = 3600


def _neighbours(ctx):
    return [p["name"] for p in ctx["people"] if p["kind"] == "neighbor"]


def _invite(ctx):
    a = ctx["agent"]
    world = a["name"] + " " + a["lives"] if a["lives"] else a["name"] + " lives at home"
    made = [c["name"] for c in ctx["creations"]][:5]
    if made:
        world += "; " + a["name"] + " has made " + ", ".join(made)
    return {"purpose": "neighbour", "mentions": True, "most": 600,
            "schema": {"properties": {
                "name": {"type": "string", "description": "what they're called"},
                "persona": {"type": "string", "description": "3-5 sentences, private: who they are, what their days are like, what they care about, how they write letters"},
                "about": {"type": "string", "description": "one short line of what " + a["name"] + " would know about them from a distance (where they live, what they're known for)"},
                "letter": {"type": "string", "description": "their first letter to " + a["name"] + ", introducing themselves (2-5 sentences, in their voice)"}},
                "required": ["name", "persona", "about", "letter"]},
            "prompt": (a["name"] + "'s world so far: " + world + "\n\nSomeone lives near " + a["name"] + " and is about to write to "
                       + a["name"] + " for the first time. Invent them freely - any kind of creature or person that fits this small world, with "
                       "their own life, work, worries and way of writing. Make their life genuinely different from " + a["name"] + "'s (not "
                       "another maker of the same kinds of things), so they have their own world to share. " + a["name"] + " may walk over and "
                       "visit them at home some day; they don't go out visiting themselves.")}


def on_install(ctx):
    return {"schedule": ctx["now"]}


def on_time(ctx):
    now, st, rng = ctx["now"], ctx["state"], random.Random(ctx["seed"])
    every = ctx["params"]["every_hours"] * 3600
    names = _neighbours(ctx)
    if not names:
        if not ctx["params"]["invent"] or ctx["asking"]:
            return {"schedule": now + RETRY}
        return {"ask": _invite(ctx), "schedule": now + RETRY}
    due = dict(st.get("due", {}))
    out = {}
    for name in names:
        if name not in due:                                       # someone new (or here before this module): their first is a while off
            due[name] = now + every * rng.uniform(*JITTER)
        elif now >= due[name] and "letter" not in out:
            out["letter"] = {"from": name}
            due[name] = now + every * rng.uniform(*JITTER)
    out["state"] = {**st, "due": due}
    out["schedule"] = min(due.values())
    return out


def on_answer(ctx):
    got = ctx["answer"]
    if got["purpose"] != "neighbour" or not got.get("data") or _neighbours(ctx):
        return {"schedule": ctx["now"] + RETRY}
    d = got["data"]
    new = {"name": d["name"][:40].strip(), "kind": "neighbor", "persona": d["persona"][:800], "about": d["about"][:160], "letter": d["letter"][:1200]}
    if got.get("mentions_place"):
        new["mentions_place"] = got["mentions_place"]
    return {"character": new, "schedule": ctx["now"] + 60}
