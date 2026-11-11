"""Creations: finished projects that keep existing (and sometimes keep doing things) in the world.

A creation is a stored spec: zero to three capabilities plus a few quirks. Many creations (art, keepsakes, writing)
have no capabilities at all. The capabilities are deliberately generic primitives - the engine knows how to *run*
them, while the GM fills in everything specific (what the thing does, says, finds, how it's tended) once, when the
project is finished. The engine owns every number (from the project's quality) and runs capabilities each monitor
pass without any LLM. New primitive = one entry in each of `sanitize_spec`, `tick` and `describe`.
"""
import random
import time

from . import abilities
from . import world_effects
from .text import clip
from .projects import quality as project_quality, scars as project_scars
from .state import clamp

CAPABILITIES = ("timekeeper", "upkeep", "periodic", "sensor", "helper", "companion", "world", "provides")
SENSOR_CONDITIONS = ("crop_ripe", "visitor", "dawn", "dusk", "hungry", "tired")
HELPER_EFFECTS = {"hurry_crops": 60, "find": 360, "comfort": 240}  # effect -> minimum minutes between runs
MAX_CAPABILITIES = 3
COMPANION_MIN_DIFFICULTY = 3  # small, simple pieces don't get a mind of their own
DRIFT_MIN_PER_DAY = {"rough": 15, "sound": 5, "fine": 1.5, "masterwork": 0.3}
UPKEEP_FACTOR = {"rough": 0.5, "sound": 1.0, "fine": 1.5, "masterwork": 2.0}
HURRY_FRACTION = 0.1      # hurry_crops: share of remaining growing time saved per run
COMFORT_ENERGY = 0.05     # comfort: energy restored per run
USE_ENERGY_COOLDOWN = 6 * 3600
DRIFT_NOTICED = 5         # minutes a clock must be off before Pip is told (and tempted to reset it every hour)


def _num(v, lo: float, hi: float, default: float) -> float:
    try:
        return max(lo, min(hi, float(v)))
    except (TypeError, ValueError):
        return default


def _line(v, n: int = 160) -> str:
    return clip(v, n)


def _lines(v, n: int, limit: int = 120) -> list[str]:
    return [_line(x, limit) for x in (v or []) if isinstance(x, str) and _line(x)][:n]


def sanitize_spec(raw: dict | None, project: dict, quality: str, scars: list[str],
                  rng: random.Random) -> tuple[str, str, dict]:
    """GM design -> (name, description, spec). Unknown capabilities and unusable params are dropped."""
    raw = raw or {}
    caps: dict[str, dict] = {}
    for c in raw.get("capabilities") or []:
        if not isinstance(c, dict) or c.get("type") not in CAPABILITIES or c["type"] in caps:
            continue
        t = c["type"]
        if t == "timekeeper":
            caps[t] = {"drift_per_day": DRIFT_MIN_PER_DAY[quality] * rng.choice((-1, 1))}
        elif t == "upkeep":
            verb = _line(c.get("verb"), 20).lower().strip(" .") or "tend"
            caps[t] = {"verb": verb, "hours": round(_num(c.get("hours"), 4, 72, 24) * UPKEEP_FACTOR[quality], 1)}
        elif t == "periodic":
            lines = _lines(c.get("lines"), 3)
            if lines:
                caps[t] = {"lines": lines, "every_minutes": _num(c.get("every_minutes"), 20, 720, 120)}
        elif t == "sensor":
            if c.get("condition") in SENSOR_CONDITIONS and _line(c.get("alert")):
                caps[t] = {"condition": c["condition"], "alert": _line(c["alert"])}
        elif t == "helper":
            effect, line = c.get("effect"), _line(c.get("line"))
            finds = _lines(c.get("finds"), 4, 40)
            if effect in HELPER_EFFECTS and line and (effect != "find" or finds):
                low = HELPER_EFFECTS[effect]
                caps[t] = {"effect": effect, "line": line, "every_minutes": _num(c.get("every_minutes"), low, 1440, low * 2),
                           **({"finds": [f.lower() for f in finds]} if effect == "find" else {})}
        elif t == "world":
            if world_effects.allowed(c.get("effect"), project):  # the engine checks; the GM only proposes
                caps[t] = {"effect": c["effect"]}
        elif t == "provides":
            if abilities.allowed(c.get("ability"), project):  # the engine checks; the GM only proposes
                caps[t] = {"ability": c["ability"]}
        elif t == "companion":
            if project["difficulty"] >= COMPANION_MIN_DIFFICULTY and _line(c.get("persona")):
                caps[t] = {"persona": _line(c["persona"], 400),
                           "chatter_minutes": _num(c.get("chatter_minutes"), 60, 720, 180)}
        if len(caps) >= MAX_CAPABILITIES:
            break
    # setbacks leave marks: the GM is asked to turn them into quirks; without it, the marks are the quirks
    quirks = _lines(raw.get("quirks"), 3) or [_line(x, 120) for x in scars[:2]]
    name = _line(raw.get("name"), 60) or project["name"]
    description = _line(raw.get("description"), 240) or f"your finished {project['name']}"
    return name, description, {"capabilities": caps, "quirks": quirks, "scars": [_line(s, 200) for s in scars[:3]]}


def initial_runtime(spec: dict, now: float) -> dict:
    rt = {"made_at": now, "last": {}, "sensor_on": False}
    if "upkeep" in spec["capabilities"]:
        rt["tended_until"] = now + spec["capabilities"]["upkeep"]["hours"] * 3600
    if "timekeeper" in spec["capabilities"]:
        rt.update(clock_set_at=now, clock_offset=0.0)
    return rt


def stopped_at(c: dict, now: float) -> float | None:
    """When it stopped (halted by a mishap, or its upkeep ran out), or None if it's going."""
    rt = c["runtime"]
    if rt.get("halted_at"):
        return rt["halted_at"]
    if "tended_until" in rt and rt["tended_until"] <= now:
        return rt["tended_until"]
    return None


def running(c: dict, now: float) -> bool:
    return stopped_at(c, now) is None


def clock_face(c: dict, now: float) -> float:
    """The time it shows, as a timestamp: the offset when last set, plus drift while it ran.
    A stopped timekeeper shows the time it stopped at."""
    rt, drift = c["runtime"], c["spec"]["capabilities"]["timekeeper"]["drift_per_day"]
    at = stopped_at(c, now) or now
    return at + rt["clock_offset"] * 60 + drift * 60 * (at - rt["clock_set_at"]) / 86400


def clock_reading(c: dict, now: float) -> tuple[str, float]:
    """(time it shows, minutes fast(+) or slow(-) against the real time)."""
    face = clock_face(c, now)
    return time.strftime("%-I:%M %p", time.localtime(face)), (face - now) / 60


def set_clock(c: dict, now: float, face: float | None = None) -> None:
    """Restart the drift from `face` (default: the right time). Mutates the runtime."""
    c["runtime"].update(clock_set_at=now, clock_offset=((face or now) - now) / 60)


def _needs(c: dict) -> str:
    part = c["runtime"].get("needs_part")
    mend = f"{part['qty']} {part['name']} to mend it, then " if part else ""
    return f"it needs {mend}tending ({c['spec']['capabilities']['upkeep']['verb']})"


# --- engine tick (no LLM) -----------------------------------------------------
def _condition(state, cond: str, now: float) -> bool:
    if cond == "crop_ripe":
        return any(g["state"] == "ready" for g in state.garden(now))
    if cond == "visitor":
        return bool(state.pending_inbox())
    hour = time.localtime(now).tm_hour
    if cond == "dawn":
        return hour == 6
    if cond == "dusk":
        return hour == 19
    a = state.agent()
    return a["hunger"] >= 0.6 if cond == "hungry" else a["energy"] <= 0.3  # tired


def _help(state, rng: random.Random, c: dict, h: dict, now: float) -> None:
    if h["effect"] == "hurry_crops":
        if state.hurry_garden(HURRY_FRACTION, now):
            state.log("creation", name=c["name"], what="helper", text=h["line"])
    elif h["effect"] == "find":
        found = rng.choice(h["finds"])
        state.add_item(found, 1, "material", f"found by your {c['name']}")
        state.log("creation", name=c["name"], what="helper", text=f"{h['line']} (found: {found})", item=found)
    else:  # comfort
        state.update_agent(energy=clamp(state.agent()["energy"] + COMFORT_ENERGY))
        state.log("creation", name=c["name"], what="helper", text=h["line"])


def tick(state, rng: random.Random, now: float | None = None, skip: set | frozenset = frozenset(),
         owned: set | frozenset = frozenset()) -> bool:
    """Run every creation's capabilities once. Returns True if Pip should be woken. Creations named (lowercase) in `skip` have their
    workings as a module (modules.py), which notices them stopping instead; those in `owned` are run wholly by the engine's shipped
    `workings` module, and left alone here."""
    now = now or time.time()
    wake = False
    for c in state.creations():
        caps, rt = c["spec"]["capabilities"], c["runtime"]
        if not caps or c["name"].lower() in owned:
            continue
        before = dict(rt, last=dict(rt["last"]))
        if not running(c, now) and c["name"].lower() in skip:
            pass
        elif not running(c, now):
            if not rt.get("stop_logged"):
                state.log("creation", name=c["name"], what="stopped",
                          text=f"Your {c['name']} has stopped" + (f" - {_needs(c)}." if "upkeep" in caps else "."))
                rt["stop_logged"] = True
                wake = True
        else:
            last = rt["last"]
            if "periodic" in caps and now - last.get("periodic", rt["made_at"]) >= caps["periodic"]["every_minutes"] * 60:
                state.log("creation", name=c["name"], what="periodic", text=rng.choice(caps["periodic"]["lines"]))
                last["periodic"] = now
            if "sensor" in caps:
                on = _condition(state, caps["sensor"]["condition"], now)
                if on and not rt.get("sensor_on"):
                    state.log("creation", name=c["name"], what="sensor", text=caps["sensor"]["alert"],
                              condition=caps["sensor"]["condition"])
                    wake = True
                rt["sensor_on"] = on
            if "helper" in caps and now - last.get("helper", rt["made_at"]) >= caps["helper"]["every_minutes"] * 60:
                last["helper"] = now
                _help(state, rng, c, caps["helper"], now)
        if rt != before:
            state.set_runtime(c["id"], rt)
    return wake


# --- actions ------------------------------------------------------------------
def tend(state, c: dict, now: float | None = None) -> str:
    now = now or time.time()
    caps, rt = c["spec"]["capabilities"], c["runtime"]
    if "upkeep" not in caps:
        return f"error: your {c['name']} doesn't need tending"
    part = rt.get("needs_part")
    if part:  # a mishap broke something: it has to be mended with a real part before it can be tended
        have, _ = state.find_item(part["name"], kind="material")
        if not have or have["qty"] < part["qty"]:
            return f"error: your {c['name']} needs {part['qty']} {part['name']} to mend it before it can be tended"
        state.take_item(have["id"], part["qty"])
        rt.pop("needs_part")
    if "timekeeper" in caps and not running(c, now):
        set_clock(c, now, clock_face(c, now))  # it starts again from the time it stopped at, so it's now behind
    up = caps["upkeep"]
    rt.update(tended_until=now + up["hours"] * 3600, stop_logged=False)
    rt.pop("halted_at", None)
    state.set_runtime(c["id"], rt)
    return f"you tend your {c['name']} ({up['verb']}); it will keep going for about {round(up['hours'])} hours"


def describe(c: dict, now: float | None = None) -> str:
    """One perception line."""
    now = now or time.time()
    caps, rt = c["spec"]["capabilities"], c["runtime"]
    head = f"- {c['name']} ({c['quality']}): {c['description']}"
    quirks = c["spec"]["quirks"]
    if not caps:  # art, keepsakes, writing: no status, it simply is
        return head + (" - " + "; ".join(quirks) if quirks else "")
    parts = []
    if running(c, now):
        if "upkeep" in caps:
            left = (rt["tended_until"] - now) / 3600
            parts.append(f"going; needs tending ({caps['upkeep']['verb']}) in about {round(left)} hours" if left >= 1.5
                         else f"going, but {_needs(c)} soon")
    else:
        parts.append(f"STOPPED - {_needs(c)}" if "upkeep" in caps else "STOPPED")
    if "timekeeper" in caps:
        shown, off = clock_reading(c, now)
        skew = "about right" if abs(off) < DRIFT_NOTICED else f"about {round(abs(off))} min {'fast' if off > 0 else 'slow'}"
        parts.append(f"it shows {shown}" + (f" (it runs {skew}; use_item can set it)" if running(c, now) else ""))
    if running(c, now) and caps.get("provides", {}).get("ability") == "news":
        parts.append("it brings you news")
    for k, text in (("world", "it made lasting room in your world"),
                    ("periodic", "does things on its own now and then"),
                    ("sensor", f"reacts when: {caps.get('sensor', {}).get('condition', '')}"),
                    ("helper", f"helps: {caps.get('helper', {}).get('line', '')}"),
                    ("companion", "has a mind of its own (talk to it: say with `to`)")):
        if k in caps:
            parts.append(text)
    if quirks:
        parts.append("quirks: " + "; ".join(quirks))
    return head + " - " + "; ".join(parts)


async def make(state, gm, rng: random.Random, project: dict, skill_level: int) -> dict:
    """Turn a finished project into a creation (one GM design call, then the engine takes over)."""
    q, marks = project_quality(project, skill_level), project_scars(project)
    allow = project["difficulty"] >= COMPANION_MIN_DIFFICULTY
    raw = await gm.design(project, q, marks, allow) if gm else None
    name, description, spec = sanitize_spec(raw, project, q, marks, rng)
    note = world_effects.apply(state, spec)
    c = state.add_creation(name, description, project["id"], q, spec, initial_runtime(spec, time.time()))
    if note:
        state.log("world_changed", effect=spec["capabilities"]["world"]["effect"], text=note, name=name)
    state.log("creation_made", id=c["id"], name=name, description=description, quality=q,
              capabilities=list(spec["capabilities"]), quirks=spec["quirks"], project=project["name"])
    return c


async def use(state, gm, c: dict, purpose: str, now: float | None = None) -> str:
    """Pip uses (or looks at, plays, reads...) a creation: the GM narrates, the engine applies capped effects."""
    now = now or time.time()
    caps, rt = c["spec"]["capabilities"], c["runtime"]
    if not running(c, now):
        return f"your {c['name']} has stopped - {_needs(c)} first" if "upkeep" in caps else f"your {c['name']} has stopped"
    a = state.agent()
    situation = f"Pip is {a['activity']}, mood {a['mood']}, hunger {a['hunger']:.1f}, energy {a['energy']:.1f}."
    left = abilities.news_left(c, now)
    verb = caps["upkeep"]["verb"] if "upkeep" in caps else ""
    out = await gm.use(describe(c, now), purpose, situation, "timekeeper" in caps, "upkeep" in caps, bulletin=left > 0,
                       tend_verb=verb) if gm else None
    if not out:
        return f"you spend a moment with your {c['name']} ({purpose})."
    done = []
    if out.get("set_clock") and "timekeeper" in caps:
        set_clock(c, now)
        done.append("it now shows the right time")
    tended = False
    if out.get("stop") and "upkeep" in caps:  # only tended things can stop: tending is how they're restarted
        rt["halted_at"] = now
        done.append(f"it has stopped until you tend it ({verb})")
    elif out.get("tend") and "upkeep" in caps:  # what Pip did was the upkeep itself: the same as the tend tool
        tend(state, c, now)
        tended = True
        done.append(f"{verb}: it will keep going for about {round(caps['upkeep']['hours'])} hours")
    fields = {}
    if out.get("mood"):
        fields["mood"] = _line(out["mood"], 40)
    if out.get("energy") and now - rt.get("last_energy_use", 0) >= USE_ENERGY_COOLDOWN:
        fields["energy"] = clamp(a["energy"] + _num(out["energy"], -0.1, 0.1, 0))
        rt["last_energy_use"] = now
    if fields:
        state.update_agent(**fields)
    state.set_runtime(c["id"], rt)
    text = _line(out["text"], 300)
    state.log("creation", name=c["name"], what="used", text=text, purpose=_line(purpose, 120))
    news = _line(out.get("bulletin"), 300) if left > 0 else ""
    if news:  # a bulletin counts against the creation's allowance for the day
        rt["news_log"] = [t for t in rt.get("news_log", []) if now - t < abilities.DAY] + [now]
        state.set_runtime(c["id"], rt)
        state.log("creation", name=c["name"], what="news", text=news)
        text += f" Bulletin: {news}"
    elif "provides" in caps and not left:
        done.append("only static now: it has told you all the news it has today")
    if "upkeep" in caps and "halted_at" not in rt and not tended:  # using it for anything else doesn't tend it
        left = (rt["tended_until"] - now) / 3600
        done.append(f"it keeps going for about {round(left)} more hours; use the tend tool to keep it going")
    return text + (f" ({'; '.join(done)})" if done else "")
