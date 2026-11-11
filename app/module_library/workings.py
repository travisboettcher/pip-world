# A creation's workings, as the engine has always run them: it runs down and stops unless tended (upkeep), keeps time and drifts
# (timekeeper), says something now and then (periodic), notices a condition and tells Pip (sensor), and helps on its own: finds something,
# hurries the garden along, or comforts Pip (helper). What it can do and how often come from the creation's capabilities; the times it last
# did each are kept in this module's state. The clock's workings live in the creation's runtime, which the engine reads to show the time.
import random


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
    caps, out = subject["capabilities"], []
    if "upkeep" in caps:
        up = caps["upkeep"]
        out.append({"name": "tend", "help": f"{up['verb']}: keeps it going about {round(up['hours'])} hours"})
    if "timekeeper" in caps:
        out.append({"name": "set", "help": "set it to the right time"})
    return out


def on_install(ctx):
    s, now = ctx["subject"], ctx["now"]
    rt = s["runtime"]
    made, last = rt.get("made_at", now), rt.get("last") or {}
    out = {"offer": _offers(s), "state": {"last": {k: last.get(k, made) for k in ("periodic", "helper")}, "sensor_on": bool(rt.get("sensor_on"))}}
    if "upkeep" in s["capabilities"]:
        out["schedule"] = max(rt.get("tended_until", now), now)
    return out


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


def _condition(ctx, cond):
    if cond == "crop_ripe":
        return any(g["state"] == "ready" for g in ctx["garden"])
    if cond == "visitor":
        return ctx["visitors"]["waiting"] > 0
    if cond == "dawn":
        return ctx["time"]["hour"] == 6
    if cond == "dusk":
        return ctx["time"]["hour"] == 19
    if cond == "hungry":
        return ctx["pip"]["hunger"] >= 0.6
    return ctx["pip"]["energy"] <= 0.3  # tired


def on_tick(ctx):
    s, now, st = ctx["subject"], ctx["now"], ctx["state"]
    if _stopped_at(s["runtime"], now) is not None:
        return {}
    caps, rng = s["capabilities"], random.Random(ctx["seed"])
    last, on, said, out = dict(st.get("last") or {}), bool(st.get("sensor_on")), [], {}
    p = caps.get("periodic")
    if p and now - last.get("periodic", now) >= p["every_minutes"] * 60:
        said.append(f"Your {s['name']}: {rng.choice(p['lines'])}")
        last["periodic"] = now
    if "sensor" in caps:
        was, on = on, _condition(ctx, caps["sensor"]["condition"])
        if on and not was:
            said.append(caps["sensor"]["alert"])
            out["wake"] = True
    h = caps.get("helper")
    if h and now - last.get("helper", now) >= h["every_minutes"] * 60:
        last["helper"] = now
        if h["effect"] == "find":
            item = rng.choice(h["finds"])
            out["find"] = {"item": item, "qty": 1}
            said.append(f"{h['line']} (found: {item})")
        elif h["effect"] == "hurry_crops":
            if any(g["state"] == "growing" for g in ctx["garden"]):
                out["garden"] = {"hurry": 0.1}
                said.append(h["line"])
        else:  # comfort
            out["affect"] = {"energy": 0.05}
            said.append(h["line"])
    new = {"last": last, "sensor_on": on}
    if new != st:
        out["state"] = new
    if said:
        out["perceive"] = out["log"] = " ".join(said)
    return out


def on_action(ctx):
    s, now, action = ctx["subject"], ctx["now"], ctx["action"]
    rt, caps = s["runtime"], s["capabilities"]
    if action == "set":
        if _stopped_at(rt, now) is not None:
            return {"reply": f"your {s['name']} has stopped; it needs tending ({caps['upkeep']['verb']}) before it will keep any time"}
        return {"runtime": {"clock_set_at": now, "clock_offset": 0.0}, "reply": f"you set your {s['name']}; it shows the right time now"}
    up = caps["upkeep"]
    out = {"runtime": {"tended_until": now + up["hours"] * 3600, "stop_logged": False, "halted_at": None, "needs_part": None},
           "schedule": now + up["hours"] * 3600}
    part = rt.get("needs_part")
    if part:  # a mishap broke something: mended with a real part first
        out["consume"] = {part["name"]: part["qty"]}
    if _stopped_at(rt, now) is not None and "timekeeper" in caps:  # it starts again from the time it stopped at, so it's now behind
        out["runtime"].update(clock_set_at=now, clock_offset=(_face(s, now) - now) / 60)
    out["reply"] = f"you tend your {s['name']} ({up['verb']}); it will keep going for about {round(up['hours'])} hours"
    return out
