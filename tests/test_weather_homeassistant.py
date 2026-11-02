from datetime import datetime, timezone

import pytest

from app import weather as W
from app import weather_homeassistant as HA
from app.config import Settings


def iso(hour, minute=0):
    return datetime(2026, 11, 1, hour, minute).astimezone(timezone.utc).isoformat()


def ha(condition="rainy", temp=8.0, unit="°C", above=True, rising=None, setting=None):
    weather = {"state": condition, "attributes": {"temperature": temp, "temperature_unit": unit}}
    sun = {"state": "above_horizon" if above else "below_horizon",
           "attributes": {"next_rising": rising or iso(7, 10), "next_setting": setting or iso(16, 52)}}
    return weather, sun


def test_parse_reads_condition_temperature_and_sun():
    w = HA.parse(*ha())
    assert (w.condition, w.temp, w.unit, w.above_horizon) == ("rainy", 8.0, "C", True)
    assert w.next_setting == datetime.fromisoformat(iso(16, 52)).timestamp() and w.next_rising == datetime.fromisoformat(iso(7, 10)).timestamp()
    assert HA.parse(*ha(unit="°F", temp=46.4)).unit == "F"
    assert HA.parse(*ha(temp="7.5")).temp == 7.5
    no_unit = {"state": "rainy", "attributes": {"temperature": 8}}
    assert HA.parse(no_unit, ha()[1]).unit == "C"
    assert HA.parse({"state": "rainy", "attributes": {"temperature": 8, "temperature_unit": "°"}}, ha()[1]).unit == "C"
    assert HA.parse({"state": "rainy", "attributes": {"temperature": 8, "temperature_unit": " °F "}}, ha()[1]).unit == "F"
    assert HA.parse(*ha(temp=None)).temp is None and HA.parse(*ha(temp="warm")).temp is None
    assert HA.parse(*ha(above=False)).above_horizon is False


def test_parse_gives_up_on_unusable_answers():
    good_w, good_s = ha()
    assert HA.parse(None, good_s) is None and HA.parse(good_w, None) is None
    assert HA.parse({"state": "unavailable", "attributes": {}}, good_s) is None
    assert HA.parse({"state": "unknown", "attributes": {}}, good_s) is None
    assert HA.parse({"attributes": {}}, good_s) is None
    assert HA.parse("rain", good_s) is None and HA.parse(good_w, "up") is None
    w = HA.parse(good_w, {"state": "above_horizon", "attributes": {"next_setting": "soon"}})
    assert w.next_setting is None and w.line() == "Outside: rain, 8 C."


class FakeHA:
    def __init__(self, answers, fail=False):
        self.answers, self.fail, self.calls, self.timeouts = answers, fail, [], []

    async def get(self, url, headers=None, timeout=None):
        self.calls.append((url, headers))
        self.timeouts.append(timeout)
        if self.fail:
            raise OSError("down")
        body = self.answers[url.rsplit("/api/states/", 1)[1]]

        class R:
            status_code = 200

            def json(_):
                return body
        return R()


def settings(**kw):
    return Settings(weather=True, hass_url="http://ha:8123/", hass_token="tok", weather_entity="weather.home", **kw)


def test_it_is_the_default_provider_and_is_ready_only_with_a_token():
    assert Settings().weather_provider == "homeassistant" and W.PROVIDERS["homeassistant"] is HA.HomeAssistant
    assert isinstance(W.provider(settings()), HA.HomeAssistant)
    assert W.provider(settings()).ready is True and W.provider(Settings(weather=True, hass_token="")).ready is False


@pytest.mark.asyncio
async def test_it_reads_exactly_two_entities_with_the_token():
    weather, sun = ha("snowy")
    http = FakeHA({"weather.home": weather, "sun.sun": sun})
    w = await W.provider(settings()).fetch(http)
    assert w.condition == "snowy"
    assert sorted(u for u, _ in http.calls) == ["http://ha:8123/api/states/sun.sun", "http://ha:8123/api/states/weather.home"]
    assert all(h == {"Authorization": "Bearer tok"} for _, h in http.calls) and http.timeouts == [10, 10]


@pytest.mark.asyncio
async def test_an_unusable_answer_gives_nothing_and_a_failure_is_left_to_the_caller():
    unusable = FakeHA({"weather.home": {"state": "unavailable", "attributes": {}}, "sun.sun": ha()[1]})
    assert await W.provider(settings()).fetch(unusable) is None
    with pytest.raises(OSError):
        await W.provider(settings()).fetch(FakeHA({}, fail=True))


def test_the_default_address_is_the_standard_home_assistant_one_and_can_be_set(monkeypatch):
    monkeypatch.delenv("HASS_URL", raising=False)
    assert Settings().hass_url == "http://homeassistant.local:8123" and Settings.from_env().hass_url == "http://homeassistant.local:8123"
    monkeypatch.setenv("HASS_URL", "http://ha.example:8123")
    assert Settings.from_env().hass_url == "http://ha.example:8123"
