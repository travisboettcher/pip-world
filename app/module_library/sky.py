# The sky (docs/DESIGN-world-packs.md, phase 5e): the world's weather and season. Every ten minutes it asks the engine's `weather` source
# (the real sky outside: Home Assistant) and publishes what it found as the world's `weather`, with the `season` (from the date, the right
# way round for the hemisphere). The scene, happenings, layouts and other modules read what it publishes; the agent sees it as "Outside".
from datetime import date

EVERY = 600
SEASON_OF_MONTH = ("winter", "winter", "spring", "spring", "spring", "summer", "summer", "summer", "autumn", "autumn", "autumn", "winter")
# how the agent hears a condition (Home Assistant's vocabulary); anything else is shown in plain words
CONDITIONS = {
    "sunny": "sunny", "clear-night": "clear", "partlycloudy": "partly cloudy", "cloudy": "cloudy", "rainy": "rain", "pouring": "heavy rain",
    "lightning-rainy": "thunder and rain", "lightning": "thunder", "snowy": "snow", "snowy-rainy": "sleet", "fog": "fog", "hail": "hail",
    "windy": "windy", "windy-variant": "windy", "exceptional": "unusual weather",
}


def local_day(ts, offset):
    return date.fromordinal(719163 + int((ts + offset) // 86400))


def season(ctx):
    month = local_day(ctx["now"], ctx["time"]["utc_offset"]).month - 1
    return SEASON_OF_MONTH[(month + (6 if ctx["params"]["hemisphere"] == "south" else 0)) % 12]


def clock(ts, offset):
    """A time as the agent reads it: 4:31 PM."""
    minutes = int(((ts + offset) % 86400) // 60)
    h, m = divmod(minutes, 60)
    return str(h % 12 or 12) + ":" + ("0" if m < 10 else "") + str(m) + (" AM" if h < 12 else " PM")


def line(w, offset):
    words = CONDITIONS.get(w["condition"], w["condition"].replace("-", " ").replace("_", " "))
    head = words + (", " + str(round(w["temp"])) + " " + w["unit"] if w["temp"] is not None else "")
    turn, at = ("sets", w["next_setting"]) if w["daylight"] else ("rises", w["next_rising"])
    return head + ("; the sun " + turn + " at " + clock(at, offset) if at else "") + "."


def ask(ctx):
    return {"source": {"name": "weather", "op": "now"}, "schedule": ctx["now"] + EVERY}


def on_install(ctx):
    return ask(ctx)


def on_time(ctx):
    return ask(ctx)


def on_source(ctx):
    w = ctx["source"]["answer"].get("reading")
    out = {"publish": {"weather": w, "season": season(ctx)}}
    out["status"] = {"title": "Outside", "lines": [line(w, ctx["time"]["utc_offset"])]} if w else {}
    return out
