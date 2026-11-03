"""What a speaker says about a place's distance and opening hours is kept, not just the word 'far' (docs/DESIGN-invented-places.md)."""
import time

import pytest

from app import invented_places as IP
from tests.test_invented_places import fresh

TRAVIS = ("The market is in Brygdon, west of your place about an hours walk. "
          "It is open 9am - 5pm, so you should have plenty of time to get here if you left now.")


@pytest.mark.parametrize("text, minutes", [
    ("It is about an hours walk.", 60),
    ("Brygdon is an hour west.", 60),
    ("Twenty minutes' walk from here.", 20),
    ("It is half an hour away.", 30),
    ("An hour and a half's walk.", 90),
    ("About 2 hours on foot.", 120),
    ("It's a 45 minute stroll.", 45),
    ("one hour away", 60),
    ("Walk there if you like. It is 20 minutes away.", 20),           # the facts can be in a later sentence
    ("It is a long walk.\nTwenty minutes, really, from here.", 20),
    ("It's seventeen minutes away. Twenty minutes' walk.", 20),       # a number the engine can't read is skipped, not fatal
    ("The stall is open for an hour.", None),             # a duration, but not a distance
    ("Give it ten minutes.", None),
    ("It's nearby.", None),
    ("", None),
])
def test_a_stated_walking_time(text, minutes):
    assert IP.stated_minutes(text) == minutes


@pytest.mark.parametrize("text, hours", [
    ("It is open 9am - 5pm.", (9, 17)),
    ("Open from nine to five.", (9, 17)),
    ("It opens at 8 and closes at 6.", (8, 18)),
    ("Open 10am to 4pm daily.", (10, 16)),
    ("Hours are 8:30 to 5:30.", (8, 17)),
    ("The market is open 9 to 5.", (9, 17)),
    ("It's open 7am-7pm.", (7, 19)),
    ("Kids aged 9 to 5 get in free.", None),               # no word about opening
    ("Open late.", None),
    ("It is open 0 to 5.", (0, 5)),
    ("Open 9 to 24.", (9, 24)),
    ("Open 12 to 12.", None),
    ("Open 7 to 7.", (7, 19)),
    ("Open 12pm to 8pm.", (12, 20)),
    ("Open 12am to 6am.", (0, 6)),
    ("Open 9 to 25.", None),
    ("Open from nine to 17.", (9, 17)),
    ("It is open 5pm to 9am.", None),                       # backwards
    ("", None),
])
def test_stated_opening_hours(text, hours):
    assert IP.stated_hours(text) == hours


def test_a_visitor_telling_pip_where_the_market_is_gives_its_kind_hours_and_walk(tmp_path):
    s, st = fresh(tmp_path)
    st.log("inbox", id=1, text=TRAVIS, sender="Travis")
    rec = IP.recall_mention(st, "Brygdon", now=time.time())
    assert rec["kind"] == "market" and rec["status"] == "heard"
    assert rec["hours"] == [9, 17]
    assert rec["walk_minutes"] == 50 and rec["distance"] == "far"                    # an hour: clamped to the longest walk
    assert "open 9am - 5pm" in rec["mentions"][0]["there"] and "an hours walk" in rec["mentions"][0]["there"]


@pytest.mark.parametrize("said, walk, distance", [
    ("Brygdon is a market town. It is ten minutes' walk.", 10, "near"),
    ("Brygdon is a market town. It is twenty minutes' walk.", 20, "near"),
    ("Brygdon is a market town. It is thirty minutes' walk.", 30, "far"),
    ("Brygdon is a market town. It is an hour's walk.", 50, "far"),
    ("Brygdon is a market town. It is two hours' walk.", 50, "far"),
    ("Brygdon is a market town. It is three hours' walk.", None, "very far"),         # beyond a day trip
    ("Brygdon is a market town. It is a walk of 1 minute.", 1, "near"),
])
def test_a_stated_walk_is_clamped_to_what_pip_can_do_in_a_day(tmp_path, said, walk, distance):
    s, st = fresh(tmp_path)
    st.log("inbox", id=1, text=said, sender="Travis")
    rec = IP.recall_mention(st, "Brygdon", now=time.time())
    assert rec["walk_minutes"] == walk and rec["distance"] == distance


def test_stated_hours_are_clamped_into_a_shops_range_and_ignored_where_there_are_none(tmp_path):
    s, st = fresh(tmp_path)
    st.log("inbox", id=1, text="Ask in Brygdon. The market is open 5am to 11pm.", sender="Travis")
    assert IP.recall_mention(st, "Brygdon", now=time.time())["hours"] == [7, 19]
    (tmp_path / "b").mkdir()
    s, st = fresh(tmp_path / "b")
    st.log("inbox", id=1, text="Ellis Wood is a lovely wood, open 9 to 5 for walkers.", sender="Travis")
    rec = IP.recall_mention(st, "Ellis Wood", now=time.time())
    assert rec["kind"] == "wild" and rec["hours"] is None


def test_without_stated_facts_the_old_defaults_stand(tmp_path):
    s, st = fresh(tmp_path)
    st.log("inbox", id=1, text="The market is in Brygdon, a good way off.", sender="Travis")
    rec = IP.recall_mention(st, "Brygdon", now=time.time())
    assert rec["hours"] == [9, 17] and rec["distance"] == "far" and 20 <= rec["walk_minutes"] <= 35


def test_only_the_sentences_that_carry_facts_follow_the_one_naming_the_place(tmp_path):
    s, st = fresh(tmp_path)
    st.log("inbox", id=1, text="Brygdon has a market. I love my dog. Open 9 to 5. Bring a basket.", sender="Travis")
    there = IP.recall_mention(st, "Brygdon", now=time.time())["mentions"][0]["there"]
    assert "Open 9 to 5" in there and "dog" not in there and "basket" not in there


def test_a_visitor_message_pointing_at_a_place_carries_its_facts_too(tmp_path):
    s, st = fresh(tmp_path)
    recs = IP.from_chat(st, "Travis", "You could go to Brygdon, it has a market. It's a 25 minute walk and open 10am to 4pm.", time.time())
    assert recs and recs[0]["walk_minutes"] == 25 and recs[0]["hours"] == [10, 16]


def test_a_later_mention_with_facts_updates_a_heard_of_place_but_not_a_real_one(tmp_path):
    s, st = fresh(tmp_path)
    now = time.time()
    st.log("inbox", id=1, text="Try Brygdon, it has a market.", sender="Travis")
    rec = IP.recall_mention(st, "Brygdon", now=now)
    assert rec["walk_minutes"] != 15
    IP.add_to(st, rec, "Travis", "Brygdon is a 15 minute walk, open 8 to 4.", {"place": "Brygdon", "there": "Brygdon is a 15 minute walk, open 8 to 4."}, now)
    row = st.place_row("Brygdon")
    assert row["walk_minutes"] == 15 and row["distance"] == "near" and row["hours"] == [8, 16]
    st.update_place("Brygdon", status="real")
    IP.add_to(st, st.place_row("Brygdon"), "Travis", "Brygdon is a 40 minute walk, open 7 to 7.", {"place": "Brygdon", "there": "Brygdon is a 40 minute walk, open 7 to 7."}, now)
    assert st.place_row("Brygdon")["walk_minutes"] == 15 and st.place_row("Brygdon")["hours"] == [8, 16]


def test_the_context_is_the_sentence_plus_the_next_two_when_they_carry_facts():
    text = "Hi there. Brygdon has a market. It's an hour away. Open 9 to 5. Bring a basket."
    at = text.index("Brygdon")
    assert IP._context(text, at, at + 7) == "Brygdon has a market. It's an hour away. Open 9 to 5."
    assert IP._context("Brygdon is nice. Open 9 to 5", 0, 7) == "Brygdon is nice. Open 9 to 5"    # no closing full stop
    assert IP._context("Brygdon is nice.   ", 0, 7) == "Brygdon is nice."
    assert IP._context("Brygdon is nice\nOpen 9 to 5\nBring cash. Open late. Two hours away.", 0, 7) == "Brygdon is nice Open 9 to 5"
    assert IP._context("Brygdon is nice. Bring cash. Open late. Open 9 to 5.", 0, 7) == "Brygdon is nice."         # only two sentences are read after it


@pytest.mark.parametrize("text, name, sentence", [
    ("Hi there. The market is in Brygdon, west. Bye.", "Brygdon", "The market is in Brygdon, west."),
    ("The market is in Brygdon, west", "Brygdon", "The market is in Brygdon, west"),
    ("Hello: Brygdon has a market!", "Brygdon", "Brygdon has a market!"),
    ("First line\nBrygdon is nice\nLast line", "Brygdon", "Brygdon is nice"),
    ("Is it Brygdon? Yes.", "Brygdon", "Is it Brygdon?"),
])
def test_the_sentence_around_a_name(text, name, sentence):
    at = text.index(name)
    assert IP._sentence(text, at, at + len(name)) == sentence


def test_facts_set_the_hours_and_clear_the_daylight_only_flag():
    assert IP._facts("market", "Open 9 to 5.") == {"hours": [9, 17], "daylight_only": 0}
    assert IP._facts("wild", "Open 9 to 5.") == {}
    assert IP._facts("market", "Nothing stated.") == {}


@pytest.mark.parametrize("text, name, sentence", [
    (". Brygdon is nice.", "Brygdon", "Brygdon is nice."),
    ("Hi there. Hello again. Brygdon is nice.", "Brygdon", "Brygdon is nice."),
    ("Brygdon sells X-rays. Bye.", "Brygdon", "Brygdon sells X-rays."),
])
def test_the_sentence_around_a_name_in_awkward_text(text, name, sentence):
    at = text.index(name)
    assert IP._sentence(text, at, at + len(name)) == sentence


def test_the_context_reads_sentences_that_follow_without_a_space_or_contain_capital_x():
    text = "Brygdon is nice.It is an hour away.Open 9 to 5."
    assert IP._context(text, 0, 7) == "Brygdon is nice. It is an hour away. Open 9 to 5."
    text = "Brygdon sells X-rays. It is an hour away."
    assert IP._context(text, 0, 7) == "Brygdon sells X-rays. It is an hour away."
    text = "Brygdon is nice. Max says it is an hour away."
    assert IP._context(text, 0, 7) == "Brygdon is nice. Max says it is an hour away."


def test_a_capital_x_is_not_a_sentence_end():
    text = "XYZ Brygdon is nice. It is an hour away from XYZ town."
    at = text.index("Brygdon")
    assert IP._sentence(text, at, at + 7) == "XYZ Brygdon is nice."
    assert IP._context(text, at, at + 7) == "XYZ Brygdon is nice. It is an hour away from XYZ town."
