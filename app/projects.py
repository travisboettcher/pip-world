"""Projects: the engine side. Pip chooses what to work on; this module decides how it went.

A project is a few stages, each needing minutes of work and maybe materials (taken when the stage's first session
starts). A work session runs in real time; when it ends, a dice roll shaped by skill, tools, difficulty and
fatigue decides the result, and the GM only narrates it. See DESIGN-creations.md.
"""
import math
import random
import time

from .text import clip, craft_name

STAGE_MINUTES = (15, 240)
SESSION_MINUTES = (15, 120)
MAX_STAGES = 5
MAX_STAGES_REVISED = 8  # discovery can grow a plan past what the GM first saw
MAX_QUESTIONS = 3
MAX_HIDDEN = 3
ABILITIES = ("precision", "patience", "ingenuity", "knowledge", "handiness")
DEFAULT_ABILITIES = ["handiness"]
FAMILIARITY = 0.5  # weight of craft-specific experience next to the transferable abilities
DRY_LIMIT = 2      # dry experiments in a row before the next relevant one is an insight
MAX_MATERIAL_UNITS = 8
CREDIT = {"setback": 0.0, "slow": 0.5, "good": 1.0, "breakthrough": 1.5}
QUALITIES = ("rough", "sound", "fine", "masterwork")


def clamp_int(v, lo: int, hi: int, default: int) -> int:
    try:
        return max(lo, min(hi, int(v)))
    except (TypeError, ValueError):
        return default


def fallback_plan() -> dict:
    return {"craft": "tinkering", "difficulty": 2, "tools": [], "questions": [], "hidden": [], "stages": [
        {"name": "gather and shape the pieces", "minutes": 45, "materials": {}, "abilities": ["handiness"]},
        {"name": "put it together", "minutes": 60, "materials": {}, "abilities": ["handiness", "precision"]},
        {"name": "finish and test", "minutes": 45, "materials": {}, "abilities": ["precision"]},
    ]}


def sanitize_abilities(raw) -> list[str]:
    names = [str(a).strip().lower() for a in (raw if isinstance(raw, list) else [])]
    out = [a for a in dict.fromkeys(names) if a in ABILITIES][:2]
    return out or list(DEFAULT_ABILITIES)


def sanitize_stages(raw, limit: int, units: int = 0) -> list[dict]:
    """GM stages -> engine stages (names, minutes, capped materials, known abilities); junk is dropped."""
    stages = []
    for st in (raw if isinstance(raw, list) else [])[:limit]:
        if not isinstance(st, dict) or not str(st.get("name") or "").strip():
            continue
        mats = {}
        for name, qty in (st.get("materials") or {}).items() if isinstance(st.get("materials"), dict) else ():
            qty = clamp_int(qty, 0, MAX_MATERIAL_UNITS - units, 0)
            name = str(name).strip().lower()[:40]
            if qty and name:
                mats[name] = mats.get(name, 0) + qty
                units += qty
        stages.append({"name": str(st["name"]).strip()[:60], "minutes": clamp_int(st.get("minutes"), *STAGE_MINUTES, 60),
                       "materials": mats, "abilities": sanitize_abilities(st.get("abilities"))})
    return stages


def sanitize_strings(raw, limit: int, size: int = 160) -> list[str]:
    return [clip(x, size) for x in (raw if isinstance(raw, list) else []) if str(x).strip()][:limit]


def sanitize_plan(raw: dict | None) -> dict:
    """Turn a GM plan into something the engine trusts (or the fallback if it's unusable)."""
    if not raw or not isinstance(raw.get("stages"), list):
        return fallback_plan()
    stages = sanitize_stages(raw["stages"], MAX_STAGES)
    if not stages:
        return fallback_plan()
    tools = [str(t).strip().lower()[:40] for t in (raw.get("tools") or []) if str(t).strip()][:3]
    craft = craft_name(raw.get("craft"))
    questions = sanitize_strings(raw.get("open_questions"), MAX_QUESTIONS)
    hidden = [{"fact": f, "found": False} for f in sanitize_strings(raw.get("hidden"), MAX_HIDDEN, 240)] if questions else []
    return {"craft": craft, "difficulty": clamp_int(raw.get("difficulty"), 1, 5, 2), "tools": tools, "stages": stages,
            "questions": questions, "hidden": hidden}


def new_stages(plan: dict) -> list[dict]:
    return [{**s, "progress": 0.0, "started": False} for s in plan["stages"]]


def current_stage(project: dict) -> int | None:
    for i, s in enumerate(project["stages"]):
        if s["progress"] < s["minutes"] - 1e-6:
            return i
    return None


def crossroads(project: dict) -> bool:
    """Everything Pip knows to do is done, but open questions remain: it has to find the way forward."""
    return project["status"] == "active" and current_stage(project) is None and bool(project["questions"])


def percent(project: dict) -> int:
    total = sum(s["minutes"] for s in project["stages"])
    done = sum(min(s["progress"], s["minutes"]) for s in project["stages"])
    pct = int(100 * done / total) if total else 100
    return min(pct, 99) if project["questions"] else pct


def upcoming_needs(project: dict, from_stage: int) -> dict[str, int]:
    """Materials still to be taken by stages from `from_stage` on."""
    out: dict[str, int] = {}
    for st in project["stages"][from_stage:]:
        if not st["started"]:
            for n, q in st["materials"].items():
                out[n] = out.get(n, 0) + q
    return out


def level(xp: float) -> int:
    return min(5, int(math.sqrt(max(0.0, xp) / 60)))


def stage_abilities(stage: dict) -> list[str]:
    return stage.get("abilities") or list(DEFAULT_ABILITIES)


def skill_for(state, project: dict, abilities: list[str]) -> float:
    """Effective skill: the mean level of the abilities in play, plus some craft-specific familiarity."""
    have = state.abilities()
    base = sum(level(have.get(a, 0)) for a in abilities) / max(1, len(abilities))
    return base + FAMILIARITY * level(state.skills().get(project["craft"], 0))


def grant_xp(state, project: dict, abilities: list[str], minutes: float) -> None:
    state.add_xp(project["craft"], minutes)
    state.add_ability_xp({a: minutes / len(abilities) for a in abilities})


def roll(rng: random.Random, skill_level: int, tools_owned: int, difficulty: int, energy: float) -> str:
    score = 0.05 * skill_level + 0.05 * min(3, tools_owned) - 0.05 * (difficulty - 1) - (0.15 if energy < 0.3 else 0)
    r = rng.random() + score
    return "setback" if r < 0.15 else "slow" if r < 0.40 else "good" if r < 0.90 else "breakthrough"


def quality(project: dict, skill_level: int) -> str:
    results = [h["result"] for h in project["history"]]
    pts = results.count("breakthrough") - results.count("setback") + skill_level / 2
    return QUALITIES[0 if pts < 0 else 1 if pts < 1.5 else 2 if pts < 3 else 3]


def scars(project: dict) -> list[str]:
    return [h["text"] for h in project["history"] if h["result"] == "setback" and h.get("text")]


# --- state-touching helpers -------------------------------------------------
def missing_materials(state, stage: dict) -> tuple[list[tuple[dict, int]], list[str]]:
    """(items to take, problems) for starting a stage."""
    take, problems = [], []
    for name, qty in stage["materials"].items():
        item, _ = state.find_item(name)
        if item and item["kind"] in ("material", "tool") and item["qty"] >= qty:
            take.append((item, qty))
        else:
            have = item["qty"] if item and item["kind"] in ("material", "tool") else 0
            problems.append(f"{qty} {name} (you have {have})")
    return take, problems


def tools_owned(state, project: dict) -> int:
    return sum(1 for t in project["tools"] if state.find_item(t, kind="tool")[0])


def fallback_narration(stage: str, result: str) -> str:
    return {"setback": f"Something went wrong on {stage}, and you'll have to redo part of it.",
            "slow": f"Work on {stage} was slow and fiddly, but it moved forward.",
            "good": f"You made steady progress on {stage}.",
            "breakthrough": f"Something clicked on {stage}, and it came together faster than expected."}[result]


async def resolve_session(state, settings, gm, rng: random.Random, now: float | None = None,
                          interrupted: bool = False) -> dict | None:
    """Finish the current work session (on time, or cut short). Returns the logged `work` event data."""
    sess = state.session()
    if not sess or sess["kind"] != "work":
        return None
    now = now or time.time()
    state.end_session()
    project = state.project(sess["project_id"])
    if not project or project["status"] != "active":
        return None
    stage = project["stages"][sess["stage"]]
    minutes = sess["minutes"]
    if interrupted:
        minutes = min(minutes, max(0.0, now - sess["started_at"]) * settings.work_speed / 60)
        result = "slow"  # cut short: half credit, no dice
    else:
        lvl = skill_for(state, project, stage_abilities(stage))
        result = roll(rng, lvl, tools_owned(state, project), project["difficulty"], state.agent()["energy"])
    remaining = stage["minutes"] - stage["progress"]
    stage["progress"] += min(remaining, minutes * CREDIT[result])
    finished_stage = stage["progress"] >= stage["minutes"] - 1e-6
    grant_xp(state, project, stage_abilities(stage), minutes)
    text = None
    if not interrupted:
        mats = list(stage["materials"]) + [i["name"] for i in state.items() if i["kind"] == "tool"]
        earlier = [h["text"] for h in project["history"] if not h.get("interrupted")][-3:]
        text = await gm.narrate(project["name"], project["goal"], stage["name"], mats, result, round(minutes),
                                finished_stage, earlier) if gm else None
    text = text or fallback_narration(stage["name"], result)
    project["history"].append({"ts": now, "stage": stage["name"], "result": result, "minutes": round(minutes),
                               "text": text, "interrupted": interrupted})
    done = current_stage(project) is None and not project["questions"]
    fields = {"stages": project["stages"], "history": project["history"]}
    if done:
        fields.update(status="done", finished_at=now)
    state.update_project(project["id"], **fields)
    if state.agent()["activity"] == "working":
        state.update_agent(activity="idle", description=f"just finished working on {project['name']}")
    data = {"project": project["name"], "project_id": project["id"], "stage": stage["name"], "result": result,
            "minutes": round(minutes), "text": text, "finished_stage": finished_stage, "project_done": done,
            "interrupted": interrupted, "percent": percent(project),
            "crossroads": crossroads({**project, "status": "active"}) and not done}
    state.log("work", **data)
    return data


# --- discovery: experiments and plan revisions ---------------------------------
EXPERIMENT_MINUTES = (20, 90)


def roll_experiment(rng: random.Random, skill_level: float, difficulty: int, energy: float) -> str:
    score = 0.05 * skill_level - 0.04 * (difficulty - 1) - (0.15 if energy < 0.3 else 0)
    r = rng.random() + score
    return "nothing" if r < 0.30 else "clue" if r < 0.60 else "insight" if r < 0.90 else "surprise"


def apply_changes(project: dict, data: dict, reveal: bool, new_question: bool = False, max_new: int = 2,
                  may_answer: bool = True) -> dict:
    """Apply a validated GM proposal to `project` (in place): reveal a hidden fact, answer a question, add or
    drop unstarted stages, nudge difficulty. Returns what changed. The GM proposes; this decides what's allowed."""
    out = {"finding": None, "answered": None, "added": [], "dropped": []}
    unfound = [i for i, h in enumerate(project["hidden"]) if not h["found"]]
    finding = clip(data.get("finding"), 240) if data.get("finding") else None
    revealed = False
    if reveal and unfound:
        revealed = True
        i = data.get("reveal")
        i = i if isinstance(i, int) and i in unfound else unfound[0]
        project["hidden"][i]["found"] = True
        finding = finding or project["hidden"][i]["fact"]
    if finding:
        project["findings"].append(finding)
        out["finding"] = finding
    if may_answer and project["questions"] and (revealed or data.get("answers") is not None):
        q = data.get("answers")
        q = q if isinstance(q, int) and 0 <= q < len(project["questions"]) else 0
        out["answered"] = project["questions"].pop(q)
    room = max(0, min(max_new, MAX_STAGES_REVISED - len(project["stages"])))
    added = sanitize_stages(data.get("new_stages"), room)
    drop = {str(n).strip().lower() for n in (data.get("drop") if isinstance(data.get("drop"), list) else [])}
    for st in list(project["stages"]):
        if st["name"].lower() in drop and not st["started"] and st["progress"] == 0:
            project["stages"].remove(st)
            out["dropped"].append(st["name"])
    if not added and out["answered"] and not project["questions"] and current_stage(project) is None:
        added = [{"name": "put it all together", "minutes": 45, "materials": {}, "abilities": ["handiness", "precision"]}]
    project["stages"] += new_stages({"stages": added})
    out["added"] = [s["name"] for s in added]
    if new_question and data.get("new_question") and len(project["questions"]) < MAX_QUESTIONS:
        project["questions"].append(clip(data["new_question"], 160))
    delta = data.get("difficulty_delta")
    if isinstance(delta, int) and delta:
        project["difficulty"] = max(1, min(5, project["difficulty"] + max(-1, min(1, delta))))
    return out


def save_changes(state, project: dict) -> None:
    state.update_project(project["id"], stages=project["stages"], questions=project["questions"],
                         hidden=project["hidden"], findings=project["findings"], history=project["history"],
                         difficulty=project["difficulty"], dry=project["dry"], revised_at=project["revised_at"])


async def resolve_experiment(state, settings, gm, rng: random.Random, now: float | None = None,
                             interrupted: bool = False) -> dict | None:
    """Finish the current experiment. The engine rolls the outcome; the GM judges relevance and describes it."""
    sess = state.session()
    if not sess or sess["kind"] != "experiment":
        return None
    now = now or time.time()
    state.end_session()
    project = state.project(sess["project_id"])
    if not project or project["status"] != "active":
        return None
    hypothesis = sess["target"]
    minutes = sess["minutes"]
    if interrupted:
        minutes = min(minutes, max(0.0, now - sess["started_at"]) * settings.work_speed / 60)
    grant_xp(state, project, ["ingenuity", "knowledge"], minutes)
    changes = {"finding": None, "answered": None, "added": [], "dropped": []}
    relevant, outcome = True, "interrupted"
    text = f"You stopped before the experiment ({hypothesis}) could show anything."
    if not interrupted:
        skill = skill_for(state, project, ["ingenuity", "knowledge"])
        outcome = roll_experiment(rng, skill, project["difficulty"], state.agent()["energy"])
        if project["dry"] >= DRY_LIMIT and outcome in ("nothing", "clue"):
            outcome = "insight"  # pity: a project can't be stuck forever
        found = [h for h in project["hidden"] if h["found"]]
        verdict = await gm.experiment(project, hypothesis, outcome, [h["fact"] for h in project["hidden"] if not h["found"]],
                                      [h["fact"] for h in found]) if gm else None
        verdict = verdict or {}
        relevant = verdict.get("relevant") is not False
        text = clip(verdict.get("text"), 400) if verdict.get("text") else (
            f"You tried it: {hypothesis}. " + {"nothing": "Nothing came of it.", "clue": "It hinted at something, no more.",
                                              "insight": "Something fell into place.",
                                              "surprise": "It did something you didn't expect."}[outcome])
        if not relevant:
            outcome = "nothing"
        changes = apply_changes(project, verdict if relevant else {}, reveal=outcome in ("insight", "surprise"),
                                new_question=outcome == "surprise", may_answer=outcome in ("insight", "surprise"))
        if relevant:
            project["dry"] = 0 if outcome in ("insight", "surprise") else project["dry"] + 1
    project["history"].append({"ts": now, "stage": f"experiment: {hypothesis}"[:80], "result": outcome,
                               "minutes": round(minutes), "text": text, "interrupted": interrupted, "kind": "experiment"})
    save_changes(state, project)
    if state.agent()["activity"] == "working":
        state.update_agent(activity="idle", description=f"just ran an experiment on {project['name']}")
    done = current_stage(project) is None and not project["questions"] and bool(project["stages"])
    if done:
        state.update_project(project["id"], status="done", finished_at=now)
    data = {"project": project["name"], "project_id": project["id"], "hypothesis": hypothesis, "outcome": outcome,
            "relevant": relevant, "minutes": round(minutes), "text": text, "finding": changes["finding"],
            "answered": changes["answered"], "added": changes["added"], "dropped": changes["dropped"],
            "interrupted": interrupted, "project_done": done, "percent": percent(project),
            "crossroads": crossroads(project)}
    state.log("experiment", **data)
    return data


async def revise(state, gm, project: dict, because: str) -> tuple[dict | None, str]:
    """Pip brings something it learned elsewhere to its plan. Returns (changes, message)."""
    if len(project["history"]) <= project["revised_at"]:
        return None, "do some work or run an experiment first; then you'll know what to change"
    verdict = await gm.revise(project, because, [h["fact"] for h in project["hidden"] if not h["found"]]) if gm else None
    if not verdict or verdict.get("accepted") is not True:
        reason = clip((verdict or {}).get("text") or "that doesn't change what you need to do", 300)
        project["revised_at"] = len(project["history"])
        save_changes(state, project)
        return None, reason
    changes = apply_changes(project, verdict, reveal=bool(verdict.get("reveal") is not None), max_new=2)
    project["revised_at"] = len(project["history"])
    save_changes(state, project)
    state.log("plan_revised", project=project["name"], project_id=project["id"], because=clip(because, 200), **changes)
    return changes, clip(verdict.get("text") or "you adjust the plan", 300)


# --- how abilities feel (Pip never sees numbers) -------------------------------
FEELINGS = {
    "precision": ("a little careful", "careful", "steady-handed", "exacting", "unerringly exact"),
    "patience": ("learning to wait", "patient", "very patient", "unhurried, even in fiddly work", "endlessly patient"),
    "ingenuity": ("starting to improvise", "inventive", "quick to find another way", "resourceful", "brilliantly inventive"),
    "knowledge": ("curious about how things work", "reasonably well-read", "well-informed", "deeply knowledgeable", "learned"),
    "handiness": ("getting used to your tools", "handy", "capable with your hands", "skilled", "a true craftsman"),
}
FAMILIAR = ("new to", "getting the hang of", "comfortable with", "skilled at", "very good at", "a master of")


def feel(state) -> list[str]:
    """Abilities and crafts in words, not numbers."""
    out = []
    abilities = [(a, level(xp)) for a, xp in state.abilities().items() if a in FEELINGS and level(xp) >= 1]
    if abilities:
        out.append("How you've grown: " + "; ".join(f"{FEELINGS[a][lv - 1]} ({a})" for a, lv in abilities))
    crafts = [f"{FAMILIAR[level(xp)]} {c}" for c, xp in state.skills().items() if level(xp) >= 1]
    if crafts:
        out.append("Your experience: " + ", ".join(crafts))
    return out
