"""Real weather and daylight (see DESIGN-weather.md).

The agent is told the conditions outside and when the sun turns; modules read the weather too (the garden's growing time is its own).
Where the weather comes from is a *provider*: a small class registered by name (`@register("homeassistant")`) that turns some source into a
`Weather`. This module is everything that does not care which source: the reading itself, how it is worded, keeping the last reading in the
state's meta table (so the tick never waits on a network call), and the throttled refresh. Pick the provider with
`WEATHER_PROVIDER`; add one by writing a module that registers a class with `ready` and `async fetch(http)`, then importing it at the bottom.

Providers must report one of the condition names in `CONDITIONS` (Home Assistant's vocabulary, which is a fair common denominator);
anything else is shown in plain words.
"""
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Callable

from .httpclient import http_client  # noqa: F401  (providers use it; kept importable from here)

REFRESH_EVERY = 600        # seconds between requests to a provider
STALE_AFTER = 3600         # a reading older than this is not shown or used

# condition -> how the agent hears it. What a condition does to the world (to a garden's growing, say) is a module's (it reads `weather`).
CONDITIONS = {
    "sunny": "sunny", "clear-night": "clear", "partlycloudy": "partly cloudy", "cloudy": "cloudy", "rainy": "rain", "pouring": "heavy rain",
    "lightning-rainy": "thunder and rain", "lightning": "thunder", "snowy": "snow", "snowy-rainy": "sleet", "fog": "fog", "hail": "hail",
    "windy": "windy", "windy-variant": "windy", "exceptional": "unusual weather",
}


@dataclass(frozen=True)
class Weather:
    condition: str
    temp: float | None
    unit: str
    above_horizon: bool
    next_rising: float | None      # epoch seconds
    next_setting: float | None

    def line(self) -> str:
        words = CONDITIONS.get(self.condition, self.condition.replace("-", " ").replace("_", " "))
        head = f"Outside: {words}" + (f", {round(self.temp)} {self.unit}" if self.temp is not None else "")
        turn, at = ("sets", self.next_setting) if self.above_horizon else ("rises", self.next_rising)
        sun = f"; the sun {turn} at {datetime.fromtimestamp(at).strftime('%-I:%M %p')}" if at else ""
        return head + sun + "."


# --- providers ------------------------------------------------------------------------------------------------------
PROVIDERS: dict[str, Callable] = {}      # name -> class(settings) with `ready` and `async fetch(http) -> Weather | None`


def register(name: str):
    def add(cls):
        PROVIDERS[name] = cls
        return cls
    return add


def provider(settings):
    """The configured provider, or None if the name is unknown."""
    cls = PROVIDERS.get(settings.weather_provider)
    return cls(settings) if cls else None


# --- the stored reading ---------------------------------------------------------------------------------------------
def save(state, w: Weather, now: float) -> None:
    state.set_meta(weather=json.dumps(w.__dict__), weather_at=now)


def current(state, now: float) -> Weather | None:
    raw, at = state.meta("weather"), state.meta("weather_at")
    if not raw or not at or now - float(at) > STALE_AFTER:
        return None
    return Weather(**json.loads(raw))


def perception(state, settings, now: float) -> list[str]:
    w = current(state, now) if settings.weather else None
    return [w.line()] if w else []


async def refresh(state, settings, now: float, http=None) -> bool:
    """Ask the provider (at most every REFRESH_EVERY seconds). True if a fresh reading was stored."""
    if not settings.weather:
        return False
    source = provider(settings)
    if not source or not source.ready:
        return False
    if now - float(state.meta("weather_try_at") or 0) < REFRESH_EVERY:
        return False
    state.set_meta(weather_try_at=now)
    try:
        w = await source.fetch(http)
    except Exception:
        return False
    if not w:
        return False
    save(state, w, now)
    return True


from . import weather_homeassistant  # noqa: E402,F401  (registers the "homeassistant" provider)
