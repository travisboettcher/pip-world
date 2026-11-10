# A clock that needs tending: it keeps time (drifting a little each day), stops when it runs down, and can be tended and set.
# Its workings live in its creation's runtime, which the engine reads to show the time it keeps.

def _stopped_at(rt, now):
    if rt.get("halted_at"):
        return rt["halted_at"]
    if "tended_until" in rt and rt["tended_until"] <= now:
        return rt["tended_until"]
    return None


def _face(subject, now):
    """The time it shows: the offset when last set, plus drift while it ran (a stopped clock shows when it stopped)."""
    rt, drift = subject["runtime"], subject["capabilities"]["timekeeper"]["drift_per_day"]
    at = _stopped_at(rt, now) or now
    return at + rt["clock_offset"] * 60 + drift * 60 * (at - rt["clock_set_at"]) / 86400


def _offers(subject):
    up = subject["capabilities"]["upkeep"]
    return [{"name": "tend", "help": f"{up['verb']}: keeps it going about {round(up['hours'])} hours"},
            {"name": "set", "help": "set it to the right time"}]


def on_install(ctx):
    s = ctx["subject"]
    return {"offer": _offers(s), "schedule": max(s["runtime"].get("tended_until", ctx["now"]), ctx["now"])}


def on_time(ctx):
    s, now = ctx["subject"], ctx["now"]
    rt = s["runtime"]
    if _stopped_at(rt, now) is None:  # tended since: wait for the new running-down time
        return {"schedule": rt["tended_until"]}
    if rt.get("stop_logged"):
        return {}
    part = rt.get("needs_part")
    need = (f"{part['qty']} {part['name']} to mend it, then " if part else "") + f"tending ({s['capabilities']['upkeep']['verb']})"
    line = f"Your {s['name']} has stopped - it needs {need}."
    return {"runtime": {"stop_logged": True}, "log": line, "perceive": line, "wake": True}


def on_action(ctx):
    s, now, action = ctx["subject"], ctx["now"], ctx["action"]
    rt, up = s["runtime"], s["capabilities"]["upkeep"]
    if action == "set":
        if _stopped_at(rt, now) is not None:
            return {"reply": f"your {s['name']} has stopped; it needs tending ({up['verb']}) before it will keep any time"}
        return {"runtime": {"clock_set_at": now, "clock_offset": 0.0}, "reply": f"you set your {s['name']}; it shows the right time now"}
    out = {"runtime": {"tended_until": now + up["hours"] * 3600, "stop_logged": False, "halted_at": None, "needs_part": None},
           "schedule": now + up["hours"] * 3600}
    part = rt.get("needs_part")
    if part:  # a mishap broke something: mended with a real part first
        out["consume"] = {part["name"]: part["qty"]}
    if _stopped_at(rt, now) is not None:  # it starts again from the time it stopped at, so it's now behind
        out["runtime"].update(clock_set_at=now, clock_offset=(_face(s, now) - now) / 60)
    out["reply"] = f"you tend your {s['name']} ({up['verb']}); it will keep going for about {round(up['hours'])} hours"
    return out
