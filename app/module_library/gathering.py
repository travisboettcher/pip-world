# Gathering (docs/DESIGN-world-packs.md, phase 5a): the `gather` tool wherever a place lists it, a session of real time, and when it
# ends a haul drawn from the place's find table (the engine's place data: `here`), smaller the more picked over the place is and a
# little kinder to rare things the better the agent's practice. What is found is given (and remembered where), the place is drawn
# down, the practice counts, a shop's haul goes on account (trade keeps it), and the model is asked for the words.
import random

RARE_WEIGHT = 6          # things at or below this weight are rare: practice helps find them
MINUTES_PER_FIND = 10    # one draw from the table per this many minutes (before the place is picked over)
MAX_DRAWS = 8
MIN_YIELD = 0.2
MOST = 20                # the most of one thing a haul gives


def _clamp(v, lo, hi, default):
    try:
        return max(lo, min(hi, int(v)))
    except (TypeError, ValueError):
        return default


def draw(rng, table, minutes, factor, skill):
    """The haul: [name, kind, qty, description, attrs]. Weighted draws; practice nudges rare finds up; a picked-over place gives less."""
    n = max(0, min(MAX_DRAWS, round(minutes / MINUTES_PER_FIND * factor + rng.uniform(-0.5, 0.5))))
    weights = [w * (1 + 0.15 * skill) if w <= RARE_WEIGHT else w for _, _, w, _, _, _ in table]
    found = {}
    for _ in range(n):
        name, kind, _, span, desc, attrs = rng.choices(table, weights=weights)[0]
        qty = max(1, round(rng.randint(span[0], span[1]) * (0.5 + 0.5 * factor)))
        if name in found:
            found[name][2] += qty
        else:
            found[name] = [name, kind, qty, desc, attrs]
    return list(found.values())


def words(label, minutes, found, depleted):
    if not found:
        return "You spend about " + str(minutes) + " minutes at " + label + " and come away with nothing" + (
            ": it's been picked over." if depleted else ".")
    return ("You spend about " + str(minutes) + " minutes at " + label + " and find " + ", ".join(str(f[2]) + " " + f[0] for f in found)
            + (", though it's getting picked over." if depleted else "."))


def on_action(ctx):
    here = ctx["here"]
    if not here or not here["finds"]:
        return {"reply": "error: there's nothing to gather here"}
    lo, hi = here["session"]
    minutes = _clamp(ctx["args"].get("minutes"), lo, hi, min(30, hi))
    speed = ctx["params"]["speed"]
    real = max(1, round(minutes / speed))
    note = " The ground looks well picked over." if here["stock"] < here["full_at"] else ""
    return {"session": {"minutes": real, "label": "out " + here["gerund"] + " at " + here["label"], "working": True},
            "doing": {"activity": "gathering", "description": here["gerund"] + " at " + here["label"]},
            "store": {"trip": {"now": {"place": here["key"], "minutes": minutes}}},
            "reply": ("you set about " + here["gerund"] + " at " + here["label"] + " for " + str(minutes) + " min." + note
                      + " You'll see what you found in about " + str(real) + " min.")}


def on_time(ctx):
    """The session is over (its time is up, or the agent rested): the haul."""
    s, trip, here = ctx.get("session"), ctx["store"].get("trip", {}).get("now"), ctx["here"]
    if not s or not trip:
        return {}
    out = {"store": {"trip": {"now": None}}}
    if not here or here["key"] != trip["place"] or not here["finds"]:
        return out
    minutes = trip["minutes"]
    if s["interrupted"]:
        minutes = min(minutes, s["minutes"] * ctx["params"]["speed"])
    factor = max(MIN_YIELD, min(1.0, here["stock"] / here["full_at"])) if here["full_at"] else 1.0
    practice = ctx["params"]["practice"]
    skill = sum(ctx["abilities"].get(a, 0) for a in practice) / max(1, len(practice))
    found = draw(random.Random(ctx["seed"]), here["finds"], minutes, factor, skill)
    depleted = factor < 0.5
    if minutes > 0:
        out["deplete"] = {"amount": min(240, minutes), "place": here["key"]}
        out["practice"] = {a: minutes / len(practice) for a in practice}
    if found:
        out["give"] = [{"item": f[0], "qty": min(MOST, f[2]), "kind": f[1], "description": f[3], "attrs": f[4], "at": here["key"]} for f in found]
        if here["shop_hours"] and here["trades"] and "owe" in ctx["answers"].get("trade", []):     # on account, kept by trade
            out["request"] = {"module": "trade", "what": "owe", "args": {"place": here["key"], "items": {f[0]: min(MOST, f[2]) for f in found}}}
    if ctx["agent"]["activity"] == "gathering":
        out["doing"] = {"activity": "idle", "description": "just back from " + here["gerund"] + " at " + here["label"]}
    account = (" It's on account at " + here["label"] + ": they're happy for you to settle up later.") if out.get("request") else ""
    text = words(here["label"], round(minutes), found, depleted) + account
    items = [{"name": f[0], "qty": min(MOST, f[2])} for f in found]
    if s["interrupted"]:                                     # cut short: told plainly, at once
        out.update(log={"text": text + " (You cut it short.)", "kind": "gathered", "items": items, "tool": "gather"}, wake=True)
        return out
    got = ", ".join(str(i["qty"]) + " " + i["name"] for i in items) or "nothing"
    out["store"]["trip"]["told"] = {"text": text, "items": items, "account": account}
    out["ask"] = {"purpose": "haul", "most": 300, "prompt": (
        ctx["agent"]["name"] + " spent about " + str(round(minutes)) + " minutes " + here["gerund"] + " at " + here["label"]
        + ". What was found (already decided; mention only these, invent no other finds): " + got + "."
        + (" The place is getting picked over, so there was little to find." if depleted else "")
        + " Describe the outing in 1-2 short concrete sentences (under 40 words), second person ('You ...'), in the manner of someone"
        + " poking around in this kind of place. No numbers.")}
    return out


def on_answer(ctx):
    told = ctx["store"].get("trip", {}).get("told")
    if not told or ctx["answer"]["purpose"] != "haul":
        return {}
    said = " ".join(ctx["answer"]["text"].split())[:300]
    text = (said + told["account"]) if said else told["text"]           # the model's words, or the plain ones if none came
    return {"store": {"trip": {"told": None}}, "log": {"text": text, "kind": "gathered", "items": told["items"], "tool": "gather"}, "wake": True}
