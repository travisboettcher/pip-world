"""Day, night and sleep (see DESIGN-sleep.md). Pure rules on the local clock; the loop and tools call in here."""
import time
from datetime import datetime, timedelta


def is_night(settings, now: float) -> bool:
    h = datetime.fromtimestamp(now).hour
    b, w = settings.bedtime_hour, settings.wake_hour
    return (h >= b or h < w) if b > w else (b <= h < w)


def period(settings, now: float) -> str:
    h = datetime.fromtimestamp(now).hour
    if is_night(settings, now):
        return "night"
    return "morning" if h < 12 else "afternoon" if h < 17 else "evening"


def next_wake(settings, now: float) -> float:
    dt = datetime.fromtimestamp(now)
    target = dt.replace(hour=settings.wake_hour, minute=0, second=0, microsecond=0)
    return (target + timedelta(days=1) if target <= dt else target).timestamp()


def asleep(state) -> bool:
    return state.agent()["activity"] == "sleeping"


def day_number(state, now: float) -> int:
    return int(max(0.0, now - state.born_at()) // 86400) + 1


def fall_asleep(state, settings, now: float | None = None) -> dict:
    """Pip goes to bed. Returns when it will wake."""
    now = now or time.time()
    until = next_wake(settings, now)
    state.update_agent(activity="sleeping", description="asleep")
    state.set_meta(sleep_started=now, sleep_until=until)
    return {"until": until}


def wake_up(state, now: float | None = None) -> dict | None:
    """End sleep (on time, or early when something woke Pip). Call after apply_decay so the night's rest counts."""
    if not asleep(state):
        return None
    now = now or time.time()
    started = float(state.meta("sleep_started") or now)
    until = float(state.meta("sleep_until") or now)
    data = {"hours": round((now - started) / 3600, 1), "early": now < until - 60}
    state.update_agent(activity="idle", description="")
    state.set_meta(sleep_until=0)
    state.log("woke", **data)
    return data


def perception(state, settings, now: float) -> list[str]:
    if not settings.sleep:
        return []
    line = f"It is {period(settings, now)}; day {day_number(state, now)} of your life here."
    if is_night(settings, now):
        line += " You can go to bed (sleep); you'll wake in the morning."
    return [line]


def woke_text(d: dict) -> str:
    bits = [f"you woke after about {d['hours']:g} hours of sleep"]
    if d["early"]:
        bits.append("you were woken early; you can go back to sleep")
    return "; ".join(bits)
