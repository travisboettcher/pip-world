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
from . import world_pack
from . import stats as stats_mod

log = logging.getLogger(__name__)

API = 1
KINDS = ("thing", "rule", "part", "place")
HOOKS = ("on_install", "on_tick", "on_time", "on_event", "on_action", "on_message", "on_answer", "on_request")
READS = ("time", "weather", "agent", "pip", "subject", "items", "facts", "works", "stalls", "places", "visitors", "people", "creations", "happenings")
PROPOSES = ("state", "publish", "perceive", "log", "schedule", "offer", "consume", "runtime", "wake", "show", "affect", "find", "sell", "voices",
            "ask", "speak", "happen", "store", "status", "take", "give", "request", "session")
SHIPPED = "library"                                   # the author of modules shipped with the engine (module_library/): reviewed like its code
AUTHORS = ("world", "pip", SHIPPED)
PIP_READS = ("time", "weather", "agent", "pip", "subject", "items", "facts", "visitors")                      # what Pip's own programs may know, and do (step 3)
PIP_PROPOSES = ("state", "perceive", "log", "schedule", "offer", "show", "consume", "runtime", "wake")
MISFIRE = {"rough": 0.25, "sound": 0.08, "fine": 0.02, "masterwork": 0.0}     # craft over code: how often Pip's work fails to fire
STATUSES = ("proposed", "waiting", "live", "disabled", "rejected", "replaced")
RUNTIME_KEYS = {"clock_set_at": "number", "clock_offset": "number", "tended_until": "number", "halted_at": "number", "stop_logged": "bool",
                "needs_part": "part"}                       # a thing's creation fields the engine's readers use (creations.py)
NAME = re.compile(r"^[a-z][a-z0-9-]{2,39}$")
SHOW_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,23}$")
SHOW_MAX, SIZE_RANGE, MOTIONS, WORKS_SHOWN = 8, (0.2, 1.5), ("bob", "sway", "spin"), 12
RULES = (  # the modules the engine ships (module_library/), in the order they are offered; each says what it is in its manifest's `reason`
    "gallery-wall", "stall-pictures", "round-tree", "pine-tree", "well", "stall", "cutaway", "scrap-heap", "shed", "bench", "standing-stones", "lighthouse", "outdoors", "home", "neighbor", "market", "shop", "library", "stall-customers", "garden", "happenings")
OFFER_NAME = re.compile(r"^[a-z][a-z ]{0,23}$")
STATE_MAX, FACTS_MAX, TEXT_MAX, OFFERS_MAX, CONSUME_MAX = 16_000, 4_000, 200, 4, 5
PER_DAY = {"calls": 600, "perceive": 12, "log": 24, "wake": 4, "affect": 6, "find": 4, "sell": 200, "ask": 12, "speak": 24, "happen": 2,
           "take": 24, "give": 24, "request": 24}
SHIPPED_PER_DAY = {**PER_DAY, "calls": 3000, "perceive": 100, "log": 100, "wake": 12, "ask": 150, "speak": 150, "happen": 8, "take": 200, "give": 200,
                   "request": 200}
# What a feature needs to be a module (docs/DESIGN-world-packs.md, "Phase 4 in detail"): tools, storage, belongings, status, requests, sessions.
TOOL_NAME, TOOLS_MAX, TOOL_PARAMS_MAX, PARAM_TYPES = re.compile(r"^[a-z][a-z_]{1,23}$"), 6, 8, ("string", "integer", "number", "boolean")
STORE_MAX, STORE_KEYS, STORE_COLLECTIONS = 64_000, 200, 8
COLLECTION, STORE_KEY = re.compile(r"^[a-z][a-z0-9_]{0,23}$"), re.compile(r"^[A-Za-z0-9 _:.-]{1,40}$")
STATUS_LINES, STATUS_TITLE, GIVE_LINES, ATTRS_MAX, FEEL_MOST, ANSWERS_MAX = 8, 40, 4, 8, 5, 8
SESSION_MINUTES, KIND_WORD, ARGS_MAX = (1, 240), re.compile(r"^[a-z][a-z_]{0,23}$"), 2_000
VOICES_MAX, ASKS_WAITING, ASK_PROMPT_MAX, ASK_MOST, SPEAK_MAX = 4, 3, 2000, 600, 400   # the engine's own: a creation ticking every minute
AFFECT_ENERGY, FINDS_MAX = 0.1, 8
FAILS_TO_DISABLE = 3
DRY_HOURS, DRY_STEP_MINUTES = 24, 30                  # a whole day, so what happens at dusk or on the hour is tried too
TICK_ONLY_HOOKS = ("on_tick", "on_time", "on_event")      # hooks the engine runs on its own each step


class Refused(ValueError):
    """A proposal the referee won't apply; the message is for the module's author."""


# --- manifests ---------------------------------------------------------------------------------------------------------------------
def _params(m: dict, lists: bool = True) -> dict:
    """Settings a module is given: plain values (and, except for a part, short lists of them)."""
    params = m.get("params") or {}
    plain = (int, float, str, bool)
    if not isinstance(params, dict) or len(params) > 16 or not all(isinstance(v, plain) or (lists and isinstance(v, list) and len(v) <= 8 and all(isinstance(x, plain) for x in v))
                                                                    for v in params.values()):
        raise Refused("`params` maps up to 16 names to plain default values")
    return params


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
    if "on_message" in out["hooks"] and "voices" not in out["proposes"]:
        raise Refused(f"`on_message` hears what {world_pack.active().agent.name} says to the module's voices: it needs `voices` among what it proposes")
    if "on_answer" in out["hooks"] and "ask" not in out["proposes"]:
        raise Refused("`on_answer` gets the words it asked for: it needs `ask` among what it proposes")
    if kind in ("part", "place"):
        if author == "pip" or out["hooks"] != ["on_build"] or out["reads"] or out["proposes"]:
            raise Refused("parts and places are the world's; they have just on_build, and read and propose nothing")
        if kind == "part":
            out["params"] = _params(m, lists=False)
        elif m.get("kinds") is not None:                     # every place of these kinds that has no layout of its own
            from . import layouts
            ks = m["kinds"]
            if not isinstance(ks, list) or not ks or any(k not in layouts.KINDS for k in ks):
                raise Refused(f"`kinds` is a list drawn from: {', '.join(layouts.KINDS)}")
            out["kinds"] = list(dict.fromkeys(ks))
        elif m.get("new") is not None:                       # a place that doesn't exist yet (step 6): it enters the world when approved
            from . import invented_places, module_places
            try:
                out["new"] = module_places.check_new(m["new"], state, name)
            except ValueError as e:
                raise Refused(str(e)) from None
            out["place"] = invented_places.key_for(out["new"]["label"])
        else:
            if not isinstance(m.get("place"), str) or not m["place"].strip():
                raise Refused("a place module names the place it lays out: `place` (or describes a new one: `new`, or covers `kinds`)")
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
    if m.get("params"):                                      # settings the module is given (ctx["params"]): plain values, or lists of them
        out["params"] = _params(m)
    finds = m.get("finds")
    if finds is not None and (not isinstance(finds, list) or not finds or len(finds) > FINDS_MAX
                              or not all(isinstance(f, str) and f.strip() and len(f) <= 40 for f in finds)):
        raise Refused(f"`finds` is a list of up to {FINDS_MAX} names of things it may find")
    if bool(finds) != ("find" in out["proposes"]):
        raise Refused(f"`find` and `finds` go together: say what it may find (up to {FINDS_MAX} names)")
    if finds:
        out["finds"] = list(dict.fromkeys(f.strip().lower() for f in finds))
    tends = m.get("tends")
    if tends is not None and (kind != "thing" or not isinstance(tends, str) or not OFFER_NAME.match(tends)):
        raise Refused("`tends` is the name of the offer that tending the thing means")
    if tends:
        out["tends"] = tends
    if m.get("tools") is not None:
        out["tools"] = _tools(m["tools"], author)
    if out.get("tools") and "on_action" not in out["hooks"]:
        raise Refused("a module's `tools` are used through on_action: add it to `hooks`")
    belongings = m.get("belongings")
    if bool(belongings) != bool({"take", "give"} & set(out["proposes"])):
        raise Refused("`take`/`give` and `belongings` go together: say which kinds of thing it may take and give, and how many at most")
    if belongings:
        out["belongings"] = _belongings(belongings)
    answers = m.get("answers") or {}
    if not isinstance(answers, dict) or len(answers) > ANSWERS_MAX or not all(KIND_WORD.match(str(k)) and isinstance(v, str) and 0 < len(v) <= TEXT_MAX
                                                                          for k, v in answers.items()):
        raise Refused(f"`answers` maps up to {ANSWERS_MAX} words (what it can be asked to do) to a line saying what each does")
    if bool(answers) != ("on_request" in out["hooks"]):
        raise Refused("`on_request` and `answers` go together: say what it can be asked to do")
    if answers:
        out["answers"] = dict(answers)
    if "session" in out["proposes"] and not {"on_action", "on_time"} <= set(out["hooks"]):
        raise Refused("a `session` starts from on_action and ends in on_time: it needs both hooks")
    return out


def _tools(tools, author: str) -> list:
    """Tools a module offers the agent: each a name, a line of help, the arguments it takes (a small JSON schema) and where it works."""
    from .tools import REGISTRY
    if author == "pip" or not isinstance(tools, list) or not 1 <= len(tools) <= TOOLS_MAX:
        raise Refused(f"`tools` is a list of up to {TOOLS_MAX} {{name, help, params?, where?}} (and not for {world_pack.active().agent.name}'s programs)")
    out = []
    for t in tools:
        if not isinstance(t, dict) or not TOOL_NAME.match(str(t.get("name") or "")):
            raise Refused("a tool's `name` is 2 to 24 lowercase letters and underscores")
        name = t["name"]
        if name in REGISTRY or name in (x["name"] for x in out):
            raise Refused(f"there is already a tool called {name}")
        params = t.get("params") or {"type": "object", "properties": {}}
        props, required = params.get("properties") if isinstance(params, dict) else None, (params or {}).get("required", []) if isinstance(params, dict) else None
        if not isinstance(props, dict) or params.get("type") != "object" or len(props) > TOOL_PARAMS_MAX or not isinstance(required, list) \
                or any(r not in props for r in required) or not all(_param_ok(k, v) for k, v in props.items()):
            raise Refused(f"`{name}`'s `params` is {{type: object, properties, required?}}: up to {TOOL_PARAMS_MAX} arguments, each "
                          f"{{type ({', '.join(PARAM_TYPES)}), description?, enum?}}")
        where = t.get("where", "anywhere")
        if not isinstance(where, str) or not where.strip() or len(where) > 60:
            raise Refused(f"`{name}`'s `where` is anywhere, home, or a place's key")
        first = t.get("first")
        if first is not None and (not isinstance(first, str) or not first.strip() or len(first) > 60):
            raise Refused(f"`{name}`'s `first` is a few words for the first time it's used (\"planted something\")")
        out.append({"name": name, "help": _text(t.get("help"), f"{name}.help"), "where": where.strip(),
                    "params": {"type": "object", "properties": props, "required": list(required)}, **({"first": first.strip()} if first else {})})
    return out


def _param_ok(name, p) -> bool:
    return (KIND_WORD.match(str(name)) is not None and isinstance(p, dict) and p.get("type") in PARAM_TYPES and set(p) <= {"type", "description", "enum"}
            and isinstance(p.get("description", ""), str) and len(p.get("description", "")) <= TEXT_MAX
            and (p.get("enum") is None or (isinstance(p["enum"], list) and 0 < len(p["enum"]) <= 12)))


def _belongings(b) -> dict:
    from . import world as world_content
    kinds = set(world_content.kinds())
    if not isinstance(b, dict) or set(b) - {"takes", "gives", "most"} or not _number(b.get("most"), 1, 20) \
            or not all(isinstance(b.get(k, []), list) and all(isinstance(x, str) and x in kinds for x in b.get(k, [])) for k in ("takes", "gives")):
        raise Refused(f"`belongings` is {{takes?, gives?, most}}: kinds of thing ({', '.join(sorted(kinds)) or 'this world has none'}), and at most 1 to 20 at a time")
    return {"takes": list(b.get("takes", [])), "gives": list(b.get("gives", [])), "most": int(b["most"])}


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
    if "store" in man["proposes"]:
        ctx["store"] = state.store(m["name"])
    if man.get("params") and m["kind"] != "part":
        ctx["params"] = man["params"]
    if "voices" in m["manifest"]["proposes"]:
        ctx["voices"] = m.get("voices") or []
    if "ask" in m["manifest"]["proposes"]:
        ctx["asking"] = len(m.get("asks") or [])          # questions still waiting for the model's words
    reads = man["reads"]
    if "time" in reads:
        from .happenings import season_of
        t = datetime.fromtimestamp(now)
        ctx["time"] = {"hour": t.hour, "minute": t.minute, "weekday": t.strftime("%A"), "season": season_of(now, settings.hemisphere)}
    if "weather" in reads:
        from . import weather
        w = weather.current(state, now)
        ctx["weather"] = {"condition": w.condition, "temp": w.temp, "unit": w.unit, "daylight": w.above_horizon} if w else None
    if "agent" in reads or "pip" in reads:                   # `pip` is the old name of the `agent` read, kept for modules written with it
        a = state.agent()
        from . import places
        me = {"where": a["location"], "at_home": a["location"] == places.HOME, "activity": a["activity"], "asleep": a["activity"] == "sleeping",
                      **{n: a[n] for n in stats_mod.declared(settings) if n in a}, "mood": a["mood"], "walking": (state.session() or {}).get("kind") == "walk",
                      "coins": state.coins()}
        ctx.update({k: me for k in ("agent", "pip") if k in reads})
    if "subject" in reads:
        c = _creation(state, man["subject"])
        ctx["subject"] = None if not c else {"name": c["name"], "quality": c["quality"], "description": c["description"],
                                              "capabilities": c["spec"]["capabilities"], "runtime": c["runtime"], "quirks": c["spec"]["quirks"]}
    if "items" in reads:
        ctx["items"] = [{"name": i["name"], "qty": i["qty"], "kind": i["kind"], "attrs": i["attrs"]} for i in state.items()]
    if "works" in reads:
        ctx["works"] = state.pictures(WORKS_SHOWN)
    if "stalls" in reads:
        from . import market
        selling = market.selling_at(state, settings, now)
        ctx["stalls"] = [{"place": r["place"], "item": r["name"], "kind": r["kind"], "qty": r["qty"], **({"work": r["attrs"]["work"]} if r["attrs"].get("work") else {}),
                          "ask": r["ask"], "fair": market.fair_price(state, r["place"], r["name"], r["kind"], r["attrs"], now),
                          "sold_today": market.sold_today(r, now), "selling": r["place"] == selling}
                         for r in state.stall_rows()]
    if "places" in reads:
        from . import worldmap
        ctx["places"] = [{"key": p["key"], "label": p["label"], "kind": p["kind"]}
                         for p in worldmap.snapshot(state, settings, None, now)["places"] if not p["heard_only"]]
    if "people" in reads:                                   # who lives in Pip's world (not what they're like)
        ctx["people"] = [{"name": c["name"], "kind": c["kind"]} for c in state.characters() if c["kind"] != "creation"]
    if "creations" in reads:
        from . import creations as cr
        ctx["creations"] = [{"name": c["name"], "running": cr.running(c, now), "tended": "upkeep" in c["spec"]["capabilities"]} for c in state.creations()]
    if "happenings" in reads:
        from . import happenings as hp
        recent = state.happenings(30)
        ctx["happenings"] = {"recent": [{k: h[k] for k in ("category", "tone", "severity", "ts", "status")} for h in recent],
                             "today": sum(1 for h in recent if h["ts"] >= hp._today_start(now)), "room": hp.room_for(state, settings, now),
                             "can_remember": len(state.memories("diary", limit=hp.MIN_DIARY)) >= hp.MIN_DIARY
                             and any(n["ts"] < now - hp.OLD_NOTE_DAYS * 86400 for n in state.memories("diary", limit=500))}
    if "visitors" in reads:
        ctx["visitors"] = {"waiting": len(state.pending_inbox())}
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


def limits(m: dict) -> dict:
    """A module's daily allowance: the engine's own modules run creations that tick every minute."""
    return SHIPPED_PER_DAY if m["author"] == SHIPPED else PER_DAY


def _budget(m: dict, now: float) -> dict:
    b = m["budget"] if m["budget"].get("day") == _day(now) else {"day": _day(now)}
    return {k: b.get(k, 0) for k in PER_DAY} | {"day": b["day"]}


def plan(state, m: dict, result: dict, now: float, hook: str, settings=None) -> list:
    """Check a hook's proposals and return the changes to make, in order; raises Refused (and changes nothing) if any is not allowed."""
    man, budget, changes, cap = m["manifest"], _budget(m, now), [], limits(m)
    allowed = set(man["proposes"]) - ({"session"} if hook != "on_action" else set()) | ({"reply"} if hook in ("on_action", "on_request") else set()) \
        | ({"refuse"} if hook == "on_request" else set())
    extra = sorted(set(result) - allowed)
    if extra:
        raise Refused("only on_action can reply" if extra == ["reply"] else "only on_action can start a session" if extra == ["session"]
                      else f"it returned {', '.join(extra)}, which its manifest doesn't propose")
    if "refuse" in result:                                    # a module asked to do something says why it won't
        raise Refused(_text(result["refuse"], "refuse"))
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
            if budget[key] >= cap[key]:
                raise Refused(f"it has used today's {cap[key]} `{key}` lines")
            changes.append((key, _log(result[key]) if key == "log" else _text(result[key], key)))
    if "store" in result:
        changes.append(("store", _store(state, m["name"], result["store"])))
    if "status" in result:
        changes.append(("standing", _status(result["status"])))
    for key in ("take", "give", "request"):
        if key in result:
            if budget[key] >= cap[key]:
                raise Refused(f"it has used today's {cap[key]} `{key}`")
            changes.append((key, _take(state, man, result[key]) if key == "take" else _give(man, result[key]) if key == "give"
                            else _request(state, m, result[key])))
    if "session" in result:
        changes.append(("session", _session(state, result["session"])))
    if result.get("wake"):
        if budget["wake"] >= cap["wake"]:
            raise Refused(f"it has woken {world_pack.active().agent.name} {cap['wake']} times today")
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
    voices = m.get("voices") or []
    if "voices" in result:
        voices = _voices(state, m, result["voices"])
        changes.append(("voices", voices))
    if "speak" in result:
        if budget["speak"] >= cap["speak"]:
            raise Refused(f"it has used today's {cap['speak']} `speak`")
        changes.append(("speak", _speak(voices, result["speak"])))
    if "ask" in result:
        if budget["ask"] >= cap["ask"]:
            raise Refused(f"it has used today's {cap['ask']} `ask`")
        if len(m.get("asks") or []) >= ASKS_WAITING:
            raise Refused(f"it already has {ASKS_WAITING} questions waiting for words")
        changes.append(("ask", _ask(result["ask"])))
    if "happen" in result:
        from . import happenings as hp
        if budget["happen"] >= cap["happen"]:
            raise Refused(f"it has used today's {cap['happen']} `happen`")
        if m.get("happen"):
            raise Refused("its last happening is still being written")
        why = hp.room_for(state, settings, now) if settings is not None else "happenings can't be checked here"
        if why:
            raise Refused(f"nothing can happen now: {why}")
        try:
            hp.shape(result["happen"])                         # the world is checked when it's written (or it's dropped, saying why)
        except ValueError as e:
            raise Refused(str(e)) from None
        p = result["happen"]
        changes.append(("happen", {k: p[k] for k in ("category", "tone", "severity", "effects", "about", "names", "fallback", "night") if k in p}))
    if "sell" in result:
        if budget["sell"] >= cap["sell"]:
            raise Refused(f"it has used today's {cap['sell']} `sell`")
        changes.append(("sell", _sell(state, settings, result["sell"], now)))
    for key in ("affect", "find"):
        if key in result:
            if budget[key] >= cap[key]:
                raise Refused(f"it has used today's {cap[key]} `{key}`")
            changes.append((key, EFFECTS[key](man, result[key])))
    if "reply" in result:
        changes.append(("reply", _text(result["reply"], "reply")))
    return changes


def _number(v, lo: float, hi: float) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and lo <= v <= hi


def _affect(man, v) -> dict:
    """How the agent is: a little of any of its stats either way (the world's own: stats.py), a mood."""
    names = list(stats_mod.declared())
    if not isinstance(v, dict) or not v or set(v) - {*names, "mood"}:
        raise Refused("`affect` is {" + ", ".join(f"{n}?" for n in [*names, "mood"]) + "}")
    for k in names:
        if k in v and not _number(v[k], -AFFECT_ENERGY, AFFECT_ENERGY):
            raise Refused(f"`affect.{k}` is a number from -{AFFECT_ENERGY} to {AFFECT_ENERGY}")
    if "mood" in v and not (isinstance(v["mood"], str) and v["mood"].strip() and len(v["mood"]) <= 40):
        raise Refused("`affect.mood` is a word or two")
    return {k: (v[k].strip() if k == "mood" else float(v[k])) for k in v}


def _find(man, v) -> dict:
    """Something found: only what its manifest says it may find, one or two at a time."""
    if not isinstance(v, dict) or not isinstance(v.get("item"), str):
        raise Refused("`find` is {item, qty}")
    item = v["item"].strip().lower()
    if item not in man.get("finds", []):
        raise Refused(f"it can only find: {', '.join(man.get('finds', []))}")
    qty = v.get("qty", 1)
    if qty not in (1, 2) or isinstance(qty, bool):
        raise Refused("`find.qty` is 1 or 2")
    return {"item": item, "qty": qty}


EFFECTS = {"affect": _affect, "find": _find}


def _log(v):
    """A line for the event log: text, or {text, kind, feel?}: a kind of moment (a first of its kind may be the pack's: content.json's
    `module_firsts`), and how it moves the agent's feelings a little."""
    if not isinstance(v, dict):
        return _text(v, "log")
    if set(v) - {"text", "kind", "feel"} or not KIND_WORD.match(str(v.get("kind") or "")):
        raise Refused("`log` is a line, or {text, kind, feel?}: kind is a word (lowercase letters and underscores)")
    feel = v.get("feel") or {}
    from . import emotions as emo
    if not isinstance(feel, dict) or any(k not in emo.NAMES or not isinstance(n, int) or isinstance(n, bool) or not -FEEL_MOST <= n <= FEEL_MOST
                                         for k, n in feel.items()):
        raise Refused(f"`log.feel` maps emotions ({', '.join(emo.NAMES)}) to whole numbers from -{FEEL_MOST} to {FEEL_MOST}")
    return {"text": _text(v.get("text"), "log.text"), "kind": v["kind"], **({"feel": feel} if feel else {})}


def _store(state, name: str, v) -> dict:
    """Changes to a module's collections: {collection: {key: value or null}}, within its size."""
    shape = f"`store` is {{collection: {{key: value or null}}}}: up to {STORE_COLLECTIONS} collections (lowercase words) of {STORE_KEYS} keys"
    if not isinstance(v, dict) or not all(isinstance(c, str) and COLLECTION.match(c) and isinstance(keys, dict)
                                          and all(isinstance(k, str) and STORE_KEY.match(k) for k in keys) for c, keys in v.items()):
        raise Refused(shape)
    merged = state.store(name)
    for c, keys in v.items():
        coll = merged.setdefault(c, {})
        for k, val in keys.items():
            coll.pop(k, None) if val is None else coll.__setitem__(k, val)
    merged = {c: keys for c, keys in merged.items() if keys}
    if len(merged) > STORE_COLLECTIONS or any(len(keys) > STORE_KEYS for keys in merged.values()):
        raise Refused(shape)
    if _size(merged) > STORE_MAX:
        raise Refused(f"its store would be over {STORE_MAX} bytes")
    return v


def _status(v) -> dict:
    """What the agent sees every time while it holds: a titled section of the prompt, replaced on each call ({} clears it)."""
    if v == {} or v is None:
        return {}
    if not isinstance(v, dict) or set(v) - {"title", "lines", "ready", "next_at"} or not isinstance(v.get("lines"), list) \
            or len(v["lines"]) > STATUS_LINES or not isinstance(v.get("ready", False), bool) \
            or (v.get("next_at") is not None and not _number(v["next_at"], 0, 1e12)):
        raise Refused(f"`status` is {{title, lines, ready?, next_at?}}: up to {STATUS_LINES} lines; ready says something waits for "
                      f"{world_pack.active().agent.name} now, next_at when something next will")
    title = _text(v.get("title"), "status.title")
    if len(title) > STATUS_TITLE:
        raise Refused(f"`status.title` is at most {STATUS_TITLE} characters")
    return {"title": title, "lines": [_text(x, "status line") for x in v["lines"]], "ready": v.get("ready", False),
            **({"next_at": float(v["next_at"])} if v.get("next_at") is not None else {})}


def _take(state, man: dict, v) -> list:
    """Things to take from the agent's belongings: only kinds the manifest takes, only what the agent has."""
    b = man["belongings"]
    if not isinstance(v, list) or not 1 <= len(v) <= GIVE_LINES or not all(isinstance(x, dict) and isinstance(x.get("item"), str) for x in v):
        raise Refused(f"`take` is a list of up to {GIVE_LINES} {{item, qty}}")
    out = []
    for x in v:
        qty = x.get("qty", 1)
        if not isinstance(qty, int) or isinstance(qty, bool) or not 1 <= qty <= b["most"]:
            raise Refused(f"`take` qty is 1 to {b['most']}")
        item, err = state.find_item(x["item"])
        if not item:
            raise Refused(err)
        if item["kind"] not in b["takes"]:
            raise Refused(f"it can only take: {', '.join(b['takes']) or 'nothing'}")
        if item["qty"] < qty:
            raise Refused(f"there are only {item['qty']} {item['name']}")
        out.append((item["id"], qty, item["name"]))
    return out


def _give(man: dict, v) -> list:
    """Things to give the agent: only kinds the manifest gives, a few at a time, with plain attributes."""
    b = man["belongings"]
    if not isinstance(v, list) or not 1 <= len(v) <= GIVE_LINES:
        raise Refused(f"`give` is a list of up to {GIVE_LINES} {{item, qty, kind, description?, attrs?}}")
    out = []
    for x in v:
        if not isinstance(x, dict) or set(x) - {"item", "qty", "kind", "description", "attrs"}:
            raise Refused("each thing in `give` is {item, qty, kind, description?, attrs?}")
        name = _text(x.get("item"), "give.item")
        if len(name) > 40:
            raise Refused("`give.item` is a name of at most 40 characters")
        if x.get("kind") not in b["gives"]:
            raise Refused(f"it can only give: {', '.join(b['gives']) or 'nothing'}")
        qty = x.get("qty", 1)
        if not isinstance(qty, int) or isinstance(qty, bool) or not 1 <= qty <= b["most"]:
            raise Refused(f"`give` qty is 1 to {b['most']}")
        out.append({"item": name, "qty": qty, "kind": x["kind"], "description": _text(x["description"], "give.description") if x.get("description") else "",
                    "attrs": _attrs(x.get("attrs") or {})})
    return out


def _attrs(a) -> dict:
    """A given thing's attributes: plain values, and `restores` only naming the world's stats."""
    plain = (int, float, str, bool)
    stats = stats_mod.declared()
    if not isinstance(a, dict) or len(a) > ATTRS_MAX or _size(a) > 500 or not all(
            KIND_WORD.match(str(k)) and (isinstance(v, plain) if k != "restores" else
                                         isinstance(v, dict) and all(s in stats and _number(n, 0, 1) for s, n in v.items()))
            for k, v in a.items()):
        raise Refused(f"`attrs` is up to {ATTRS_MAX} plain values; `restores` maps the world's stats ({', '.join(stats)}) to 0 to 1")
    return a


def _request(state, m: dict, v) -> dict:
    """Something asked of another live module, which answers it in its on_request."""
    if not isinstance(v, dict) or set(v) - {"module", "what", "args"} or not isinstance(v.get("args", {}), dict) or _size(v.get("args", {})) > ARGS_MAX:
        raise Refused("`request` is {module, what, args?}")
    target = answering(state, v.get("module"), v.get("what"))
    if target["id"] == m["id"]:
        raise Refused("a module changes its own state itself, not by asking")
    return {"module": target["name"], "what": v["what"], "args": v.get("args", {})}


def answering(state, name, what) -> dict:
    """The live module called `name` that answers `what`; raises Refused saying why there isn't one."""
    target = live_named(state, str(name or ""))
    if not target:
        raise Refused(f"there is no live module called {name!r}")
    answers = target["manifest"].get("answers") or {}
    if what not in answers:
        raise Refused(f"{target['name']} answers: {', '.join(answers) or 'nothing'}")
    return target


def _session(state, v) -> dict:
    """Something that takes real time: the agent is busy with it until it ends (then on_time runs)."""
    if not isinstance(v, dict) or set(v) - {"minutes", "label", "working"} or not _number(v.get("minutes"), *SESSION_MINUTES) \
            or not isinstance(v.get("working", False), bool):
        raise Refused(f"`session` is {{minutes ({SESSION_MINUTES[0]} to {SESSION_MINUTES[1]}), label, working?}}")
    if state.session():
        raise Refused(f"{world_pack.active().agent.name} is busy with something else")
    label = _text(v.get("label"), "session.label")
    return {"minutes": float(v["minutes"]), "label": label[:80], "working": v.get("working", False)}


def _voices(state, m: dict, v) -> list:
    """The names a module speaks as: each somewhere ("home", "subject" or a place's key), never someone already in the world."""
    shape = f"`voices` is a list of up to {VOICES_MAX} {{name, at, about?}}: at is \"home\", \"subject\" or a place's key"
    if not isinstance(v, list) or len(v) > VOICES_MAX or not all(
            isinstance(x, dict) and isinstance(x.get("name"), str) and 1 <= len(x["name"].strip()) <= 40 and isinstance(x.get("at"), str)
            and x["at"].strip() and isinstance(x.get("about", ""), str) and len(x.get("about", "")) <= 200 for x in v):
        raise Refused(shape)
    names = [x["name"].strip().lower() for x in v]
    if len(names) != len(set(names)):
        raise Refused("two voices can't share a name")
    own = _creation(state, m["manifest"]["subject"]) if m["manifest"].get("subject") else None
    taken = {c["name"].lower() for c in state.characters() if not (own and c["kind"] == "creation" and c["creation_id"] == own["id"])} \
        | {x["name"].lower() for o in state.modules("live") if o["id"] != m["id"] for x in o["voices"]}
    for x in v:
        if x["name"].strip().lower() in taken:
            raise Refused(f"someone called {x['name'].strip()} is already in the world")
    return [{"name": x["name"].strip(), "at": x["at"].strip()[:60], "about": x.get("about", "").strip()} for x in v]


def _speak(voices: list, v) -> dict:
    """A line spoken as one of the module's own voices (to Pip, or just aloud)."""
    if not isinstance(v, dict) or not isinstance(v.get("as"), str) or not isinstance(v.get("text"), str) \
            or not v["text"].strip() or len(v["text"]) > SPEAK_MAX:
        raise Refused(f"`speak` is {{as, text, to_agent?}}: text is a line of up to {SPEAK_MAX} characters")
    voice = next((x for x in voices if x["name"].lower() == v["as"].strip().lower()), None)
    if not voice:
        raise Refused("it can only speak as its own voices: " + (", ".join(x["name"] for x in voices) or "it has none"))
    return {"name": voice["name"], "text": v["text"].strip(), "to_agent": v.get("to_agent", v.get("to_pip")) is True}   # to_pip: the old name


def _ask(v) -> dict:
    """A prompt for the model; the words come back later, to on_answer."""
    if not isinstance(v, dict) or not isinstance(v.get("prompt"), str) or not v["prompt"].strip() or len(v["prompt"]) > ASK_PROMPT_MAX \
            or not isinstance(v.get("purpose", ""), str) or len(v.get("purpose", "")) > 40 or not _number(v.get("most", 300), 20, ASK_MOST):
        raise Refused(f"`ask` is {{prompt, purpose?, most?}}: a prompt of up to {ASK_PROMPT_MAX} characters, at most {ASK_MOST} characters back")
    return {"prompt": v["prompt"].strip(), "purpose": v.get("purpose", ""), "most": int(v.get("most", 300))}
SELL_LINES = 3


def _sell(state, settings, v, now: float) -> list:
    """Customers buying from Pip's stall: only lines on it, where Pip is selling right now, at Pip's ask, within what the market takes today."""
    from . import market
    from .state import name_key
    if not isinstance(v, list) or not 1 <= len(v) <= SELL_LINES or not all(isinstance(x, dict) and {"place", "item", "qty"} <= set(x) for x in v):
        raise Refused("`sell` is a list of {place, item, qty}")
    out = []
    for x in v:
        place = str(x["place"])
        if settings is None or market.selling_at(state, settings, now) != place:
            raise Refused(f"{world_pack.active().agent.name} isn't selling at {place} right now")
        row = next((r for r in state.stall_rows(place) if r["item"] == name_key(str(x["item"]))), None)
        if not row:
            raise Refused(f"there is no {x['item']} on {world_pack.active().agent.possessive} stall at {place}")
        most = min(row["qty"], market.STALL_DAILY_UNITS - market.sold_today(row, now))
        if not isinstance(x["qty"], int) or isinstance(x["qty"], bool) or not 1 <= x["qty"] <= most:
            raise Refused(f"`sell` qty is 1 to {most} (what is on the stall, and what the market takes today)")
        out.append((place, row["item"], x["qty"]))
    return out


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
            state.log("module", name=m["name"], author=m["author"], **({"text": val} if isinstance(val, str) else
                                                                     {"text": val["text"], "moment": val["kind"], **({"feel": val["feel"]} if "feel" in val else {})}))
            budget["log"] += 1
        elif kind == "store":
            state.merge_store(m["name"], val)
        elif kind == "standing":
            fields["standing"] = val
        elif kind == "take":
            for item_id, qty, _ in val:
                state.take_item(item_id, qty)
            budget["take"] += 1
        elif kind == "give":
            for g in val:
                state.add_item(g["item"], g["qty"], g["kind"], g["description"], g["attrs"])
            budget["give"] += 1
        elif kind == "request":
            target = live_named(state, val["module"])
            if target:
                state.update_module(target["id"], requests=(target.get("requests") or [])[-9:] + [{"what": val["what"], "args": val["args"], "from": m["name"], "ts": now}])
            budget["request"] += 1
        elif kind == "session":
            state.start_session(0, int(val["working"]), val["minutes"], now + val["minutes"] * 60, kind="module", target=m["name"], expect=val["label"])
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
        elif kind == "affect":
            from .state import clamp
            a = state.agent()
            state.update_agent(**{k: (v if k == "mood" else clamp(a[k] + v)) for k, v in val.items() if k == "mood" or k in a})
            budget["affect"] += 1
        elif kind == "find":
            state.add_item(val["item"], val["qty"], "material", f"found by your {m['manifest'].get('subject') or m['name']}")
            budget["find"] += 1
        elif kind == "voices":
            fields["voices"] = val
        elif kind == "happen":
            fields["happen"] = [val]
            budget["happen"] += 1
        elif kind == "speak":
            state.log("companion", name=val["name"], text=val["text"], reply=val["to_agent"], module=m["name"])
            out["wake"] = out["wake"] or val["to_agent"]
            budget["speak"] += 1
        elif kind == "ask":
            asks = fields.get("asks", m.get("asks") or [])
            fields["asks"] = asks + [{**val, "id": max([a["id"] for a in asks] + [0]) + 1, "ts": now}]
            budget["ask"] += 1
        elif kind == "sell":
            from . import market
            for place, item, qty in val:
                row = next((r for r in state.stall_rows(place) if r["item"] == item), None)
                if row:
                    market.sell_units(state, place, row, min(qty, row["qty"]), now)
            budget["sell"] += 1
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
    if budget["calls"] >= limits(m)["calls"]:
        return {"ok": False, "error": "", "refused": f"it has used today's {limits(m)['calls']} calls", "wake": False, "reply": "", "changed": False}
    if not trial and misfires(state, m, hook, now):                # a trial shows the program itself, not its luck
        state.add_module_call(m["id"], now, hook, True, 0, "misfired (the work is rough)")
        return {"ok": True, "error": "", "refused": "", "wake": False, "reply": "", "misfired": True, "changed": False}
    t0 = time.monotonic()
    res = await runner.run(m["source"], hook, context(state, settings, m, now, **extra))
    ms = round((time.monotonic() - t0) * 1000)
    changes, refused, out = None, "", {"wake": False, "reply": ""}
    if res.get("ok") and not res.get("missing"):
        try:
            changes = plan(state, m, res["result"], now, hook, settings)
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
    return {"ok": bool(res.get("ok")), "error": res.get("error", ""), "refused": refused, **out,
            "changed": any(k != "reply" for k, _ in changes or [])}


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
    now, wake, local = now or time.time(), False, LocalRunner()
    for m in state.modules("live"):
        hooks = m["manifest"]["hooks"]
        run = runner or (local if m["author"] == SHIPPED else None)       # shipped modules run even without the runner
        if run is None:
            continue
        if "on_time" in hooks and m["due"] and m["due"] <= now and m["status"] == "live":
            wake |= (await call(state, settings, run, m, "on_time", now, due=m["due"]))["wake"]
        if "on_event" in hooks and m["status"] == "live":
            kinds = set(m["manifest"]["events"])
            for e in state.events(limit=50, after_id=m["cursor"]):
                if e["kind"] in kinds and (pub := pv.public_event(e)):
                    wake |= (await call(state, settings, run, m, "on_event", now, event=pub))["wake"]
                m["cursor"] = e["id"]
            state.update_module(m["id"], cursor=m["cursor"])
        if "on_tick" in hooks and m["status"] == "live":
            wake |= (await call(state, settings, run, m, "on_tick", now))["wake"]
        if m.get("heard") and m["status"] == "live":           # what Pip said to its voices, once each
            heard = m["heard"]
            state.update_module(m["id"], heard=[])
            m["heard"] = []
            if "on_message" in hooks:
                for msg in heard:
                    wake |= (await call(state, settings, run, m, "on_message", now, message=msg))["wake"]
        if m.get("requests") and m["status"] == "live":        # what other modules asked of it, once each
            asked = m["requests"]
            state.update_module(m["id"], requests=[])
            m["requests"] = []
            for r in asked:
                wake |= (await call(state, settings, run, m, "on_request", now, request={**r, "apply": True}))["wake"]
    return wake


async def ask_module(state, settings, runner, name: str, what: str, args: dict, apply: bool, now: float | None = None, **about) -> str:
    """Ask a live module, now, to do what it answers (or, with apply false, to say what it would do): its reply. Raises Refused when it
    can't (it doesn't answer that, its code failed, or it refused). `about` is more for it to go on: a happening's tone and severity."""
    now = now or time.time()
    m = answering(state, name, what)
    run = runner or (LocalRunner() if m["author"] == SHIPPED else None)
    if run is None:
        raise Refused(f"{m['name']} can't run right now")
    r = await call(state, settings, run, m, "on_request", now, request={"what": what, "args": args, "from": "engine", "apply": apply, **about})
    if r["refused"] or not r["ok"]:
        raise Refused(r["refused"] or f"{m['name']} failed: {r['error']}")
    return r["reply"]


# --- tools a module offers, and the sessions they start ------------------------------------------------------------------------
def tools_offered(state) -> list[tuple[dict, dict]]:
    """(module, tool) for every tool live modules offer."""
    return [(m, t) for m in state.modules("live") for t in m["manifest"].get("tools") or []]


def check_args(params: dict, args) -> tuple[dict, str]:
    """A tool's arguments against its schema: (clean, '') or ({}, what's wrong). A number given as a string is taken as the number."""
    if not isinstance(args, dict):
        return {}, "the arguments are an object"
    props, out = params["properties"], {}
    for k in args:
        if k not in props:
            return {}, f"it takes: {', '.join(props) or 'nothing'}"
    for k in params["required"]:
        if args.get(k) in (None, ""):
            return {}, f"`{k}` is needed"
    for k, v in args.items():
        if v is None or v == "":
            continue
        kind = props[k]["type"]
        if kind in ("integer", "number") and isinstance(v, str):
            try:
                v = int(v) if kind == "integer" else float(v)
            except ValueError:
                return {}, f"`{k}` is a {kind}"
        ok = {"string": isinstance(v, str), "boolean": isinstance(v, bool), "integer": isinstance(v, int) and not isinstance(v, bool),
              "number": isinstance(v, (int, float)) and not isinstance(v, bool)}[kind]
        if not ok:
            return {}, f"`{k}` is a {kind}"
        if props[k].get("enum") and v not in props[k]["enum"]:
            return {}, f"`{k}` is one of {', '.join(map(str, props[k]['enum']))}"
        out[k] = v
    return out, ""


async def use_tool(state, settings, runner, m: dict, tool: dict, args, now: float | None = None) -> tuple[str, bool]:
    """The agent uses a module's tool: its arguments checked, then the module's on_action. Returns (the result for the agent, whether
    anything changed)."""
    now = now or time.time()
    clean, why = check_args(tool["params"], args)
    if why:
        return f"error: {why}", False
    run = runner or (LocalRunner() if m["author"] == SHIPPED else None)
    if run is None:
        return "error: that can't be done right now", False
    r = await call(state, settings, run, m, "on_action", now, tool=tool["name"], args=clean)
    if r["refused"]:
        return f"error: {r['refused']}", False
    if not r["ok"]:
        return f"error: it didn't work ({r['error']})", False
    return r["reply"] or f"you {tool['name'].replace('_', ' ')}.", r["changed"]


def busy_with(sess: dict) -> str:
    return sess["expect"] or "something"


async def end_session(state, settings, runner, interrupted: bool = False, now: float | None = None) -> dict | None:
    """A module's session is over (its time is up, or the agent rested): the module's on_time hears it. Returns {label, module}."""
    now = now or time.time()
    sess = state.session()
    if not sess or sess["kind"] != "module":
        return None
    state.end_session()
    m = live_named(state, sess["target"])
    done = {"label": busy_with(sess), "module": sess["target"], "interrupted": interrupted}
    run = runner or (LocalRunner() if m and m["author"] == SHIPPED else None)
    if m and run and "on_time" in m["manifest"]["hooks"]:
        await call(state, settings, run, m, "on_time", now, session={"label": done["label"], "interrupted": interrupted,
                                                                      "minutes": round((now - sess["started_at"]) / 60)})
    return done


UNTIL = re.compile(r"\{in:(\d+(?:\.\d+)?)\}")


def until(line: str, now: float) -> str:
    """A status line as it reads now: `{in:<time>}` becomes how long until then ("45 min", "3 hours")."""
    from .text import span
    return UNTIL.sub(lambda m: span(max(0, -(-(float(m.group(1)) - now) // 60))), line)


def standing(state, now: float | None = None) -> list[dict]:
    """Live modules' status sections, oldest module first: [{title, lines, ready?, next_at?, module}], each line as it reads now."""
    now = now or time.time()
    return [{**m["standing"], "lines": [until(l, now) for l in m["standing"]["lines"]], "module": m["name"]}
            for m in state.modules("live") if m.get("standing")]


def status_lines(state) -> list[str]:
    """The status sections for the agent's prompt."""
    out = []
    for s in standing(state):
        out += [f"{s['title']}:"] + [f"- {l}" for l in s["lines"]]
    return out


async def answer(state, settings, gm, runner, now: float | None = None) -> bool:
    """Ask the model what live modules asked for, and hand each its words (empty when there were none). True if Pip should wake."""
    now, wake, local = now or time.time(), False, LocalRunner()
    for m in state.modules("live"):
        run = runner or (local if m["author"] == SHIPPED else None)
        if not m.get("asks") or run is None:
            continue
        asks = m["asks"]
        state.update_module(m["id"], asks=[])
        m["asks"] = []
        for a in asks:
            words = (await gm.words(a["prompt"], a["most"]) if gm else None) or ""
            if "on_answer" in m["manifest"]["hooks"] and m["status"] == "live":
                wake |= (await call(state, settings, run, m, "on_answer", now, answer={"purpose": a["purpose"], "text": words}))["wake"]
    return wake


def voice_named(state, name: str):
    """(module, voice) for a live module's voice by name (case aside), or None."""
    q = str(name or "").strip().lower()
    return next(((m, v) for m in state.modules("live") for v in m.get("voices") or [] if v["name"].lower() in (q, f"the {q}")), None)


def voice_where(state, m: dict, v: dict) -> str | None:
    return where(state, m, v["at"])


def voices_here(state) -> list[str]:
    """Who Pip can talk to where it is, among modules' voices."""
    from . import places
    here = places.present_at(state)
    found = [v for m in state.modules("live") for v in m.get("voices") or [] if here and voice_where(state, m, v) == here]
    if not found:
        return []
    return ["Here to talk to (say with `to`): " + "; ".join(v["name"] + (f" ({v['about']})" if v["about"] else "") for v in found) + "."]


def hear(state, m: dict, voice: dict, text: str, now: float | None = None) -> bool:
    """Pip spoke to a module's voice: kept for its on_message. False if the module has no ears."""
    if "on_message" not in m["manifest"]["hooks"]:
        return False
    state.update_module(m["id"], heard=(m.get("heard") or [])[-4:] + [{"to": voice["name"], "text": str(text)[:1000], "from": f"{world_pack.active().agent.name}", "ts": now or time.time()}])
    return True


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
    return anchors.place(layouts.anchors_for(state, key, kind) or (), wanted)       # no layout built yet: nowhere to put anything


def scene_objects(state, key: str, kind: str) -> list[dict]:
    """The objects for the scene view: what to draw and where (anchors.py worked out the where)."""
    placed, _ = objects_for(state, key, kind)
    return [{"key": o["key"], "rows": o["sprite"]["rows"], "palette": o["sprite"]["palette"], "frame": o["frame"], "w": o["w"], "h": o["h"],
             "pos": o["pos"], "normal": o["normal"], "upright": o["upright"], **{k: o[k] for k in ("motion", "tip") if k in o}} for o in placed]


def live_named(state, name: str) -> dict | None:
    """The live module with this name, if there is one."""
    return next((m for m in state.modules("live") if m["name"] == name), None)


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
    own = [h for h in HOOKS if h != "on_request"]                   # a program isn't asked things by other modules
    hooks = [n.name for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in own]
    if not hooks:
        raise Refused(f"define at least one of {', '.join(own)}")
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
                       ("replies", "Using it"), ("unplaced", "Couldn't show"), ("asked", "It would ask the model"), ("spoken", "It would say"), ("happened", "It would make happen")):
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
        who = "the world" if m["author"] == "world" else f"{world_pack.active().agent.name}"
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
    runner = runner or (LocalRunner() if m["author"] == SHIPPED else None)
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
    if replaces and (not old or old["name"] != man["name"] or old["author"] not in (author, *(["world"] if author == SHIPPED else []))):
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


def _covers(new: dict, old: dict) -> bool:
    """Whether a place module takes over from another: the same place, or every kind of place the other laid out."""
    if "place" in new or "place" in old:
        return new.get("place") == old.get("place")
    return set(old.get("kinds", [])) <= set(new.get("kinds", []))


async def approve(state, settings, runner, module_id: int, note: str = "", now: float | None = None, by: str = "owner") -> dict:
    """Make a waiting (or disabled) module live: the version it replaces steps aside, and it installs."""
    now = now or time.time()
    m = state.module(module_id)
    if not m or m["status"] not in ("waiting", "disabled"):
        return {"error": "only a waiting or disabled module can go live"}
    if m["report"].get("offers") is not None and (why := untended(state, m, m["report"]["offers"])):
        return {"error": why}
    for o in state.modules("live"):
        if o["name"] == m["name"] or (m["kind"] == "thing" and o["kind"] == "thing" and o["subject"].lower() == m["subject"].lower()) \
                or (m["kind"] == "place" and o["kind"] == "place" and _covers(m["manifest"], o["manifest"])):
            state.update_module(o["id"], status="replaced")                # one module runs a thing at a time
    last = state.events(limit=1)
    state.update_module(module_id, status="live", decided_at=now, note=str(note or "")[:500], fails=0, cursor=last[0]["id"] if last else 0)
    state.log("module_live", name=m["name"], author=m["author"], version=m["version"], by=by, subject=m["subject"])
    m = state.module(module_id)
    if m["kind"] == "place" and m["manifest"].get("new"):
        from . import module_places
        module_places.introduce(state, m, now)                       # someone tells Pip about it
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
        elif "kinds" in m["manifest"]:                           # a kind's layout: tried on a made-up place of each kind
            from .looks import fallback_scene
            shapes = anchors_n = 0
            for k in m["manifest"]["kinds"]:
                scene = fallback_scene(f"trial-{k}", k, "")
                details = {"key": f"trial-{k}", "label": "a place", "kind": k, "coastal": False, **{x: y for x, y in scene.items()}}
                b = await layouts.build_place(state, settings, runner, m, now, waiting=True, key=details["key"], details=details)
                shapes, anchors_n = shapes + len(b["shapes"]), anchors_n + len(b["anchors"])
                report["calls"] += 1 + len(b["parts"])
            b = {"shapes": [None] * shapes, "anchors": [None] * anchors_n}
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
        report = {"calls": 0, "errors": [], "refused": [], "perceived": [], "logged": [], "replies": [], "offers": [], "slowest_ms": 0,
                  "asked": [], "spoken": [], "happened": []}
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
            report["spoken"] += [f"{e['data']['name']}: {e['data']['text']}" for e in world.events(after_id=last) if e["kind"] == "companion"]
            sim.update(world.module(sim["id"]))
            if sim.get("happen"):                                       # what would happen, not written on a trial
                h = sim["happen"][0]
                report["happened"].append(f"{h['tone']} {h['category']} ({h.get('severity', 'minor')})")
                world.update_module(sim["id"], happen=[])
                sim["happen"] = []
            asks = sim.get("asks") or []
            if asks:                                                    # the model isn't asked on a trial: the words are stood in for
                report["asked"] += [a["prompt"] for a in asks]
                world.update_module(sim["id"], asks=[])
                sim["asks"] = []
                if "on_answer" in sim["manifest"]["hooks"] and hook != "on_answer":
                    for a in asks:
                        await run("on_answer", at, answer={"purpose": a["purpose"], "text": "(the model's words)"})
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
        if "on_message" in hooks:
            for v in list(sim.get("voices") or [])[:2]:
                await run("on_message", at, message={"to": v["name"], "text": "Hello.", "from": f"{world_pack.active().agent.name}", "ts": at})
        report["offers"] = [o["name"] for o in sim["offers"]]
        if (why := untended(state, m, report["offers"])):
            report["refused"].append(why)
        if "on_action" in hooks:
            for o in list(sim["offers"]):
                await run("on_action", at, action=o["name"], args={"purpose": "trying it"})
        report["placed"], report["unplaced"] = list(placed), list(unplaced)
        report["asked"], report["spoken"] = list(dict.fromkeys(report["asked"]))[:10], list(dict.fromkeys(report["spoken"]))[:10]
        report["happened"] = report["happened"][:10]
        report["clean"] = not report["errors"] and not report["refused"] and not report["unplaced"] and sim["status"] == "live"
        return report
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def untended(state, m: dict, offers) -> str:
    """Why a thing's workings can't go live ('' if they can): a creation that runs down needs its workings to offer tending it."""
    c = _creation(state, m["manifest"]["subject"]) if m["kind"] == "thing" else None
    if c and "upkeep" in c["spec"]["capabilities"] and m["manifest"].get("tends", "tend") not in offers:
        return f"the {c['name']} runs down: its workings must offer `{m['manifest'].get('tends', 'tend')}`, or nobody could keep it going"
    return ""


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


SETTINGS_PARAMS = {"garden": {"plots": "garden_plots", "plots_max": "garden_plots_max", "speed": "garden_speed"},
                   "happenings": {"chance": "happenings_chance", "slot_hours": "happenings_slot_hours", "severity": "happenings_severity",
                                  "seasons": "happenings_seasons", "wake_hour": "wake_hour", "bedtime_hour": "bedtime_hour"}}


def settings_params(settings, name: str, defaults: dict) -> dict:
    """A shipped module's params from the engine's settings (HAPPENINGS_CHANCE and the like), so the owner's tuning still applies."""
    out = dict(defaults)
    for key, attr in SETTINGS_PARAMS.get(name, {}).items():
        val = getattr(settings, attr)
        out[key] = list(val) if isinstance(val, tuple) else val
    return out


RUNS = {"upkeep", "periodic", "sensor", "helper", "companion"}          # capabilities a creation's workings run (a clock that never stops has nothing to run)
WORKS = {"upkeep": "it stops when it runs down, and can be tended", "timekeeper": "it keeps time, and can be set",
         "periodic": "it says something now and then", "sensor": "it tells you when something happens", "helper": "it helps on its own",
         "companion": "it talks, and answers when you talk to it", "provides": "it brings news when you listen"}


def workings_manifest(c: dict) -> tuple[dict, str]:
    """The shipped workings for one creation: (manifest, source), with only the hooks, effects and finds its capabilities need."""
    man, source = library("workings")
    caps = c["spec"]["capabilities"]
    talks, news = "companion" in caps, caps.get("provides", {}).get("ability") == "news"
    hooks = ["on_install"] + (["on_time"] if "upkeep" in caps else []) + (["on_tick"] if {"periodic", "sensor", "helper", "companion"} & set(caps) else []) \
        + (["on_action"] if "upkeep" in caps or "timekeeper" in caps or news else []) + (["on_message"] if talks else []) \
        + (["on_answer"] if talks or news else [])
    finds = caps.get("helper", {}).get("finds") or []
    out = {**man, "name": f"{slug(c['name'])}-workings", "subject": c["name"], "hooks": hooks,
           "reads": man["reads"] + (["weather"] if news else []),
           "proposes": [p for p in man["proposes"] if (p != "find" or finds) and (p not in ("voices", "speak") or talks) and (p != "ask" or talks or news)],
           **({"finds": finds} if finds else {})}
    if "upkeep" not in caps:
        out.pop("tends")
    return out, source


def slug(text: str) -> str:
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", text.lower())).strip("-")[:28] or "thing"


async def offer_library(state, settings, runner, now: float | None = None) -> list[int]:
    """The modules shipped with the engine (module_library/), proposed once each whatever the owner later decides: its rules, parts and
    layouts (RULES), and for a timekeeper that needs tending, its clock's workings. They're the engine's own code, so they go live without
    waiting for approval when their trial is clean, and run in a local sandbox when there is no runner. When a new release changes one
    that is live, its new version is proposed the same way; one the owner disabled or rejected is left alone."""
    if settings.module_library != "on":
        return []
    runner = runner or LocalRunner()
    made = []
    for name in RULES:                                        # the world's own rules, once each, and again when the engine changes one
        man, source = library(name)
        reason = man.pop("reason", "")
        man = {**man, "params": settings_params(settings, name, man["params"])} if name in SETTINGS_PARAMS else man
        last = ([o for o in state.modules() if o["name"] == name] or [None])[-1]
        if last and not (last["author"] in (SHIPPED, "world") and last["status"] == "live"           # once shipped as the world's
                         and (last["source"] != source or last["manifest"] != check_manifest(man, SHIPPED))):
            continue
        r = await propose(state, settings, runner, SHIPPED, man, source, reason, replaces=last["id"] if last else None, now=now)
        if "id" in r:
            made.append(r["id"])
        else:
            log.warning("library module %s refused: %s", name, r["error"])
    for c in state.creations():                              # a creation's workings, for each one that does something on its own
        caps = c["spec"]["capabilities"]
        if not set(caps) & RUNS and caps.get("provides", {}).get("ability") != "news":
            continue
        man, source = workings_manifest(c)
        last = ([o for o in state.modules() if o["subject"].lower() == c["name"].lower()] or [None])[-1]
        if last and not (last["author"] in (SHIPPED, "world") and last["status"] == "live" and last["name"] == man["name"]
                         and (last["source"] != source or last["manifest"] != check_manifest(man, SHIPPED))):
            continue
        r = await propose(state, settings, runner, SHIPPED, man, source,
                          f"Your {c['name']}'s workings as code: " + "; ".join(WORKS[k] for k in caps if k in WORKS) + ".",
                          replaces=last["id"] if last else None, now=now)
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
