"""Modules: features the world and Pip write as code (docs/DESIGN-modules.md).

A module is source code plus a manifest. Its hooks are pure functions run in the sandbox (sandbox.py, in the `pip-runner` container): each
gets one JSON `ctx` and returns a dict of proposals. Here the engine is the referee: it checks every proposal against the manifest and the
world's rules and applies the call's proposals together, or refuses them all with a reason the author can read. Step 1 (this file): things
and rules, with state, facts, lines for Pip, events, a schedule, offers, consuming Pip's materials, and their creation's runtime.
"""
import json
import logging
import random
import re
import shutil
import sqlite3
import tempfile
import time
from dataclasses import replace
from datetime import datetime
from pathlib import Path

from . import public_view as pv
from . import sandbox

log = logging.getLogger(__name__)

API = 1
KINDS = ("thing", "rule", "part", "place")
HOOKS = ("on_install", "on_tick", "on_time", "on_event", "on_action")
READS = ("time", "weather", "pip", "subject", "items", "facts", "works", "stalls", "places")
PROPOSES = ("state", "publish", "perceive", "log", "schedule", "offer", "consume", "runtime", "wake", "show")
AUTHORS = ("world", "pip")
PIP_READS = ("time", "weather", "pip", "subject", "items")                      # what Pip's own programs may know, and do (step 3)
PIP_PROPOSES = ("state", "perceive", "log", "schedule", "offer", "show", "consume", "runtime", "wake")
MISFIRE = {"rough": 0.25, "sound": 0.08, "fine": 0.02, "masterwork": 0.0}     # craft over code: how often Pip's work fails to fire
STATUSES = ("proposed", "waiting", "live", "disabled", "rejected", "replaced")
RUNTIME_KEYS = {"clock_set_at": "number", "clock_offset": "number", "tended_until": "number", "halted_at": "number", "stop_logged": "bool",
                "needs_part": "part"}                       # a thing's creation fields the engine's readers use (creations.py)
NAME = re.compile(r"^[a-z][a-z0-9-]{2,39}$")
SHOW_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,23}$")
SHOW_MAX, SIZE_RANGE, MOTIONS, WORKS_SHOWN = 8, (0.2, 1.5), ("bob", "sway", "spin"), 12
RULES = {"gallery-wall": "Pip's newest drawings, framed on the workshop's back wall.",
         "stall-pictures": "What Pip made, shown on its market stall: copies of drawings framed, creations as Pip drew them.",
         # parts and a first layout (step 5): the scene kit's own pieces as parts, and the woods built from them
         "round-tree": "A part: a round, leafy tree (scale), in the season's colours.",
         "pine-tree": "A part: a pine (scale), darker in winter.",
         "well": "A part: a stone well with a little thatched roof.",
         "stall": "A part: a market stall with a striped awning (two colours), and a counter to set things on.",
         "cutaway": "A part: a building opened like a dollhouse (width, depth, height, walls, roof, a door), with its walls and floor as anchors.",
         "woods-layout": "The woods, built from parts instead of hand-written: the same trees and clearing, now data the world can change."}
OFFER_NAME = re.compile(r"^[a-z][a-z ]{0,23}$")
STATE_MAX, FACTS_MAX, TEXT_MAX, OFFERS_MAX, CONSUME_MAX = 16_000, 4_000, 200, 4, 5
PER_DAY = {"calls": 600, "perceive": 12, "log": 24, "wake": 4}
FAILS_TO_DISABLE = 3
DRY_HOURS, DRY_STEP_MINUTES = 24, 30                  # a whole day, so what happens at dusk or on the hour is tried too
TICK_ONLY_HOOKS = ("on_tick", "on_time", "on_event")      # hooks the engine runs on its own each step


class Refused(ValueError):
    """A proposal the referee won't apply; the message is for the module's author."""


# --- manifests ---------------------------------------------------------------------------------------------------------------------
def check_manifest(m, author: str, state=None) -> dict:
    """A manifest as the referee will hold the module to it; raises Refused with what to fix."""
    if not isinstance(m, dict):
        raise Refused("the manifest must be an object")
    if author not in AUTHORS:
        raise Refused(f"unknown author {author!r}")
    name, kind = str(m.get("name") or ""), m.get("kind")
    if not NAME.match(name):
        raise Refused("`name` is 3 to 40 lowercase letters, digits and dashes, starting with a letter")
    if kind not in KINDS:
        raise Refused(f"`kind` is one of {', '.join(KINDS)}")
    if m.get("api") != API:
        raise Refused(f"`api` must be {API}")
    out = {"name": name, "kind": kind, "api": API}
    builds = kind in ("part", "place")
    for key, allowed in (("hooks", ("on_build",) if builds else HOOKS), ("reads", READS), ("proposes", PROPOSES)):
        vals = m.get(key) or []
        if not isinstance(vals, list) or any(v not in allowed for v in vals):
            raise Refused(f"`{key}` is a list drawn from: {', '.join(allowed)}")
        out[key] = list(dict.fromkeys(vals))
    if not out["hooks"]:
        raise Refused("`hooks` needs at least one hook")
    if kind in ("part", "place"):
        if author != "world" or out["hooks"] != ["on_build"] or out["reads"] or out["proposes"]:
            raise Refused("parts and places are the world's; they have just on_build, and read and propose nothing")
        if kind == "part":
            params = m.get("params") or {}
            if not isinstance(params, dict) or len(params) > 16 or not all(isinstance(v, (int, float, str, bool)) for v in params.values()):
                raise Refused("`params` maps up to 16 names to plain default values")
            out["params"] = params
        else:
            if not isinstance(m.get("place"), str) or not m["place"].strip():
                raise Refused("a place module names the place it lays out: `place`")
            out["place"] = m["place"].strip()[:60]
        out.update(events=[], consumes={})
        return out
    if author == "pip":
        if kind != "thing":
            raise Refused("your programs make one of your creations work")
        extra = [v for v in out["reads"] if v not in PIP_READS] + [v for v in out["proposes"] if v not in PIP_PROPOSES]
        if extra:
            raise Refused(f"your programs can't use: {', '.join(extra)}")
    subject = str(m.get("subject") or "").strip()
    if kind == "thing":
        if not subject:
            raise Refused("a thing needs a `subject`: the name of the creation it makes work")
        if state is not None and not _creation(state, subject):
            raise Refused(f"there is no creation called {subject!r}")
        out["subject"] = subject
    elif subject or "subject" in out["reads"] or "runtime" in out["proposes"]:
        raise Refused("only a thing has a subject (and reads or changes its runtime)")
    events = m.get("events") or []
    if not isinstance(events, list) or any(e not in pv.EVENT_FIELDS for e in events):
        raise Refused("`events` is a list of public event kinds: " + ", ".join(sorted(pv.EVENT_FIELDS)))
    if bool(events) != ("on_event" in out["hooks"]):
        raise Refused("`on_event` and `events` go together: list the event kinds the hook wants")
    out["events"] = events
    consumes = m.get("consumes") or {}
    if not isinstance(consumes, dict) or any(not isinstance(k, str) or not isinstance(v, int) or isinstance(v, bool) or not 1 <= v <= CONSUME_MAX
                                             for k, v in consumes.items()):
        raise Refused(f"`consumes` maps item names (or \"*\" for any material) to at most {CONSUME_MAX} per call")
    if bool(consumes) != ("consume" in out["proposes"]):
        raise Refused("`consume` and `consumes` go together: say which materials it may use up")
    out["consumes"] = consumes
    tends = m.get("tends")
    if tends is not None and (kind != "thing" or not isinstance(tends, str) or not OFFER_NAME.match(tends)):
        raise Refused("`tends` is the name of the offer that tending the thing means")
    if tends:
        out["tends"] = tends
    return out


def _creation(state, name: str) -> dict | None:
    return next((c for c in state.creations() if c["name"].lower() == name.lower()), None)


# --- running a hook --------------------------------------------------------------------------------------------------------------
class LocalRunner:
    """Runs hooks in a subprocess here. For tests and development; production uses the pip-runner container."""
    name = "local"

    async def run(self, source: str, hook: str, ctx: dict) -> dict:
        return await sandbox.run(source, hook, ctx)


class HttpRunner:
    """The pip-runner container (runner_service.py): on a Unix socket in a shared volume (unix:///path), so the runner needs no network
    at all, or over HTTP for development."""
    name = "http"

    def __init__(self, url: str):
        self.url = url.rstrip("/")
        self.socket = self.url[len("unix://"):] if self.url.startswith("unix://") else None

    async def run(self, source: str, hook: str, ctx: dict) -> dict:
        import httpx
        base, transport = ("http://runner", httpx.AsyncHTTPTransport(uds=self.socket)) if self.socket else (self.url, None)
        try:
            async with httpx.AsyncClient(timeout=sandbox.WALL_SECONDS + 5, transport=transport) as c:
                r = await c.post(base + "/run", json={"source": source, "hook": hook, "ctx": ctx})
            return r.json()
        except Exception as e:  # the runner is down: the call fails like any other, and is retried next step
            return {"ok": False, "error": f"the runner couldn't be reached ({type(e).__name__})", "runner_down": True}


def runner_for(settings):
    """The runner settings ask for, or None when modules can't run."""
    if settings.modules != "on":
        return None
    if settings.module_runner == "local":
        return LocalRunner()
    if settings.module_runner.startswith(("http", "unix://")):
        return HttpRunner(settings.module_runner)
    return None


def context(state, settings, m: dict, now: float, **extra) -> dict:
    """What a hook may know: the clock, a seed, its own state, and what its manifest says it reads."""
    man = m["manifest"]
    ctx = {"now": now, "seed": int(now) * 7919 + m["id"], "state": m["state"], "offers": m["offers"], **extra}
    reads = man["reads"]
    if "time" in reads:
        from .happenings import season_of
        t = datetime.fromtimestamp(now)
        ctx["time"] = {"hour": t.hour, "minute": t.minute, "weekday": t.strftime("%A"), "season": season_of(now, settings.hemisphere)}
    if "weather" in reads:
        from . import weather
        w = weather.current(state, now)
        ctx["weather"] = {"condition": w.condition, "temp": w.temp, "unit": w.unit, "daylight": w.above_horizon} if w else None
    if "pip" in reads:
        a = state.agent()
        from . import places
        ctx["pip"] = {"where": a["location"], "at_home": a["location"] == places.HOME, "activity": a["activity"], "asleep": a["activity"] == "sleeping"}
    if "subject" in reads:
        c = _creation(state, man["subject"])
        ctx["subject"] = None if not c else {"name": c["name"], "quality": c["quality"], "description": c["description"],
                                              "capabilities": c["spec"]["capabilities"], "runtime": c["runtime"]}
    if "items" in reads:
        ctx["items"] = [{"name": i["name"], "qty": i["qty"], "kind": i["kind"]} for i in state.items()]
    if "works" in reads:
        ctx["works"] = state.pictures(WORKS_SHOWN)
    if "stalls" in reads:
        ctx["stalls"] = [{"place": r["place"], "item": r["name"], "kind": r["kind"], "qty": r["qty"], **({"work": r["attrs"]["work"]} if r["attrs"].get("work") else {})}
                         for r in state.stall_rows()]
    if "places" in reads:
        from . import worldmap
        ctx["places"] = [{"key": p["key"], "label": p["label"], "kind": p["kind"]}
                         for p in worldmap.snapshot(state, settings, None, now)["places"] if not p["heard_only"]]
    if "facts" in reads:
        ctx["facts"] = {o["name"]: o["facts"] for o in state.modules("live") if o["id"] != m["id"] and o["facts"]}
    return ctx


# --- the referee -----------------------------------------------------------------------------------------------------------------
def _text(v, what: str) -> str:
    if not isinstance(v, str) or not v.strip():
        raise Refused(f"`{what}` is a line of text")
    if len(v) > TEXT_MAX:
        raise Refused(f"`{what}` is at most {TEXT_MAX} characters")
    return v.strip()


def _size(v) -> int:
    return len(json.dumps(v))


def _day(now: float) -> str:
    return datetime.fromtimestamp(now).strftime("%Y-%m-%d")


def _budget(m: dict, now: float) -> dict:
    b = m["budget"] if m["budget"].get("day") == _day(now) else {"day": _day(now)}
    return {k: b.get(k, 0) for k in PER_DAY} | {"day": b["day"]}


def plan(state, m: dict, result: dict, now: float, hook: str) -> list:
    """Check a hook's proposals and return the changes to make, in order; raises Refused (and changes nothing) if any is not allowed."""
    man, budget, changes = m["manifest"], _budget(m, now), []
    allowed = set(man["proposes"]) | ({"reply"} if hook == "on_action" else set())
    extra = sorted(set(result) - allowed)
    if extra:
        raise Refused(f"it returned {', '.join(extra)}, which its manifest doesn't propose" if set(extra) - {"reply"}
                      else "only on_action can reply")
    if "state" in result:
        if not isinstance(result["state"], dict) or _size(result["state"]) > STATE_MAX:
            raise Refused(f"`state` is an object of at most {STATE_MAX} bytes")
        changes.append(("state", result["state"]))
    if "publish" in result:
        if not isinstance(result["publish"], dict) or _size(result["publish"]) > FACTS_MAX:
            raise Refused(f"`publish` is an object of at most {FACTS_MAX} bytes")
        changes.append(("facts", result["publish"]))
    for key in ("perceive", "log"):
        if key in result:
            if budget[key] >= PER_DAY[key]:
                raise Refused(f"it has used today's {PER_DAY[key]} `{key}` lines")
            changes.append((key, _text(result[key], key)))
    if result.get("wake"):
        if budget["wake"] >= PER_DAY["wake"]:
            raise Refused(f"it has woken Pip {PER_DAY['wake']} times today")
        changes.append(("wake", True))
    if "schedule" in result and result["schedule"] is not None:
        at = result["schedule"]
        if not isinstance(at, (int, float)) or isinstance(at, bool) or at <= now - 60:
            raise Refused("`schedule` is a time (seconds, like ctx['now']) still to come")
        changes.append(("due", float(at)))
    if "offer" in result:
        offers = result["offer"]
        if not isinstance(offers, list) or len(offers) > OFFERS_MAX or not all(
                isinstance(o, dict) and OFFER_NAME.match(str(o.get("name") or "")) and isinstance(o.get("help"), str) for o in offers):
            raise Refused(f"`offer` is a list of at most {OFFERS_MAX} {{name, help}}; a name is a few lowercase words")
        changes.append(("offers", [{"name": o["name"], "help": _text(o["help"], "offer help")} for o in offers]))
    if "consume" in result:
        changes.append(("consume", _consume(state, man["consumes"], result["consume"])))
    if "runtime" in result:
        changes.append(("runtime", _runtime(result["runtime"])))
    if "show" in result:
        shown = _show(result["show"])
        if m["author"] == "pip" and any(o["at"]["place"] != "subject" for o in shown):
            raise Refused("your things show themselves where they are: `at.place` is \"subject\"")
        changes.append(("show", shown))
    if "reply" in result:
        changes.append(("reply", _text(result["reply"], "reply")))
    return changes


def _show(objs) -> list:
    """Things to draw in scenes: pixel pictures, each asking for an anchor (anchors.py)."""
    from . import anchors, art
    if not isinstance(objs, list) or len(objs) > SHOW_MAX:
        raise Refused(f"`show` is a list of at most {SHOW_MAX} objects")
    out, ids = [], set()
    for o in objs:
        if not isinstance(o, dict) or not SHOW_ID.match(str(o.get("id") or "")) or o["id"] in ids:
            raise Refused("each object in `show` needs its own `id`: up to 24 lowercase letters, digits and dashes")
        oid, ids = o["id"], ids | {o["id"]}
        sprite = o.get("sprite")
        try:
            rows, palette = art.clean_pixels((sprite or {}).get("rows"), (sprite or {}).get("palette")) if isinstance(sprite, dict) else (None, None)
        except art.SvgRejected as e:
            raise Refused(f"`show` {oid}: {e}") from None
        if rows is None:
            raise Refused(f"`show` {oid}: `sprite` is {{rows, palette}}, a pixel picture")
        size = o.get("size", 0.6)
        if not isinstance(size, (int, float)) or isinstance(size, bool) or not SIZE_RANGE[0] <= size <= SIZE_RANGE[1]:
            raise Refused(f"`show` {oid}: `size` is {SIZE_RANGE[0]} to {SIZE_RANGE[1]}")
        at = o.get("at")
        if not isinstance(at, dict) or at.get("type") not in anchors.TYPES or not isinstance(at.get("place"), str) or not at["place"].strip():
            raise Refused(f"`show` {oid}: `at` is {{type, place, tags?, near?}}; type is one of {', '.join(anchors.TYPES)}")
        tags = at.get("tags") or []
        if not isinstance(tags, list) or len(tags) > 4 or not all(isinstance(t, str) for t in tags):
            raise Refused(f"`show` {oid}: `at.tags` is a list of up to 4 words")
        motion = o.get("motion")
        if motion is not None and motion not in MOTIONS:
            raise Refused(f"`show` {oid}: `motion` is one of {', '.join(MOTIONS)}")
        tip = o.get("tip")
        if tip is not None and not (isinstance(tip, dict) and isinstance(tip.get("title", ""), str) and isinstance(tip.get("text", ""), str)):
            raise Refused(f"`show` {oid}: `tip` is {{title, text}}")
        clean = {"id": oid, "sprite": {"rows": rows, "palette": palette}, "size": float(size), "frame": bool(o.get("frame")),
                 "at": {"type": at["type"], "place": at["place"].strip()[:60], "tags": [t.strip().lower()[:24] for t in tags],
                        **({"near": str(at["near"])[:40]} if at.get("near") else {})}}
        if motion:
            clean["motion"] = motion
        if tip:
            clean["tip"] = {"title": str(tip.get("title", ""))[:60], "text": str(tip.get("text", ""))[:200]}
        out.append(clean)
    return out


def _consume(state, may: dict, want) -> list:
    """Materials to take from Pip's belongings: only what the manifest allows, and only what Pip has."""
    if not isinstance(want, dict):
        raise Refused("`consume` maps item names to quantities")
    take = []
    for name, qty in want.items():
        limit = may.get(name, may.get("*"))
        if limit is None:
            raise Refused(f"its manifest doesn't let it use up {name}")
        if not isinstance(qty, int) or isinstance(qty, bool) or not 1 <= qty <= limit:
            raise Refused(f"it may use up 1 to {limit} {name} at a time")
        item, _ = state.find_item(name, kind="material")
        if not item or item["qty"] < qty:
            raise Refused(f"you need {qty} {name} for that")
        take.append((item["id"], qty, item["name"]))
    return take


def _runtime(rt) -> dict:
    if not isinstance(rt, dict):
        raise Refused("`runtime` maps runtime fields to values")
    for k, v in rt.items():
        kind = RUNTIME_KEYS.get(k)
        if kind is None:
            raise Refused(f"`runtime` can only set: {', '.join(RUNTIME_KEYS)}")
        ok = v is None or (kind == "number" and isinstance(v, (int, float)) and not isinstance(v, bool)) or (kind == "bool" and isinstance(v, bool)) \
            or (kind == "part" and isinstance(v, dict) and isinstance(v.get("name"), str) and isinstance(v.get("qty"), int))
        if not ok:
            raise Refused(f"`runtime.{k}` must be a {kind} (or null to clear it)")
    return rt


def apply(state, m: dict, changes: list, now: float) -> dict:
    """Make the checked changes. Returns what the caller needs: {"wake": bool, "reply": str}."""
    budget, fields, out = _budget(m, now), {}, {"wake": False, "reply": ""}
    for kind, val in changes:
        if kind in ("state", "facts", "offers", "due", "show"):
            fields[kind] = val
        elif kind == "perceive":
            fields["lines"] = (fields.get("lines", m["lines"]) + [{"ts": now, "text": val}])[-PER_DAY["perceive"]:]
            budget["perceive"] += 1
        elif kind == "log":
            state.log("module", name=m["name"], text=val, author=m["author"])
            budget["log"] += 1
        elif kind == "wake":
            out["wake"] = True
            budget["wake"] += 1
        elif kind == "consume":
            for item_id, qty, _ in val:
                state.take_item(item_id, qty)
        elif kind == "runtime":
            c = _creation(state, m["manifest"]["subject"])
            if c:
                rt = {**c["runtime"], **{k: v for k, v in val.items() if v is not None}}
                for k in [k for k, v in val.items() if v is None]:
                    rt.pop(k, None)
                state.set_runtime(c["id"], rt)
        elif kind == "reply":
            out["reply"] = val
    if "due" not in fields and m.get("due") and m["due"] <= now:
        fields["due"] = None                                    # it was due and didn't ask again
    budget["calls"] += 1
    state.update_module(m["id"], **fields, budget=budget)
    m.update(fields, budget=budget)
    return out


def _summary(res: dict, changes: list | None, refused: str = "") -> str:
    if not res.get("ok"):
        return "error: " + res.get("error", "?")
    if res.get("missing"):
        return "(no such hook)"
    if refused:
        return "refused: " + refused
    return ", ".join(k for k, _ in changes) or "nothing"


async def call(state, settings, runner, m: dict, hook: str, now: float, trial: bool = False, **extra) -> dict:
    """Run one hook and apply what it proposes. Returns {"ok", "error", "refused", "wake", "reply"}; never raises."""
    budget = _budget(m, now)
    if budget["calls"] >= PER_DAY["calls"]:
        return {"ok": False, "error": "", "refused": f"it has used today's {PER_DAY['calls']} calls", "wake": False, "reply": ""}
    if not trial and misfires(state, m, hook, now):                # a trial shows the program itself, not its luck
        state.add_module_call(m["id"], now, hook, True, 0, "misfired (the work is rough)")
        return {"ok": True, "error": "", "refused": "", "wake": False, "reply": "", "misfired": True}
    t0 = time.monotonic()
    res = await runner.run(m["source"], hook, context(state, settings, m, now, **extra))
    ms = round((time.monotonic() - t0) * 1000)
    changes, refused, out = None, "", {"wake": False, "reply": ""}
    if res.get("ok") and not res.get("missing"):
        try:
            changes = plan(state, m, res["result"], now, hook)
        except Refused as e:
            refused = str(e)
        else:
            out = apply(state, m, changes, now)
    if not res.get("runner_down"):
        state.add_module_call(m["id"], now, hook, bool(res.get("ok")) and not refused, ms, _summary(res, changes, refused)[:300])
        fails = 0 if res.get("ok") else m["fails"] + 1
        if fails != m["fails"]:
            state.update_module(m["id"], fails=fails)
            m["fails"] = fails
        if fails >= FAILS_TO_DISABLE and m["status"] == "live":
            disable(state, m["id"], f"its code failed {fails} times in a row: {res.get('error', '')}")
            m["status"] = "disabled"
    return {"ok": bool(res.get("ok")), "error": res.get("error", ""), "refused": refused, **out}


def misfires(state, m: dict, hook: str, now: float) -> bool:
    """Pip's programs run in things Pip made, and a thing is only as good as its making: now and then a rough one doesn't fire."""
    if m["author"] != "pip" or hook == "on_install":
        return False
    c = _creation(state, m["manifest"].get("subject", ""))
    chance = MISFIRE.get(c["quality"], 0.0) if c else 0.0
    return chance > 0 and random.Random(f"{m['id']}:{hook}:{int(now)}").random() < chance


# --- the engine's step -----------------------------------------------------------------------------------------------------------
async def step(state, settings, runner, now: float | None = None) -> bool:
    """Run every live module's hooks that are due: its tick, its scheduled time, the events it listens for. True if Pip should wake."""
    if runner is None:
        return False
    now, wake = now or time.time(), False
    for m in state.modules("live"):
        hooks = m["manifest"]["hooks"]
        if "on_time" in hooks and m["due"] and m["due"] <= now and m["status"] == "live":
            wake |= (await call(state, settings, runner, m, "on_time", now, due=m["due"]))["wake"]
        if "on_event" in hooks and m["status"] == "live":
            kinds = set(m["manifest"]["events"])
            for e in state.events(limit=50, after_id=m["cursor"]):
                if e["kind"] in kinds and (pub := pv.public_event(e)):
                    wake |= (await call(state, settings, runner, m, "on_event", now, event=pub))["wake"]
                m["cursor"] = e["id"]
            state.update_module(m["id"], cursor=m["cursor"])
        if "on_tick" in hooks and m["status"] == "live":
            wake |= (await call(state, settings, runner, m, "on_tick", now))["wake"]
    return wake


def perception(state) -> list[str]:
    """Lines live modules have for Pip since it last looked (each is shown once)."""
    lines = []
    for m in state.modules("live"):
        if m["lines"]:
            lines += [f"- {l['text']}" for l in m["lines"]]
            state.update_module(m["id"], lines=[])
    return ["Things in the world:"] + lines if lines else []


def where(state, m: dict, place: str) -> str | None:
    """The place key an object's `at.place` means: "home"; "subject" (where a thing's creation is: at home while Pip has it); or a key."""
    from . import places
    if place == "home":
        return places.HOME
    if place == "subject":
        return places.HOME if m["kind"] == "thing" and _creation(state, m["manifest"]["subject"]) else None
    return place


def objects_for(state, key: str, kind: str) -> tuple[list[dict], list[str]]:
    """What live modules show at one place, packed onto its anchors: (placed, unplaced). Oldest module first, objects in their order."""
    from . import anchors
    wanted = [{**o, "key": f"{m['name']}:{o['id']}", "id": f"{m['name']}:{o['id']}"} for m in state.modules("live") for o in m["show"]
              if where(state, m, o["at"]["place"]) == key]
    from . import layouts
    return anchors.place(layouts.anchors_for(state, key) or anchors.for_kind(kind), wanted)


def scene_objects(state, key: str, kind: str) -> list[dict]:
    """The objects for the scene view: what to draw and where (anchors.py worked out the where)."""
    placed, _ = objects_for(state, key, kind)
    return [{"key": o["key"], "rows": o["sprite"]["rows"], "palette": o["sprite"]["palette"], "frame": o["frame"], "w": o["w"], "h": o["h"],
             "pos": o["pos"], "normal": o["normal"], "upright": o["upright"], **{k: o[k] for k in ("motion", "tip") if k in o}} for o in placed]


def bound(state) -> dict:
    """Live things by their creation's name (lowercase): the creations whose workings are code."""
    return {m["manifest"]["subject"].lower(): m for m in state.modules("live") if m["kind"] == "thing"}


# --- Pip's own programs (step 3) -------------------------------------------------------------------------------------------------
PROGRAMS_PER_DAY = 6


def program_manifest(source: str, creation: dict, events=None) -> dict:
    """The manifest for one of Pip's programs, worked out from the code: the hooks it defines; everything Pip's programs may read and do.
    Raises sandbox.Rejected (bad code) or Refused (a hook without what it needs)."""
    import ast
    tree = sandbox.check(source)
    hooks = [n.name for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in HOOKS]
    if not hooks:
        raise Refused(f"define at least one of {', '.join(HOOKS)}")
    events = [e for e in (events or []) if isinstance(e, str)]
    if ("on_event" in hooks) != bool(events):
        raise Refused("on_event needs `events`: the kinds of thing that happen it listens for" if "on_event" in hooks
                      else "`events` is only for a program with on_event")
    man = {"name": f"{slug(creation['name'])}-by-pip", "kind": "thing", "api": API, "subject": creation["name"], "hooks": hooks,
           "reads": list(PIP_READS), "proposes": list(PIP_PROPOSES), "events": events, "consumes": {"*": 2}}
    if "upkeep" in creation["spec"]["capabilities"]:
        man["tends"] = "tend"                                       # if the program offers "tend", the tend tool uses it
    return man


def programs(state) -> dict:
    """Pip's newest program for each of its creations (by creation name, lowercase), whatever became of it."""
    out = {}
    for m in state.modules():
        if m["author"] == "pip" and m["status"] != "replaced":
            out[m["subject"].lower()] = m
    return out


def program_status(m: dict) -> str:
    return {"live": f"working (version {m['version']})", "waiting": f"version {m['version']} waiting to be tried",
            "proposed": f"version {m['version']} waiting to be tried", "disabled": "switched off" + (f": {m['note']}" if m["note"] else ""),
            "rejected": f"version {m['version']} not taken up" + (f": {m['note']}" if m["note"] else "")}.get(m["status"], m["status"])


def trial_text(report: dict) -> str:
    """A dry run, told to Pip in a few lines."""
    if report.get("skipped"):
        return "It couldn't be tried just now."
    parts = [f"On a trial run it was called {report['calls']} times."]
    for key, label in (("errors", "It went wrong"), ("refused", "Not allowed"), ("perceived", "It would tell you"), ("logged", "It would note"),
                       ("replies", "Using it"), ("unplaced", "Couldn't show")):
        items = list(dict.fromkeys(report.get(key) or []))[:3]
        if items:
            parts.append(f"{label}: " + "; ".join(items) + ".")
    if report.get("offers"):
        parts.append("It offers: " + ", ".join(report["offers"]) + ".")
    if report.get("placed"):
        parts.append("It shows itself: " + "; ".join(report["placed"][:3]) + ".")
    return " ".join(parts)


# --- telling the owner -----------------------------------------------------------------------------------------------------------
def owner_notices(state, settings) -> list[tuple[int, str, str]]:
    """What the owner hasn't been told yet: a module waiting for approval, or one switched off because its code kept failing.
    (module id, the status being told, the message)."""
    link = f" {settings.dashboard_url.rstrip('/')}/ui/#work" if settings.dashboard_url else ""
    out = []
    for m in state.modules(("waiting", "disabled")):
        if m["notified"] == m["status"] or (m["status"] == "disabled" and not m["note"].startswith("its code failed")):
            continue
        who = "the world" if m["author"] == "world" else "Pip"
        what = f"{m['name']} v{m['version']} by {who}" + (f", for {m['subject']}" if m["subject"] else "")
        if m["status"] == "waiting":
            r = m["report"]
            trial = (f" Trial run: {r['calls']} calls, " + ("clean." if r.get("clean") else "with problems.")) if r.get("calls") is not None else ""
            text = f"pip-world: a module is waiting for your approval - {what}." + (f" {m['reason']}" if m["reason"] else "") + trial
        else:
            text = f"pip-world: module {what} was switched off: {m['note']}"
        out.append((m["id"], m["status"], text + f"{link} (pipchat modules show {m['id']})"))
    return out


async def notify_owner(state, settings, outreach) -> int:
    """Send the owner what they haven't been told (see owner_notices); each once. Returns how many went."""
    if settings.modules_notify != "on" or outreach is None:
        return 0
    sent = 0
    for mid, status, text in owner_notices(state, settings):
        ok = await outreach.notify_owner(text, settings.modules_notify_room or None)
        if ok:
            state.update_module(mid, notified=status)
            sent += 1
    return sent


def offers_line(m: dict) -> str:
    return "; ".join(f"{o['name']} ({o['help']})" for o in m["offers"])


async def act(state, settings, runner, m: dict, action: str, args: dict, now: float | None = None) -> str:
    """Pip uses one of a module's offers (through use_item or tend). Returns the result for Pip."""
    now = now or time.time()
    names = [o["name"] for o in m["offers"]]
    if action not in names:
        return f"error: that isn't something it offers; it offers: {', '.join(names) or 'nothing right now'}"
    if runner is None:
        return "error: that can't be done right now"
    r = await call(state, settings, runner, m, "on_action", now, action=action, args=args)
    if r.get("misfired"):
        return "it doesn't respond this time (it's rough work; try again)"
    if r["refused"]:
        return f"that didn't work: {r['refused']}"
    if not r["ok"]:
        return f"it doesn't respond (its workings failed: {r['error']})"
    return r["reply"] or f"you {action} it."


# --- lifecycle -------------------------------------------------------------------------------------------------------------------
def needs_approval(settings, author: str) -> bool:
    return author in {a.strip() for a in settings.modules_approval.split(",")}


async def propose(state, settings, runner, author: str, manifest: dict, source: str, reason: str = "", replaces: int | None = None,
                  now: float | None = None) -> dict:
    """A new module (or a new version of one): checked, dry-run, then waiting for the owner, or live if its author needs no approval.
    Returns {"id", "status", "report"} or {"error"} with what to fix."""
    now = now or time.time()
    try:
        man = check_manifest(manifest, author, state)
        sandbox.check(source)
    except (Refused, sandbox.Rejected) as e:
        return {"error": str(e)}
    old = state.module(replaces) if replaces else None
    if replaces and (not old or old["name"] != man["name"] or old["author"] != author):
        return {"error": f"there is no module #{replaces} called {man['name']} by {author} to replace"}
    if not old and any(o["name"] == man["name"] and o["status"] in ("proposed", "waiting", "live", "disabled") for o in state.modules()):
        return {"error": f"a module called {man['name']} already exists; send a new version of it instead"}
    mid = state.add_module(name=man["name"], kind=man["kind"], author=author, api=API, subject=man.get("subject", ""), manifest=man,
                           source=source, reason=str(reason or "")[:500], status="proposed", version=(old["version"] + 1) if old else 1,
                           replaces=replaces, created_at=now)
    if old and old["status"] in ("proposed", "waiting"):
        state.update_module(old["id"], status="replaced")              # a newer version supersedes one still waiting
    report = await dry_run(state, settings, runner, state.module(mid), now) if runner else {"skipped": "no runner"}
    state.update_module(mid, report=report, status="waiting")
    if report.get("clean") and not needs_approval(settings, author):
        await approve(state, settings, runner, mid, now=now, by="auto")
    return {"id": mid, "status": state.module(mid)["status"], "report": report}


async def approve(state, settings, runner, module_id: int, note: str = "", now: float | None = None, by: str = "owner") -> dict:
    """Make a waiting (or disabled) module live: the version it replaces steps aside, and it installs."""
    now = now or time.time()
    m = state.module(module_id)
    if not m or m["status"] not in ("waiting", "disabled"):
        return {"error": "only a waiting or disabled module can go live"}
    for o in state.modules("live"):
        if o["name"] == m["name"] or (m["kind"] == "thing" and o["kind"] == "thing" and o["subject"].lower() == m["subject"].lower()) \
                or (m["kind"] == "place" and o["kind"] == "place" and o["manifest"].get("place") == m["manifest"].get("place")):
            state.update_module(o["id"], status="replaced")                # one module runs a thing at a time
    last = state.events(limit=1)
    state.update_module(module_id, status="live", decided_at=now, note=str(note or "")[:500], fails=0, cursor=last[0]["id"] if last else 0)
    state.log("module_live", name=m["name"], author=m["author"], version=m["version"], by=by, subject=m["subject"])
    m = state.module(module_id)
    if runner and "on_install" in m["manifest"]["hooks"]:
        await call(state, settings, runner, m, "on_install", now)
    return {"id": module_id, "status": "live"}


def reject(state, module_id: int, note: str = "", now: float | None = None) -> dict:
    m = state.module(module_id)
    if not m or m["status"] not in ("waiting", "proposed"):
        return {"error": "only a waiting module can be rejected"}
    state.update_module(module_id, status="rejected", note=str(note or "")[:500], decided_at=now or time.time())
    state.log("module_rejected", name=m["name"], author=m["author"], version=m["version"], note=str(note or "")[:500], subject=m["subject"])
    return {"id": module_id, "status": "rejected"}


def disable(state, module_id: int, why: str = "", now: float | None = None) -> dict:
    m = state.module(module_id)
    if not m or m["status"] != "live":
        return {"error": "only a live module can be switched off"}
    state.update_module(module_id, status="disabled", note=str(why or "")[:500], decided_at=now or time.time())
    state.log("module_disabled", name=m["name"], author=m["author"], why=str(why or "")[:300], subject=m["subject"])
    return {"id": module_id, "status": "disabled"}


# --- the dry run -----------------------------------------------------------------------------------------------------------------
async def _try_build(state, settings, runner, m: dict, now: float) -> dict:
    """A part or place's trial: build it (a part with its default params; a place with the parts it names, live or still waiting)."""
    from . import layouts
    report = {"calls": 1, "errors": [], "refused": [], "perceived": [], "logged": [], "replies": [], "offers": [], "placed": [], "unplaced": []}
    try:
        if m["kind"] == "part":
            b = await layouts.build_part(runner, m, {}, layouts.season(settings, now), layouts.seed_of(m["name"]))
        else:
            b = await layouts.build_place(state, settings, runner, m, now, waiting=True)
            report["calls"] += len(b["parts"])
        report["built"] = f"{len(b['shapes'])} shapes, {len(b['anchors'])} anchors"
    except layouts.Bad as e:
        report["errors"].append(f"on_build: {e}")
    report["clean"] = not report["errors"]
    return report


async def dry_run(state, settings, runner, m: dict, now: float) -> dict:
    """Run a module on a copy of the world for DRY_HOURS simulated hours, then each declared event once and each offer once, noting where
    everything it showed along the way went.
    Returns a report; `clean` means no errors and nothing refused."""
    from .state import State
    if m["kind"] in ("part", "place"):
        return await _try_build(state, settings, runner, m, now)
    tmp = Path(tempfile.mkdtemp(prefix="pip-dry-"))
    copy_db = tmp / "world.db"
    try:
        with state.lock:
            dst = sqlite3.connect(copy_db)
            state.db.backup(dst)
            dst.close()
        world = State(replace(settings, db_path=str(copy_db)))
        world.update_module(m["id"], status="live", cursor=(world.events(limit=1) or [{"id": 0}])[0]["id"])
        sim = world.module(m["id"])
        report = {"calls": 0, "errors": [], "refused": [], "perceived": [], "logged": [], "replies": [], "offers": [], "slowest_ms": 0}
        placed, unplaced = {}, {}                                       # every placement seen along the way, not just the last

        async def run(hook, at, **extra):
            last, shown = (world.events(limit=1) or [{"id": 0}])[0]["id"], sim["show"]
            t0 = time.monotonic()
            r = await call(world, settings, runner, sim, hook, at, trial=True, **extra)
            report["slowest_ms"] = max(report["slowest_ms"], round((time.monotonic() - t0) * 1000))
            report["calls"] += 1
            if r["error"]:
                report["errors"].append(f"{hook}: {r['error']}")
            if r["refused"]:
                report["refused"].append(f"{hook}: {r['refused']}")
            if r["reply"]:
                report["replies"].append(f"{extra.get('action')}: {r['reply']}")
            report["logged"] += [e["data"]["text"] for e in world.events(after_id=last) if e["kind"] == "module"]
            sim.update(world.module(sim["id"]))
            report["perceived"] += [l["text"] for l in sim["lines"]]
            world.update_module(sim["id"], lines=[])
            sim["lines"] = []
            if sim["show"] != shown:
                p, u = _placement(world, settings, sim, at)
                placed.update(dict.fromkeys(p))
                unplaced.update(dict.fromkeys(u))

        hooks = m["manifest"]["hooks"]
        if "on_install" in hooks:
            await run("on_install", now)
        at = now
        while at < now + DRY_HOURS * 3600 and len(report["errors"]) < FAILS_TO_DISABLE:
            at += DRY_STEP_MINUTES * 60
            if "on_time" in hooks and sim["due"] and sim["due"] <= at:
                await run("on_time", at, due=sim["due"])
            if "on_tick" in hooks:
                await run("on_tick", at)
        for kind in m["manifest"]["events"]:
            sample = next((e for e in state.events(limit=500) if e["kind"] == kind), None)
            if sample:
                await run("on_event", at, event=pv.public_event(sample))
        report["offers"] = [o["name"] for o in sim["offers"]]
        if "on_action" in hooks:
            for o in list(sim["offers"]):
                await run("on_action", at, action=o["name"], args={"purpose": "trying it"})
        report["placed"], report["unplaced"] = list(placed), list(unplaced)
        report["clean"] = not report["errors"] and not report["refused"] and not report["unplaced"] and sim["status"] == "live"
        return report
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _placement(state, settings, m: dict, now: float) -> tuple[list[str], list[str]]:
    """Where a module's objects would go at the end of its dry run, and which wouldn't fit."""
    from . import worldmap
    kinds = {p["key"]: p["kind"] for p in worldmap.snapshot(state, settings, None, now)["places"]}
    placed, unplaced = [], []
    for key in dict.fromkeys(where(state, m, o["at"]["place"]) for o in m["show"]):
        if key not in kinds:
            unplaced += [f"{o['id']}: {o['at']['place']!r} isn't a place in the world" for o in m["show"] if where(state, m, o["at"]["place"]) == key]
            continue
        ok, bad = objects_for(state, key, kinds[key])
        placed += [f"{o['key'][len(m['name']) + 1:]}: {o['anchor']} at {key}" for o in ok if o["key"].startswith(m["name"] + ":")]
        unplaced += [line[len(m["name"]) + 1:] for line in bad if line.startswith(m["name"] + ":")]
    return placed, unplaced


# --- the library: modules the world proposes for itself ---------------------------------------------------------------------------
LIBRARY = Path(__file__).parent / "module_library"


def library(name: str) -> tuple[dict, str]:
    """A module from the library: (manifest template, source)."""
    return json.loads((LIBRARY / f"{name}.json").read_text()), (LIBRARY / f"{name}.py").read_text()


def slug(text: str) -> str:
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", text.lower())).strip("-")[:28] or "thing"


async def offer_library(state, settings, runner, now: float | None = None) -> list[int]:
    """The world proposes its own workings for things that have built-in ones, once each whatever the owner decides: its rules (RULES),
    and for a timekeeper that needs tending, its clock's workings."""
    if runner is None:
        return []
    made = []
    for name, reason in RULES.items():                       # the world's own rules, once each
        if any(o["name"] == name for o in state.modules()):
            continue
        man, source = library(name)
        r = await propose(state, settings, runner, "world", man, source, reason, now=now)
        if "id" in r:
            made.append(r["id"])
        else:
            log.warning("library module %s refused: %s", name, r["error"])
    for c in state.creations():
        caps = c["spec"]["capabilities"]
        if not ("timekeeper" in caps and "upkeep" in caps) or any(o["subject"].lower() == c["name"].lower() for o in state.modules()):
            continue
        man, source = library("timekeeper")
        man = {**man, "name": f"{slug(c['name'])}-workings", "subject": c["name"]}
        r = await propose(state, settings, runner, "world", man, source,
                          f"Your {c['name']}'s clockwork as code: it keeps time, stops when it runs down, and can be wound and set.", now=now)
        if "id" in r:
            made.append(r["id"])
        else:
            log.warning("library module for %s refused: %s", c["name"], r["error"])
    return made


def public_row(m: dict, full: bool = False) -> dict:
    """What anyone may see of a module (the code too, once it's live); `full` adds what only the owner sees."""
    out = {k: m[k] for k in ("id", "name", "kind", "author", "subject", "status", "version", "reason", "created_at", "decided_at")}
    out["offers"], out["hooks"] = m["offers"], m["manifest"]["hooks"]
    if full or m["status"] in ("live", "disabled", "replaced"):
        out["source"], out["manifest"] = m["source"], m["manifest"]
    if full:
        out.update(report=m["report"], note=m["note"], state=m["state"], facts=m["facts"], fails=m["fails"], budget=m["budget"])
    return out
