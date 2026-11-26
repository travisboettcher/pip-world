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


NAP_MINUTES = (20, 120)      # a nap lasts until the agent is rested, within these (DESIGN-stamina.md)


def nap_before(settings) -> int:
    """The hour before which going to bed is a nap: NAP_BEFORE_HOUR, else two hours before the usual bedtime."""
    return settings.nap_before_hour if settings.nap_before_hour is not None else (settings.bedtime_hour - 2) % 24


def is_nap(settings, now: float) -> bool:
    """Whether going to bed now is a nap: by day, before the evening's cut-off (after it, an early night)."""
    h, nb, b = datetime.fromtimestamp(now).hour, nap_before(settings), settings.bedtime_hour
    early_night = (nb <= h < b) if nb <= b else (h >= nb or h < b)
    return not is_night(settings, now) and not early_night


def nap_until(state, settings, now: float) -> float:
    """When a nap ends: once the agent is rested at its asleep rate, within NAP_MINUTES."""
    from . import stats
    t = stats.tiring(settings)
    d = stats.declared(settings).get(t, {}) if t else {}
    rate = abs(d.get("asleep_per_hour", 0))                             # toward rested, whichever way the stat counts
    if not rate:
        return now + NAP_MINUTES[1] * 60
    v = state.agent()[t]
    to_go = (1 - v) if stats.good_sign(d) > 0 else v
    return now + min(max(to_go / rate * 60, NAP_MINUTES[0]), NAP_MINUTES[1]) * 60


def fall_asleep(state, settings, now: float | None = None, night: bool = False, doze: bool = False) -> dict:
    """The agent goes to bed: a nap until rested by day, the night's sleep until morning after the evening's cut-off (or whenever,
    with `night`: spent for the day; `doze`: exhausted, where it is). Returns when it will wake, and whether it is a nap."""
    now = now or time.time()
    nap = not night and is_nap(settings, now)
    until = nap_until(state, settings, now) if nap else next_wake(settings, now)
    state.update_agent(activity="sleeping", description="dozing" if doze else "napping" if nap else "asleep")
    state.set_meta(sleep_started=now, sleep_until=until, sleep_kind="nap" if nap else "night")
    return {"until": until, "nap": nap}


def wake_up(state, now: float | None = None) -> dict | None:
    """End sleep (on time, or early when something woke the agent). Call after apply_decay so the night's rest counts."""
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
    else:
        usual = datetime(2000, 1, 1, settings.bedtime_hour).strftime("%-I %p").lower()
        line += (f" You usually go to bed around {usual}; lying down now is a nap until you're rested." if is_nap(settings, now) else
                 f" You usually go to bed around {usual}; you can go to bed now for the night (you'd wake in the morning).")
    return [line]


def woke_text(d: dict) -> str:
    bits = [f"you woke after about {d['hours']:g} hours of sleep"]
    if d["early"]:
        bits.append("you were woken early; you can go back to sleep")
    return "; ".join(bits)
