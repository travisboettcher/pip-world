"""Creations: finished projects that keep existing (and sometimes keep doing things) in the world.

A creation is a stored spec: zero to three capabilities plus a few quirks. Many creations (art, keepsakes, writing)
have no capabilities at all. The capabilities are deliberately generic primitives - the engine knows how to *run*
them, while the GM fills in everything specific (what the thing does, says, finds, how it's tended) once, when the
project is finished. The engine owns every number (from the project's quality) and runs capabilities each monitor
pass without any LLM: a creation's capabilities run in its shipped `workings` module (module_library/workings.py). New primitive = one
entry in `sanitize_spec` and `describe`, and its behaviour in the workings.
"""
import random
import re
import time

from . import abilities
from . import world_effects
from .text import clip
from .state import clamp
from . import world_pack
from . import stats as stats_mod

CAPABILITIES = ("timekeeper", "upkeep", "periodic", "sensor", "helper", "companion", "world", "provides")
# What a sensor can notice and a helper can do (docs/DESIGN-engine-audit.md, C2): the engine's own, which any world has, and the world
# pack's (content.json `sensors` and `helpers`), each saying what it `watches` or `does` in the engine's few words:
#   watches  ready:<module> (it shows something ready), next:<module> (it expects something later), low:<stat> (on its bad side)
#   does     request:<module>:<what> (asks it, as a world effect does), affect:<stat>:<amount>
# `when` (a watch) is when a helper is any use; `every` the fewest minutes between its turns.
ENGINE_SENSORS = {"visitor": {"help": "someone comes to talk to {name}"}, "dawn": {"help": "dawn"}, "dusk": {"help": "dusk"}}
ENGINE_HELPERS = {"find": {"help": "it turns up small useful things; give `finds`: 2-4 kinds of thing it would find", "every": 360}}
WATCH = re.compile(r"^(ready|next):([a-z][a-z0-9-]*)$|^low:([a-z_]+)$")
DOES = re.compile(r"^request:([a-z][a-z0-9-]*):([a-z_]+)$|^affect:([a-z_]+):(-?\d+(?:\.\d+)?)$")
MAX_CAPABILITIES = 3
COMPANION_MIN_DIFFICULTY = 3  # small, simple pieces don't get a mind of their own
DRIFT_MIN_PER_DAY = {"rough": 15, "sound": 5, "fine": 1.5, "masterwork": 0.3}
UPKEEP_FACTOR = {"rough": 0.5, "sound": 1.0, "fine": 1.5, "masterwork": 2.0}
USE_ENERGY_COOLDOWN = 6 * 3600
DRIFT_NOTICED = 5         # minutes a clock must be off before the agent is told (and tempted to reset it every hour)


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
            if c.get("condition") in sensors() and _line(c.get("alert")):
                caps[t] = {"condition": c["condition"], "alert": _line(c["alert"])}
        elif t == "helper":
            effect, line = c.get("effect"), _line(c.get("line"))
            finds = _lines(c.get("finds"), 4, 40)
            if effect in helpers() and line and (effect != "find" or finds):
                low = helpers()[effect].get("every", 60)
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


def sensors() -> dict:
    """{name: {help, watches?}}: what a sensor may notice in this world (the engine's, then the pack's)."""
    return {**ENGINE_SENSORS, **(world_pack.active().data("content").get("sensors") or {})}


def helpers() -> dict:
    """{name: {help, every?, does?, when?}}: how a helper may help in this world (the engine's, then the pack's)."""
    return {**ENGINE_HELPERS, **(world_pack.active().data("content").get("helpers") or {})}


NAME = re.compile(r"^[a-z][a-z0-9_]*$")
WATCH_SAYS, DOES_SAYS = "ready:<module>, next:<module> or low:<stat>", "request:<module>:<what> or affect:<stat>:<amount>"


def check_catalogue(content: dict) -> None:
    """A pack's `sensors` and `helpers` (content.json), checked when it loads: each needs a `help` line and, unless it only words one of
    the engine's own anew, what it watches or does; raises ValueError saying what is wrong."""
    for key, word, pattern, says, own in (("sensors", "watches", WATCH, WATCH_SAYS, ENGINE_SENSORS),
                                          ("helpers", "does", DOES, DOES_SAYS, ENGINE_HELPERS)):
        entries = content.get(key, {})
        if not isinstance(entries, dict):
            raise ValueError(f"content.json `{key}` maps a name to {{help, {word}, ...}}")
        for name, e in entries.items():
            where = f"content.json {key} {name!r}"
            if not NAME.match(name):
                raise ValueError(f"{where}: a name is a word in lower case")
            if not isinstance(e, dict) or not str(e.get("help") or "").strip():
                raise ValueError(f"{where}: needs a `help` line for the narrator")
            if (word in e or name not in own) and not pattern.match(str(e.get(word) or "")):
                raise ValueError(f"{where}: `{word}` is {says}")
            if "when" in e and not WATCH.match(str(e["when"])):
                raise ValueError(f"{where}: `when` is {WATCH_SAYS}")
            if "every" in e and not (type(e["every"]) is int and 1 <= e["every"] <= 1440):
                raise ValueError(f"{where}: `every` is a whole number of minutes, 1 to 1440")


def _live(state) -> dict:
    return {m["name"]: m for m in state.modules("live")}


def usable(state, entry: dict) -> bool:
    """Whether a sensor or helper makes sense in the world as it is: what it watches and asks is there (a live module, a stat)."""
    live, stats = _live(state), stats_mod.declared(state.s)
    for spec in (entry.get("watches"), entry.get("when"), entry.get("does")):
        if not spec:
            continue
        w, d = WATCH.match(spec), DOES.match(spec)
        if w and ((w.group(2) and w.group(2) not in live) or (w.group(3) and w.group(3) not in stats)):
            return False
        if d and ((d.group(1) and (d.group(1) not in live or d.group(2) not in (live[d.group(1)]["manifest"].get("answers") or {})))
                  or (d.group(3) and d.group(3) not in stats)):
            return False
        if not w and not d:
            return False
    return True


def watching(state, watch: str, now: float) -> bool:
    """Whether a watch holds just now: the engine's own (visitor, dawn, dusk) or one the world named (ready:, next:, low:)."""
    hour = time.localtime(now).tm_hour
    if watch in ("visitor", "dawn", "dusk"):
        return len(state.pending_inbox()) > 0 if watch == "visitor" else hour == (6 if watch == "dawn" else 19)
    m = WATCH.match(watch or "")
    if not m:
        return False
    if m.group(3):
        d = stats_mod.declared(state.s).get(m.group(3))
        return d is not None and stats_mod.is_low(d, stats_mod.values(state).get(m.group(3), 0.5))
    standing = (_live(state).get(m.group(2)) or {}).get("standing") or {}
    return bool(standing.get("ready")) if m.group(1) == "ready" else bool(standing.get("next_at"))


def at_work(state, caps: dict, now: float) -> dict:
    """A creation's capabilities as its workings read them: the sensor's watch worked out (`on`), the helper's way of helping (`does`)
    and whether it is any use just now (`can`)."""
    out = {k: dict(v) for k, v in caps.items()}
    if "sensor" in out:
        cond = out["sensor"]["condition"]
        out["sensor"]["on"] = watching(state, sensors().get(cond, {}).get("watches") or cond, now)
    if "helper" in out:
        entry = helpers().get(out["helper"]["effect"]) or {}
        out["helper"]["does"] = entry.get("does", "")
        out["helper"]["can"] = not entry.get("when") or watching(state, entry["when"], now)
    return out


def menu(allow_companion: bool, state=None) -> list[str]:
    """What a made thing can do, as the narrator is told when it designs one: the capabilities `sanitize_spec` keeps, worded (a sensor
    or helper of the world's only where what it watches and asks is in the world just now: `state`)."""
    a = world_pack.active().agent
    say = lambda e: e["help"].replace("{name}", a.name).replace("{possessive}", a.possessive)   # noqa: E731
    ok = lambda e: state is None or usable(state, e)                                               # noqa: E731
    caps = [
        "timekeeper: it tells the time",
        f"upkeep: it only keeps going if {a.name} tends it regularly; give `verb` (a word or two for how it's tended, "
        "whatever fits this thing) and `hours` (4-72) it lasts between tendings",
        "periodic: now and then it does something noticeable on its own; give 1-3 `lines` (short sentences "
        "describing it, in this thing's own manner) and `every_minutes` (20-720)",
        "sensor: it notices something and reacts; `condition` is one of "
        + ", ".join(f"{n} ({say(e)})" if n not in ("dawn", "dusk") else n for n, e in sensors().items() if ok(e))
        + "; `alert` is a short line describing how it reacts",
        "helper: it regularly helps in one of these ways (`effect`): "
        + ", ".join(f"{n} ({say(e)})" for n, e in helpers().items() if ok(e))
        + "; give `line` (one sentence describing what it does) and `every_minutes`",
        world_effects.gm_lines(), abilities.gm_lines(),
    ]
    if allow_companion:
        caps.append("companion: it has a mind of its own and can communicate; give a `persona` (2-3 sentences: "
                    "who it is, how it expresses itself) and `chatter_minutes` (60-720) for how often it speaks up")
    return caps


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


def _needs(c: dict) -> str:
    part = c["runtime"].get("needs_part")
    mend = f"{part['qty']} {part['name']} to mend it, then " if part else ""
    return f"it needs {mend}tending ({c['spec']['capabilities']['upkeep']['verb']})"


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


async def made(state, raw: dict | None, project: dict, q: str, marks: list[str], rng: random.Random) -> dict:
    """A design (the narrator's, or a module's: modules.py `creation`) made real: checked, its world effect carried out, kept, told."""
    name, description, spec = sanitize_spec(raw, project, q, marks, rng)
    note = await world_effects.apply(state, spec)
    c = state.add_creation(name, description, project["id"], q, spec, initial_runtime(spec, time.time()))
    if note:
        state.log("world_changed", effect=spec["capabilities"]["world"]["effect"], text=note, name=name)
    state.log("creation_made", id=c["id"], name=name, description=description, quality=q,
              capabilities=list(spec["capabilities"]), quirks=spec["quirks"], project=project["name"])
    return c


async def use(state, gm, c: dict, purpose: str, now: float | None = None, actions=()) -> tuple[str, str | None]:
    """The agent uses (or looks at, plays, reads...) a creation: the GM narrates, the engine applies capped effects. Returns (text, action): when
    what the agent does is one of the thing's own `actions` (its workings' offers: tending it, setting it, listening to it...), the action's name,
    for the caller to carry out through the module."""
    now = now or time.time()
    caps, rt = c["spec"]["capabilities"], c["runtime"]
    if not running(c, now):
        return (f"your {c['name']} has stopped - {_needs(c)} first" if "upkeep" in caps else f"your {c['name']} has stopped"), None
    a = state.agent()
    situation = f"{world_pack.active().agent.name} is {a['activity']}, mood {a['mood']}, {stats_mod.line(state)}."
    actions = [x for x in actions if isinstance(x, dict) and x.get("name")]
    out = await gm.use(describe(c, now), purpose, situation, actions) if gm else None
    if not out:
        return f"you spend a moment with your {c['name']} ({purpose}).", None
    fields = {}
    if out.get("mood"):
        fields["mood"] = _line(out["mood"], 40)
    tiring = stats_mod.tiring(state.s)
    if out.get("energy") and tiring and now - rt.get("last_energy_use", 0) >= USE_ENERGY_COOLDOWN:
        fields[tiring] = clamp(a[tiring] + _num(out["energy"], -0.1, 0.1, 0))
        rt["last_energy_use"] = now
    if fields:
        state.update_agent(**fields)
    state.set_runtime(c["id"], rt)
    text = _line(out["text"], 300)
    state.log("creation", name=c["name"], what="used", text=text, purpose=_line(purpose, 120))
    action = out.get("action") if out.get("action") in {x["name"] for x in actions} else None
    if "upkeep" in caps and action is None:                    # using it for anything else doesn't keep it going
        left = (rt["tended_until"] - now) / 3600
        text += f" (it keeps going for about {round(left)} more hours; use the tend tool to keep it going)"
    return text, action
