"""Projects: the engine side. Pip chooses what to work on; this module decides how it went.

A project is a few stages, each needing minutes of work and maybe materials (taken when the stage's first session
starts). A work session runs in real time; when it ends, a dice roll shaped by skill, tools, difficulty and
fatigue decides the result, and the GM only narrates it. See DESIGN-creations.md.
"""
import math
import random
import time

STAGE_MINUTES = (15, 240)
SESSION_MINUTES = (15, 120)
MAX_STAGES = 5
MAX_MATERIAL_UNITS = 8
CREDIT = {"setback": 0.0, "slow": 0.5, "good": 1.0, "breakthrough": 1.5}
QUALITIES = ("rough", "sound", "fine", "masterwork")


def clamp_int(v, lo: int, hi: int, default: int) -> int:
    try:
        return max(lo, min(hi, int(v)))
    except (TypeError, ValueError):
        return default


def fallback_plan() -> dict:
    return {"craft": "tinkering", "difficulty": 2, "tools": [], "stages": [
        {"name": "gather and shape the pieces", "minutes": 45, "materials": {}},
        {"name": "put it together", "minutes": 60, "materials": {}},
        {"name": "finish and test", "minutes": 45, "materials": {}},
    ]}


def sanitize_plan(raw: dict | None) -> dict:
    """Turn a GM plan into something the engine trusts (or the fallback if it's unusable)."""
    if not raw or not isinstance(raw.get("stages"), list):
        return fallback_plan()
    stages, units = [], 0
    for st in raw["stages"][:MAX_STAGES]:
        if not isinstance(st, dict) or not str(st.get("name") or "").strip():
            continue
        mats = {}
        for name, qty in (st.get("materials") or {}).items() if isinstance(st.get("materials"), dict) else ():
            qty = clamp_int(qty, 0, MAX_MATERIAL_UNITS - units, 0)
            name = str(name).strip().lower()[:40]
            if qty and name:
                mats[name] = mats.get(name, 0) + qty
                units += qty
        stages.append({"name": str(st["name"]).strip()[:60],
                       "minutes": clamp_int(st.get("minutes"), *STAGE_MINUTES, 60), "materials": mats})
    if not stages:
        return fallback_plan()
    tools = [str(t).strip().lower()[:40] for t in (raw.get("tools") or []) if str(t).strip()][:3]
    craft = str(raw.get("craft") or "tinkering").strip().lower()[:30] or "tinkering"
    return {"craft": craft, "difficulty": clamp_int(raw.get("difficulty"), 1, 5, 2), "tools": tools, "stages": stages}


def new_stages(plan: dict) -> list[dict]:
    return [{**s, "progress": 0.0, "started": False} for s in plan["stages"]]


def current_stage(project: dict) -> int | None:
    for i, s in enumerate(project["stages"]):
        if s["progress"] < s["minutes"] - 1e-6:
            return i
    return None


def percent(project: dict) -> int:
    total = sum(s["minutes"] for s in project["stages"])
    done = sum(min(s["progress"], s["minutes"]) for s in project["stages"])
    return int(100 * done / total) if total else 100


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
    if not sess:
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
        lvl = level(state.skills().get(project["craft"], 0))
        result = roll(rng, lvl, tools_owned(state, project), project["difficulty"], state.agent()["energy"])
    remaining = stage["minutes"] - stage["progress"]
    stage["progress"] += min(remaining, minutes * CREDIT[result])
    finished_stage = stage["progress"] >= stage["minutes"] - 1e-6
    state.add_xp(project["craft"], minutes)
    text = None
    if not interrupted:
        mats = list(stage["materials"]) + [i["name"] for i in state.items() if i["kind"] == "tool"]
        earlier = [h["text"] for h in project["history"] if not h.get("interrupted")][-3:]
        text = await gm.narrate(project["name"], project["goal"], stage["name"], mats, result, round(minutes),
                                finished_stage, earlier) if gm else None
    text = text or fallback_narration(stage["name"], result)
    project["history"].append({"ts": now, "stage": stage["name"], "result": result, "minutes": round(minutes),
                               "text": text, "interrupted": interrupted})
    done = current_stage(project) is None
    fields = {"stages": project["stages"], "history": project["history"]}
    if done:
        fields.update(status="done", finished_at=now)
    state.update_project(project["id"], **fields)
    if state.agent()["activity"] == "working":
        state.update_agent(activity="idle", description=f"just finished working on {project['name']}")
    data = {"project": project["name"], "project_id": project["id"], "stage": stage["name"], "result": result,
            "minutes": round(minutes), "text": text, "finished_stage": finished_stage, "project_done": done,
            "interrupted": interrupted, "percent": percent(project)}
    state.log("work", **data)
    return data
