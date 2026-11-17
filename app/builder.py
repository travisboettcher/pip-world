"""The builder: the world adding to itself, one small rule at a time (docs/DESIGN-modules.md, "The builder").

Once a world night, after an agent's reflection, the GM is shown the world bible (what this world is and isn't), the modules that already exist
(and what the owner said about its own), for every agent what happened lately, its open wishes and how long each has been open, its oldest
open to-dos and what its sleeping self chose to focus on, what the world can produce (each place's finds, which booths sell), places only
heard of, and the module API. It may propose one rule
module, revise one of its own, or propose nothing. A second, separate GM call checks the idea against the bible and what is already there; a
proposal that doesn't fit is dropped. One that fits goes through the usual dry run (modules.propose); if the trial goes wrong the builder gets
one go at fixing it. Then it waits for the owner like any other module. Every night's outcome is logged as a `builder` event.
"""
import ast
import json
import time
from datetime import datetime
from pathlib import Path

from . import modules as M
from . import world_pack
from . import public_view as pv
from . import sandbox

DIR = Path(__file__).parent / "builder"
RULE_PROPOSES = ("state", "publish", "perceive", "event", "schedule", "show", "wake", "voices", "ask", "speak", "happen")   # a rule can't offer, take or change a thing
RULE_READS = tuple(r for r in M.READS if r != "subject")
SYSTEM = "You are the world of a small simulation, adding to yourself carefully. You answer only through the report tool."
RECENT_EVENTS, MAX_TOKENS = 40, 4000


def bible(settings) -> str:
    """What this world is and isn't: the owner's own if they wrote one (WORLD_BIBLE_PATH), else the engine's."""
    own = Path(settings.world_bible_path) if settings.world_bible_path else None
    return (own.read_text() if own and own.is_file() else world_pack.load(settings).bible()).strip()


def api(state=None) -> str:
    from . import geometry, place_kinds, places
    from .looks import scene_lists
    SCENE = scene_lists()
    return ((DIR / "api.md").read_text().replace("EVENT_KINDS", ", ".join(sorted(pv.EVENT_FIELDS))).replace("ANCHORS", anchor_list(state))
            .replace("PLACE_KINDS", "; ".join(f"{k.name} ({k.help})" for k in place_kinds.KINDS.values()))
            .replace("SETTINGS", ", ".join(SCENE.get("setting", []))).replace("TEXTURES", ", ".join(geometry.TEXTURES))
            .replace("CONDITIONS", geometry.CONDITION_LIST)
            .replace("AGENT_POSS", world_pack.active().agent.possessive).replace("AGENT_NAME", world_pack.active().agent.name)
            .replace("HOME_KEY", places.HOME)
            .replace("PARTS", parts_list(state)).strip())


def parts_list(state) -> str:
    """The live parts a layout can use, with their params' defaults and what each is."""
    rows = [m for m in state.modules("live") if m["kind"] == "part"] if state is not None else []
    return "\n".join(f"  {m['name']} (params {m['manifest'].get('params') or {}}): {m['reason']}" for m in rows) or "  (none yet: no place for now)"


def anchor_list(state=None) -> str:
    """Every kind of place and the anchors its scene has (type tagged ...), so a module can ask for one that exists: from what a kind's
    layout module has built."""
    from . import anchors, layouts
    spots = lambda rows: "; ".join(dict.fromkeys(f"{a['type']} tagged {', '.join(a['tags'])}" for a in rows if anchors.RESERVED not in a["tags"]))
    laid = {}
    for kind in layouts.kinds():
        m = layouts.kind_module(state, kind) if state is not None else None
        built = next(iter((m or {}).get("built", {}).get("places", {}).values()), None) if m else None
        laid.setdefault(spots(built["anchors"]) if built and built.get("anchors") else "ground tagged outside (once its layout is built)", []).append(kind)
    return "\n".join(f"  {'/'.join(kinds)}: {where}" for where, kinds in laid.items())


def manifest(source: str, name: str, events) -> dict:
    """A rule's manifest from its code: the hooks it defines, all a rule may read and do, the events it listens for."""
    tree = sandbox.check(source)
    hooks = [n.name for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in M.HOOKS]
    events = [e for e in (events or []) if isinstance(e, str)]
    return {"name": name, "kind": "rule", "api": M.API, "scope": "world", "hooks": hooks, "reads": list(RULE_READS), "proposes": list(RULE_PROPOSES),
            "events": events if "on_event" in hooks else []}


def place_manifest(source: str, draft: dict) -> dict:
    """A new place's manifest from the builder's draft: its description (checked by modules.check_manifest) and its layout code."""
    sandbox.check(source)
    new = {"label": draft.get("label"), "kind": draft.get("place_kind"), "description": draft.get("description"),
           "distance": draft.get("distance") or "far", "items": draft.get("items") or [], "setting": draft.get("setting")}
    new.update({k: draft[k] for k in ("opens", "closes") if draft.get(k) is not None})
    return {"name": draft["name"], "kind": "place", "api": M.API, "hooks": ["on_build"], "new": new}


def name_of(raw) -> str:
    """A module name from whatever the GM called it: lowercase words joined by dashes, starting with a letter."""
    n = M.slug(str(raw or ""))
    n = n if n[:1].isalpha() else "rule-" + n
    return (n + "-rule" if len(n) < 3 else n)[:40]


def catalogue(state) -> str:
    rows = [m for m in state.modules() if m["status"] != "replaced"]
    if not rows:
        return "(none yet)"
    out = []
    for m in rows:
        who = "you" if m["author"] == "world" else world_pack.active().agent.name
        line = f"- {m['name']} ({m['kind']}{', for ' + m['subject'] if m['subject'] else ''}; by {who}; {m['status']}): {m['reason']}"
        if m["author"] == "world" and m["note"]:
            line += f" The owner said: {m['note']}"
        out.append(line)
    return "\n".join(out)


def _open(ts: float, now: float) -> str:
    days = max(0, int((now - ts) // 86400))
    return f" (open {days} day{'' if days == 1 else 's'})"


def lately(state, settings, now: float, who=None) -> str:
    """What happened recently to an agent (`who`, else the one acting), in public terms, plus its open wishes (and how long each has been
    open) and places only heard of."""
    from . import worldmap
    lines = []
    for e in reversed(state.events(limit=300)):
        pub = pv.public_event(e)
        if not pub or e["kind"] in ("tick", "emotion", "module") or e["ts"] < now - 2 * 86400:
            continue
        d = pub["data"]
        text = d.get("text") or d.get("title") or d.get("summary") or d.get("label") or d.get("name") or ""
        lines.append(f"- {datetime.fromtimestamp(e['ts']).strftime('%a %H:%M')} {e['kind']}: {str(text)[:140]}")
    lines = lines[-RECENT_EVENTS:]
    me = who or world_pack.active().agent
    wishes = [m["text"] + _open(m["ts"], now) for m in state.memories("wishlist", status="open", limit=8)]
    heard = [p["label"] for p in worldmap.snapshot(state, settings, None, now)["places"] if p["heard_only"]]
    return "\n".join([f"Lately for {who.name}:" if who else "Lately:", *(lines or ["- (quiet)"]),
                      f"{me.possessive} open wishes: " + ("; ".join(wishes) if wishes else "none"),
                      f"Places {me.name} has only heard of: " + (", ".join(heard) if heard else "none")])


def minds(agents, now: float) -> str:
    """What each agent keeps coming back to: its open wishes and oldest open to-dos, with how long each has been open, and what its
    sleeping self chose to focus on (the night pass). A gap shows here: something wanted for days, a concern the world never answers."""
    out = []
    for who, st in agents:
        wishes = [m["text"] + _open(m["ts"], now) for m in st.memories("wishlist", status="open", limit=8)]
        todos = sorted(st.memories("todo", status="open", limit=50), key=lambda m: m["ts"])[:4]
        focus = [f["text"] for f in st.focus("open", limit=5)]
        out += [f"{who.possessive} open wishes: " + ("; ".join(wishes) or "none"),
                f"{who.possessive} oldest open to-dos: " + ("; ".join(m["text"] + _open(m["ts"], now) for m in todos) or "none"),
                f"What {who.possessive} sleeping self chose to focus on: " + (" / ".join(focus) or "nothing yet")]
    return "\n".join(out)


def produce(state, settings) -> str:
    """What the world can produce, by place: what turns up there or its booths sell (finds, an invented place's own), so a wish nothing
    can answer shows as one."""
    from . import finds, places
    loot, lines = finds.loot(), []
    for key in places.registry(state, settings, None):
        row = state.place_row(key)
        table = loot.get(key) or (row or {}).get("loot") or []
        names = list(dict.fromkeys(e[0] for e in table))[:12]
        if names:
            lines.append(f"- {places.label(key)}: {', '.join(names)}")
    return "\n".join(["What can be had in this world (where, and what turns up or is sold there):", *(lines or ["- (nothing yet)"])])


DRAFT = {"action": {"type": "string", "enum": ["propose", "revise", "nothing"]},
         "module": {"type": "string", "enum": ["rule", "place"], "description": "a rule (default), or rarely a new place"},
         "label": {"type": "string", "description": "a place: its name as people say it"},
         "place_kind": {"type": "string"}, "description": {"type": "string"}, "distance": {"type": "string", "enum": ["near", "far"]},
         "items": {"type": "array", "items": {"type": "string"}}, "setting": {"type": "string"},
         "opens": {"type": "integer"}, "closes": {"type": "integer"},
         "name": {"type": "string", "description": "a short name, lowercase words joined by dashes"},
         "revises": {"type": "string", "description": "with revise: the name of your module this is a new version of"},
         "reason": {"type": "string", "description": "one or two sentences: what it adds and why now (shown to the owner)"},
         "events": {"type": "array", "items": {"type": "string"}, "description": "with on_event: the event kinds it listens for"},
         "code": {"type": "string", "description": "the whole module"}}


async def _draft(state, settings, gm, now: float, agents) -> dict | None:
    each = "\n\n".join(lately(st, settings, now, who if len(agents) > 1 else None) for who, st in agents)
    task = (f"What this world is:\n{bible(settings)}\n\nModules that already exist:\n{catalogue(state)}\n\n{each}\n\n"
            f"What they keep coming back to:\n{minds(agents, now)}\n\n{produce(state, settings)}\n\n"
            f"How a module works:\n{api(state)}\n\nYou may add one small rule module tonight (or, rarely, a new place), revise one of yours (by its name), or add nothing. "
            "Fill a real gap: something the world is missing that fits it, answering to what has been happening; not a copy of what "
            "exists. Look hardest at what someone has wanted for days that nothing in the world can give (see what can be had, above), and "
            "at what someone keeps coming back to that the world never answers: that is a gap worth filling, within what this world is. "
            "When there is no such gap, nothing is a fine answer. Report action, reason, and for propose or revise the name and the code.")
    return await gm.ask(task, DRAFT, ["action", "reason"], "builder", system=SYSTEM, max_tokens=MAX_TOKENS)


async def _fits(state, settings, gm, draft: dict) -> dict | None:
    task = (f"What this world is:\n{bible(settings)}\n\nModules that already exist:\n{catalogue(state)}\n\n"
            f"Proposed: {draft.get('name')}: {draft.get('reason')}\n\n"
            + (f"A new place, {draft.get('label')} ({draft.get('place_kind')}, {draft.get('setting')}): {draft.get('description')}\n\n" if draft.get("module") == "place" else "")
            + f"Code:\n{draft.get('code')}\n\n"
            f"Does this fit the world as described, add something the existing modules don't, and stay quiet enough (rarely speaking to {world_pack.active().agent.name})? "
            "Report fits (true or false) and why, in one sentence.")
    return await gm.ask(task, {"fits": {"type": "boolean"}, "why": {"type": "string"}}, ["fits", "why"], "builder check", system=SYSTEM)


PLACE_FIELDS = ("label", "place_kind", "description", "distance", "items", "setting", "opens", "closes")


async def _fix(gm, draft: dict, problem: str, state=None) -> dict | None:
    place = draft.get("module") == "place"
    fields = "".join(f"{k}: {json.dumps(draft.get(k))}\n" for k in PLACE_FIELDS) if place else ""
    task = (f"How a module works:\n{api(state)}\n\nYour module {draft.get('name')} ({draft.get('reason')}):\n{fields}{draft.get('code')}\n\n"
            f"It didn't work: {problem}\nFix it. Report the whole corrected code" + (", and any of the place's fields you change." if place else "."))
    props = {"code": {"type": "string"}, **({k: DRAFT[k] for k in PLACE_FIELDS} if place else {})}
    return await gm.ask(task, props, ["code"], "builder fix", system=SYSTEM, max_tokens=MAX_TOKENS)


async def _submit(state, settings, runner, draft: dict, code: str, replaces: int | None, now: float) -> dict:
    try:
        man = place_manifest(code, draft) if draft.get("module") == "place" else manifest(code, draft["name"], draft.get("events"))
    except sandbox.Rejected as e:
        return {"error": str(e)}
    return await M.propose(state, settings, runner, "world", man, code, str(draft.get("reason") or "")[:500], replaces=replaces, now=now)


def _done(state, outcome: str, **data) -> dict:
    state.log("builder", outcome=outcome, **data)
    return {"outcome": outcome, **data}


async def night(state, settings, gm, runner, now: float | None = None, agents=None) -> dict | None:
    """The builder's turn, once a night (see the module docstring), seeing every one of `agents` ((identity, State) each; else the one
    acting). Returns what happened, or None if it wasn't its turn."""
    agents = agents or [(world_pack.active().agent, state)]
    now = now or time.time()
    day = datetime.fromtimestamp(now).date().isoformat()
    if settings.module_builder != "on" or runner is None or gm is None or state.meta("builder_day") == day:
        return None
    state.set_meta(builder_day=day)                                  # once a night, whatever happens
    draft = await _draft(state, settings, gm, now, agents)
    if not draft:
        return _done(state, "failed", why="the GM gave no answer")
    if draft["action"] == "nothing" or not draft.get("code"):
        return _done(state, "nothing", why=str(draft.get("reason") or "")[:300])
    old = None
    if draft["action"] == "revise":
        old = next((m for m in reversed(state.modules()) if m["author"] == "world" and m["name"] == str(draft.get("revises") or draft.get("name"))
                    and m["status"] != "replaced"), None)
        if not old:
            return _done(state, "failed", why=f"there is no module of yours called {draft.get('revises') or draft.get('name')!r} to revise")
    draft["name"] = old["name"] if old else name_of(draft.get("name"))
    if not old and any(m["name"] == draft["name"] and m["status"] in ("proposed", "waiting", "live", "disabled") for m in state.modules()):
        return _done(state, "failed", name=draft["name"], why="a module with that name already exists")
    check = await _fits(state, settings, gm, draft)
    if not check or not check["fits"]:
        return _done(state, "dropped", name=draft["name"], why=str((check or {}).get("why") or "the check gave no answer")[:300])
    code = draft["code"]
    r = await _submit(state, settings, runner, draft, code, old["id"] if old else None, now)
    problem = r.get("error") or ("" if r["report"].get("clean") else M.trial_text(r["report"]))
    if problem:
        fixed = await _fix(gm, draft, problem, state)
        if fixed and fixed.get("code"):
            draft.update({k: fixed[k] for k in PLACE_FIELDS if k in fixed and draft.get("module") == "place"})
            replaces = r.get("id") or (old["id"] if old else None)
            r2 = await _submit(state, settings, runner, draft, fixed["code"], replaces, now)
            if "id" in r2 or "id" not in r:
                r = r2
    if "id" not in r:
        return _done(state, "failed", name=draft["name"], why=r["error"][:300])
    return _done(state, "proposed", name=draft["name"], module=r["id"], status=state.module(r["id"])["status"],
                 clean=bool(state.module(r["id"])["report"].get("clean")), revised=bool(old))
