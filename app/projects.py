"""Projects: the engine side. Pip chooses what to work on; this module decides how it went.

A project is a few stages, each needing minutes of work and maybe materials (taken when the stage's first session
starts). A work session runs in real time; when it ends, a dice roll shaped by skill, tools, difficulty and
fatigue decides the result, and the GM only narrates it. See DESIGN-creations.md.
"""
import math
import random
import time

from . import expectations as exp
from .state import name_key
from .text import clip, craft_name
from . import world_pack
from . import stats as stats_mod

STAGE_MINUTES = (15, 240)
SESSION_MINUTES = (15, 120)
MAX_STAGES = 5
MAX_STAGES_REVISED = 8  # discovery can grow a plan past what the GM first saw
MAX_QUESTIONS = 3
MAX_HIDDEN = 3
def abilities() -> tuple:
    """What a stage of work exercises (the pack's content.json `crafting`)."""
    return tuple(world_pack.active().data("content").get("crafting", {}).get("abilities", ()))


def default_abilities() -> list:
    return list(world_pack.active().data("content").get("crafting", {}).get("default_abilities", ()))


def __getattr__(name):            # the old constant names, from the active world
    if name == "ABILITIES":
        return abilities()
    if name == "DEFAULT_ABILITIES":
        return default_abilities()
    raise AttributeError(name)
FAMILIARITY = 0.5  # weight of craft-specific experience next to the transferable abilities
DRY_LIMIT = 2      # dry experiments in a row before the next relevant one is an insight
MAX_MATERIAL_UNITS = 8
CREDIT = {"blowup": 0.0, "setback": 0.0, "slow": 0.5, "good": 1.0, "breakthrough": 1.5}
VERDICTS = ("blowup", "setback", "slow", "good", "breakthrough")  # worst to best; the die allows one step either way
BLOWUP_LOSS = 0.25   # share of the stage's minutes lost when a try blows up
BLOWUP_ENERGY = 0.1
LESSONS_KEPT = 8
QUALITIES = ("rough", "sound", "fine", "masterwork")


def clamp_int(v, lo: int, hi: int, default: int) -> int:
    try:
        return max(lo, min(hi, int(v)))
    except (TypeError, ValueError):
        return default


def sanitize_abilities(raw) -> list[str]:
    names = [str(a).strip().lower() for a in (raw if isinstance(raw, list) else [])]
    out = [a for a in dict.fromkeys(names) if a in abilities()][:2]
    return out or default_abilities()


def sanitize_stages(raw, limit: int, units: int = 0) -> list[dict]:
    """Steps (Pip's, or annotated by the GM) -> engine stages: names, minutes, capped materials, known abilities.
    A bare string is a step with default minutes. Junk is dropped."""
    stages = []
    for st in (raw if isinstance(raw, list) else [])[:limit]:
        if isinstance(st, str):
            st = {"name": st}
        if not isinstance(st, dict) or not str(st.get("name") or "").strip():
            continue
        mats = {}
        for name, qty in (st.get("materials") or {}).items() if isinstance(st.get("materials"), dict) else ():
            qty = clamp_int(qty, 0, MAX_MATERIAL_UNITS - units, 0)
            name = str(name).strip().lower()[:40]
            if qty and name:
                mats[name] = mats.get(name, 0) + qty
                units += qty
        minutes = clamp_int(st.get("minutes"), *STAGE_MINUTES, 60)
        stages.append({"name": str(st["name"]).strip()[:60], "minutes": minutes, "guess": minutes,  # guess = Pip's own
                       "materials": mats, "abilities": sanitize_abilities(st.get("abilities"))})
    return stages


def sanitize_strings(raw, limit: int, size: int = 160) -> list[str]:
    return [clip(x, size) for x in (raw if isinstance(raw, list) else []) if str(x).strip()][:limit]


def annotate(steps: list[dict], notes) -> list[dict]:
    """Merge the GM's per-step notes (same order as Pip's steps) into Pip's own steps: the GM tags abilities and may
    correct a duration, but never renames, adds or removes a step."""
    notes = notes if isinstance(notes, list) else []
    out = []
    for i, st in enumerate(steps):
        n = notes[i] if i < len(notes) and isinstance(notes[i], dict) else {}
        out.append({**st, "abilities": sanitize_abilities(n.get("abilities")),
                    "minutes": clamp_int(n.get("minutes"), *STAGE_MINUTES, st["minutes"])})
    return out


def build_plan(steps: list[dict], review: dict | None) -> dict:
    """A project plan from Pip's steps plus the GM's review (craft, difficulty, tools, what Pip can't know yet)."""
    review = review or {}
    questions = sanitize_strings(review.get("open_questions"), MAX_QUESTIONS)
    hidden = [{"fact": f, "found": False} for f in sanitize_strings(review.get("hidden"), MAX_HIDDEN, 240)] if questions else []
    tools = [str(t).strip().lower()[:40] for t in (review.get("tools") or []) if str(t).strip()][:3]
    return {"craft": craft_name(review.get("craft")), "difficulty": clamp_int(review.get("difficulty"), 1, 5, 2),
            "tools": tools, "stages": annotate(steps, review.get("steps")), "questions": questions, "hidden": hidden}


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
    return stage.get("abilities") or default_abilities()


def skill_for(state, project: dict, abilities: list[str]) -> float:
    """Effective skill: the mean level of the abilities in play, plus some craft-specific familiarity."""
    have = state.abilities()
    base = sum(level(have.get(a, 0)) for a in abilities) / max(1, len(abilities))
    return base + FAMILIARITY * level(state.skills().get(project["craft"], 0))


def grant_xp(state, project: dict, abilities: list[str], minutes: float) -> None:
    state.add_xp(project["craft"], minutes)
    state.add_ability_xp({a: minutes / len(abilities) for a in abilities})


def roll(rng: random.Random, skill_level: int, tools_owned: int, difficulty: int, tired: bool) -> str:
    score = 0.05 * skill_level + 0.05 * min(3, tools_owned) - 0.05 * (difficulty - 1) - (0.15 if tired else 0)
    r = rng.random() + score
    return "setback" if r < 0.15 else "slow" if r < 0.40 else "good" if r < 0.90 else "breakthrough"


def clamp_verdict(rolled: str, verdict) -> str:
    """The GM arbitrates an attempt, but the die bounds it: one step better or worse than the roll, no more."""
    if verdict not in VERDICTS:
        return rolled
    i = VERDICTS.index(rolled)
    return VERDICTS[max(i - 1, min(i + 1, VERDICTS.index(verdict)))]


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


def mentioned_materials(state, stage: dict) -> list[dict]:
    """Materials Pip owns that the stage is plainly about (its name says 'pendulum') but its plan doesn't list.
    They are built into the stage like listed ones. Tools are never used up; whole words only."""
    listed = {name_key(n) for n in stage["materials"]}
    text = f" {name_key(stage['name'])} "
    return [i for i in state.items()
            if i["kind"] == "material" and name_key(i["name"]) not in listed and f" {name_key(i['name'])} " in text]


def tools_owned(state, project: dict) -> int:
    return sum(1 for t in project["tools"] if state.find_item(t, kind="tool")[0])


def fallback_narration(stage: str, result: str) -> str:
    return {"blowup": f"It went badly wrong on {stage}, and you lost ground.",
            "setback": f"Something went wrong on {stage}, and you'll have to redo part of it.",
            "slow": f"Work on {stage} was slow and fiddly, but it moved forward.",
            "good": f"You made steady progress on {stage}.",
            "breakthrough": f"Something clicked on {stage}, and it came together faster than expected."}[result]


def _expectation_fields(c: dict | None, step: dict | None) -> dict:
    """What a session's event records about expectations (empty when Pip predicted nothing)."""
    out = {}
    if c:
        out.update(expected=c["expected"], expectation=c["phrase"], error=c["error"], surprise=c["surprise"])
    if step:
        out.update(step_note=step["phrase"], step_surprise=step["surprise"])
    return out


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
    approach = (sess.get("target") or "").strip()
    lesson, lost = None, []
    if interrupted:
        minutes = min(minutes, max(0.0, now - sess["started_at"]) * settings.work_speed / 60)
        result = "slow"  # cut short: half credit, no dice
    else:
        lvl = skill_for(state, project, stage_abilities(stage))
        result = roll(rng, lvl, tools_owned(state, project), project["difficulty"], stats_mod.tired(state))
    text = None
    if not interrupted:
        mats = list(stage["materials"]) + [i["name"] for i in state.items() if i["kind"] == "tool"]
        earlier = [h["text"] for h in project["history"] if not h.get("interrupted")][-3:]
        if approach and gm:  # the GM arbitrates what Pip tried; the die bounds how far it can go either way
            ruling = await gm.adjudicate(project, stage, approach, result, round(minutes), mats, earlier,
                                         feel(state))
            if ruling:
                result = clamp_verdict(result, ruling.get("verdict"))
                text = clip(ruling.get("text"), 300) if ruling.get("text") else None
                lesson = ruling
    remaining = stage["minutes"] - stage["progress"]
    if result == "blowup":
        stage["progress"] = max(0.0, stage["progress"] - BLOWUP_LOSS * stage["minutes"])
        if (t := stats_mod.tiring(state.s)):
            state.update_agent(**{t: max(0.0, state.agent()[t] - BLOWUP_ENERGY)})
        owned = [state.find_item(n)[0] for n in stage["materials"]]
        owned = [i for i in owned if i and i["kind"] == "material"]
        if owned:
            item = rng.choice(owned)
            state.take_item(item["id"], 1)
            lost.append(item["name"])
    else:
        stage["progress"] += min(remaining, minutes * CREDIT[result])
    finished_stage = stage["progress"] >= stage["minutes"] - 1e-6
    grant_xp(state, project, stage_abilities(stage), minutes)
    comparison = None if interrupted else exp.compare_session(sess.get("expect") or "", result)
    step = None
    if finished_stage:  # how long it really took vs Pip's own guess when it wrote the step
        spent = minutes + sum(h["minutes"] for h in project["history"]
                              if h["stage"] == stage["name"] and h.get("kind") != "experiment")
        step = exp.compare_step(stage.get("guess", stage["minutes"]), spent)
    learned = None
    if lesson:  # trying (and failing) can teach: a lesson, or even a hidden fact
        ch = apply_changes(project, {**lesson, "new_question": None}, reveal=lesson.get("reveal") is not None,
                           may_answer=True)
        learned = ch["finding"]
        project["findings"] = project["findings"][-LESSONS_KEPT:]
    if not interrupted and not text:
        text = await gm.narrate(project["name"], project["goal"], stage["name"], mats, result, round(minutes),
                                finished_stage, earlier) if gm else None
    text = text or fallback_narration(stage["name"], result)
    project["history"].append({"ts": now, "stage": stage["name"], "result": result, "minutes": round(minutes),
                               "text": text, "interrupted": interrupted})
    done = current_stage(project) is None and not project["questions"]
    fields = {"stages": project["stages"], "history": project["history"], "findings": project["findings"],
              "questions": project["questions"], "hidden": project["hidden"]}
    if done:
        fields.update(status="done", finished_at=now)
    state.update_project(project["id"], **fields)
    if state.agent()["activity"] == "working":
        state.update_agent(activity="idle", description=f"just finished working on {project['name']}")
    data = {"project": project["name"], "project_id": project["id"], "stage": stage["name"], "result": result,
            "craft": project["craft"], "abilities": stage_abilities(stage),
            "minutes": round(minutes), "text": text, "finished_stage": finished_stage, "project_done": done,
            "interrupted": interrupted, "percent": percent(project), "approach": approach, "lost": lost,
            "learned": learned, **_expectation_fields(comparison, step), "crossroads": crossroads({**project, "status": "active"}) and not done}
    event_id = state.log("work", **data)
    for c, subject in ((comparison, stage["name"]), (step, stage["name"])):
        if c:
            state.add_expectation(c["kind"], project["id"], project["craft"], subject, c, event_id)
    return data


# --- discovery: experiments and plan revisions ---------------------------------
EXPERIMENT_MINUTES = (20, 90)


def roll_experiment(rng: random.Random, skill_level: float, difficulty: int, tired: bool) -> str:
    score = 0.05 * skill_level - 0.04 * (difficulty - 1) - (0.15 if tired else 0)
    r = rng.random() + score
    return "nothing" if r < 0.30 else "clue" if r < 0.60 else "insight" if r < 0.90 else "surprise"


def apply_changes(project: dict, data: dict, reveal: bool, new_question: bool = False, may_answer: bool = True) -> dict:
    """Apply what the GM found out to `project` (in place): reveal a hidden fact, answer an open question, add a
    new question, nudge difficulty. Never adds or removes steps - the plan is Pip's. Returns what changed."""
    out = {"finding": None, "answered": None, "added": []}
    unfound = [i for i, h in enumerate(project["hidden"]) if not h["found"]]
    finding = clip(data.get("finding"), 240) if data.get("finding") else None
    revealed = False
    if reveal and unfound:
        revealed = True
        i = data.get("reveal")
        i = i if isinstance(i, int) and i in unfound else unfound[0]
        project["hidden"][i]["found"] = True
        finding = finding or project["hidden"][i]["fact"]
    if finding and finding not in project["findings"]:
        project["findings"].append(finding)
        out["finding"] = finding
    # an insight settles a question even when no hidden fact stands behind it (a question a surprise raised has none)
    if may_answer and project["questions"] and (reveal or isinstance(data.get("answers"), int)):
        q = data.get("answers")
        q = q if isinstance(q, int) and 0 <= q < len(project["questions"]) else 0
        out["answered"] = project["questions"].pop(q)
    if not project["questions"] and out["answered"] and current_stage(project) is None:
        # the last unknown is settled and nothing is left to do: a plain final step, which Pip can replace
        fin = {"name": "put it all together", "minutes": 45, "materials": {}, "abilities": ["handiness", "precision"]}
        project["stages"] += new_stages({"stages": [fin]})
        out["added"] = [fin["name"]]
    if new_question and data.get("new_question") and len(project["questions"]) < MAX_QUESTIONS:
        project["questions"].append(clip(data["new_question"], 160))
    delta = data.get("difficulty_delta")
    if isinstance(delta, int) and delta:
        project["difficulty"] = max(1, min(5, project["difficulty"] + max(-1, min(1, delta))))
    return out


def edit_plan(project: dict, steps: list[dict], drop: list) -> tuple[list[str], list[str]]:
    """Pip's own changes to its plan: drop steps it hasn't begun, add new ones after the rest."""
    wanted = {str(n).strip().lower() for n in (drop if isinstance(drop, list) else [])}
    dropped = []
    for st in list(project["stages"]):
        if st["name"].lower() in wanted and not st["started"] and st["progress"] == 0:
            project["stages"].remove(st)
            dropped.append(st["name"])
    room = max(0, MAX_STAGES_REVISED - len(project["stages"]))
    steps = steps[:room]
    project["stages"] += new_stages({"stages": steps})
    return [s["name"] for s in steps], dropped


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
    comparison = None
    relevant, outcome = True, "interrupted"
    text = f"You stopped before the experiment ({hypothesis}) could show anything."
    if not interrupted:
        skill = skill_for(state, project, ["ingenuity", "knowledge"])
        outcome = roll_experiment(rng, skill, project["difficulty"], stats_mod.tired(state))
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
        comparison = exp.compare_experiment(sess.get("expect") or "", outcome)
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
    data = {"project": project["name"], "project_id": project["id"], "craft": project["craft"],
            "hypothesis": hypothesis, "outcome": outcome,
            "relevant": relevant, "minutes": round(minutes), "text": text, "finding": changes["finding"],
            "answered": changes["answered"], "added": changes["added"],
            "interrupted": interrupted, "project_done": done, "percent": percent(project),
            "crossroads": crossroads(project), **_expectation_fields(comparison, None)}
    event_id = state.log("experiment", **data)
    if comparison:
        state.add_expectation("experiment", project["id"], project["craft"], hypothesis, comparison, event_id)
    return data


async def revise(state, gm, project: dict, steps: list[dict], drop: list, because: str) -> tuple[dict, str]:
    """Pip edits its plan (free: it's Pip's plan), and may bring what it learned elsewhere to its open questions
    (the GM judges that, and only after new experience). Returns (changes, message)."""
    claim = bool(because)
    fresh = len(project["history"]) > project["revised_at"]
    note = ""
    if claim and not fresh:
        claim = False
        note = " (what you learned will count once you've worked or experimented again)"
    unknowns = bool(project["questions"] or any(not h["found"] for h in project["hidden"]))
    verdict = None
    if gm and (steps or (claim and unknowns)):
        verdict = await gm.revise(project, steps, because if claim and unknowns else "")
    verdict = verdict or {}
    if steps:
        steps = annotate(steps, verdict.get("steps"))
    added, dropped = edit_plan(project, steps, drop)
    changes = {"finding": None, "answered": None, "added": added, "dropped": dropped}
    msg = clip(verdict.get("text"), 300) if verdict.get("text") else ""
    if claim and unknowns and verdict.get("accepted") is True:
        learned = apply_changes(project, verdict, reveal=verdict.get("reveal") is not None)
        changes.update(finding=learned["finding"], answered=learned["answered"])
        changes["added"] += learned["added"]
        project["revised_at"] = len(project["history"])
    elif claim:
        project["revised_at"] = len(project["history"])
        msg = msg or "that doesn't change what you need to do"
    save_changes(state, project)
    state.log("plan_revised", project=project["name"], project_id=project["id"], because=clip(because, 200), **changes)
    return changes, (msg + note).strip()


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
