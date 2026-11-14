"""Turning-point candidates: stretches of time where the logged facts changed more than usual (DESIGN-self.md, 5).

Deterministic and facts-only. Signals: a count far from Pip's own baseline, major firsts, surprises, goal changes,
a change in who Pip talks to most, and returning to something after a long gap. Enough of them make a *candidate*,
which only gives the nightly reflection an occasion to ask whether it mattered. Pip decides; it is never forced.
"""
import statistics

TURNING_MIN = 3        # score needed to flag a candidate
BASELINE_DAYS = 15
BASELINE_MIN = 3       # prior days needed before counts can be compared with a "usual"
DEVIATION_SD = 2.0
DEVIATION_FLOOR = 2    # and at least this far from the mean, in counts
MAX_SIGNALS = {"first": 2, "surprise": 2, "baseline": 2, "goal": 1, "partner": 1, "return": 1}


def _baseline(state, stats: dict, today: str, labels) -> list[dict]:
    prior = [v for d, v in state.day_stats(BASELINE_DAYS) if d != today]
    if len(prior) < BASELINE_MIN:
        return []
    out = []
    labels = dict(labels)
    for v in prior:                                       # a count only earlier days had (none today) is a change too
        for key in v:
            labels.setdefault(key, key.replace("_", " "))
    for key, label in labels.items():
        vals = [v.get(key, 0) for v in prior]
        mean, sd, x = statistics.mean(vals), statistics.pstdev(vals), stats.get(key, 0)
        gap = abs(x - mean)
        if gap >= DEVIATION_FLOOR and (gap >= DEVIATION_SD * sd if sd else gap >= 3):
            out.append({"kind": "baseline", "events": [], "weight": gap / (sd or 1),
                        "text": f"{label}: {x:g} today, against your usual {mean:.1f} (range {min(vals):g}-{max(vals):g})"})
    return sorted(out, key=lambda s: -s["weight"])


def _top_sender(events) -> tuple[str | None, int]:
    counts: dict[str, int] = {}
    for e in events:
        d = e["data"]
        if e["kind"] == "inbox" and not d.get("letter") and not d.get("gift") and d.get("sender") not in (None, "A visitor"):
            counts[d["sender"]] = counts.get(d["sender"], 0) + 1
    if not counts:
        return None, 0
    who = max(counts, key=counts.get)
    return who, counts[who]


def detect(state, since: float, now: float, stats: dict, today: str, labels) -> dict:
    """{'score', 'flagged', 'signals': [{kind, text, events}]} for the stretch (since, now]."""
    events = [e for e in state.events_since(since, limit=5000) if e["ts"] <= now]
    sig: list[dict] = []
    for e in events:
        d = e["data"]
        for f in d.get("firsts", []):
            if f["tier"] == "major":
                sig.append({"kind": "first", "events": [e["id"]], "text": f["label"]})
        for r in d.get("returns", []):
            sig.append({"kind": "return", "events": [e["id"]], "text": r["label"].replace(
                "the first time", f"the first time in {round(r['days'])} days", 1)})
        if (d.get("read") or {}).get("goal"):                  # a module's event that says it is a turning in what the agent is after
            sig.append({"kind": "goal", "events": [e["id"]], "text": d["read"]["goal"]})
    for x in state.expectations(limit=30, since=since, surprising=True):
        if x["kind"] != "step" and x["ts"] <= now and x["event_id"]:
            sig.append({"kind": "surprise", "events": [x["event_id"]],
                        "text": f"{x['subject']}: you expected {x['expected']}; {x['actual']}"})
    today_top, n = _top_sender(events)
    before_top, _ = _top_sender([e for e in state.events_since(since - 7 * 86400, limit=5000) if e["ts"] <= since])
    if today_top and n >= 2 and before_top and today_top != before_top:
        sig.append({"kind": "partner", "events": [], "text": f"you talked with {today_top} most; before it was {before_top}"})
    sig += _baseline(state, stats, today, labels)
    kept, per_kind = [], {}
    for s in sig:  # cap each kind so one busy day of one thing doesn't swamp the list
        if per_kind.get(s["kind"], 0) < MAX_SIGNALS[s["kind"]]:
            per_kind[s["kind"]] = per_kind.get(s["kind"], 0) + 1
            kept.append({k: v for k, v in s.items() if k != "weight"})
    score = len(kept)
    return {"score": score, "flagged": score >= TURNING_MIN, "signals": kept}
