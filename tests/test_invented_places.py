"""Places that characters mention become real (DESIGN-invented-places.md)."""
import time

from app.config import Settings
from app.state import State


def fresh(tmp_path):
    s = Settings(db_path=str(tmp_path / "t.db"))
    return s, State(s)


# --- the places table ---------------------------------------------------------------------------
def test_a_place_row_round_trips_its_lists_and_maps(tmp_path):
    s, st = fresh(tmp_path)
    st.add_place("Saltholm", "saltholm", aliases=["saltholm ironmonger"], walk_minutes=30.0, hours=[9, 17],
                 mentions=[{"by": "Briar", "there": "an ironmonger"}], created_at=100.0, heard_at=100.0)
    row = st.place_row("saltholm")                                          # keys match without case
    assert row["key"] == "Saltholm" and row["core"] == "saltholm" and row["status"] == "heard"
    assert row["aliases"] == ["saltholm ironmonger"] and row["hours"] == [9, 17] and row["walk_minutes"] == 30.0
    assert row["mentions"] == [{"by": "Briar", "there": "an ironmonger"}] and row["loot"] == [] and row["verbs"] == {}
    assert row["on_account"] == {} and row["grown"] == 0 and row["real_at"] is None and row["kind"] == "sight"
    st.update_place("Saltholm", status="real", loot=[["brass wire", "material", 9, [1, 2], "wire", {}]], on_account={"brass wire": 2})
    row = st.place_row("Saltholm")
    assert row["status"] == "real" and row["loot"][0][0] == "brass wire" and row["on_account"] == {"brass wire": 2}
    assert [r["key"] for r in st.place_rows()] == ["Saltholm"] and st.place_row("Nowhere") is None


def test_an_older_database_gains_the_places_table(tmp_path):
    s, st = fresh(tmp_path)
    st.db.execute("DROP TABLE places")
    st.db.commit()
    st.db.close()
    st = State(s)
    assert st.place_rows() == []


# --- names: normalising and dedupe ---------------------------------------------------------------
import random

import pytest

from app import invented_places as IP

TIP = "You'll want the ironmonger in Saltholm; he keeps thin brass wire, the fishing-hook gauge."
SALT = {"place": "Saltholm", "there": "an ironmonger with a drawer of odds and ends; thin brass wire", "distance": "far"}


@pytest.mark.parametrize("said, core", [
    ("Saltholm", "saltholm"), ("the Saltholm ironmonger", "saltholm"), ("Saltholm's ironmonger", "saltholm"),
    ("the ironmonger in Saltholm", "saltholm"), ("Saltholm Harbour", "saltholm"), ("the old mill", "old mill"),
    ("The Old Mill", "old mill"), ("North Fens", "north fen"), ("Saltholm’s quay", "saltholm"), ("", ""),
])
def test_the_core_of_a_name_drops_articles_possessives_and_trade_words(said, core):
    assert IP.core(said) == core


@pytest.mark.parametrize("said, key", [
    ("Saltholm", "Saltholm"), ("the Saltholm ironmonger", "Saltholm"), ("the old mill", "old mill"),
    ("The Old Mill", "old mill"), ("  North Fen. ", "North Fen"), ("the ironmonger in Saltholm", "Saltholm"),
])
def test_the_key_is_the_proper_noun_form_or_the_plain_name(said, key):
    assert IP.key_for(said) == key


def test_a_mention_records_a_heard_of_place(tmp_path):
    s, st = fresh(tmp_path)
    rec = IP.accept(st, "Briar", TIP, SALT, now=1000.0, rng=random.Random(1))
    assert rec["key"] == "Saltholm" and rec["status"] == "heard" and rec["distance"] == "far"
    assert 20 <= rec["walk_minutes"] <= 35 and rec["walk_minutes"] == round(rec["walk_minutes"])
    assert rec["mentions"] == [{"by": "Briar", "there": SALT["there"], "items": [], "ts": 1000.0}]
    assert rec["kind"] == "shop" and rec["hours"] == [9, 17] and not rec["daylight_only"]   # an ironmonger keeps shop hours
    ev = st.events(limit=1)[0]
    assert ev["kind"] == "heard_of_place" and ev["data"] == {"place": "Saltholm", "by": "Briar", "there": SALT["there"],
                                                            "distance": "far"}


def test_a_place_the_words_never_name_is_dropped(tmp_path):
    s, st = fresh(tmp_path)
    assert IP.accept(st, "Briar", "Lovely weather for the bees today.", SALT) is None
    assert st.place_rows() == [] and st.events(limit=1) == []


@pytest.mark.parametrize("raw", [None, "Saltholm", {}, {"place": 7}, {"place": "  "}, {"place": "S"},
                                 {"place": "a place with far too many words in it"}, {"place": "x" * 41}])
def test_a_malformed_mention_is_ignored(tmp_path, raw):
    s, st = fresh(tmp_path)
    assert IP.accept(st, "Briar", "S Saltholm a place with far too many words in it " + "x" * 41, raw) is None
    assert st.place_rows() == []


def test_the_four_saltholm_spellings_make_one_place_with_aliases(tmp_path):
    s, st = fresh(tmp_path)
    first = IP.accept(st, "Briar", TIP, SALT, now=1000.0)
    for said in ("the Saltholm ironmonger", "Saltholm's ironmonger", "the ironmonger in Saltholm"):
        text = f"Try {said} for wire."
        IP.accept(st, "Briar", text, {"place": said, "there": "wire", "distance": "near"}, now=2000.0)
    rows = st.place_rows()
    assert [r["key"] for r in rows] == ["Saltholm"] and rows[0]["walk_minutes"] == first["walk_minutes"]   # minutes fixed once
    assert rows[0]["distance"] == "far"
    assert rows[0]["aliases"] == ["saltholm ironmonger", "ironmonger in saltholm"]
    assert len(rows[0]["mentions"]) == 4 and rows[0]["heard_at"] == 2000.0
    assert [e["kind"] for e in st.events(limit=10)].count("heard_of_place") == 1


@pytest.mark.parametrize("name", ["home", "the workshop", "the library", "the woods", "the junkyard", "the market",
                                  "Pip's garden", "Briar", "Briar's cottage", "Briar Fennick's home"])
def test_reserved_names_neighbors_and_homes_are_refused(tmp_path, name):
    s, st = fresh(tmp_path)
    st.add_character("Briar Fennick", "neighbor", None, "a mender of nets", 60, 0)
    assert IP.accept(st, "Briar Fennick", f"Come to {name} some time.", {"place": name, "distance": "near"}) is None
    assert st.place_rows() == []


def test_pip_cannot_invent_a_place(tmp_path):
    s, st = fresh(tmp_path)
    assert IP.accept(st, "Pip", TIP, SALT) is None and st.place_rows() == []


@pytest.mark.parametrize("distance, lo, hi", [("near", 12, 20), ("far", 20, 35), ("somewhere", 20, 35), (None, 20, 35)])
def test_distance_picks_a_band_of_walking_minutes(tmp_path, distance, lo, hi):
    s, st = fresh(tmp_path)
    for seed in range(8):
        name = f"Saltholm{chr(97 + seed)}"
        rec = IP.accept(st, "Briar", f"Go to {name}.", {"place": name, "distance": distance}, now=1000.0 + seed * 90000,
                        rng=random.Random(seed))
        assert lo <= rec["walk_minutes"] <= hi
    assert {r["distance"] for r in st.place_rows()} == {"near" if distance == "near" else "far"}


def test_a_very_far_place_is_known_but_has_no_walk(tmp_path):
    s, st = fresh(tmp_path)
    rec = IP.accept(st, "Briar", "My sister lives in Brightwater, days away over the marsh.",
                    {"place": "Brightwater", "there": "where Briar's sister lives", "distance": "very far"})
    assert rec["distance"] == "very far" and rec["walk_minutes"] is None


def test_caps_two_new_places_a_day_and_twelve_in_all(tmp_path):
    s, st = fresh(tmp_path)
    say = lambda name, now: IP.accept(st, "Briar", f"Visit {name}.", {"place": name}, now=now)   # noqa: E731
    day = 86400.0
    assert say("Aldmoor", 1000.0) and say("Brenfold", 1001.0)
    assert say("Cailey", 1002.0) is None                                     # the third in a day
    assert say("Cailey", 1000.0 + day + 1)                                   # a day later there's room again
    for i, name in enumerate(("Dunmere", "Eskdale", "Fallow", "Garth", "Hollin", "Ingle", "Jessop", "Kettle", "Lune")):
        assert say(name, 1000.0 + day * (2 + i)), name
    assert len(st.place_rows()) == 12
    assert say("Marrow", 1000.0 + day * 20) is None                          # the 13th
    assert say("Aldmoor", 1000.0 + day * 20)["key"] == "Aldmoor"             # a known place is still talked about


def test_an_unvisited_place_is_forgotten_after_thirty_days_freeing_room(tmp_path):
    s, st = fresh(tmp_path)
    s.invented_places_max = 1
    day = 86400.0
    IP.accept(st, "Briar", "Visit Aldmoor.", {"place": "Aldmoor"}, now=1000.0)
    assert IP.accept(st, "Briar", "Visit Brenfold.", {"place": "Brenfold"}, now=1000.0 + 29 * day) is None
    assert [r["key"] for r in IP.records(st, now=1000.0 + 29 * day)] == ["Aldmoor"]
    assert IP.records(st, now=1001.0 + 30 * day) == []
    assert IP.accept(st, "Briar", "Visit Brenfold.", {"place": "Brenfold"}, now=1001.0 + 30 * day)
    assert st.place_row("Aldmoor")["status"] == "forgotten"


# --- heard-of places in the directory, go_to and where_to -----------------------------------------
from app import places as P
from tests.test_projects import call, make


def heard(st, name="Saltholm", distance="far", there=SALT["there"], by="Briar", text=None, now=None):
    return IP.accept(st, by, text or f"Go and see {name}: {there}", {"place": name, "there": there, "distance": distance},
                     now=now, rng=random.Random(3))


def test_a_proper_noun_place_is_said_without_an_article():
    assert P.label("Saltholm") == "Saltholm" and P.label("old mill") == "the old mill" and P.label("woods") == "the woods"


def test_the_registry_lists_reachable_heard_of_places_after_the_built_ins(tmp_path):
    s, st, *_ = make(tmp_path)
    rec = heard(st)
    heard(st, "Brightwater", "very far", "Briar's sister's town")
    reg = P.registry(st, s, None)
    assert list(reg) == ["workshop", "woods", "junkyard", "Saltholm"]          # very far: known, not walkable
    p = reg["Saltholm"]
    assert p.invented and p.heard and p.walk_minutes == rec["walk_minutes"] and p.verbs == {} and p.offers == ()
    assert p.hours == (9, 17) and not p.daylight_only and p.label == "Saltholm" and p.scope == "Saltholm"
    st.update_place("Saltholm", status="removed")
    assert "Saltholm" not in P.registry(st, s, None)


def test_the_directory_lists_heard_of_places_in_their_own_blocks(tmp_path):
    s, st, *_ = make(tmp_path, wild_places=[])
    rec = heard(st)
    IP.accept(st, "Morgan", "Saltholm has a harbour too.", {"place": "Saltholm", "there": "a harbour full of boats"})
    heard(st, "Brightwater", "very far", "where Briar's sister lives")
    noon = time.mktime(time.localtime()[:3] + (12, 0, 0, 0, 0, -1))
    lines = P.directory(st, s, None, now=noon)
    assert lines == [
        "Places you've heard of but not been to (go_to works):",
        f"- Saltholm, about {round(rec['walk_minutes'])} min, a long walk - Briar says: {SALT['there']}; "
        "Morgan says: a harbour full of boats",
        "Places you've heard of that are too far to walk to:",
        "- Brightwater - Briar says: where Briar's sister lives",
    ]
    midnight = time.mktime(time.localtime()[:3] + (2, 0, 0, 0, 0, -1))
    assert ", a long walk, closed now - " in P.directory(st, s, None, now=midnight)[1]
    st.update_agent(location="Saltholm")
    assert P.directory(st, s, None, now=noon)[:2] == ["Places you can go (go_to):",
                                                      "- workshop, 10 min - your home: your workshop and garden "
                                                      "[projects, garden, sleep]"]
    assert not any(l.startswith("- Saltholm") for l in P.directory(st, s, None, now=noon))   # not where Pip is


def test_a_near_place_with_no_words_said_about_it_is_a_short_walk_someone_mentioned(tmp_path):
    s, st, *_ = make(tmp_path, wild_places=[])
    IP.accept(st, "Briar", "Go to Fallow.", {"place": "Fallow", "distance": "near"})
    assert P.directory(st, s, None) == ["Places you've heard of but not been to (go_to works):",
                                            f"- Fallow, about {round(st.place_row('Fallow')['walk_minutes'])} min, a short walk"
                                            " - Briar mentioned it"]


async def test_go_to_a_heard_of_place_walks_there_for_its_minutes(tmp_path):
    s, st, gm, agent = make(tmp_path, work_speed=1)
    rec = heard(st)
    r = await call(agent, "go_to", place="the Saltholm ironmonger")
    assert r.text.startswith(f"you set off for Saltholm; you'll be there in about {round(rec['walk_minutes'])} min.")
    sess = st.session()
    assert sess["kind"] == "walk" and sess["target"] == "Saltholm" and sess["minutes"] == rec["walk_minutes"]


async def test_go_to_a_very_far_place_is_refused_kindly(tmp_path):
    s, st, gm, agent = make(tmp_path)
    heard(st, "Brightwater", "very far", "where Briar's sister lives")
    r = await call(agent, "go_to", place="Brightwater")
    assert r.text == ("Brightwater is too far to walk to: you've only heard of it (Briar says: where Briar's sister "
                      "lives)") and r.followup and st.session() is None


async def test_where_to_finds_what_characters_said_is_at_a_heard_of_place(tmp_path):
    s, st, gm, agent = make(tmp_path)
    heard(st)
    heard(st, "Brightwater", "very far", "a glassworks with brass wire")
    r = await call(agent, "where_to", what="brass wire")
    assert f"- Saltholm: Briar says: {SALT['there']} (you haven't been)" in r.text
    assert "- Brightwater: Briar says: a glassworks with brass wire (too far to walk)" in r.text
    assert "- the junkyard: " in r.text                                           # the real place is still there


# --- the backstop: a go_to nobody recorded -----------------------------------------------------------
async def test_go_to_a_place_a_character_said_records_it_and_walks(tmp_path):
    s, st, gm, agent = make(tmp_path)
    st.log("companion", name="Briar", text="Ask the ironmonger in Saltholm for thin brass wire. It's a long walk.",
           reply=True, visit=True)
    r = await call(agent, "go_to", place="Saltholm")
    rec = st.place_row("Saltholm")
    assert rec and rec["mentions"][0]["by"] == "Briar"
    assert rec["mentions"][0]["there"] == "Ask the ironmonger in Saltholm for thin brass wire."
    assert r.text.startswith("you set off for Saltholm") and st.session()["minutes"] == rec["walk_minutes"]


async def test_go_to_a_place_a_visitor_said_in_chat_records_it(tmp_path):
    s, st, gm, agent = make(tmp_path)
    st.log("inbox", id=1, text="there's a lovely lake called Lake Ennis just down the lane", sender="Morgan")
    r = await call(agent, "go_to", place="lake ennis")
    rec = st.place_row("Lake Ennis")
    assert rec and rec["mentions"][0]["by"] == "Morgan" and rec["distance"] == "near"
    assert r.text.startswith("you set off for Lake Ennis")


async def test_go_to_a_name_only_pip_has_used_is_still_unknown(tmp_path):
    s, st, gm, agent = make(tmp_path)
    st.add_memory("ask the ironmonger in Saltholm for wire", "todo")
    st.log("say", text="I'm off to Saltholm!")
    st.log("inbox", id=2, text="Morgan gave you 1 x Saltholm map (tool).", gift=True, sender="Morgan")
    r = await call(agent, "go_to", place="Saltholm")
    assert r.text.startswith("error: you don't know a place called 'Saltholm'") and st.place_rows() == []


@pytest.mark.parametrize("sentence, distance", [
    ("Brightwater is days away over the marsh.", "very far"), ("Brightwater is just down the lane.", "near"),
    ("Brightwater is nearby.", "near"), ("Brightwater, if you're up for a walk.", "far"),
    ("Brightwater is far away across the sea.", "very far"),
])
def test_the_distance_of_a_backstop_mention_comes_from_its_words(sentence, distance):
    assert IP.guess_distance(sentence) == distance


async def test_go_to_a_backstop_place_that_is_very_far_is_recorded_but_refused(tmp_path):
    s, st, gm, agent = make(tmp_path)
    st.log("companion", name="Briar", text="My sister is in Brightwater, days away over the marsh.")
    r = await call(agent, "go_to", place="Brightwater")
    assert r.text.startswith("Brightwater is too far to walk to") and st.place_row("Brightwater")


# --- what Pip is shown -----------------------------------------------------------------------------
def test_a_to_do_naming_a_heard_of_place_says_it_can_go_there(tmp_path):
    s, st, gm, agent = make(tmp_path)
    todo = st.add_memory("Ask the ironmonger in Saltholm for thin brass wire", "todo")
    far = st.add_memory("Write to Briar's sister in Brightwater", "todo")
    other = st.add_memory("Fix the clock", "todo")
    heard(st)
    heard(st, "Brightwater", "very far", "where Briar's sister lives")
    p = agent._perception("timer", [])
    assert (f"- #{todo} Ask the ironmonger in Saltholm for thin brass wire  [Saltholm: you've heard of it; go_to "
            "Saltholm to walk there]") in p
    assert f"- #{far} Write to Briar's sister in Brightwater  [Brightwater: you've heard of it, but it's too far to walk]" in p
    assert f"- #{other} Fix the clock\n" in p
    st.update_place("Saltholm", status="real")
    assert "go_to Saltholm to walk there" not in agent._perception("timer", [])       # been there: nothing to point at


def test_hearing_of_a_place_shows_in_recent_events_and_recall(tmp_path):
    s, st, gm, agent = make(tmp_path)
    heard(st)
    assert f"- Briar told you about Saltholm: {SALT['there']}" in agent._perception("timer", [])
    assert any("Briar told you about Saltholm" in h["text"] for h in st.recall("Saltholm"))


# --- the one-time backfill ---------------------------------------------------------------------------
LETTER = ("A letter from Briar: Dear Pip, the gulls are back. Ask the ironmonger in Saltholm for thin brass wire; "
          "he keeps a drawer of odds and ends. Thursday I mend nets.")


def test_the_backfill_finds_a_place_a_character_named_in_an_open_to_do(tmp_path):
    s, st = fresh(tmp_path)
    st.log("inbox", id=1, text=LETTER, sender="Briar", letter=True, gift=False)
    for i in range(40):
        st.log("companion", name="Briar", text=f"Lovely day {i}.")             # long since out of the backstop's reach
    st.add_memory("Ask the ironmonger in Saltholm for thin brass wire (Briar said, Thursday)", "todo")
    done = st.add_memory("Visit Dunmere", "todo")
    st.resolve_memory(done)
    st.log("companion", name="Briar", text="Dunmere is lovely.")
    IP.backfill(st)
    assert [r["key"] for r in st.place_rows()] == ["Saltholm"]                # not 'Ask', 'Briar', 'Thursday' or a done to-do
    rec = st.place_row("Saltholm")
    assert rec["mentions"][0]["by"] == "Briar" and rec["mentions"][0]["there"].startswith("Ask the ironmonger in Saltholm")
    st.update_place("Saltholm", status="removed")
    IP.backfill(st)                                                          # once only
    assert st.place_row("Saltholm")["status"] == "removed" and st.meta("invented_places_backfill") == "1"


def test_the_backfill_runs_when_pip_starts(tmp_path):
    s, st = fresh(tmp_path)
    st.log("inbox", id=1, text=LETTER, sender="Briar", letter=True, gift=False)
    st.add_memory("Ask the ironmonger in Saltholm for thin brass wire", "todo")
    st.db.close()
    s2, st2, gm, agent = make(tmp_path)
    assert st2.place_row("Saltholm")


# --- visitors in chat ------------------------------------------------------------------------------------
@pytest.mark.parametrize("said, key, distance", [
    ("There's a lovely lake called Lake Ennis just down the lane, Pip!", "Lake Ennis", "near"),
    ("You should go to Fen Hollow some time.", "Fen Hollow", "far"),
    ("there's a market in the next valley", "next valley", "far"),
    ("Ask the baker in Saltholm for a bun.", "Saltholm", "far"),
    ("walk over to the old mill tomorrow", "old mill", "far"),
    ("visit Brightwater one day - it's days away though", "Brightwater", "very far"),
])
def test_a_visitor_pointing_pip_somewhere_in_chat_records_the_place(tmp_path, said, key, distance):
    s, st = fresh(tmp_path)
    got = IP.from_chat(st, "Morgan", said)
    assert [r["key"] for r in got] == [key] and got[0]["distance"] == distance
    assert got[0]["mentions"][0]["by"] == "Morgan" and got[0]["mentions"][0]["there"]


@pytest.mark.parametrize("said", ["I was in Berlin today.", "Happy Halloween, Pip!", "go to the library", "go to bed",
                                  "My cat is called Tom.", "Go to Briar's and say hi", "try Mozart", ""])
def test_chat_that_doesnt_point_at_a_new_place_records_nothing(tmp_path, said):
    s, st = fresh(tmp_path)
    st.add_character("Briar Fennick", "neighbor", None, "a mender of nets", 60, 0)
    assert IP.from_chat(st, "Morgan", said) == [] and st.place_rows() == []


def test_a_visitor_message_reaching_pip_is_checked_for_places(tmp_path):
    s, st, gm, agent = make(tmp_path)
    agent.receive("You should go to Fen Hollow some time.", "Morgan")
    assert st.place_row("Fen Hollow")["mentions"][0]["by"] == "Morgan"
