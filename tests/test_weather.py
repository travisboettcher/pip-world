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


def test_the_sky_says_what_it_is_like_and_when_the_sun_turns():
    from tests.test_sky import G                                                       # the wording is the sky module's (0.40.0)
    off = round(datetime.fromtimestamp(NOW).astimezone().utcoffset().total_seconds())

    def line(*a, **kw):
        w = reading(*a, **kw)
        return "Outside: " + G["line"]({"condition": w.condition, "temp": w.temp, "unit": w.unit, "daylight": w.above_horizon,
                                         "next_rising": w.next_rising, "next_setting": w.next_setting}, off)
    assert line() == "Outside: rain, 8 C; the sun sets at 4:52 PM."
    assert line(above=False) == "Outside: rain, 8 C; the sun rises at 7:10 AM."
    assert line("partlycloudy", 21.0) == "Outside: partly cloudy, 21 C; the sun sets at 4:52 PM."
    assert line("clear-night", 3.4) == "Outside: clear, 3 C; the sun sets at 4:52 PM."
    assert line("lightning-rainy").startswith("Outside: thunder and rain, 8 C")
    assert line("mystery-weather", None) == "Outside: mystery weather; the sun sets at 4:52 PM."
    assert line(temp=None).startswith("Outside: rain; the sun") and line("very_odd-sky", None).startswith("Outside: very odd sky;")
    assert line("rainy", 46.4, "F") == "Outside: rain, 46 F; the sun sets at 4:52 PM."
    assert line(setting=None) == "Outside: rain, 8 C." and line(above=False, rising=None) == "Outside: rain, 8 C."


def test_the_weather_is_kept_in_the_state_and_goes_stale_after_an_hour(tmp_path):
    s, st, *_ = make(tmp_path)
    assert W.current(st, NOW) is None
    W.save(st, reading(), NOW)
    got = W.current(st, NOW + 3599)
    assert got == reading()
    assert W.current(st, NOW + 3600).condition == "rainy" and W.current(st, NOW + 3601) is None
    st.set_meta(weather_at="", weather="")
    assert W.current(st, NOW) is None
    st.set_meta(weather=json.dumps(got.__dict__))                      # a reading without its time is not trusted
    st.set_meta(weather_at="")
    assert W.current(st, NOW) is None
    W.save(st, reading("snowy"), NOW + 4000)
    assert W.current(st, NOW + 4001).condition == "snowy"


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
