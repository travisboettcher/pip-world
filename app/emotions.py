"""Emotion state: eight numbers (0-100) the engine keeps, moved by logged events by fixed rules (see DESIGN-emotions.md).

A functional model, not a claim that the agent feels: the numbers make its days more coherent. The engine owns them; The agent sees a short
readout and decides what to do. Every move is logged with its cause. Each emotion decays toward a baseline with its own half-life; an agent's temperament (world.json) moves its baselines.
"""
import time
from datetime import datetime

NAMES = ("joy", "sadness", "anger", "fear", "trust", "disgust", "surprise", "anticipation")
BASELINE = {"joy": 45, "sadness": 15, "anger": 8, "fear": 10, "trust": 55, "disgust": 5, "surprise": 10, "anticipation": 35}
HALF_LIFE_MIN = {"joy": 360, "sadness": 1440, "anger": 180, "fear": 120, "trust": 2880, "disgust": 240, "surprise": 20, "anticipation": 240}
HIGH = 60                 # entering this band is worth an event
NOTABLE = 10              # how far from baseline an emotion must be to be shown to the agent
SHOWN = 4
WAKE_EASE = 0.4           # a night's sleep closes this fraction of every gap to baseline
SETTLE_EASE = 35          # points a settled feeling drops (never below baseline)
SETTLE_MIN_EXCESS = 5
LONELY_AFTER_HOURS = 8
DRIFT_EVERY_SECONDS = 3600

POSITIVE = ("joy", "trust", "anticipation")
NEGATIVE = ("sadness", "anger", "fear", "disgust")
AROUSING = ("anger", "fear", "surprise", "anticipation", "joy")
DYADS = {frozenset(("joy", "trust")): "warmth", frozenset(("trust", "fear")): "submission", frozenset(("fear", "surprise")): "awe",
         frozenset(("surprise", "sadness")): "disappointment", frozenset(("sadness", "disgust")): "remorse",
         frozenset(("disgust", "anger")): "contempt", frozenset(("anger", "anticipation")): "aggression",
         frozenset(("anticipation", "joy")): "optimism"}
BLEND_MIN_EXCESS = 8
TALKED = {"joy": 4, "trust": 2, "sadness": -3}   # a talk with another agent, once (the owner, 2026-11-18: not every line, as a visitor's), and once a day with each (2026-11-20)

def alert_feelings(stat: str) -> dict:
    """How an alert on a stat moves the emotions (the stat's `alert_feelings` in the pack's stats.json)."""
    from . import stats as stats_mod
    return stats_mod.declared().get(stat, {}).get("alert_feelings", {})


def baseline() -> dict[str, int]:
    """Where the acting agent's feelings rest: the engine's baselines, with its own temperament over them (world.json)."""
    from . import world_pack
    return {**BASELINE, **dict(world_pack.active().agent.temperament)}


def decayed(value: float, baseline: float, half_life_min: float, minutes: float) -> float:
    """`value` after `minutes`: the distance from baseline halves every half-life."""
    if minutes <= 0:
        return value
    return baseline + (value - baseline) * 0.5 ** (minutes / half_life_min)


def levels(state, now: float | None = None) -> dict[str, float]:
    now = now or time.time()
    rows, rest = state.emotion_rows(), baseline()
    out = {}
    for n in NAMES:
        if n in rows:
            v, ts = rows[n]
            out[n] = decayed(v, rest[n], HALF_LIFE_MIN[n], (now - ts) / 60)
        else:
            out[n] = float(rest[n])
    return out


def _clamp(v: float) -> float:
    return max(0.0, min(100.0, v))


def nudge(state, deltas: dict, cause: str, now: float | None = None) -> dict[str, float]:
    """Move emotions by `deltas` (clamped to 0-100), log each move with its cause, and note entering the high band."""
    now = now or time.time()
    current = levels(state, now)
    for name, delta in deltas.items():
        if name not in NAMES or not delta:
            continue
        before = current[name]
        after = _clamp(before + delta)
        current[name] = after
        state.set_emotion(name, after, now)
        state.add_emotion_log(now, name, float(delta), after, cause)
        if before < HIGH <= after:
            state.log("emotion", emotion=name, value=round(after), cause=cause)
    return current


def ease(state, fraction: float, cause: str, now: float | None = None) -> dict[str, float]:
    """Close `fraction` of every gap to baseline (a night's sleep)."""
    now = now or time.time()
    current, rest = levels(state, now), baseline()
    return nudge(state, {n: (rest[n] - current[n]) * fraction for n in NAMES}, cause, now)


def _appraisal(kind: str, data: dict) -> tuple[dict, str]:
    """(moves, cause) for one logged event; empty when the event means nothing to feelings."""
    if kind == "gift":
        return {"joy": 10, "trust": 6, "surprise": 8}, f"{data.get('sender', 'someone')} gave a gift"
    if kind == "inbox" and data.get("source") == "agent":   # another agent's line in a talk: the talk counts, once (below)
        return {}, ""
    if kind == "inbox":
        return {"joy": 5, "trust": 4, "sadness": -6}, f"{data.get('sender', 'someone')} wrote"
    if kind == "talk" and data.get("agent"):                # a talk with another agent, as company, once a day; how it felt is the agent's own `feel`
        return ({}, "") if data.get("again") else (dict(TALKED), f"talked with {data.get('name', 'someone')}")
    if (data.get("read") or {}).get("feel"):             # a module's event, and how it says it moves the agent (modules.py, `event.read`)
        return dict(data["read"]["feel"]), str(data["read"].get("line") or kind)[:80]
    if kind == "creation_made":
        return {"joy": 20, "anticipation": 6}, f"finished {data.get('name', 'something')}"
    if kind == "module" and data.get("feel"):         # a moment a module logged, and how it says it feels (modules.py, `log`)
        return dict(data["feel"]), str(data.get("text", ""))[:80]
    if kind == "alert":
        return dict(alert_feelings(data.get("stat"))), f"{data.get('stat')} needs attention"
    if kind == "stall_sale":
        return {"joy": 2}, f"sold {data['item']} at your stall" if data.get("item") else "sold something at your stall"
    if kind == "happening":   # the startle lands at once; the meaning waits for the agent's reading (happenings.py)
        return ({"surprise": data["jolt"]} if data.get("jolt") else {}), f"something happened: {data.get('title', 'an event')}"
    if kind == "happening_felt":
        return dict(data.get("moves") or {}), f"{data.get('title', 'an event')}, read as {data.get('read_as')}"
    if kind == "tool" and str(data.get("result", "")).startswith("error"):
        return {"anger": 2}, f"{data.get('tool')} failed"
    if kind == "outreach" and data.get("what") == "postcard" and data.get("delivered"):
        return {"anticipation": 6}, "a postcard went out"
    return {}, ""


def appraise(state, settings, kind: str, data: dict, now: float | None = None) -> None:
    if kind == "woke":
        ease(state, WAKE_EASE, "a night's sleep", now)
        return
    moves, cause = _appraisal(kind, data)
    if moves:
        nudge(state, moves, cause, now)


def attach(state, settings) -> None:
    """Start listening to the event log (unless emotions are off)."""
    if settings.emotions == "off":
        return
    state.listeners.append(lambda kind, data, ts: appraise(state, settings, kind, data, ts) if kind not in ("emotion", "settled") else None)


def drift(state, settings, now: float | None = None) -> None:
    """Hours without company slowly saddens; checked by the monitor, at most once an hour."""
    now = now or time.time()
    if settings.emotions == "off" or state.agent()["activity"] == "sleeping":
        return
    if now - float(state.meta("emotion_drift_ts") or 0) < DRIFT_EVERY_SECONDS:
        return
    heard = [e["ts"] for e in state.events(200) if e["kind"] == "inbox"]
    alone = now - (max(heard) if heard else state.born_at())
    if alone < LONELY_AFTER_HOURS * 3600:
        return
    state.set_meta(emotion_drift_ts=now)
    nudge(state, {"sadness": 3, "trust": -1}, f"alone for about {int(alone // 3600)} hours", now)


def valence(lv: dict) -> int:
    pos = sum(lv[n] for n in POSITIVE) / len(POSITIVE)
    neg = sum(lv[n] for n in NEGATIVE) / len(NEGATIVE)
    return round(pos - neg)


def arousal(lv: dict) -> int:
    return round(sum(lv[n] for n in AROUSING) / len(AROUSING))


def valence_word(v: int) -> str:
    return "very good" if v >= 55 else "pleasant" if v >= 25 else "neutral" if v >= 0 else "unpleasant" if v >= -25 else "bad"


def arousal_word(a: int) -> str:
    return "very calm" if a < 15 else "calm" if a < 30 else "stirred up" if a < 50 else "highly activated"


def blend(lv: dict) -> str | None:
    """The strongest Plutchik pair whose members are both clearly above their baselines."""
    best, name, rest = 0.0, None, baseline()
    for pair, word in DYADS.items():
        strength = min(lv[n] - rest[n] for n in pair)
        if strength >= BLEND_MIN_EXCESS and strength > best:
            best, name = strength, word
    return name


def snapshot(state, now: float | None = None) -> dict:
    lv, rest = levels(state, now), baseline()
    v, a = valence(lv), arousal(lv)
    return {"emotions": [{"name": n, "value": round(lv[n]), "baseline": rest[n]} for n in NAMES],
            "valence": v, "arousal": a, "valence_word": valence_word(v), "arousal_word": arousal_word(a), "blend": blend(lv)}


def readout(state, now: float | None = None) -> list[str]:
    """What the agent is shown: only what stands out, then the overall tone."""
    lv, rest = levels(state, now), baseline()
    v, a, b = valence(lv), arousal(lv), blend(lv)
    notable = sorted((n for n in NAMES if abs(lv[n] - rest[n]) >= NOTABLE), key=lambda n: -abs(lv[n] - rest[n]))[:SHOWN]
    if not notable:
        return [f"Emotion state: close to your usual self ({valence_word(v)}, {arousal_word(a)})."]
    shown = ", ".join(f"{n} {round(lv[n])} ({round(lv[n] - rest[n]):+d})" for n in notable)
    tail = f"; it feels like {b}" if b else ""
    return [f"Emotion state (0-100): {shown}.", f"Overall: {valence_word(v)}, {arousal_word(a)}{tail}."]


def perception(state, settings, now: float | None = None) -> list[str]:
    return readout(state, now) if settings.emotions == "on" else []


def _today(now: float) -> float:
    return datetime.fromtimestamp(now).replace(hour=0, minute=0, second=0, microsecond=0).timestamp()


def settle(state, settings, emotion: str, how: str = "", now: float | None = None) -> tuple[bool, str]:
    """The agent takes a quiet moment to ease one strong feeling. Limited per day; never below the usual level."""
    now = now or time.time()
    emotion = str(emotion or "").strip().lower()
    if emotion not in NAMES:
        return False, f"you can settle one of: {', '.join(NAMES)}"
    if len([e for e in state.events(500) if e["kind"] == "settled" and e["ts"] >= _today(now)]) >= settings.emotion_settle_per_day:
        return False, "you've taken enough quiet moments today; it will ease on its own"
    before, rest = levels(state, now)[emotion], baseline()[emotion]
    if before - rest < SETTLE_MIN_EXCESS:
        return False, f"you're already settled: {emotion} is near its usual level"
    after = max(float(rest), before - SETTLE_EASE)
    state.set_emotion(emotion, after, now)
    state.add_emotion_log(now, emotion, after - before, after, "settled" + (f": {how}" if how else ""))
    state.log("settled", emotion=emotion, **{"from": round(before), "to": round(after)}, how=str(how or "")[:120])
    return True, f"You take a quiet moment. {emotion.capitalize()} eases from {round(before)} to {round(after)}."
