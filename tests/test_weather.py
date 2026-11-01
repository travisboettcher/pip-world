import json
import time
from datetime import datetime, timezone

import pytest

from app import weather as W
from app.config import Settings
from tests.test_projects import call, make, report

NOW = datetime(2026, 11, 1, 14, 0).timestamp()


def iso(hour, minute=0):
    return datetime(2026, 11, 1, hour, minute).astimezone(timezone.utc).isoformat()


def ha(condition="rainy", temp=8.0, unit="°C", above=True, rising=None, setting=None):
    weather = {"state": condition, "attributes": {"temperature": temp, "temperature_unit": unit}}
    sun = {"state": "above_horizon" if above else "below_horizon",
           "attributes": {"next_rising": rising or iso(7, 10), "next_setting": setting or iso(16, 52)}}
    return weather, sun


def test_parse_reads_condition_temperature_and_sun():
    w = W.parse(*ha())
    assert (w.condition, w.temp, w.unit, w.above_horizon) == ("rainy", 8.0, "C", True)
    assert W.parse(*ha(unit="°F", temp=46.4)).unit == "F"
    assert W.parse(*ha(temp="7.5")).temp == 7.5
    no_unit = {"state": "rainy", "attributes": {"temperature": 8}}
    assert W.parse(no_unit, ha()[1]).unit == "C"
    assert W.parse({"state": "rainy", "attributes": {"temperature": 8, "temperature_unit": "°"}}, ha()[1]).unit == "C"
    assert W.parse({"state": "rainy", "attributes": {"temperature": 8, "temperature_unit": " °F "}}, ha()[1]).unit == "F"
    assert W.parse(*ha(temp=None)).temp is None and W.parse(*ha(temp="warm")).temp is None


def test_parse_gives_up_on_unusable_answers():
    good_w, good_s = ha()
    assert W.parse(None, good_s) is None and W.parse(good_w, None) is None
    assert W.parse({"state": "unavailable", "attributes": {}}, good_s) is None
    assert W.parse({"state": "unknown", "attributes": {}}, good_s) is None
    assert W.parse({"attributes": {}}, good_s) is None
    assert W.parse("rain", good_s) is None and W.parse(good_w, "up") is None
    w = W.parse(good_w, {"state": "above_horizon", "attributes": {"next_setting": "soon"}})
    assert w.next_setting is None and w.line() == "Outside: rain, 8 C."


def test_the_line_says_what_it_is_like_and_when_the_sun_turns():
    assert W.parse(*ha()).line() == "Outside: rain, 8 C; the sun sets at 4:52 PM."
    assert W.parse(*ha(above=False)).line() == "Outside: rain, 8 C; the sun rises at 7:10 AM."
    assert W.parse(*ha("partlycloudy", 21.0)).line() == "Outside: partly cloudy, 21 C; the sun sets at 4:52 PM."
    assert W.parse(*ha("clear-night", 3.4)).line() == "Outside: clear, 3 C; the sun sets at 4:52 PM."
    assert W.parse(*ha("lightning-rainy")).line().startswith("Outside: thunder and rain, 8 C")
    assert W.parse(*ha("mystery-weather", None)).line() == "Outside: mystery weather; the sun sets at 4:52 PM."
    assert W.parse(*ha(temp=None)).line().startswith("Outside: rain; the sun")
    assert W.parse(*ha("very_odd-sky", None)).line().startswith("Outside: very odd sky;")


def test_growing_time_is_scaled_by_the_weather_within_a_cap():
    f = lambda c: W.parse(*ha(c)).grow_factor  # noqa: E731
    assert f("sunny") == 0.95 and f("rainy") == 0.85 and f("pouring") == 0.85
    assert f("snowy") == 1.15 and f("cloudy") == 1.03 and f("partlycloudy") == 1.0
    assert f("mystery-weather") == 1.0
    assert all(0.85 <= v <= 1.15 for v in W.GROW_FACTORS.values())


def test_the_weather_is_kept_in_the_state_and_goes_stale_after_an_hour(tmp_path):
    s, st, *_ = make(tmp_path)
    assert W.current(st, NOW) is None
    W.save(st, W.parse(*ha()), NOW)
    got = W.current(st, NOW + 3599)
    assert got.condition == "rainy" and got.temp == 8.0 and got.line().startswith("Outside: rain, 8 C")
    assert W.current(st, NOW + 3600).condition == "rainy" and W.current(st, NOW + 3601) is None
    st.set_meta(weather_at="", weather="")
    assert W.current(st, NOW) is None
    st.set_meta(weather=json.dumps(got.__dict__))                      # a reading without its time is not trusted
    st.set_meta(weather_at="")
    assert W.current(st, NOW) is None
    W.save(st, W.parse(*ha("snowy")), NOW + 4000)
    assert W.current(st, NOW + 4001).condition == "snowy"


def test_perception_and_growth_need_the_feature_on_and_a_fresh_reading(tmp_path):
    s, st, *_ = make(tmp_path)
    W.save(st, W.parse(*ha()), NOW)
    assert W.perception(st, s, NOW) == [] and W.grow_factor(st, s, NOW) == 1.0          # off by default
    s.weather = True
    assert W.perception(st, s, NOW) == [W.parse(*ha()).line()] and W.grow_factor(st, s, NOW) == 0.85
    assert W.perception(st, s, NOW + 7200) == [] and W.grow_factor(st, s, NOW + 7200) == 1.0   # stale: say nothing


class FakeHA:
    def __init__(self, answers, fail=False):
        self.answers, self.fail, self.calls = answers, fail, []

    async def get(self, url, headers=None, timeout=None):
        self.calls.append((url, headers))
        self.timeouts = getattr(self, "timeouts", []) + [timeout]
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


@pytest.mark.asyncio
async def test_refresh_reads_exactly_two_entities_with_the_token_and_remembers_the_answer(tmp_path):
    s, st, *_ = make(tmp_path)
    s2 = settings()
    weather, sun = ha("snowy")
    http = FakeHA({"weather.home": weather, "sun.sun": sun})
    assert await W.refresh(st, s2, NOW, http) is True
    assert sorted(u for u, _ in http.calls) == ["http://ha:8123/api/states/sun.sun", "http://ha:8123/api/states/weather.home"]
    assert all(h == {"Authorization": "Bearer tok"} for _, h in http.calls)
    assert W.current(st, NOW).condition == "snowy"
    assert await W.refresh(st, s2, NOW + 60, http) is False and len(http.calls) == 2      # asked recently: no new request
    assert await W.refresh(st, s2, NOW + 599, http) is False and len(http.calls) == 2
    assert await W.refresh(st, s2, NOW + 600, http) is True and len(http.calls) == 4
    assert http.timeouts == [10, 10, 10, 10]


@pytest.mark.asyncio
async def test_refresh_does_nothing_without_the_feature_or_a_token_and_survives_failures(tmp_path):
    s, st, *_ = make(tmp_path)
    http = FakeHA({})
    assert await W.refresh(st, Settings(weather=False, hass_token="tok"), NOW, http) is False
    assert await W.refresh(st, Settings(weather=True, hass_token=""), NOW, http) is False and http.calls == []
    W.save(st, W.parse(*ha()), NOW)
    assert await W.refresh(st, settings(), NOW + 700, FakeHA({}, fail=True)) is False
    assert W.current(st, NOW + 800).condition == "rainy"                                    # the last good reading stays
    assert await W.refresh(st, settings(), NOW + 1400, FakeHA({"weather.home": {"state": "unavailable", "attributes": {}},
                                                                "sun.sun": ha()[1]})) is False
    assert W.current(st, NOW + 1500).condition == "rainy"


@pytest.mark.asyncio
async def test_planting_takes_the_weather_into_account(tmp_path):
    s, st, gm, agent = make(tmp_path)
    s.weather = True
    W.save(st, W.parse(*ha("rainy")), time.time())
    r = await call(agent, "plant", seed="carrot seeds")        # 45 minutes of growing, 15% less in the rain
    assert "ready in about 38 min" in r.text
    plot = st.garden()[0]
    assert plot["ready_in_min"] in (38, 39)
    s.weather = False
    r = await call(agent, "plant", seed="tomato seeds")
    assert "ready in about 60 min" in r.text
