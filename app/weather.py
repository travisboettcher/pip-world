"""Real weather and daylight (see DESIGN-weather.md).

Home Assistant already knows the sky over the homelab. Pip is told the conditions and when the sun turns, and the weather nudges how
long crops take to grow. Exactly two entities are ever read, with read-only GETs: the weather entity and `sun.sun`. Nothing here can
touch anything else in the house. The reading is kept in the state's meta table, so the tick never waits on Home Assistant.
"""
import json
from dataclasses import dataclass
from datetime import datetime

import httpx

SUN_ENTITY = "sun.sun"
REFRESH_EVERY = 600        # seconds between requests to Home Assistant
STALE_AFTER = 3600         # a reading older than this is not shown or used
UNUSABLE = ("unavailable", "unknown")

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
    next_rising: float | None
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


def _time(v) -> float | None:
    try:
        return datetime.fromisoformat(str(v)).timestamp()
    except (TypeError, ValueError):
        return None


def _temp(v) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def parse(weather, sun) -> Weather | None:
    """Home Assistant's two state objects -> Weather, or None if either is missing or unusable."""
    if not isinstance(weather, dict) or not isinstance(sun, dict):
        return None
    condition = weather.get("state")
    if not isinstance(condition, str) or condition in UNUSABLE:
        return None
    at, sa = weather.get("attributes") or {}, sun.get("attributes") or {}
    unit = str(at.get("temperature_unit") or "C").replace("°", "").strip() or "C"
    return Weather(condition, _temp(at.get("temperature")), unit, sun.get("state") == "above_horizon",
                   _time(sa.get("next_rising")), _time(sa.get("next_setting")))


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
    """Ask Home Assistant (at most every REFRESH_EVERY seconds). True if a fresh reading was stored."""
    if not (settings.weather and settings.hass_token):
        return False
    if now - float(state.meta("weather_try_at") or 0) < REFRESH_EVERY:
        return False
    state.set_meta(weather_try_at=now)
    base, headers = settings.hass_url.rstrip("/"), {"Authorization": f"Bearer {settings.hass_token}"}
    try:
        async with (http and _Borrowed(http) or httpx.AsyncClient()) as client:
            got = [(await client.get(f"{base}/api/states/{entity}", headers=headers, timeout=10)).json()
                   for entity in (settings.weather_entity, SUN_ENTITY)]
    except Exception:
        return False
    w = parse(*got)
    if not w:
        return False
    save(state, w, now)
    return True


class _Borrowed:
    """Lets a caller-supplied client be used in `async with` without being closed."""
    def __init__(self, client):
        self.client = client

    async def __aenter__(self):
        return self.client

    async def __aexit__(self, *exc):
        return False
