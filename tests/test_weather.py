import json
import time
from datetime import datetime

import pytest

from app import weather as W
from app.config import Settings
from tests.test_projects import call, make

NOW = datetime(2026, 11, 1, 14, 0).timestamp()
SETS = datetime(2026, 11, 1, 16, 52).timestamp()
RISES = datetime(2026, 11, 1, 7, 10).timestamp()


def reading(condition="rainy", temp=8.0, unit="C", above=True, rising=RISES, setting=SETS):
    return W.Weather(condition, temp, unit, above, rising, setting)


def test_the_line_says_what_it_is_like_and_when_the_sun_turns():
    assert reading().line() == "Outside: rain, 8 C; the sun sets at 4:52 PM."
    assert reading(above=False).line() == "Outside: rain, 8 C; the sun rises at 7:10 AM."
    assert reading("partlycloudy", 21.0).line() == "Outside: partly cloudy, 21 C; the sun sets at 4:52 PM."
    assert reading("clear-night", 3.4).line() == "Outside: clear, 3 C; the sun sets at 4:52 PM."
    assert reading("lightning-rainy").line().startswith("Outside: thunder and rain, 8 C")
    assert reading("mystery-weather", None).line() == "Outside: mystery weather; the sun sets at 4:52 PM."
    assert reading(temp=None).line().startswith("Outside: rain; the sun")
    assert reading("very_odd-sky", None).line().startswith("Outside: very odd sky;")
    assert reading("rainy", 46.4, "F").line() == "Outside: rain, 46 F; the sun sets at 4:52 PM."
    assert reading(setting=None).line() == "Outside: rain, 8 C." and reading(above=False, rising=None).line() == "Outside: rain, 8 C."


def test_growing_time_is_scaled_by_the_weather_within_a_cap():
    f = lambda c: reading(c).grow_factor  # noqa: E731
    assert f("sunny") == 0.95 and f("rainy") == 0.85 and f("pouring") == 0.85
    assert f("snowy") == 1.15 and f("cloudy") == 1.03 and f("partlycloudy") == 1.0
    assert f("mystery-weather") == 1.0
    assert all(0.85 <= v <= 1.15 for v in W.GROW_FACTORS.values())


def test_the_weather_is_kept_in_the_state_and_goes_stale_after_an_hour(tmp_path):
    s, st, *_ = make(tmp_path)
    assert W.current(st, NOW) is None
    W.save(st, reading(), NOW)
    got = W.current(st, NOW + 3599)
    assert got == reading() and got.line().startswith("Outside: rain, 8 C")
    assert W.current(st, NOW + 3600).condition == "rainy" and W.current(st, NOW + 3601) is None
    st.set_meta(weather_at="", weather="")
    assert W.current(st, NOW) is None
    st.set_meta(weather=json.dumps(got.__dict__))                      # a reading without its time is not trusted
    st.set_meta(weather_at="")
    assert W.current(st, NOW) is None
    W.save(st, reading("snowy"), NOW + 4000)
    assert W.current(st, NOW + 4001).condition == "snowy"


def test_perception_and_growth_need_the_feature_on_and_a_fresh_reading(tmp_path):
    s, st, *_ = make(tmp_path)
    W.save(st, reading(), NOW)
    assert W.perception(st, s, NOW) == [] and W.grow_factor(st, s, NOW) == 1.0          # off by default
    s.weather = True
    assert W.perception(st, s, NOW) == [reading().line()] and W.grow_factor(st, s, NOW) == 0.85
    assert W.perception(st, s, NOW + 7200) == [] and W.grow_factor(st, s, NOW + 7200) == 1.0   # stale: say nothing


class FakeProvider:
    """A weather source for the tests: registered under a name, like any real one. Its behaviour lives on the class because the
    engine builds a fresh provider from the settings on every refresh."""
    built, calls, answer, fail, ready = 0, [], None, False, True

    def __init__(self, settings):
        self.settings = settings
        FakeProvider.built += 1

    async def fetch(self, http=None):
        FakeProvider.calls.append(http)
        if FakeProvider.fail:
            raise OSError("down")
        return FakeProvider.answer


@pytest.fixture
def fake(monkeypatch):
    for name, value in dict(built=0, calls=[], answer=reading("snowy"), fail=False, ready=True).items():
        monkeypatch.setattr(FakeProvider, name, value)
    monkeypatch.setitem(W.PROVIDERS, "fake", FakeProvider)
    return FakeProvider


def settings(**kw):
    return Settings(weather=True, weather_provider="fake", **kw)


@pytest.mark.asyncio
async def test_refresh_asks_the_chosen_provider_and_remembers_the_answer_without_asking_too_often(tmp_path, fake):
    s, st, *_ = make(tmp_path)
    http = object()
    assert await W.refresh(st, settings(), NOW, http) is True
    assert W.current(st, NOW) == reading("snowy") and fake.calls == [http]
    assert await W.refresh(st, settings(), NOW + 60, http) is False
    assert await W.refresh(st, settings(), NOW + 599, http) is False and len(fake.calls) == 1
    assert await W.refresh(st, settings(), NOW + 600, http) is True and len(fake.calls) == 2


@pytest.mark.asyncio
async def test_refresh_does_nothing_when_off_unknown_or_not_set_up(tmp_path, fake):
    s, st, *_ = make(tmp_path)
    assert await W.refresh(st, Settings(weather=False, weather_provider="fake"), NOW) is False and fake.built == 0
    assert await W.refresh(st, Settings(weather=True, weather_provider="no-such-source"), NOW) is False
    fake.ready = False
    assert await W.refresh(st, settings(), NOW) is False and fake.calls == []
    assert W.current(st, NOW) is None and st.meta("weather_try_at") is None          # not even counted as an attempt


@pytest.mark.asyncio
async def test_refresh_survives_failures_and_keeps_the_last_good_reading(tmp_path, fake):
    s, st, *_ = make(tmp_path)
    assert await W.refresh(st, settings(), NOW) is True
    fake.answer, fake.fail = reading("fog"), True
    assert await W.refresh(st, settings(), NOW + 700) is False and len(fake.calls) == 2
    assert W.current(st, NOW + 800).condition == "snowy"


@pytest.mark.asyncio
async def test_refresh_ignores_a_provider_with_nothing_to_say(tmp_path, fake):
    s, st, *_ = make(tmp_path)
    W.save(st, reading(), NOW)
    fake.answer = None
    assert await W.refresh(st, settings(), NOW + 700) is False and len(fake.calls) == 1
    assert W.current(st, NOW + 800).condition == "rainy"


def test_providers_register_by_name_and_are_built_from_the_settings(fake):
    s = settings()
    p = W.provider(s)
    assert isinstance(p, FakeProvider) and p.settings is s and fake.built == 1
    assert W.provider(Settings(weather_provider="no-such-source")) is None
    assert W.register("another")(FakeProvider) is FakeProvider and W.PROVIDERS.pop("another") is FakeProvider


@pytest.mark.asyncio
async def test_the_http_client_helper_borrows_a_given_client_and_makes_its_own_otherwise():
    class Client:
        closed = False

        async def aclose(self):
            self.closed = True
    mine = Client()
    async with W.http_client(mine) as c:
        assert c is mine
    assert mine.closed is False                                  # the caller's client is left open
    async with W.http_client() as c:
        assert c is not None and not c.is_closed
    assert c.is_closed


@pytest.mark.asyncio
async def test_planting_takes_the_weather_into_account(tmp_path):
    s, st, gm, agent = make(tmp_path)
    s.weather = True
    W.save(st, reading("rainy"), time.time())
    r = await call(agent, "plant", seed="carrot seeds")        # 45 minutes of growing, 15% less in the rain
    assert "ready in about 38 min" in r.text
    plot = st.garden()[0]
    assert plot["ready_in_min"] in (38, 39)
    s.weather = False
    r = await call(agent, "plant", seed="tomato seeds")
    assert "ready in about 60 min" in r.text
