"""The builder: the world adding to itself, one small rule at a time (docs/DESIGN-modules.md, "The builder").

Once a night, after Pip's reflection, the GM is shown the world bible (what this world is and isn't), the modules that already exist (and
what the owner said about its own), what happened lately, open wishes and places only heard of, and the module API. It may propose one rule
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
from . import public_view as pv
from . import sandbox

DIR = Path(__file__).parent / "builder"
RULE_PROPOSES = ("state", "publish", "perceive", "log", "schedule", "show", "wake")     # a rule can't offer, consume or change a thing
RULE_READS = tuple(r for r in M.READS if r != "subject")
SYSTEM = "You are the world of a small simulation, adding to yourself carefully. You answer only through the report tool."
RECENT_EVENTS, MAX_TOKENS = 40, 4000


def bible(settings) -> str:
    """What this world is and isn't: the owner's own if they wrote one (WORLD_BIBLE_PATH), else the engine's."""
    own = Path(settings.world_bible_path) if settings.world_bible_path else None
    return (own.read_text() if own and own.is_file() else (DIR / "bible.md").read_text()).strip()


def api(state=None) -> str:
    from . import geometry, place_kinds
    from .looks import SCENE
    return ((DIR / "api.md").read_text().replace("EVENT_KINDS", ", ".join(sorted(pv.EVENT_FIELDS))).replace("ANCHORS", anchor_list())
            .replace("PLACE_KINDS", "; ".join(f"{k.name} ({k.help})" for k in place_kinds.KINDS.values()))
            .replace("SETTINGS", ", ".join(SCENE["setting"])).replace("TEXTURES", ", ".join(geometry.TEXTURES))
            .replace("PARTS", parts_list(state)).strip())


def parts_list(state) -> str:
    """The live parts a layout can use, with their params' defaults and what each is."""
    rows = [m for m in state.modules("live") if m["kind"] == "part"] if state is not None else []
    return "\n".join(f"  {m['name']} (params {m['manifest'].get('params') or {}}): {m['reason']}" for m in rows) or "  (none yet: no place for now)"


def anchor_list() -> str:
    """Every kind of place and the anchors its scene has (type tagged ...), so a module can ask for one that exists."""
    from . import anchors
    by_template = {}
    for kind, template in anchors.TEMPLATE_OF_KIND.items():
        by_template.setdefault(template, []).append(kind)
    lines = []
    for template, kinds in by_template.items():
        spots = "; ".join(dict.fromkeys(f"{a['type']} tagged {', '.join(a['tags'])}" for a in anchors.manifest(template)))
        lines.append(f"  {'/'.join(kinds)}: {spots}")
    return "\n".join(lines)


def manifest(source: str, name: str, events) -> dict:
    """A rule's manifest from its code: the hooks it defines, all a rule may read and do, the events it listens for."""
    tree = sandbox.check(source)
    hooks = [n.name for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in M.HOOKS]
    events = [e for e in (events or []) if isinstance(e, str)]
    return {"name": name, "kind": "rule", "api": M.API, "hooks": hooks, "reads": list(RULE_READS), "proposes": list(RULE_PROPOSES),
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
        who = "you" if m["author"] == "world" else "Pip"
        line = f"- {m['name']} ({m['kind']}{', for ' + m['subject'] if m['subject'] else ''}; by {who}; {m['status']}): {m['reason']}"
        if m["author"] == "world" and m["note"]:
            line += f" The owner said: {m['note']}"
        out.append(line)
    return "\n".join(out)


def lately(state, settings, now: float) -> str:
    """What happened recently, in public terms, plus open wishes and places only heard of."""
    from . import worldmap
    lines = []
    for e in reversed(state.events(limit=300)):
        pub = pv.public_event(e)
        if not pub or e["kind"] in ("tick", "emotion", "module") or e["ts"] < now - 2 * 86400:
            continue
        d = pub["data"]
        text = d.get("text") or d.get("title") or d.get("summary") or d.get("label") or d.get("name") or d.get("crop") or ""
        lines.append(f"- {datetime.fromtimestamp(e['ts']).strftime('%a %H:%M')} {e['kind']}: {str(text)[:140]}")
    lines = lines[-RECENT_EVENTS:]
    wishes = [m["text"] for m in state.memories("wishlist", status="open", limit=8)]
    heard = [p["label"] for p in worldmap.snapshot(state, settings, None, now)["places"] if p["heard_only"]]
    return "\n".join(["Lately:", *(lines or ["- (quiet)"]),
                      "Pip's open wishes: " + ("; ".join(wishes) if wishes else "none"),
                      "Places Pip has only heard of: " + (", ".join(heard) if heard else "none")])


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


async def _draft(state, settings, gm, now: float) -> dict | None:
    task = (f"What this world is:\n{bible(settings)}\n\nModules that already exist:\n{catalogue(state)}\n\n{lately(state, settings, now)}\n\n"
            f"How a module works:\n{api(state)}\n\nYou may add one small rule module tonight (or, rarely, a new place), revise one of yours (by its name), or add nothing. "
            "Fill a real gap: something the world is missing that fits it, answering to what has been happening; not a copy of what "
            "exists. Most nights, nothing is a fine answer. Report action, reason, and for propose or revise the name and the code.")
    return await gm.ask(task, DRAFT, ["action", "reason"], "builder", system=SYSTEM, max_tokens=MAX_TOKENS)


async def _fits(state, settings, gm, draft: dict) -> dict | None:
    task = (f"What this world is:\n{bible(settings)}\n\nModules that already exist:\n{catalogue(state)}\n\n"
            f"Proposed: {draft.get('name')}: {draft.get('reason')}\n\n"
            + (f"A new place, {draft.get('label')} ({draft.get('place_kind')}, {draft.get('setting')}): {draft.get('description')}\n\n" if draft.get("module") == "place" else "")
            + f"Code:\n{draft.get('code')}\n\n"
            "Does this fit the world as described, add something the existing modules don't, and stay quiet enough (rarely speaking to Pip)? "
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


async def night(state, settings, gm, runner, now: float | None = None) -> dict | None:
    """The builder's turn, once a night (see the module docstring). Returns what happened, or None if it wasn't its turn."""
    now = now or time.time()
    day = datetime.fromtimestamp(now).date().isoformat()
    if settings.module_builder != "on" or runner is None or gm is None or state.meta("builder_day") == day:
        return None
    state.set_meta(builder_day=day)                                  # once a night, whatever happens
    draft = await _draft(state, settings, gm, now)
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
