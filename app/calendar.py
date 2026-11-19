"""The calendar (the owner, 2026-11-19; docs/DESIGN-calendar.md): a section of the agent's journal for commitments with a time, the
promises a to-do can't keep. An agent carried "Thursday at half past four" at a neighbour's as a to-do for weeks, restating it every wake and
keeping it on the wrong day. A commitment has a time (the engine reads "Thursday 16:30", so the model does no date sums), maybe a place
and a weekly repeat. The agent sees what is coming in the next few days, with when to set off; it is woken when it's time to go; and an
hour after, the engine says whether it was kept (it was at the place in time), missed, or simply came. A weekly one moves on a week.
"""
import re
import time
from datetime import datetime, timedelta

from . import places

DAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
PARTS = {"morning": (8, 0), "noon": (12, 0), "midday": (12, 0), "afternoon": (14, 0), "evening": (18, 0), "night": (21, 0)}
WEEK = 7 * 86400
AHEAD_DAYS = 3                  # how far ahead the agent is shown
EARLY, LATE = 30 * 60, 60 * 60  # at the place from half an hour before to an hour after: kept; an hour after, it is settled


def parse(text: str, now: float) -> float | None:
    """When a commitment is, read from words: "Thursday 16:30", "tomorrow morning", "Friday 4:30 pm", "2026-11-24 09:15", "today noon"
    (a day alone is its morning). None if it can't be read, or is already past."""
    t = " ".join(str(text or "").lower().replace(" at ", " ").split())
    m = re.fullmatch(r"(today|tomorrow|monday|tuesday|wednesday|thursday|friday|saturday|sunday|\d{4}-\d{2}-\d{2})"
                     r"(?: (\d{1,2})(?::(\d{2}))? ?(am|pm)?| (morning|noon|midday|afternoon|evening|night))?", t)
    if not m:
        return None
    day, hour, minute, half, part = m.groups()
    if part:
        hour, minute = PARTS[part]
    elif hour is None:
        hour, minute = PARTS["morning"]
    else:
        hour, minute = int(hour), int(minute or 0)
        if half:
            if not 1 <= hour <= 12:
                return None
            hour = hour % 12 + (12 if half == "pm" else 0)
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return None
    today = datetime.fromtimestamp(now).replace(hour=hour, minute=minute, second=0, microsecond=0)
    if day == "today":
        when = today
    elif day == "tomorrow":
        when = today + timedelta(days=1)
    elif day in DAYS:
        when = today + timedelta(days=(DAYS.index(day) - today.weekday()) % 7)
        if when.timestamp() <= now:
            when += timedelta(days=7)                     # that day's time has gone this week: next week's
    else:
        try:
            when = datetime.strptime(day, "%Y-%m-%d").replace(hour=hour, minute=minute)
        except ValueError:
            return None
    return when.timestamp() if when.timestamp() > now else None


def say_when(ts: float) -> str:
    """"Thursday 19 November, 4:30 pm"."""
    d = datetime.fromtimestamp(ts)
    return f"{d:%A} {d.day} {d:%B}, {d.hour % 12 or 12}:{d:%M} {'am' if d.hour < 12 else 'pm'}"


def clock(ts: float) -> str:
    d = datetime.fromtimestamp(ts)
    return f"{d.hour % 12 or 12}:{d:%M} {'am' if d.hour < 12 else 'pm'}"


def _until(ts: float, now: float) -> str:
    days = (datetime.fromtimestamp(ts).date() - datetime.fromtimestamp(now).date()).days
    if days == 0:
        hours = round((ts - now) / 3600)
        return f"today, in about {hours} hour{'' if hours == 1 else 's'}" if hours >= 1 else "today, within the hour"
    return "tomorrow" if days == 1 else f"in {days} days"


def _where(place: str) -> str:
    return f" at {places.label(place)}" if place else ""


def walk_minutes(state, settings, library, place: str) -> float:
    """How long the walk there is (nothing from where the agent is already)."""
    if not place or places.present_at(state) == place:
        return 0.0
    rec = places.registry(state, settings, library).get(place)
    return float(rec.walk_minutes if rec else 0)


def open_items(state) -> list[dict]:
    return sorted(state.memories("calendar", status="open", limit=200), key=lambda m: m["due_at"] or 0)


def lines(state, settings, library, now: float | None = None, here: str | None = None) -> list[str]:
    """What the agent is shown: what it missed (once), what is due now, and what is coming in the next few days."""
    now, out = now or time.time(), []
    here = here if here is not None else places.present_at(state)
    for e in state.events(50):
        d = e["data"]
        if e["kind"] == "calendar" and d.get("outcome") == "missed" and not state.meta(f"cal_told:{e['id']}"):
            state.set_meta(**{f"cal_told:{e['id']}": "1"})
            out.append(f"- You missed: {d['text']} ({say_when(d['due_at'])}{', ' + places.label(d['place']) if d.get('place') else ''})"
                       .replace(", the", ", at the").replace(", home", ", at home"))
    for m in open_items(state):
        due = m["due_at"]
        if due is None or due - now > AHEAD_DAYS * 86400:
            continue
        walk = walk_minutes(state, settings, library, m["place"])
        go = due - walk * 60
        if m["place"] and here == m["place"] and now >= due - EARLY:
            out.append(f"- Now, here: {m['text']} (#{m['id']}, {clock(due)})")
        elif now >= go:
            out.append(f"- It's time to set off: {m['text']}{_where(m['place'])}, at {clock(due)} (#{m['id']})")
        else:
            leave = f"; a {round(walk)}-minute walk: set off by {clock(go)}" if walk else ""
            out.append(f"- {say_when(due)} ({_until(due, now)}){_where(m['place'])}: {m['text']} (#{m['id']}{leave})")
    return ["Your calendar (what's coming; it will remind you):"] + out if out else []


def step(state, settings, library, now: float | None = None) -> bool:
    """The monitor's look at the calendar (cheap, no model): note whether the agent is where a commitment is while it's due, settle the
    ones an hour past, and say whether it's time to wake the agent for one (once each)."""
    now, wake = now or time.time(), False
    here = places.present_at(state)
    for m in open_items(state):
        due, key = m["due_at"], f"{m['id']}:{m['due_at']}"
        if due is None:
            continue
        if m["place"] and here == m["place"] and due - EARLY <= now <= due + LATE:
            state.set_meta(**{f"cal_kept:{key}": "1"})
        if now > due + LATE:
            outcome = ("kept" if state.meta(f"cal_kept:{key}") else "missed") if m["place"] else "its time came"
            state.log("calendar", id=m["id"], text=m["text"], due_at=due, place=m["place"], outcome=outcome)
            if m["every"]:
                nxt = due
                while nxt <= now:
                    nxt += m["every"]
                state.update_memory_due(m["id"], nxt)
            else:
                state.resolve_memory(m["id"], outcome)
            continue
        go = due - walk_minutes(state, settings, library, m["place"]) * 60
        if now >= go and not state.meta(f"cal_woke:{key}"):
            state.set_meta(**{f"cal_woke:{key}": "1"})
            wake = True
    return wake
