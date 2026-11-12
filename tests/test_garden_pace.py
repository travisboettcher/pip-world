"""Crops take about a day: a plot can be harvested once a day at most, so replanting forever cannot flood the pantry."""
import pytest

from app import gathering as G
from app import world
from app.text import span


@pytest.mark.parametrize("minutes,text", [(1, "1 min"), (45, "45 min"), (119, "119 min"), (120, "2 hours"), (1440, "24 hours"),
                                          (1500, "25 hours"), (918, "15 hours"), (2160, "36 hours")])
def test_span_is_minutes_for_short_waits_and_hours_for_long_ones(minutes, text):
    assert span(minutes) == text


def test_the_starter_crops_take_about_a_day():
    attrs = {i["name"]: i["attrs"]["grow_minutes"] for i in world.STARTER_ITEMS}
    assert attrs == {"tomato seeds": 1440, "carrot seeds": 1080}


def test_seeds_with_no_stated_time_take_a_day():
    assert world.normalize_attrs("mystery seeds", "seed", None)["grow_minutes"] == 1440


def test_wild_seeds_take_half_a_day_or_more():
    times = {name: a["grow_minutes"] for name, kind, _w, _q, _d, a in G.WOODS if kind == "seed"}
    assert times and min(times.values()) >= 720
    assert times["radish seeds"] == 720 and times["sunflower seeds"] == 2160
