"""Real weather and daylight (see DESIGN-weather.md).

Pip is told the conditions outside and when the sun turns, and the weather nudges how long crops take to grow. Where the weather comes
from is a *provider*: a small class registered by name (`@register("homeassistant")`) that turns some source into a `Weather`. This module
is everything that does not care which source: the reading itself, how it is worded to Pip, the growing-time factors, keeping the last
reading in the state's meta table (so the tick never waits on a network call), and the throttled refresh. Pick the provider with
`WEATHER_PROVIDER`; add one by writing a module that registers a class with `ready` and `async fetch(http)`, then importing it at the bottom.

Providers must report one of the condition names in `CONDITIONS` (Home Assistant's vocabulary, which is a fair common denominator);
anything else is shown in plain words and has no effect on the garden.
"""
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Callable

import httpx

REFRESH_EVERY = 600        # seconds between requests to a provider
STALE_AFTER = 3600         # a reading older than this is not shown or used

# condition -> (how Pip hears it, growing-time multiplier). Rain helps, cold and snow hinder; the cap is +-15%.
CONDITIONS = {
    "sunny": ("sunny", 0.95), "clear-night": ("clear", 1.0), "partlycloudy": ("partly cloudy", 1.0),
    "cloudy": ("cloudy", 1.03), "rainy": ("rain", 0.85), "pouring": ("heavy rain", 0.85),
    "lightning-rainy": ("thunder and rain", 0.85), "lightning": ("thunder", 1.0), "snowy": ("snow", 1.15),
    "snowy-rainy": ("sleet", 1.1), "fog": ("fog", 1.05), "hail": ("hail", 1.1), "windy": ("windy", 1.0),
    "windy-variant": ("windy", 1.0), "exceptional": ("unusual weather", 1.0),
}
GROW_FACTORS = {k: v[1] for k, v in CONDITIONS.items()}


@dataclass(frozen=True)
class Weather:
    condition: str
    temp: float | None
    unit: str
    above_horizon: bool
    next_rising: float | None      # epoch seconds
    next_setting: float | None

    @property
    def grow_factor(self) -> float:
        return GROW_FACTORS.get(self.condition, 1.0)

    def line(self) -> str:
        words = CONDITIONS.get(self.condition, (self.condition.replace("-", " ").replace("_", " "), 1.0))[0]
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


class http_client:
    """`async with http_client(http) as client`: the caller's client if given (left open), else a fresh one."""
    def __init__(self, client=None):
        self.client, self.own = client, client is None

    async def __aenter__(self):
        if self.own:
            self.client = httpx.AsyncClient()
        return self.client

    async def __aexit__(self, *exc):
        if self.own:
            await self.client.aclose()
        return False


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


def grow_factor(state, settings, now: float) -> float:
    w = current(state, now) if settings.weather else None
    return w.grow_factor if w else 1.0


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
