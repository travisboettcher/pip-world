# A creation's workings, as the engine has always run them: it runs down and stops unless tended (upkeep), keeps time and drifts
# (timekeeper), says something now and then (periodic), notices a condition and tells Pip (sensor), and helps on its own: finds something,
# hurries the garden along, or comforts Pip (helper), and, with a mind of its own, talks (companion): it is a voice where it is, chatters
# now and then, and answers when Pip talks to it, in words the model writes from who it is and what has been said. What it can do and how
# often come from the creation's capabilities; the times it last did each, and its conversation, are kept in this module's state. The
# clock's workings live in the creation's runtime, which the engine reads to show the time. Once it's sold or given away it does nothing.
import random

JITTER = (0.7, 1.3)
REPLIES_PER_HOUR, LINES_KEPT, BULLETINS_PER_DAY = 4, 6, 3


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
    if _news(subject):
        out.append({"name": "listen", "help": f"listen for news (up to {BULLETINS_PER_DAY} bulletins a day)"})
    return out


def _news(subject):
    return subject["capabilities"].get("provides", {}).get("ability") == "news"


def on_install(ctx):
    s, now = ctx["subject"], ctx["now"]
    if s is None:
        return {}
    rt, caps = s["runtime"], s["capabilities"]
    made, last = rt.get("made_at", now), rt.get("last") or {}
    out = {"offer": _offers(s), "state": {"last": {k: last.get(k, made) for k in ("periodic", "helper")}, "sensor_on": bool(rt.get("sensor_on"))}}
    if "upkeep" in caps:
        out["schedule"] = max(rt.get("tended_until", now), now)
    if "companion" in caps:
        out["voices"] = [{"name": s["name"], "at": "subject", "about": s["description"][:200]}]
        out["state"]["chatter_at"] = now + caps["companion"]["chatter_minutes"] * 60 * random.Random(ctx["seed"]).uniform(*JITTER)
    return out


def on_time(ctx):
    s, now = ctx["subject"], ctx["now"]
    if s is None:
        return {}
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
    if s is None or _stopped_at(s["runtime"], now) is not None:
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
    new = {**st, "last": last, "sensor_on": on}
    comp = caps.get("companion")
    if comp and not ctx["asking"] and now >= st.get("chatter_at", now):   # time to say something on its own
        out["ask"] = {"prompt": _prompt(ctx, []), "purpose": "chatter", "most": 300}
        new["chatter_at"] = now + comp["chatter_minutes"] * 60 * rng.uniform(*JITTER)
    if new != st:
        out["state"] = new
    if said:
        out["perceive"] = out["log"] = " ".join(said)
    return out


def on_action(ctx):
    s, now, action = ctx["subject"], ctx["now"], ctx["action"]
    if s is None:
        return {"reply": "it isn't yours any more"}
    rt, caps = s["runtime"], s["capabilities"]
    if action == "listen":
        return _listen(ctx)
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


# --- a mind of its own ---------------------------------------------------------------------------------------------------------
def _prompt(ctx, heard):
    s, pip, name = ctx["subject"], ctx["pip"], ctx["subject"]["name"]
    about = s["description"] + (f" Quirks: {'; '.join(s['quirks'])}." if s.get("quirks") else "")
    lines = ctx["state"].get("lines") or []
    return (f"Voice {name}, something Pip made that has a mind of its own: {about}\n"
            f"Who {name} is: {s['capabilities']['companion']['persona']}\n"
            f"Right now: Pip is {pip['activity']}, feeling {pip['mood']}.\n"
            + ("Recent conversation:\n" + "\n".join(lines) + "\n" if lines else "")
            + (f"Pip just said to {name}: " + " / ".join(f'"{h}"' for h in heard) + f"\nAnswer Pip as {name}."
               if heard else f"Nobody spoke to {name}; say something on its own that fits the moment, or do a small action (in *asterisks*) "
                             "if words don't fit.")
            + " One short line, at most 2 sentences, in character, and not something already said in the conversation above. It can't do "
              "more than such a thing plausibly could.")


def _quiet(ctx):
    s = ctx["subject"]
    return s is None or _stopped_at(s["runtime"], ctx["now"]) is not None


def on_message(ctx):
    """Pip spoke to it: remember it, and ask for an answer (unless it has answered enough this hour, or is already finding words)."""
    st, now = dict(ctx["state"]), ctx["now"]
    if _quiet(ctx):
        return {}
    text = ctx["message"]["text"]
    st["heard"] = (st.get("heard") or []) + [text]
    st["lines"] = ((st.get("lines") or []) + [f"Pip: {text}"])[-LINES_KEPT:]
    replies = [t for t in st.get("replies") or [] if now - t < 3600]
    st["replies"] = replies
    out = {"state": st}
    if not ctx["asking"] and len(replies) < REPLIES_PER_HOUR:
        out["ask"] = {"prompt": _prompt({**ctx, "state": ctx["state"]}, st["heard"]), "purpose": "reply", "most": 300}
        st["replies"] = replies + [now]
        st["answering"] = len(st["heard"])
    return out


def _listen(ctx):
    """Pip tunes in: a bulletin comes through (the model writes it), a few a day."""
    s, now, st = ctx["subject"], ctx["now"], dict(ctx["state"])
    if _stopped_at(s["runtime"], now) is not None:
        return {"reply": f"your {s['name']} has stopped; it needs tending ({s['capabilities']['upkeep']['verb']}) first"}
    heard = [t for t in st.get("news_log") or [] if now - t < 86400]
    if len(heard) >= BULLETINS_PER_DAY or ctx["asking"]:
        return {"reply": f"only static now: your {s['name']} has told you all the news it has today"}
    st["news_log"] = heard + [now]
    w, t = ctx.get("weather"), ctx["time"]
    prompt = (f"Pip listens to {s['name']}, something it made: {s['description']}. It is {t['weekday']}, {t['hour']}:00, in {t['season']}"
              + (f", and the weather is {w['condition']}" if w else "") + ". Write the bulletin that comes through: 2-3 sentences of news "
              "about Pip's own small world only (the weather, the neighbors, the season, something invented and harmless), never real-world "
              "events, in the voice of whatever this receiver picks up.")
    return {"state": st, "ask": {"prompt": prompt, "purpose": "news", "most": 400},
            "reply": f"you tune in to your {s['name']}; a bulletin is coming through"}


def on_answer(ctx):
    """The model's words: a bulletin for Pip, or said aloud (to Pip, if they answer it)."""
    st, a, s = dict(ctx["state"]), ctx["answer"], ctx["subject"]
    if a["purpose"] == "news":
        if not a["text"] or s is None:
            return {}
        line = f"Your {s['name']}: {a['text']}"
        return {"perceive": line, "log": line}
    reply = a["purpose"] == "reply"
    if reply:
        st["heard"] = (st.get("heard") or [])[st.pop("answering", 0):]
    if not a["text"] or s is None:
        return {"state": st}
    st["lines"] = ((st.get("lines") or []) + [f"{s['name']}: {a['text']}"])[-LINES_KEPT:]
    return {"state": st, "speak": {"as": s["name"], "text": a["text"], "to_pip": reply}}
