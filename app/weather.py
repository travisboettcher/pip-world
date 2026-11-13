"""Real weather and daylight (see DESIGN-weather.md): the engine's `weather` source (sources.py).

The shipped `sky` module asks it and publishes the world's weather, which the agent is told ("Outside") and the scene and modules read.
Where the weather comes from is a *provider*: a small class registered by name (`@register("homeassistant")`) that turns some source into a
`Weather`. This module is everything that does not care which source: the reading itself, how it is worded, keeping the last reading in the
state's meta table (so the tick never waits on a network call), and the throttled refresh. Pick the provider with
`WEATHER_PROVIDER`; add one by writing a module that registers a class with `ready` and `async fetch(http)`, then importing it at the bottom.

Providers report Home Assistant's condition names (a fair common denominator); how each is worded is the sky module's.
"""
import json
from dataclasses import dataclass
from typing import Callable

from .httpclient import http_client  # noqa: F401  (providers use it; kept importable from here)

REFRESH_EVERY = 600        # seconds between requests to a provider
STALE_AFTER = 3600         # a reading older than this is not shown or used

@dataclass(frozen=True)
class Weather:
    condition: str
    temp: float | None
    unit: str
    above_horizon: bool
    next_rising: float | None      # epoch seconds
    next_setting: float | None


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
