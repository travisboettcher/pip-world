"""Emotion state: eight numbers (0-100) the engine keeps, moved by logged events by fixed rules (see DESIGN-emotions.md).

A functional model, not a claim that Pip feels: the numbers make its days more coherent. The engine owns them; Pip sees a short
readout and decides what to do. Every move is logged with its cause. Each emotion decays toward a baseline with its own half-life.
"""
import time
from datetime import datetime

NAMES = ("joy", "sadness", "anger", "fear", "trust", "disgust", "surprise", "anticipation")
BASELINE = {"joy": 45, "sadness": 15, "anger": 8, "fear": 10, "trust": 55, "disgust": 5, "surprise": 10, "anticipation": 35}
HALF_LIFE_MIN = {"joy": 360, "sadness": 1440, "anger": 180, "fear": 120, "trust": 2880, "disgust": 240, "surprise": 20, "anticipation": 240}
HIGH = 60                 # entering this band is worth an event
NOTABLE = 10              # how far from baseline an emotion must be to be shown to Pip
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

WORK = {"breakthrough": {"joy": 10, "surprise": 6, "anticipation": 5}, "good": {"joy": 4, "anticipation": 3}, "slow": {"sadness": 2},
        "setback": {"sadness": 8, "anger": 6}, "blowup": {"fear": 12, "sadness": 8, "anger": 8, "surprise": 8}}
EXPERIMENT = {"nothing": {"sadness": 3, "anger": 2}, "clue": {"anticipation": 3}, "insight": {"joy": 6, "anticipation": 4},
              "surprise": {"surprise": 12, "joy": 4}}
SURPRISE = {"better": {"surprise": 6, "joy": 4}, "worse": {"surprise": 6, "fear": 3, "sadness": 3}}
ALERT = {"hunger": {"anger": 6, "sadness": 2}, "energy": {"sadness": 5, "anger": 2}}


def decayed(value: float, baseline: float, half_life_min: float, minutes: float) -> float:
    """`value` after `minutes`: the distance from baseline halves every half-life."""
    if minutes <= 0:
        return value
    return baseline + (value - baseline) * 0.5 ** (minutes / half_life_min)


def levels(state, now: float | None = None) -> dict[str, float]:
    now = now or time.time()
    rows = state.emotion_rows()
    out = {}
    for n in NAMES:
        if n in rows:
            v, ts = rows[n]
            out[n] = decayed(v, BASELINE[n], HALF_LIFE_MIN[n], (now - ts) / 60)
        else:
            out[n] = float(BASELINE[n])
    return out


def _clamp(v: float) -> float:
    return max(0.0, min(100.0, v))


def nudge(state, deltas: dict, cause: str, now: float | None = None) -> dict[str, float]:
    """Move emotions by `deltas` (clamped to 0-100), log each move with its cause, and note entering the high band."""
    now = now or time.time()
    current = levels(state, now)
    for name, delta in deltas.items():
        if name not in BASELINE or not delta:
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
    current = levels(state, now)
    return nudge(state, {n: (BASELINE[n] - current[n]) * fraction for n in NAMES}, cause, now)


def _appraisal(kind: str, data: dict) -> tuple[dict, str]:
    """(moves, cause) for one logged event; empty when the event means nothing to feelings."""
    if kind == "gift":
        return {"joy": 10, "trust": 6, "surprise": 8}, f"{data.get('sender', 'someone')} gave a gift"
    if kind == "inbox":
        return {"joy": 5, "trust": 4, "sadness": -6}, f"{data.get('sender', 'someone')} wrote"
    if kind == "work":
        moves = dict(WORK.get(data.get("result"), {}))
        for k, v in SURPRISE.get(data.get("surprise"), {}).items():
            moves[k] = moves.get(k, 0) + v
        return moves, f"work went {data.get('result')}" + (f", {data['surprise']} than expected" if data.get("surprise") else "")
    if kind == "experiment":
        return dict(EXPERIMENT.get(data.get("outcome"), {})), f"an experiment: {data.get('outcome')}"
    if kind == "creation_made":
        return {"joy": 20, "anticipation": 6}, f"finished {data.get('name', 'something')}"
    if kind == "garden":
        return {"joy": 3}, f"{data.get('crop', 'a crop')} ripened"
    if kind == "alert":
        return dict(ALERT.get(data.get("stat"), {})), f"{data.get('stat')} needs attention"
    if kind == "happening":   # the startle lands at once; the meaning waits for Pip's reading (happenings.py)
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
    best, name = 0.0, None
    for pair, word in DYADS.items():
        strength = min(lv[n] - BASELINE[n] for n in pair)
        if strength >= BLEND_MIN_EXCESS and strength > best:
            best, name = strength, word
    return name


def snapshot(state, now: float | None = None) -> dict:
    lv = levels(state, now)
    v, a = valence(lv), arousal(lv)
    return {"emotions": [{"name": n, "value": round(lv[n]), "baseline": BASELINE[n]} for n in NAMES],
            "valence": v, "arousal": a, "valence_word": valence_word(v), "arousal_word": arousal_word(a), "blend": blend(lv)}


def readout(state, now: float | None = None) -> list[str]:
    """What Pip is shown: only what stands out, then the overall tone."""
    lv = levels(state, now)
    v, a, b = valence(lv), arousal(lv), blend(lv)
    notable = sorted((n for n in NAMES if abs(lv[n] - BASELINE[n]) >= NOTABLE), key=lambda n: -abs(lv[n] - BASELINE[n]))[:SHOWN]
    if not notable:
        return [f"Emotion state: close to your usual self ({valence_word(v)}, {arousal_word(a)})."]
    shown = ", ".join(f"{n} {round(lv[n])} ({round(lv[n] - BASELINE[n]):+d})" for n in notable)
    tail = f"; it feels like {b}" if b else ""
    return [f"Emotion state (0-100): {shown}.", f"Overall: {valence_word(v)}, {arousal_word(a)}{tail}."]


def perception(state, settings, now: float | None = None) -> list[str]:
    return readout(state, now) if settings.emotions == "on" else []


def _today(now: float) -> float:
    return datetime.fromtimestamp(now).replace(hour=0, minute=0, second=0, microsecond=0).timestamp()


def settle(state, settings, emotion: str, how: str = "", now: float | None = None) -> tuple[bool, str]:
    """Pip takes a quiet moment to ease one strong feeling. Limited per day; never below the usual level."""
    now = now or time.time()
    emotion = str(emotion or "").strip().lower()
    if emotion not in BASELINE:
        return False, f"you can settle one of: {', '.join(NAMES)}"
    if len([e for e in state.events(500) if e["kind"] == "settled" and e["ts"] >= _today(now)]) >= settings.emotion_settle_per_day:
        return False, "you've taken enough quiet moments today; it will ease on its own"
    before = levels(state, now)[emotion]
    if before - BASELINE[emotion] < SETTLE_MIN_EXCESS:
        return False, f"you're already settled: {emotion} is near its usual level"
    after = max(float(BASELINE[emotion]), before - SETTLE_EASE)
    state.set_emotion(emotion, after, now)
    state.add_emotion_log(now, emotion, after - before, after, "settled" + (f": {how}" if how else ""))
    state.log("settled", emotion=emotion, **{"from": round(before), "to": round(after)}, how=str(how or "")[:120])
    return True, f"You take a quiet moment. {emotion.capitalize()} eases from {round(before)} to {round(after)}."
