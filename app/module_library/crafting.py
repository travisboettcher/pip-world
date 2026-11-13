# Crafting (docs/DESIGN-world-packs.md, phase 5f): the agent's projects. A project is a few stages of its own plan, each needing minutes of
# work and maybe materials (taken when the stage's first session starts). A work session runs in real time; when it ends a die shaped by
# skill, tools, difficulty and tiredness decides how it went, the narrator (the engine's `narrator` source) judges what the agent tried and
# tells it, and at the end the narrator designs what it turned out to be, which the engine makes real (`creation`). Experiments find out
# what the agent couldn't know; plans are the agent's to revise. Projects and craft skills live in this module's store; what happens is
# logged as the engine's own `work`, `experiment` and `plan_revised` events, so memory, firsts and feelings read it as before.
import math
import random

STAGE_MINUTES, SESSION_MINUTES, EXPERIMENT_MINUTES = (15, 240), (15, 120), (20, 90)
MAX_STAGES, MAX_STAGES_REVISED, MAX_QUESTIONS, MAX_HIDDEN = 5, 8, 3, 3
FAMILIARITY = 0.5            # weight of craft-specific experience next to the transferable abilities
DRY_LIMIT = 2                # dry experiments in a row before the next relevant one is an insight
MAX_MATERIAL_UNITS = 8
CREDIT = {"blowup": 0.0, "setback": 0.0, "slow": 0.5, "good": 1.0, "breakthrough": 1.5}
VERDICTS = ("blowup", "setback", "slow", "good", "breakthrough")   # worst to best; the die allows one step either way
BLOWUP_LOSS, BLOWUP_ENERGY = 0.25, 0.1
LESSONS_KEPT, FINISHED_KEPT, HISTORY_KEPT = 8, 30, 4
QUALITIES = ("rough", "sound", "fine", "masterwork")
EXPERIMENT_ABILITIES = ["ingenuity", "knowledge"]
FINAL_STEP = {"name": "put it all together", "minutes": 45, "materials": {}, "abilities": ["handiness", "precision"]}
FEELINGS = {
    "precision": ("a little careful", "careful", "steady-handed", "exacting", "unerringly exact"),
    "patience": ("learning to wait", "patient", "very patient", "unhurried, even in fiddly work", "endlessly patient"),
    "ingenuity": ("starting to improvise", "inventive", "quick to find another way", "resourceful", "brilliantly inventive"),
    "knowledge": ("curious about how things work", "reasonably well-read", "well-informed", "deeply knowledgeable", "learned"),
    "handiness": ("getting used to your tools", "handy", "capable with your hands", "skilled", "a true craftsman"),
}
FAMILIAR = ("new to", "getting the hang of", "comfortable with", "skilled at", "very good at", "a master of")
# what the agent said it expected, against how it went (its sense of its own judgement: the engine's expectations)
SESSION_EXPECT = {"well": 3, "slowly": 2, "badly": 1}
SESSION_SCALE = {"blowup": 0, "setback": 1, "slow": 2, "good": 3, "breakthrough": 4}
SESSION_WORDS = {"blowup": "very badly - it blew up", "setback": "badly - a setback", "slow": "slowly", "good": "well", "breakthrough": "unusually well"}
EXPERIMENT_SCALE = {"nothing": 0, "clue": 1, "insight": 2, "surprise": 2}
EXPERIMENT_EXPECT = {"fails": 0, "partly": 1, "works": 2}
EXPERIMENT_EXPECT_PHRASE = {"fails": "to fail", "partly": "to partly work", "works": "to work"}
EXPERIMENT_WORDS = {"nothing": "it failed", "clue": "it partly worked", "insight": "it worked", "surprise": "it worked, with something unexpected"}
STEP_LONGER, STEP_SHORTER = 1.8, 0.5
STEP = {"type": "object", "properties": {"abilities": {"type": "array", "items": {"type": "string"}}, "minutes": {"type": "integer"}}}
CHANGES = {"finding": {"type": "string"}, "reveal": {"type": "integer"}, "answers": {"type": "integer"}}


# --- small things ----------------------------------------------------------------------------------------------------------------------
def clip(text, limit):
    text = " ".join(str(text or "").split())
    if len(text) <= limit:
        return text
    cut = text[:limit]
    end = max(cut.rfind(". "), cut.rfind("! "), cut.rfind("? "), cut.rfind("* "))
    return cut[:end + 1] if end > limit // 3 else cut.rsplit(" ", 1)[0] + "..."


def clamp_int(v, lo, hi, default):
    try:
        return max(lo, min(hi, int(v)))
    except (TypeError, ValueError):
        return default


def singular(word):
    if word.endswith("ies") and len(word) > 4:
        return word[:-3] + "y"
    if word.endswith("oes") and len(word) > 4:
        return word[:-2]
    if word.endswith("s") and not word.endswith("ss") and len(word) > 3:
        return word[:-1]
    return word


def name_key(name):
    return " ".join(singular(w) for w in str(name).lower().split())


def craft_name(raw):
    """'Clockmaking (gear train, escapement)' -> 'clockmaking': the core craft, so experience carries across projects (and a skill's key in
    the store: letters, digits and spaces)."""
    text = " ".join(str(raw or "").lower().split())
    for sep in ("(", ",", ";", "/", " - ", ":"):
        text = text.split(sep)[0]
    words = "".join(c if c.isalnum() and c.isascii() else " " for c in text).split()[:3]
    while words and words[-1] in ("and", "or", "of", "with", "the", "for"):
        words.pop()
    return " ".join(words)[:30] or "tinkering"


def level(xp):
    return min(5, int(math.sqrt(max(0.0, xp) / 60)))


def direction(err):
    return "better" if err > 0 else "worse" if err < 0 else None


def compare_session(expect, verdict):
    if expect not in SESSION_EXPECT or verdict not in SESSION_SCALE:
        return None
    err = SESSION_SCALE[verdict] - SESSION_EXPECT[expect]
    return {"kind": "session", "expected": expect, "actual": SESSION_WORDS[verdict], "error": err,
            "surprise": direction(err) if abs(err) >= 2 else None, "phrase": "you expected it to go " + expect + "; it went " + SESSION_WORDS[verdict]}


def compare_experiment(expect, outcome):
    if expect not in EXPERIMENT_EXPECT or outcome not in EXPERIMENT_SCALE:
        return None
    err = EXPERIMENT_SCALE[outcome] - EXPERIMENT_EXPECT[expect]
    return {"kind": "experiment", "expected": expect, "actual": EXPERIMENT_WORDS[outcome], "error": err,
            "surprise": direction(err) if abs(err) == 2 else None,
            "phrase": "you expected it " + EXPERIMENT_EXPECT_PHRASE[expect] + "; " + EXPERIMENT_WORDS[outcome]}


def compare_step(guess, actual):
    if not guess or guess <= 0 or actual <= 0:
        return None
    ratio = actual / guess
    surprise = "longer" if ratio >= STEP_LONGER else "shorter" if ratio <= STEP_SHORTER else None
    return {"kind": "step", "expected": str(round(guess)) + " min", "actual": str(round(actual)) + " min", "error": round(ratio, 2),
            "surprise": surprise, "phrase": "you guessed " + str(round(guess)) + " minutes; it took " + str(round(actual))}


def expectation_fields(c, step):
    out = {}
    if c:
        out.update(expected=c["expected"], expectation=c["phrase"], error=c["error"], surprise=c["surprise"])
    if step:
        out.update(step_note=step["phrase"], step_surprise=step["surprise"])
    return out


def settled(c, subject):
    return {k: c[k] for k in ("kind", "expected", "actual", "error", "surprise", "phrase")} | {"subject": subject[:200]}


# --- plans --------------------------------------------------------------------------------------------------------------------------
def known_abilities(ctx):
    return list(ctx["params"]["abilities"])


def sanitize_abilities(ctx, raw):
    names = [str(a).strip().lower() for a in (raw if isinstance(raw, list) else [])]
    out = [a for a in dict.fromkeys(names) if a in known_abilities(ctx)][:2]
    return out or list(ctx["params"]["default_abilities"])


def sanitize_stages(ctx, raw, limit, units=0):
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
        minutes = clamp_int(st.get("minutes"), STAGE_MINUTES[0], STAGE_MINUTES[1], 60)
        stages.append({"name": str(st["name"]).strip()[:60], "minutes": minutes, "guess": minutes, "materials": mats,
                       "abilities": sanitize_abilities(ctx, st.get("abilities"))})
    return stages


def strings(raw, limit, size=160):
    return [clip(x, size) for x in (raw if isinstance(raw, list) else []) if str(x).strip()][:limit]


def annotate(ctx, steps, notes):
    """The narrator's per-step notes merged into the agent's own steps: abilities tagged, a badly-off duration corrected; never renamed."""
    notes = notes if isinstance(notes, list) else []
    out = []
    for i, st in enumerate(steps):
        n = notes[i] if i < len(notes) and isinstance(notes[i], dict) else {}
        out.append({**st, "abilities": sanitize_abilities(ctx, n.get("abilities")),
                    "minutes": clamp_int(n.get("minutes"), STAGE_MINUTES[0], STAGE_MINUTES[1], st["minutes"])})
    return out


def build_plan(ctx, steps, review):
    review = review or {}
    questions = strings(review.get("open_questions"), MAX_QUESTIONS)
    hidden = [{"fact": f, "found": False} for f in strings(review.get("hidden"), MAX_HIDDEN, 240)] if questions else []
    tools = [str(t).strip().lower()[:40] for t in (review.get("tools") or []) if str(t).strip()][:3]
    return {"craft": craft_name(review.get("craft")), "difficulty": clamp_int(review.get("difficulty"), 1, 5, 2), "tools": tools,
            "stages": annotate(ctx, steps, review.get("steps")), "questions": questions, "hidden": hidden}


def new_stages(stages):
    return [{**s, "progress": 0.0, "started": False} for s in stages]


def current_stage(p):
    for i, s in enumerate(p["stages"]):
        if s["progress"] < s["minutes"] - 1e-6:
            return i
    return None


def crossroads(p):
    return p["status"] == "active" and current_stage(p) is None and bool(p["questions"])


def percent(p):
    total = sum(s["minutes"] for s in p["stages"])
    done = sum(min(s["progress"], s["minutes"]) for s in p["stages"])
    pct = int(100 * done / total) if total else 100
    return min(pct, 99) if p["questions"] else pct


def upcoming_needs(p, from_stage):
    out = {}
    for st in p["stages"][from_stage:]:
        if not st["started"]:
            for n, q in st["materials"].items():
                out[n] = out.get(n, 0) + q
    return out


def stage_abilities(ctx, stage):
    return stage.get("abilities") or list(ctx["params"]["default_abilities"])


def skill_for(ctx, p, abilities):
    have = ctx["abilities"]
    base = sum(have.get(a, 0) for a in abilities) / max(1, len(abilities))
    return base + FAMILIARITY * level(skills(ctx).get(p["craft"], 0))


def roll(rng, skill_level, tools_owned, difficulty, tired):
    score = 0.05 * skill_level + 0.05 * min(3, tools_owned) - 0.05 * (difficulty - 1) - (0.15 if tired else 0)
    r = rng.random() + score
    return "setback" if r < 0.15 else "slow" if r < 0.40 else "good" if r < 0.90 else "breakthrough"


def roll_experiment(rng, skill_level, difficulty, tired):
    score = 0.05 * skill_level - 0.04 * (difficulty - 1) - (0.15 if tired else 0)
    r = rng.random() + score
    return "nothing" if r < 0.30 else "clue" if r < 0.60 else "insight" if r < 0.90 else "surprise"


def clamp_verdict(rolled, verdict):
    if verdict not in VERDICTS:
        return rolled
    i = VERDICTS.index(rolled)
    return VERDICTS[max(i - 1, min(i + 1, VERDICTS.index(verdict)))]


def quality(p, skill_level):
    results = [h["result"] for h in p["history"]]
    pts = results.count("breakthrough") - results.count("setback") + skill_level / 2
    return QUALITIES[0 if pts < 0 else 1 if pts < 1.5 else 2 if pts < 3 else 3]


def scars(p):
    return [h["text"] for h in p["history"] if h["result"] == "setback" and h.get("text")]


def fallback_narration(stage, result):
    return {"blowup": "It went badly wrong on " + stage + ", and you lost ground.",
            "setback": "Something went wrong on " + stage + ", and you'll have to redo part of it.",
            "slow": "Work on " + stage + " was slow and fiddly, but it moved forward.",
            "good": "You made steady progress on " + stage + ".",
            "breakthrough": "Something clicked on " + stage + ", and it came together faster than expected."}[result]


def apply_changes(p, data, reveal, new_question=False, may_answer=True):
    """What the narrator found out, applied (in place): a hidden fact revealed, an open question answered, a new one, the difficulty
    nudged. Never adds or removes the agent's steps (but a last plain step when the last unknown is settled and nothing is left to do)."""
    out = {"finding": None, "answered": None, "added": []}
    unfound = [i for i, h in enumerate(p["hidden"]) if not h["found"]]
    finding = clip(data.get("finding"), 240) if data.get("finding") else None
    if reveal and unfound:
        i = data.get("reveal")
        i = i if isinstance(i, int) and i in unfound else unfound[0]
        p["hidden"][i]["found"] = True
        finding = finding or p["hidden"][i]["fact"]
    if finding and finding not in p["findings"]:
        p["findings"].append(finding)
        out["finding"] = finding
    if may_answer and p["questions"] and (reveal or isinstance(data.get("answers"), int)):
        q = data.get("answers")
        q = q if isinstance(q, int) and 0 <= q < len(p["questions"]) else 0
        out["answered"] = p["questions"].pop(q)
    if not p["questions"] and out["answered"] and current_stage(p) is None:
        p["stages"] += new_stages([dict(FINAL_STEP)])
        out["added"] = [FINAL_STEP["name"]]
    if new_question and data.get("new_question") and len(p["questions"]) < MAX_QUESTIONS:
        p["questions"].append(clip(data["new_question"], 160))
    delta = data.get("difficulty_delta")
    if isinstance(delta, int) and not isinstance(delta, bool) and delta:
        p["difficulty"] = max(1, min(5, p["difficulty"] + max(-1, min(1, delta))))
    return out


def edit_plan(p, steps, drop):
    wanted = {str(n).strip().lower() for n in (drop if isinstance(drop, list) else [])}
    dropped = []
    for st in list(p["stages"]):
        if st["name"].lower() in wanted and not st["started"] and st["progress"] == 0:
            p["stages"].remove(st)
            dropped.append(st["name"])
    steps = steps[:max(0, MAX_STAGES_REVISED - len(p["stages"]))]
    p["stages"] += new_stages(steps)
    return [s["name"] for s in steps], dropped


# --- the store ------------------------------------------------------------------------------------------------------------------------
def projects(ctx):
    return ctx["store"].get("projects", {})


def skills(ctx):
    return ctx["store"].get("skills", {})


def meta(ctx):
    return ctx["store"].get("meta", {}).get("all", {})


def now_session(ctx):
    return ctx["store"].get("now", {}).get("session")


def by_status(ctx, status):
    return sorted((p for p in projects(ctx).values() if p["status"] == status), key=lambda p: p["id"])


def limit(ctx):
    return min(ctx["params"]["cap"], ctx["params"]["most"] + meta(ctx).get("extra_slots", 0))


def find(ctx, query, status="active"):
    q = str(query or "").strip().lstrip("#")
    pool = by_status(ctx, status) if status else sorted(projects(ctx).values(), key=lambda p: p["id"])
    if q.isdigit():
        p = projects(ctx).get(q)
        return (p, "") if p and (not status or p["status"] == status) else (None, "no " + (status + " " if status else "") + "project #" + q)
    exact = [p for p in pool if p["name"].lower() == q.lower()]
    part = [p for p in pool if q and q.lower() in p["name"].lower()]
    if exact or len(part) == 1:
        return (exact or part)[0], ""
    if part:
        return None, "which one? " + ", ".join("#" + str(p["id"]) + " " + p["name"] for p in part)
    names = ", ".join("#" + str(p["id"]) + " " + p["name"] for p in pool)
    return None, "no " + (status + " " if status else "") + "project like " + repr(str(query)) + (" (yours: " + names + ")" if names else "")


def compact(p):
    """A finished or abandoned project, kept small: what it was and the last of how it went."""
    return {**p, "history": [{k: h.get(k) for k in ("ts", "stage", "result", "minutes", "text", "kind", "interrupted")} for h in p["history"][-HISTORY_KEPT:]],
            "hidden": [], "findings": p["findings"][-2:], "stages": [{**s, "materials": {}} for s in p["stages"]]}


def save(store, p):
    """A project's changes, for the store: kept small once it's over, and the oldest finished ones let go of."""
    store.setdefault("projects", {})[str(p["id"])] = compact(p) if p["status"] in ("done", "abandoned") else p
    return store


def prune(ctx, store):
    over = [p for p in projects(ctx).values() if p["status"] in ("done", "abandoned")]
    over.sort(key=lambda p: p.get("finished_at") or 0)
    for p in over[:max(0, len(over) - FINISHED_KEPT)]:
        store.setdefault("projects", {})[str(p["id"])] = None
    return store


def feel(ctx):
    out = []
    abilities = [(a, lv) for a, lv in ctx["abilities"].items() if a in FEELINGS and lv >= 1]
    if abilities:
        out.append("How you've grown: " + "; ".join(FEELINGS[a][lv - 1] + " (" + a + ")" for a, lv in abilities))
    crafts = [FAMILIAR[level(xp)] + " " + c for c, xp in skills(ctx).items() if level(xp) >= 1]
    if crafts:
        out.append("Your experience: " + ", ".join(crafts))
    return out


def have(ctx, name, kinds=("material", "tool")):
    q = name_key(name)
    exact = [i for i in ctx["items"] if name_key(i["name"]) == q and i["kind"] in kinds]
    return exact[0] if exact else None


def missing_materials(ctx, stage):
    take, problems = [], []
    for name, qty in stage["materials"].items():
        item = have(ctx, name)
        if item and item["qty"] >= qty:
            take.append((item, qty))
        else:
            problems.append(str(qty) + " " + name + " (you have " + str(item["qty"] if item else 0) + ")")
    return take, problems


def mentioned_materials(ctx, stage):
    listed = {name_key(n) for n in stage["materials"]}
    text = " " + name_key(stage["name"]) + " "
    return [i for i in ctx["items"] if i["kind"] == "material" and name_key(i["name"]) not in listed and " " + name_key(i["name"]) + " " in text]


def tools_owned(ctx, p):
    return sum(1 for t in p["tools"] if have(ctx, t, ("tool",)))


def related(a, b):
    words = lambda s: {name_key(w) for w in str(s).lower().replace(",", " ").split() if len(w) > 3}  # noqa: E731
    return bool(words(a) & words(b)) or name_key(a) == name_key(b)


def found_where(ctx, name):
    return [f for f in ctx["found"] if related(name, f["item"])]


# --- what the agent sees, and what's published ------------------------------------------------------------------------------------
def describe_stage(p, i):
    st = p["stages"][i]
    mats = ", ".join(str(q) + " " + n for n, q in st["materials"].items())
    return ("stage " + str(i + 1) + "/" + str(len(p["stages"])) + " '" + st["name"] + "' (about " + str(st["minutes"]) + " min of work"
            + ("; uses " + mats if mats and not st["started"] else "") + ")")


def project_line(ctx, p):
    i = current_stage(p)
    line = "#" + str(p["id"]) + " " + p["name"] + " (" + p["craft"] + ", difficulty " + str(p["difficulty"]) + "/5): " + str(percent(p)) + "% done"
    if i is not None:
        st = p["stages"][i]
        line += ", now on stage " + str(i + 1) + "/" + str(len(p["stages"])) + " '" + st["name"] + "'"
        if st["materials"]:
            needs = ", ".join(str(q) + " " + n for n, q in st["materials"].items())
            if st["started"]:
                line += " (its " + needs + " are already in hand)"
            else:
                take, missing = missing_materials(ctx, st)
                got = {name_key(t["name"]) for t, _ in take}
                hints = ["you found " + n + " at " + f["label"] for n in st["materials"] if name_key(n) not in got for f in found_where(ctx, n)[:1]]
                line += " (needs " + needs + ("; missing " + ", ".join(missing) if missing else "; you have them")
                line += (" - " + "; ".join(hints) if hints else "") + ")"
        later = upcoming_needs(p, i + 1)
        if later:
            line += "; later stages need " + ", ".join(str(q) + " " + n + " (you have " + str((have(ctx, n) or {"qty": 0})["qty"]) + ")"
                                                         for n, q in later.items())
    elif crossroads(p):
        line += ", all you know to do is done - the way forward isn't clear yet"
    s = now_session(ctx)
    if s and s["project_id"] == p["id"]:
        line += " - you're " + ("experimenting on" if s["kind"] == "experiment" else "working on") + " it now"
    return line


def status(ctx):
    lines = []
    for p in by_status(ctx, "active"):
        lines.append(project_line(ctx, p))
        if p["questions"]:
            lines.append("  you don't know yet: " + "; ".join(p["questions"]))
        if p["findings"]:
            lines.append("  you've found out: " + "; ".join(p["findings"][-4:]))
    if not lines:
        lines.append("(none - start_project when you want to make something)")
    held = by_status(ctx, "paused")
    if held:
        lines.append("On hold (resume_project to pick one back up): " + ", ".join(p["name"] for p in held))
    lines += feel(ctx)
    return {"title": "Your projects", "lines": [clip(x, 400) for x in lines[:12]]}


def published(ctx, store):
    """For the dashboard and the night pass: each project as it stands, and the crafts' experience."""
    ps = dict(projects(ctx))
    for k, v in (store.get("projects") or {}).items():
        if v is None:
            ps.pop(k, None)
        else:
            ps[k] = v
    sk = {**skills(ctx), **(store.get("skills") or {})}
    out = []
    for p in sorted(ps.values(), key=lambda p: p["id"]):
        worked = [h["ts"] for h in p["history"]]
        out.append({"id": p["id"], "name": p["name"], "goal": p["goal"], "craft": p["craft"], "difficulty": p["difficulty"], "status": p["status"],
                    "percent": percent(p), "current_stage": current_stage(p), "last_worked": max(worked) if worked else p["ts"],
                    "stages": [{"name": s["name"], "minutes": s["minutes"], "progress": round(s["progress"], 1)} for s in p["stages"]]})
    extra = {**meta(ctx), **((store.get("meta") or {}).get("all") or {})}.get("extra_slots", 0)
    return {"projects": out[-40:], "skills": {c: {"xp": round(x, 1), "level": level(x)} for c, x in sk.items()},
            "project_limit": min(ctx["params"]["cap"], ctx["params"]["most"] + extra)}


def finish(ctx, out, store=None):
    store = prune(ctx, dict(store or {}))
    merged = {}
    for c in set(ctx["store"]) | set(store):                 # the store as it will be: changes over what was, deletions gone
        keys = {**ctx["store"].get(c, {}), **(store.get(c) or {})}
        merged[c] = {k: v for k, v in keys.items() if v is not None}
    after = dict(ctx, store=merged)
    out["status"] = status(after)
    out["publish"] = published(ctx, store)
    if any(store.values()):
        out["store"] = {c: keys for c, keys in store.items() if keys}
    return out


# --- the narrator's tasks -------------------------------------------------------------------------------------------------------------
def ask(prompt, props, required, purpose):
    return {"name": "narrator", "op": "ask", "args": {"prompt": prompt, "schema": {"properties": props, "required": required}}}


def brief(ctx, p):
    a = ctx["agent"]
    done = [s["name"] for s in p["stages"] if s["progress"] >= s["minutes"] - 1e-6]
    todo = [s["name"] for s in p["stages"] if s["progress"] < s["minutes"] - 1e-6]
    return ("Project " + repr(p["name"]) + " (" + p["craft"] + "): " + (p["goal"] or "(no stated goal)") + "\n"
            + "Done stages: " + (", ".join(done) or "none") + ". Remaining: " + (", ".join(todo) or "none") + ".\n"
            + "Open questions: " + ("; ".join("[" + str(i) + "] " + q for i, q in enumerate(p["questions"])) or "none")
            + "\nWhat " + a["name"] + " has found out so far: " + ("; ".join(p["findings"]) or "nothing yet"))


def hidden_list(p):
    return "; ".join("[" + str(i) + "] " + h["fact"] + (" (already found)" if h["found"] else "") for i, h in enumerate(p["hidden"])) or "none"


def review_task(ctx, name, goal, steps):
    a = ctx["agent"]
    listing = "\n".join(str(i) + ". " + s["name"] + " (" + a["name"] + " thinks ~" + str(s["minutes"]) + " min"
                        + (", using " + ", ".join(str(q) + " " + n for n, q in s["materials"].items()) if s["materials"] else "") + ")"
                        for i, s in enumerate(steps))
    owns = ", ".join(i["name"] + " x" + str(i["qty"]) + " (" + i["kind"] + ")" for i in ctx["items"]) or "nothing"
    feelings = feel(ctx)
    task = (a["name"] + " wants to start a project: " + repr(name) + ". What " + a["name"] + " has in mind: " + (goal or "(not said)") + "\n"
            + a["possessive"] + " own plan, in " + a["their"] + " own words:\n" + listing + "\n" + a["name"] + " owns: " + owns + "\n"
            + ("About " + a["name"] + ": " + " ".join(feelings) + "\n" if feelings else "")
            + "\nThis is " + a["possessive"] + " plan: do not rewrite, add or remove steps. Review it. For each step (same order, same count) give the "
            "1-2 `abilities` it exercises, from: " + ", ".join(known_abilities(ctx)) + ", and correct `minutes` only if " + a["possessive"]
            + " guess is badly off (15-240). Give the project's `craft` (a word or two), `difficulty` 1-5, and up to 3 `tools` or instruments that "
            "would help. Then decide what " + a["name"] + " cannot know yet: if there are real unknowns in making this (anything about finding out, "
            "tuning or how the thing really behaves), list up to 3 `open_questions` (short) and 1-3 `hidden` facts: how the thing really works, "
            "consistent with each other and plausibly able to trip up " + a["possessive"] + " plan. " + a["name"] + " never sees hidden facts until "
            + a["name"] + " discovers them. If the path is plain, leave both empty. Finally `concerns`: one short sentence only if something in the "
            "plan is obviously unworkable to anyone with " + a["possessive"] + " experience (otherwise empty); don't hint at hidden facts.")
    return ask(task, {"steps": {"type": "array", "items": STEP}, "craft": {"type": "string"}, "difficulty": {"type": "integer"},
                      "tools": {"type": "array", "items": {"type": "string"}}, "open_questions": {"type": "array", "items": {"type": "string"}},
                      "hidden": {"type": "array", "items": {"type": "string"}}, "concerns": {"type": "string"}}, ["craft", "difficulty"], "review")


def adjudicate_task(ctx, p, stage, approach, rolled, minutes, mats, earlier):
    a = ctx["agent"]
    hidden = [h["fact"] for h in p["hidden"] if not h["found"]]
    meaning = {"blowup": "so badly it goes wrong in " + a["possessive"] + " face", "setback": "poorly", "slow": "slowly but surely",
               "good": "well", "breakthrough": "unusually well"}[rolled]
    feelings = feel(ctx)
    task = ("Project " + repr(p["name"]) + " (" + p["craft"] + ", difficulty " + str(p["difficulty"]) + "/5): " + (p["goal"] or "(no stated goal)") + "\n"
            + "Stage: " + repr(stage["name"]) + ". " + a["name"] + " worked " + str(minutes) + " minutes and described " + a["their"]
            + " approach: " + repr(approach) + "\n"
            + (a["name"] + " is working with: " + ", ".join(mats) + ". " if mats else "")
            + ("About " + a["name"] + ": " + " ".join(feelings) + "\n" if feelings else "")
            + ("Things " + a["name"] + " has found out so far: " + "; ".join(p["findings"]) + "\n" if p["findings"] else "")
            + ("Hidden truths about this project (" + a["name"] + " cannot see them): " + "; ".join(hidden) + "\n" if hidden else "")
            + "The die says this kind of effort goes " + meaning + " on average. Decide the `verdict` for what " + a["name"] + " actually did: blowup, "
            "setback, slow, good or breakthrough. A sound, clever approach that respects how the thing really works may go one step better than the "
            "die says; a careless, wrong-headed or reckless one one step worse (the world won't allow more than one step either way). Blowup means it "
            "goes wrong in " + a["possessive"] + " face (a snapped part, a burn, a spoiled piece): pick it only if the approach was reckless or clearly "
            "flawed. Never decide that " + a["name"] + " is finished with the stage. Write `text`: 1-3 concrete sentences, second person, under 50 "
            "words, true to this kind of work, using only what " + a["name"] + " has. If the attempt taught " + a["name"] + " something, give "
            "`finding` (one plain sentence); if it exposed one of the hidden truths, give its index in `reveal` (index = order listed, from 0)."
            + ("\nEarlier sessions (something different happens this time):\n" + "\n".join("- " + e for e in earlier) if earlier else ""))
    return ask(task, {"verdict": {"type": "string", "enum": list(VERDICTS)}, "text": {"type": "string"}, "finding": {"type": "string"},
                      "reveal": {"type": "integer"}}, ["verdict", "text"], "adjudicate")


def narrate_task(ctx, p, stage, mats, result, minutes, finished_stage, earlier):
    a = ctx["agent"]
    meaning = {"blowup": "it went badly wrong and lost ground", "setback": "something went wrong and no progress was made; it leaves a small lasting trace in the work",
               "slow": "progress was real but slow and fiddly", "good": "steady, satisfying progress",
               "breakthrough": "it went unusually well; something clicked"}[result]
    task = (a["name"] + " just spent " + str(minutes) + " minutes on the stage " + repr(stage) + " of " + a["their"] + " project " + repr(p["name"])
            + (" (" + p["goal"] + ")" if p["goal"] else "") + ". "
            + (a["name"] + " is working with: " + ", ".join(mats) + ". " if mats else "")
            + "The result (already decided, don't change it): " + result + " - " + meaning + "."
            + (" This finished the stage." if finished_stage else " The stage is NOT finished yet; don't say it is.")
            + ("\nEarlier sessions (don't repeat these; something different happens this time):\n" + "\n".join("- " + e for e in earlier) if earlier else "")
            + "\nDescribe what happened in 1-2 short concrete sentences (under 40 words), second person ('You ...'), no numbers, true to the kind of "
            "work this is. Only mention materials and tools " + a["name"] + " actually has.")
    return ask(task, {"text": {"type": "string"}}, ["text"], "narrate")


def experiment_task(ctx, p, hypothesis, outcome):
    a = ctx["agent"]
    meaning = {"nothing": "it showed nothing useful; say what " + a["name"] + " saw, without hinting at the answer",
               "clue": "it hinted at something, but nothing certain; the `finding` is only a partial, honest observation",
               "insight": "it worked: it shows one of the hidden facts, and " + a["name"] + " understands something real " + a["they"] + " did not",
               "surprise": "it showed one of the hidden facts and also something unexpected that opens a new direction"}[outcome]
    task = (brief(ctx, p) + "\nHidden facts (index: fact; " + a["name"] + " cannot see these): " + hidden_list(p) + "\n"
            + a["name"] + " ran an experiment. " + a["their"][:1].upper() + a["their"][1:] + " hypothesis: " + repr(hypothesis) + ".\n"
            + "The engine already rolled the outcome (" + outcome + "): " + meaning + ".\n"
            + "Decide `relevant`: false if the hypothesis has nothing to do with the project or the hidden facts (then the result is simply "
            "inconclusive and `text` should say so). Write `text` (1-3 concrete sentences, second person, under 60 words) describing what "
            + a["name"] + " observed. For a clue, insight or surprise give `finding`: what " + a["name"] + " now knows, in one plain sentence, based on "
            "the hidden fact (do not reveal facts the outcome doesn't show). For an insight or surprise give `reveal` (the index of the hidden fact it "
            "shows) and, if it answers an open question, `answers` (that question's index). " + a["name"] + " decides what to do next; you don't add "
            "steps. For a surprise, `new_question` may name what " + a["name"] + " now wonders about, and `difficulty_delta` (-1, 0 or 1) says if it "
            "made the project easier or harder. Never decide that " + a["name"] + " succeeded or failed at the project itself.")
    return ask(task, {"relevant": {"type": "boolean"}, "text": {"type": "string"}, "new_question": {"type": "string"},
                      "difficulty_delta": {"type": "integer"}, **CHANGES}, ["relevant", "text"], "experiment")


def revise_task(ctx, p, steps, because):
    a = ctx["agent"]
    parts = [brief(ctx, p)]
    if steps:
        parts.append(a["name"] + " added these steps to " + a["their"] + " own plan:\n"
                     + "\n".join(str(i) + ". " + s["name"] + " (~" + str(s["minutes"]) + " min)" for i, s in enumerate(steps)))
    if because:
        parts.append("Hidden facts (index: fact; " + a["name"] + " cannot see these): " + hidden_list(p) + "\n" + a["name"] + " says " + a["they"]
                     + " learned, from elsewhere (reading, searching, a visitor): " + repr(because) + ".")
    task = "\n".join(parts) + "\n"
    if steps:
        task += ("For each added step (same order and count) give `steps` notes: 1-2 `abilities` from " + ", ".join(known_abilities(ctx))
                 + ", and `minutes` only if " + a["possessive"] + " guess is badly off. Do not rename, add or remove steps. ")
    if because:
        task += ("Decide `accepted`: true only if what " + a["name"] + " learned plausibly settles one of its open questions or matches a hidden "
                 "fact (otherwise false, and say kindly in `text` why it doesn't help). If accepted, give `answers` (the open question's index) "
                 "and/or `reveal` (a hidden fact's index, only if the source would really contain it) with a `finding` (one plain sentence). ")
    task += "`text`: one or two sentences, second person. Never decide success or failure."
    return ask(task, {"accepted": {"type": "boolean"}, "text": {"type": "string"}, "steps": {"type": "array", "items": STEP}, **CHANGES},
               ["text"], "revise")


def design_task(ctx, p, q, marks):
    a = ctx["agent"]
    story = "\n".join("- " + h["stage"] + ": " + h["text"] for h in p["history"] if not h.get("interrupted"))
    caps = list(ctx["making"]["capabilities"]) + ([ctx["making"]["companion"]] if p["difficulty"] >= ctx["making"]["companion_from"] else [])
    task = (a["name"] + " just finished " + a["their"] + " project " + repr(p["name"]) + " (" + p["craft"] + "). It was meant to: "
            + (p["goal"] or "(not said)") + "\nHow the work went:\n" + (story or "(no notes)") + "\nFinished quality: " + q + ".\n"
            + ("Setbacks that left marks: " + "; ".join(marks) + "\n" if marks else "")
            + "\nDescribe what it turned out to be. Most things are simply themselves - made to be looked at, read, heard, worn, kept or given - and "
            "have NO capabilities: that is the right answer for them, so don't invent behaviour. Only if it genuinely works or acts on its own, choose "
            "the 1-3 capabilities below that honestly describe it, matching its goal and quality (a rough piece can still work, just less well). These "
            "are the only behaviours the world can run; if what it does doesn't fit them, describe it in words instead:\n"
            + "\n".join("- " + c for c in caps)
            + "\nAlso give a name (keep " + a["possessive"] + " name unless something better fits; anything with a mind of its own gets a short name "
            + a["name"] + " can call it by), one or two sentences on what it is and is like (under 40 words), and 1-3 short quirks that give it "
            "character (turn the setback marks into quirks if there were any). The name, description and quirks are what " + a["name"]
            + " sees: describe the thing itself, never what it can or can't do.")
    cap = {"type": "object", "properties": {"type": {"type": "string"}, "hours": {"type": "number"}, "every_minutes": {"type": "number"},
                                            "verb": {"type": "string"}, "condition": {"type": "string"}, "alert": {"type": "string"},
                                            "effect": {"type": "string"}, "line": {"type": "string"}}, "required": ["type"]}
    extra = {"type": "object", "properties": {"type": {"type": "string"}, "lines": {"type": "array", "items": {"type": "string"}},
                                              "finds": {"type": "array", "items": {"type": "string"}}, "persona": {"type": "string"},
                                              "chatter_minutes": {"type": "number"}, "ability": {"type": "string"}}, "required": ["type"]}
    return ask(task, {"name": {"type": "string"}, "description": {"type": "string"}, "capabilities": {"type": "array", "items": cap},
                      "more": {"type": "array", "items": extra, "description": "the same capabilities' lines, finds, persona, ability (by type)"},
                      "quirks": {"type": "array", "items": {"type": "string"}}}, ["description"], "design")


# --- the tools ------------------------------------------------------------------------------------------------------------------------
def error(text):
    return {"reply": "error: " + text}


def start_project(ctx, args):
    name, goal = str(args.get("name") or "").strip()[:60], str(args.get("goal") or "").strip()[:300]
    if not name:
        return error("a project needs a name")
    steps = sanitize_stages(ctx, args.get("steps"), MAX_STAGES)
    if not steps:
        return error("sketch at least the first step or two of how you'd do it. If you don't know how to begin, look it up (web_search, the "
                     "library) or ask a visitor, then start")
    active = by_status(ctx, "active")
    if any(p["name"].lower() == name.lower() for p in active):
        return {"reply": "you're already working on " + repr(name) + "; use work_on"}
    if len(active) >= limit(ctx):
        return {"reply": "you already have " + str(len(active)) + " projects going (" + ", ".join(p["name"] for p in active) + "); finish or "
                         "abandon_project one first"}
    return {"store": {"now": {"start": {"name": name, "goal": goal, "steps": steps}}}, "source": review_task(ctx, name, goal, steps)}


def started(ctx, review):
    start = ctx["store"]["now"]["start"]
    plan = build_plan(ctx, start["steps"], review)
    pid = meta(ctx).get("next_id", 1)
    p = {"id": pid, "name": start["name"], "goal": start["goal"], "craft": plan["craft"], "difficulty": plan["difficulty"], "stages": new_stages(plan["stages"]),
         "tools": plan["tools"], "questions": plan["questions"], "hidden": plan["hidden"], "findings": [], "history": [], "status": "active",
         "dry": 0, "revised_at": 0, "ts": ctx["now"], "finished_at": None, "outcome": ""}
    store = save({"meta": {"all": {**meta(ctx), "next_id": pid + 1}}, "now": {"start": None}}, p)
    listing = "; ".join(str(i + 1) + ". " + s["name"] + " (~" + str(s["minutes"]) + " min"
                        + (", needs " + ", ".join(str(q) + " " + n for n, q in s["materials"].items()) if s["materials"] else "") + ")"
                        for i, s in enumerate(plan["stages"]))
    tools = " Helpful tools: " + ", ".join(plan["tools"]) + "." if plan["tools"] else ""
    concern = " A thought on your plan: " + clip((review or {}).get("concerns"), 200) if (review or {}).get("concerns") else ""
    unknown = (" What you don't know yet: " + "; ".join(plan["questions"]) + ". Work out what you can, then experiment or look things up, and "
               "revise_plan as you learn." if plan["questions"] else "")
    sketch = " You could sketch it first with draw." if "draw" in ctx["agent"].get("tools", []) else ""
    return finish(ctx, {"reply": "started project #" + str(pid) + " " + p["name"] + " (" + plan["craft"] + ", difficulty " + str(plan["difficulty"])
                        + "/5). Your plan: " + listing + "." + tools + concern + unknown + sketch}, store)


def work_on(ctx, args):
    p, err = find(ctx, args.get("project"))
    if not p:
        return error(err)
    s = now_session(ctx)
    if s and s["project_id"] == p["id"] and s["kind"] == "work" and ctx["agent"]["busy"]:
        return {"reply": "you're already working on " + p["name"]}
    if ctx["agent"]["busy"]:
        return {"reply": ctx["agent"]["busy"]}
    i = current_stage(p)
    if i is None:
        if p["questions"]:
            return {"reply": "you've done everything you know to do on " + p["name"] + ". Still open: " + "; ".join(p["questions"])
                             + ". Try an experiment, or learn more and revise_plan."}
        return {"reply": p["name"] + " is already finished"}
    stage, out, used_up = p["stages"][i], {}, ""
    if not stage["started"]:
        take, missing = missing_materials(ctx, stage)
        if missing:
            return {"reply": "can't start " + describe_stage(p, i) + " yet: it needs " + ", ".join(missing)}
        built_in = mentioned_materials(ctx, stage)
        used = [{"item": item["name"], "qty": qty} for item, qty in take if item["kind"] == "material"] + [{"item": i2["name"], "qty": 1} for i2 in built_in]
        if used:
            out["take"] = used
        stage["started"] = True
        if built_in:
            used_up = " You used up your " + ", ".join(i2["name"] for i2 in built_in) + " on it."
    minutes = clamp_int(args.get("minutes"), SESSION_MINUTES[0], SESSION_MINUTES[1], 60)
    approach = str(args.get("approach") or "").strip()[:240]
    expect = str(args.get("expect") or "").strip().lower()
    real = max(1, round(minutes / ctx["params"]["speed"]))
    store = save({"now": {"session": {"kind": "work", "project_id": p["id"], "stage": i, "minutes": minutes, "approach": approach,
                                      "expect": expect if expect in SESSION_EXPECT else ""}}}, p)
    out.update(session={"minutes": real, "label": "working on " + p["name"] + ": " + stage["name"], "working": True, "about": p["name"]},
               doing={"activity": "working", "description": p["name"] + ": " + stage["name"]},
               reply="you settle in to work on " + p["name"] + ", " + describe_stage(p, i) + ", for " + str(minutes) + " min. You'll hear how it went in "
                     "about " + str(real) + " min." + used_up)
    return finish(ctx, out, store)


def experiment(ctx, args):
    p, err = find(ctx, args.get("project"))
    if not p:
        return error(err)
    hypothesis = str(args.get("hypothesis") or "").strip()[:240]
    if len(hypothesis) < 8:
        return error("say what you think might be true or work, and how you'll test it")
    if ctx["agent"]["busy"]:
        return {"reply": ctx["agent"]["busy"]}
    minutes = clamp_int(args.get("minutes"), EXPERIMENT_MINUTES[0], EXPERIMENT_MINUTES[1], 45)
    expect = str(args.get("expect") or "").strip().lower()
    real = max(1, round(minutes / ctx["params"]["speed"]))
    store = {"now": {"session": {"kind": "experiment", "project_id": p["id"], "stage": -1, "minutes": minutes, "hypothesis": hypothesis,
                                 "expect": expect if expect in EXPERIMENT_EXPECT else ""}}}
    return finish(ctx, {"session": {"minutes": real, "label": "experimenting on " + p["name"], "working": True, "about": p["name"]},
                        "doing": {"activity": "working", "description": "experiment on " + p["name"] + ": " + hypothesis[:80]},
                        "reply": "you set up an experiment on " + p["name"] + " (" + hypothesis + ") for " + str(minutes) + " min. You'll see what "
                                 "happens in about " + str(real) + " min."}, store)


def revise_plan(ctx, args):
    p, err = find(ctx, args.get("project"))
    if not p:
        return error(err)
    steps = sanitize_stages(ctx, args.get("steps"), MAX_STAGES_REVISED)
    drop = args.get("drop") if isinstance(args.get("drop"), list) else []
    because = str(args.get("because") or "").strip()[:400]
    if not (steps or drop or because):
        return error("give steps to add, steps to drop, or what you learned")
    claim, note = bool(because), ""
    if claim and not len(p["history"]) > p["revised_at"]:
        claim, note = False, " (what you learned will count once you've worked or experimented again)"
    unknowns = bool(p["questions"] or any(not h["found"] for h in p["hidden"]))
    revise = {"project_id": p["id"], "steps": steps, "drop": drop, "because": because, "claim": claim and unknowns, "claimed": claim, "note": note}
    if steps or (claim and unknowns):
        return {"store": {"now": {"revise": revise}}, "source": revise_task(ctx, p, steps, because if claim and unknowns else "")}
    return revised(ctx, revise, {})


def revised(ctx, r, verdict):
    p = projects(ctx)[str(r["project_id"])]
    verdict = verdict or {}
    steps = annotate(ctx, r["steps"], verdict.get("steps")) if r["steps"] else []
    added, dropped = edit_plan(p, steps, r["drop"])
    changes = {"finding": None, "answered": None, "added": added, "dropped": dropped}
    msg = clip(verdict.get("text"), 300) if verdict.get("text") else ""
    if r["claim"] and verdict.get("accepted") is True:
        learned = apply_changes(p, verdict, reveal=verdict.get("reveal") is not None)
        changes.update(finding=learned["finding"], answered=learned["answered"])
        changes["added"] += learned["added"]
        p["revised_at"] = len(p["history"])
    elif r["claimed"]:
        p["revised_at"] = len(p["history"])
        msg = msg or "that doesn't change what you need to do"
    bits = (["added: " + ", ".join(changes["added"])] if changes["added"] else []) + (["dropped: " + ", ".join(changes["dropped"])] if changes["dropped"] else []) \
        + (["you now know: " + changes["finding"]] if changes["finding"] else []) + (["settled: " + changes["answered"]] if changes["answered"] else [])
    reply = " ".join(x for x in ((msg + r["note"]).strip(), "; ".join(bits) or "the plan stays as it is") if x)
    store = save({"now": {"revise": None}}, p)
    return finish(ctx, {"reply": reply, "event": {"kind": "plan_revised", "data": {"project": p["name"], "project_id": p["id"],
                                                                                    "because": clip(r["because"], 200), **changes}}}, store)


def abandon_project(ctx, args):
    p, err = find(ctx, args.get("project"), status=None)
    if not p or p["status"] not in ("active", "paused"):
        return error(err or p["name"] + " is already " + p["status"])
    p = {**p, "status": "abandoned", "outcome": str(args.get("reason") or "")[:300], "finished_at": ctx["now"]}
    return finish(ctx, {"reply": "abandoned " + p["name"]}, save({}, p))


def resume_project(ctx, args):
    p, err = find(ctx, args.get("project"), status="paused")
    if not p:
        return error(err)
    if len(by_status(ctx, "active")) >= limit(ctx):
        return {"reply": "you already have as many projects going as you can keep up with; finish, pause or abandon one first"}
    return finish(ctx, {"reply": "you pick " + p["name"] + " back up"}, save({}, {**p, "status": "active"}))


TOOLS = {"start_project": start_project, "work_on": work_on, "experiment": experiment, "revise_plan": revise_plan,
         "abandon_project": abandon_project, "resume_project": resume_project}


def on_action(ctx):
    return TOOLS[ctx["tool"]](ctx, ctx["args"])


def on_install(ctx):
    return finish(ctx, {})


# --- a session's end -------------------------------------------------------------------------------------------------------------------
def on_time(ctx):
    s, now = ctx.get("session"), now_session(ctx)
    if not s or not now:
        return finish(ctx, {})
    p = projects(ctx).get(str(now["project_id"]))
    if not p or p["status"] != "active":
        out = {"doing": {"activity": "idle", "description": ""}} if ctx["agent"]["activity"] == "working" else {}
        return finish(ctx, out, {"now": {"session": None}})
    minutes = now["minutes"]
    if s["interrupted"]:
        minutes = min(minutes, s["minutes"] * ctx["params"]["speed"])
    rng = random.Random(ctx["seed"])
    if now["kind"] == "experiment":
        return experiment_ended(ctx, p, now, minutes, s["interrupted"], rng)
    return work_ended(ctx, p, now, minutes, s["interrupted"], rng)


def work_ended(ctx, p, now, minutes, interrupted, rng):
    stage = p["stages"][now["stage"]]
    run = {**now, "read": minutes, "interrupted": interrupted, "result": "slow", "text": None, "lesson": None}
    if interrupted:
        return work_told(ctx, p, run)
    lvl = skill_for(ctx, p, stage_abilities(ctx, stage))
    run["result"] = roll(rng, lvl, tools_owned(ctx, p), p["difficulty"], ctx["agent"]["tired"])
    mats = list(stage["materials"]) + [i["name"] for i in ctx["items"] if i["kind"] == "tool"]
    earlier = [h["text"] for h in p["history"] if not h.get("interrupted")][-3:]
    if now["approach"]:                                       # the narrator weighs what the agent tried; the die bounds how far either way
        return {"store": {"now": {"run": run}}, "source": adjudicate_task(ctx, p, stage, now["approach"], run["result"], round(minutes), mats, earlier)}
    return {"store": {"now": {"run": run}}, "source": narrate_task(ctx, p, stage["name"], mats, run["result"], round(minutes),
                                                                   stage["progress"] + minutes * CREDIT[run["result"]] >= stage["minutes"] - 1e-6, earlier)}


def judged(ctx, ruling):
    run, p = ctx["store"]["now"]["run"], projects(ctx)[str(ctx["store"]["now"]["run"]["project_id"])]
    stage = p["stages"][run["stage"]]
    if ruling:
        run = {**run, "result": clamp_verdict(run["result"], ruling.get("verdict")), "lesson": ruling,
               "text": clip(ruling.get("text"), 300) if ruling.get("text") else None}
    if run["text"]:
        return work_told(ctx, p, run)
    mats = list(stage["materials"]) + [i["name"] for i in ctx["items"] if i["kind"] == "tool"]
    earlier = [h["text"] for h in p["history"] if not h.get("interrupted")][-3:]
    finishes = stage["progress"] + run["read"] * CREDIT[run["result"]] >= stage["minutes"] - 1e-6
    return {"store": {"now": {"run": run}}, "source": narrate_task(ctx, p, stage["name"], mats, run["result"], round(run["read"]), finishes, earlier)}


def work_told(ctx, p, run):
    """How the session went, applied: progress, what was lost, practice, what was learned and expected, the words, the event."""
    stage, minutes, result, out = p["stages"][run["stage"]], run["read"], run["result"], {}
    lost = []
    if result == "blowup":
        stage["progress"] = max(0.0, stage["progress"] - BLOWUP_LOSS * stage["minutes"])
        if ctx["agent"]["tiring"]:
            out["affect"] = {ctx["agent"]["tiring"]: -BLOWUP_ENERGY}
        owned = [have(ctx, n, ("material",)) for n in stage["materials"]]
        owned = [i for i in owned if i]
        if owned:
            item = random.Random(ctx["seed"] + 1).choice(owned)
            out["take"] = [{"item": item["name"], "qty": 1}]
            lost.append(item["name"])
    else:
        stage["progress"] += min(stage["minutes"] - stage["progress"], minutes * CREDIT[result])
    finished_stage = stage["progress"] >= stage["minutes"] - 1e-6
    abilities = stage_abilities(ctx, stage)
    if minutes > 0:
        out["practice"] = {a: min(240.0, minutes / len(abilities)) for a in abilities}
    comparison = None if run["interrupted"] else compare_session(run["expect"], result)
    step = None
    if finished_stage:
        spent = minutes + sum(h["minutes"] for h in p["history"] if h["stage"] == stage["name"] and h.get("kind") != "experiment")
        step = compare_step(stage.get("guess", stage["minutes"]), spent)
    learned = None
    if run["lesson"]:
        ch = apply_changes(p, {**run["lesson"], "new_question": None}, reveal=run["lesson"].get("reveal") is not None, may_answer=True)
        learned = ch["finding"]
        p["findings"] = p["findings"][-LESSONS_KEPT:]
    text = run["text"] or fallback_narration(stage["name"], result)
    p["history"].append({"ts": ctx["now"], "stage": stage["name"], "result": result, "minutes": round(minutes), "text": text, "interrupted": run["interrupted"]})
    done = current_stage(p) is None and not p["questions"]
    if done:
        p.update(status="done", finished_at=ctx["now"])
    out["doing"] = {"activity": "idle", "description": "just finished working on " + p["name"]} if ctx["agent"]["activity"] == "working" else None
    if out["doing"] is None:
        del out["doing"]
    data = {"project": p["name"], "project_id": p["id"], "stage": stage["name"], "result": result, "craft": p["craft"], "abilities": abilities,
            "minutes": round(minutes), "text": text, "finished_stage": finished_stage, "project_done": done, "interrupted": run["interrupted"],
            "percent": percent(p), "approach": run.get("approach", ""), "lost": lost, "learned": learned, **expectation_fields(comparison, step),
            "crossroads": crossroads({**p, "status": "active"}) and not done}
    out["event"] = {"kind": "work", "data": data, "expect": [settled(c, stage["name"]) for c in (comparison, step) if c]}
    out["wake"] = True
    sk = skills(ctx)
    store = save({"skills": {p["craft"]: sk.get(p["craft"], 0) + minutes}, "now": {"session": None, "run": None}}, p)
    if done:                                                  # what it turned out to be, designed by the narrator and made by the engine
        q, marks = quality(p, level(sk.get(p["craft"], 0) + minutes)), scars(p)
        store["now"]["made"] = {"project_id": p["id"], "quality": q, "scars": marks}
        out["source"] = design_task(ctx, p, q, marks)
    return finish(ctx, out, store)


def experiment_ended(ctx, p, now, minutes, interrupted, rng):
    run = {**now, "read": minutes, "interrupted": interrupted, "outcome": "interrupted"}
    if interrupted:
        return experiment_told(ctx, p, run, {})
    skill = skill_for(ctx, p, EXPERIMENT_ABILITIES)
    outcome = roll_experiment(rng, skill, p["difficulty"], ctx["agent"]["tired"])
    if p["dry"] >= DRY_LIMIT and outcome in ("nothing", "clue"):
        outcome = "insight"                                   # pity: a project can't be stuck forever
    run["outcome"] = outcome
    return {"store": {"now": {"run": run}}, "source": experiment_task(ctx, p, now["hypothesis"], outcome)}


def experiment_told(ctx, p, run, verdict):
    hypothesis, minutes, out = run["hypothesis"], run["read"], {}
    changes = {"finding": None, "answered": None, "added": []}
    comparison, relevant, outcome = None, True, run["outcome"]
    text = "You stopped before the experiment (" + hypothesis + ") could show anything."
    if not run["interrupted"]:
        verdict = verdict or {}
        relevant = verdict.get("relevant") is not False
        text = clip(verdict.get("text"), 400) if verdict.get("text") else (
            "You tried it: " + hypothesis + ". " + {"nothing": "Nothing came of it.", "clue": "It hinted at something, no more.",
                                                    "insight": "Something fell into place.", "surprise": "It did something you didn't expect."}[outcome])
        if not relevant:
            outcome = "nothing"
        comparison = compare_experiment(run["expect"], outcome)
        changes = apply_changes(p, verdict if relevant else {}, reveal=outcome in ("insight", "surprise"), new_question=outcome == "surprise",
                                may_answer=outcome in ("insight", "surprise"))
        if relevant:
            p["dry"] = 0 if outcome in ("insight", "surprise") else p["dry"] + 1
    if minutes > 0:
        out["practice"] = {a: min(240.0, minutes / len(EXPERIMENT_ABILITIES)) for a in EXPERIMENT_ABILITIES}
    p["history"].append({"ts": ctx["now"], "stage": ("experiment: " + hypothesis)[:80], "result": outcome, "minutes": round(minutes), "text": text,
                         "interrupted": run["interrupted"], "kind": "experiment"})
    done = current_stage(p) is None and not p["questions"] and bool(p["stages"])
    if done:
        p.update(status="done", finished_at=ctx["now"])
    if ctx["agent"]["activity"] == "working":
        out["doing"] = {"activity": "idle", "description": "just ran an experiment on " + p["name"]}
    data = {"project": p["name"], "project_id": p["id"], "craft": p["craft"], "hypothesis": hypothesis, "outcome": outcome, "relevant": relevant,
            "minutes": round(minutes), "text": text, "finding": changes["finding"], "answered": changes["answered"], "added": changes["added"],
            "interrupted": run["interrupted"], "project_done": done, "percent": percent(p), "crossroads": crossroads(p), **expectation_fields(comparison, None)}
    out["event"] = {"kind": "experiment", "data": data, "expect": [settled(comparison, hypothesis)] if comparison else []}
    out["wake"] = True
    sk = skills(ctx)
    store = save({"skills": {p["craft"]: sk.get(p["craft"], 0) + minutes}, "now": {"session": None, "run": None}}, p)
    if done:
        q, marks = quality(p, level(sk.get(p["craft"], 0) + minutes)), scars(p)
        store["now"]["made"] = {"project_id": p["id"], "quality": q, "scars": marks}
        out["source"] = design_task(ctx, p, q, marks)
    return finish(ctx, out, store)


def designed(ctx, raw):
    """What the finished thing turned out to be: the narrator's design, made real by the engine (`creation`)."""
    made = ctx["store"]["now"]["made"]
    p = projects(ctx)[str(made["project_id"])]
    raw = raw or {}
    more = {m["type"]: m for m in raw.get("more") or [] if isinstance(m, dict) and m.get("type")}
    caps = [{**c, **{k: v for k, v in more.get(c["type"], {}).items() if k != "type"}} for c in raw.get("capabilities") or [] if isinstance(c, dict)][:6]
    creation = {"name": clip(raw.get("name") or p["name"], 60), "description": clip(raw.get("description") or "your finished " + p["name"], 240),
                "quality": made["quality"], "capabilities": caps, "quirks": [clip(x, 120) for x in raw.get("quirks") or []][:5],
                "scars": [clip(x, 200) for x in made["scars"]][:5],
                "made_of": {"id": p["id"], "name": p["name"], "goal": p["goal"], "difficulty": p["difficulty"], "stages": [s["name"] for s in p["stages"]][:8]}}
    if not raw.get("quirks"):
        creation["quirks"] = [clip(x, 120) for x in made["scars"][:2]]
    return finish(ctx, {"creation": creation}, {"now": {"made": None}})


def on_source(ctx):
    data = (ctx["source"]["answer"] or {}).get("data")
    now = ctx["store"].get("now", {})
    if now.get("made"):
        return designed(ctx, data)
    if now.get("start"):
        return started(ctx, data)
    if now.get("revise"):
        return revised(ctx, now["revise"], data)
    run = now.get("run")
    if not run:
        return finish(ctx, {})
    p = projects(ctx)[str(run["project_id"])]
    if run["kind"] == "experiment":
        return experiment_told(ctx, p, run, data)
    if run.get("lesson") is None and run.get("approach") and not run.get("judged"):
        ctx["store"]["now"]["run"] = {**run, "judged": True}
        return judged(ctx, data)
    return work_told(ctx, p, {**run, "text": clip((data or {}).get("text"), 300) if (data or {}).get("text") else run.get("text")})


# --- what the engine asks: the night pass, and a world effect --------------------------------------------------------------------
def on_request(ctx):
    r = ctx["request"]
    if r["what"] == "add_slot":
        if limit(ctx) >= ctx["params"]["cap"]:
            return {"refuse": "there's no room for more projects at once"}
        n = meta(ctx).get("extra_slots", 0) + 1
        out = finish(ctx, {}, {"meta": {"all": {**meta(ctx), "extra_slots": n}}})
        out["reply"] = "You can keep " + str(min(ctx["params"]["cap"], ctx["params"]["most"] + n)) + " projects going at once now."
        return out
    p, err = find(ctx, r["args"].get("project"), status="active" if r["what"] == "pause" else "paused")
    if not p:
        return {"refuse": err}
    if r["what"] == "resume" and len(by_status(ctx, "active")) >= limit(ctx):
        return {"refuse": "there's no room to pick it back up"}
    if not r["apply"]:
        return {"reply": ("Put " if r["what"] == "pause" else "Pick ") + p["name"] + (" on hold." if r["what"] == "pause" else " back up.")}
    out = finish(ctx, {}, save({}, {**p, "status": "paused" if r["what"] == "pause" else "active"}))
    out["reply"] = ("Put " if r["what"] == "pause" else "Picked ") + p["name"] + (" on hold." if r["what"] == "pause" else " back up.")
    return out
