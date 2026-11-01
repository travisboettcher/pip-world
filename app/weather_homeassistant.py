"""The Home Assistant weather provider (see DESIGN-weather.md).

Exactly two entities are ever read, with read-only GETs: the weather entity and `sun.sun`. There is no code path that calls another
entity or any service, so a long-lived token here can look at the sky and nothing else in the house.
"""
from datetime import datetime

from .weather import Weather, http_client, register

SUN_ENTITY = "sun.sun"
UNUSABLE = ("unavailable", "unknown")


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


@register("homeassistant")
class HomeAssistant:
    def __init__(self, settings):
        self.base = settings.hass_url.rstrip("/")
        self.token, self.entity = settings.hass_token, settings.weather_entity

    @property
    def ready(self) -> bool:
        return bool(self.token)

    async def fetch(self, http=None) -> Weather | None:
        headers = {"Authorization": f"Bearer {self.token}"}
        async with http_client(http) as client:
            got = [(await client.get(f"{self.base}/api/states/{entity}", headers=headers, timeout=10)).json()
                   for entity in (self.entity, SUN_ENTITY)]
        return parse(*got)
