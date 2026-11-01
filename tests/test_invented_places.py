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


# --- real on arrival: the design -------------------------------------------------------------------------
from app import gathering as G
from app import tools as T
from app.gm import GameMaster
from app.llm.fake import FakeBackend
from tests.test_projects import report

DESIGN = {"kind": "shop", "blurb": "a harbour village with an ironmonger's",
          "description": "Saltholm is a huddle of tarred houses round a harbour. The ironmonger's has a drawer of odds and ends.",
          "opens": 8, "closes": 18, "gather_help": "ask Mr Teague to let you pick through the drawer",
          "gerund": "rummaging in the ironmonger's drawer", "browse_help": "see what Mr Teague has in stock",
          "loot": [{"name": "Brass Wires", "kind": "material", "tier": "common", "description": "thin brass wire"},
                   {"name": "fish hooks", "kind": "material", "tier": "uncommon", "description": "a twist of hooks"},
                   {"name": "pliers", "kind": "tool", "tier": "common", "description": "small pliers"},
                   {"name": "awl", "kind": "tool", "tier": "rare", "description": "an awl"},
                   {"name": "hacksaw", "kind": "tool", "tier": "rare", "description": "a hacksaw"},
                   {"name": "sea biscuits", "kind": "food", "tier": "rare", "description": "hard biscuits"},
                   {"name": "kelp seeds", "kind": "seed", "tier": "uncommon", "description": "seeds"},
                   {"name": "a dragon", "kind": "creature", "tier": "rare", "description": "no"},
                   {"name": "  ", "kind": "material"}, "junk", {"name": "fish hooks", "kind": "material"}]}


def known_shop(st, now=1000.0):
    return IP.accept(st, "Briar", TIP, {**SALT, "items": ["thin brass wire", "copper rivets"]}, now=now)


def test_design_builds_a_validated_real_place(tmp_path):
    s, st = fresh(tmp_path)
    rec = IP.design(st, known_shop(st), DESIGN, random.Random(2), now=5000.0)
    assert rec["status"] == "real" and rec["kind"] == "shop" and rec["real_at"] == 5000.0
    assert rec["hours"] == [8, 18] and not rec["daylight_only"] and rec["blurb"] == DESIGN["blurb"]
    assert rec["description"] == DESIGN["description"] and st.meta("place:Saltholm") == DESIGN["description"]
    assert rec["verbs"] == {"browse": ["see what Mr Teague has in stock", None],
                            "gather": ["ask Mr Teague to let you pick through the drawer", "rummaging in the ironmonger's drawer"]}
    loot = {e[0]: e for e in rec["loot"]}
    assert "brass wire" in loot and "Brass Wires" not in loot                   # the junkyard's name, so it stacks
    assert loot["brass wire"][1] == "material" and 15 <= loot["brass wire"][2] <= 30 and loot["brass wire"][3] == [1, 3]
    assert 6 <= loot["fish hooks"][2] <= 12 and loot["fish hooks"][3] == [1, 2]
    assert [e[0] for e in rec["loot"]].count("fish hooks") == 1
    tools = [e for e in rec["loot"] if e[1] == "tool"]
    assert [e[0] for e in tools] == ["pliers", "awl"]                            # at most two, and always rare
    assert all(2 <= e[2] <= 5 and e[3] == [1, 1] for e in tools)
    assert loot["sea biscuits"][5] == {"food_value": 0.3} and loot["kelp seeds"][5]["crop"] == "kelp"
    assert "a dragon" not in loot
    assert loot["copper rivets"][2] <= 12 and loot["copper rivets"][1] == "material"   # promised but left out: added
    assert "thin brass wire" not in loot                                       # the brass wire already keeps that promise


def test_a_promised_thing_named_in_what_was_said_is_found_there(tmp_path):
    s, st = fresh(tmp_path)
    rec = IP.accept(st, "Briar", "The beach at Skerry has driftwood and wild berries.",
                    {"place": "Skerry", "there": "driftwood and wild berries on the beach", "distance": "near"})
    out = IP.design(st, rec, {"kind": "wild", "description": "A shingle beach.", "loot": [
        {"name": "driftwood", "kind": "material", "tier": "common"}]}, random.Random(1))
    loot = {e[0]: e for e in out["loot"]}
    assert set(loot) == {"driftwood", "wild berries"} and loot["wild berries"][1] == "food"   # the woods' own kind
    assert out["verbs"] == {"gather": ["forage for what grows here", "foraging"]} and out["hours"] is None
    assert out["daylight_only"] and out["blurb"] == "A shingle beach."


def test_a_kind_nobody_said_falls_back_and_a_sight_has_nothing_to_do(tmp_path):
    s, st = fresh(tmp_path)
    rec = IP.accept(st, "Briar", "Lake Ennis has the loveliest view.", {"place": "Lake Ennis", "there": "the loveliest view"})
    out = IP.design(st, rec, {**DESIGN, "kind": "shop", "description": "A still lake under the hills."}, random.Random(1))
    assert out["kind"] == "sight" and out["verbs"] == {} and out["loot"] == [] and out["hours"] is None


@pytest.mark.parametrize("raw", [None, "text", {}, {"description": "  "}, {"kind": "shop"}])
def test_an_unusable_design_leaves_the_place_heard_of(tmp_path, raw):
    s, st = fresh(tmp_path)
    rec = known_shop(st)
    assert IP.design(st, rec, raw, random.Random(1)) is None and st.place_row("Saltholm")["status"] == "heard"


def test_a_shop_with_nothing_in_its_table_offers_nothing_to_do(tmp_path):
    s, st = fresh(tmp_path)
    rec = IP.accept(st, "Briar", "Saltholm has a shop.", {"place": "Saltholm", "there": "a shop"})
    out = IP.design(st, rec, {"kind": "shop", "description": "A shop, shut up and empty.", "loot": []}, random.Random(1))
    assert out["kind"] == "shop" and out["loot"] == [] and out["verbs"] == {}


async def test_gm_design_place_is_told_the_mentions_kinds_and_existing_names(tmp_path):
    s, st = fresh(tmp_path)
    fake = FakeBackend([report(**DESIGN)])
    gm = GameMaster(fake, st)
    out = await gm.design_place("Saltholm", ["Briar says: an ironmonger"], ["brass wire", "sticks"])
    assert out["kind"] == "shop"
    prompt = fake.calls[0]["messages"][0]["content"]
    assert "Saltholm" in prompt and "Briar says: an ironmonger" in prompt and "brass wire, sticks" in prompt
    assert all(f"{k} (" in prompt for k in ("wild", "yard", "shop", "sight"))
    fake.queue(report(kind="shop"))
    assert await gm.design_place("Saltholm", [], []) is None                       # no description: unusable


async def test_first_arrival_designs_the_place_once(tmp_path):
    s, st, gm, agent = make(tmp_path, work_speed=10**6)
    known_shop(st, now=time.time())
    gm.queue(report(**DESIGN))
    await call(agent, "go_to", place="Saltholm")
    time.sleep(0.01)
    data = await P.arrive(st, s, agent.gm, None, rng=random.Random(1))
    assert data["first_time"] and data["description"] == DESIGN["description"] and len(gm.calls) == 1
    assert st.place_row("Saltholm")["status"] == "real"
    assert [r["key"] for r in st.place_rows()] == ["Saltholm"]
    reg = P.registry(st, s, None)["Saltholm"]
    assert not reg.heard and reg.offers == ("browse", "gather") and reg.blurb == DESIGN["blurb"]
    assert reg.verbs["gather"][0] == "ask Mr Teague to let you pick through the drawer"
    assert "15-30 minutes" in reg.verbs["gather"][1] and "on account" in reg.verbs["gather"][1]
    st.update_agent(location="workshop")
    await call(agent, "go_to", place="Saltholm")
    time.sleep(0.01)
    again = await P.arrive(st, s, agent.gm, None)
    assert not again["first_time"] and len(gm.calls) == 1                     # designed once


async def test_a_failed_design_leaves_a_bare_place_and_the_next_arrival_retries(tmp_path):
    s, st, gm, agent = make(tmp_path, work_speed=10**6)
    known_shop(st, now=time.time())
    gm.queue(report(kind="shop"))                                              # unusable
    await call(agent, "go_to", place="Saltholm")
    time.sleep(0.01)
    data = await P.arrive(st, s, agent.gm, None)
    assert data["description"] == "you find Saltholm, but can't get your bearings today"
    assert st.place_row("Saltholm")["status"] == "heard" and P.here(st, s, None).verbs == {}
    st.update_agent(location="workshop")
    gm.queue(report(**DESIGN))
    await call(agent, "go_to", place="Saltholm")
    time.sleep(0.01)
    data = await P.arrive(st, s, agent.gm, None)
    assert st.place_row("Saltholm")["status"] == "real" and data["description"] == DESIGN["description"]
    assert data["first_time"] is False


async def test_only_one_place_is_designed_a_day(tmp_path):
    s, st, gm, agent = make(tmp_path, work_speed=10**6)
    known_shop(st, now=time.time())
    IP.accept(st, "Briar", "Visit Fallow.", {"place": "Fallow", "there": "a meadow", "distance": "near"})
    st.update_place("Fallow", status="real", real_at=time.time() - 3600)      # one designed an hour ago
    await call(agent, "go_to", place="Saltholm")
    time.sleep(0.01)
    data = await P.arrive(st, s, agent.gm, None)
    assert gm.calls == [] and st.place_row("Saltholm")["status"] == "heard"
    assert data["description"] == "you find Saltholm, but can't get your bearings today"


# --- scoping: gather and browse wherever the place lists them -----------------------------------------
def real_shop(st, now=None):
    rec = known_shop(st, now=now or time.time())
    return IP.design(st, rec, DESIGN, random.Random(2))


def test_specs_offer_gather_at_a_real_shop_but_not_at_a_sight_or_a_heard_of_place(tmp_path):
    s, st, gm, agent = make(tmp_path)
    tools = {n: T.REGISTRY[n] for n in ("say", "gather", "browse", "plant")}
    names = lambda key, open_=True: sorted(sp.name for sp in T.specs_for(tools, key, P.registry(st, s, None)[key], open_))  # noqa: E731
    s.invented_places_per_day = 3
    real_shop(st)
    IP.accept(st, "Briar", "Lake Ennis has a view.", {"place": "Lake Ennis", "there": "a view"}, now=time.time())
    heard(st, "Fallow", "near", "a meadow")
    IP.design(st, st.place_row("Lake Ennis"), {"description": "A still lake."}, random.Random(1))
    assert names("Saltholm") == ["browse", "gather", "say"]
    assert names("Saltholm", open_=False) == ["say"]                          # a closed shop offers nothing
    assert names("Lake Ennis") == ["say"] and names("Fallow") == ["say"]
    sp = {x.name: x for x in T.specs_for(tools, "Saltholm", P.registry(st, s, None)["Saltholm"])}
    assert "15-30 minutes" in sp["gather"].description


async def test_gather_is_refused_at_a_closed_shop_and_where_it_isnt_offered(tmp_path):
    s, st, gm, agent = make(tmp_path)
    real_shop(st)
    h = (time.localtime().tm_hour + 1) % 24
    st.update_place("Saltholm", hours=[h, (h + 1) % 24])                       # opens in an hour
    st.update_agent(location="Saltholm")
    assert T.out_of_place(agent.ctx, "gather") == f"Saltholm is closed for now; it opens at {h}:00"
    st.update_place("Saltholm", hours=None)
    assert T.out_of_place(agent.ctx, "gather") == "" and T.out_of_place(agent.ctx, "browse") == ""
    assert T.out_of_place(agent.ctx, "plant") == "you're at Saltholm; go_to home first"
    IP.accept(st, "Briar", "Lake Ennis has a view.", {"place": "Lake Ennis", "there": "a view"}, now=time.time())
    st.update_agent(location="Lake Ennis")
    assert T.out_of_place(agent.ctx, "gather") == "you're not at the woods; go_to woods first"


def test_perception_says_when_a_closed_shop_opens(tmp_path):
    s, st, gm, agent = make(tmp_path)
    real_shop(st)
    h = (time.localtime().tm_hour + 1) % 24
    st.update_place("Saltholm", hours=[h, (h + 1) % 24])
    st.update_agent(location="Saltholm")
    lines = P.perception(st, s, None)
    assert lines[0] == f"You are at: Saltholm, closed for now (it opens at {h}:00) - {DESIGN['description']}"
    assert not any(l.startswith("Here you can") for l in lines)
    st.update_place("Saltholm", hours=None)
    assert "Here you can: browse (see what Mr Teague has in stock), gather (ask Mr Teague to let you pick through the drawer)." \
        in P.perception(st, s, None)


# --- gathering at invented places, and shops on account ---------------------------------------------------
from tests.test_gather import daytime, gather_and_wait, setup


def wild_place(st):
    rec = IP.accept(st, "Briar", "The beach at Skerry has driftwood and wild berries.",
                    {"place": "Skerry", "there": "driftwood and wild berries on the beach", "distance": "near"}, now=time.time())
    return IP.design(st, rec, {"kind": "wild", "description": "A shingle beach.", "gerund": "beachcombing", "loot": [
        {"name": "driftwood", "kind": "material", "tier": "common"}]}, random.Random(1))


async def test_gathering_at_an_invented_wild_place_draws_from_its_own_table(tmp_path):
    s, st, gm, agent = setup(tmp_path, where="Skerry")
    wild_place(st)
    r = await gather_and_wait(agent, 40)
    assert r.text.startswith("you set about beachcombing at Skerry for 40 min.")
    ev = st.events(limit=5)
    got = next(e["data"] for e in ev if e["kind"] == "gathered")
    assert got["place"] == "Skerry" and got["stock"] == 80 and "on_account" not in got     # 120 - 40, like the woods
    assert {i["name"] for i in got["items"]} <= {"driftwood", "wild berries"}
    assert {f["item"] for f in st.finds_at("Skerry")} == {i["name"] for i in got["items"]}
    assert G.loot_for(st, "Skerry")[0][0] == "driftwood" and G.loot_for(st, "Nowhere") is None
    assert G.verb_for(st, "Skerry") == "beachcombing" and G.verb_for(st, "woods") == "foraging"
    assert G.verb_for(st, "Nowhere") == "gathering"


async def test_rummaging_at_a_shop_is_short_slow_to_restock_and_on_account(tmp_path):
    s, st, gm, agent = setup(tmp_path, where="Saltholm")
    real_shop(st)
    st.update_place("Saltholm", hours=None)
    r = await call(agent, "gather", minutes=60)
    assert r.text.startswith("you set about rummaging in the ironmonger's drawer at Saltholm for 30 min.")  # 15-30 at a shop
    assert T.busy(agent.ctx).startswith("you're out rummaging in the ironmonger's drawer at Saltholm")
    time.sleep(0.05)
    await agent.resolve_world()
    got = next(e["data"] for e in st.events(limit=5) if e["kind"] == "gathered")
    assert got["stock"] == 10                                                  # a shop holds 40, not 120
    haul = {i["name"]: i["qty"] for i in got["items"]}
    assert haul and got["on_account"] == haul and st.place_row("Saltholm")["on_account"] == haul
    assert got["text"].endswith("It's on account at Saltholm: they're happy for you to settle up later.")
    assert G.stock(st, "Saltholm", time.time() + 3600) == pytest.approx(12, abs=0.1)     # 2 an hour back
    assert G.full_yield_at(st, "Saltholm") == 20 and G.full_yield_at(st, "woods") == G.FULL_YIELD_AT


async def test_browsing_a_shop_shows_whats_in_stock_and_whats_on_account(tmp_path):
    s, st, gm, agent = setup(tmp_path, where="Saltholm")
    real_shop(st)
    st.update_place("Saltholm", hours=None, on_account={"brass wire": 2})
    r = await call(agent, "browse")
    stock = r.text.split("\n")[0]
    assert stock.startswith("In stock at Saltholm today: ") and stock.endswith(". gather to pick through it.")
    assert len(stock.removeprefix("In stock at Saltholm today: ").split(", ")) == 4
    assert r.text.split("\n")[1] == "On account here: 2 brass wire (nothing's owed yet; you can settle up later)."
    st.set_meta(**{"stock:Saltholm": 0, "stock_at:Saltholm": time.time()})
    r = await call(agent, "browse")
    assert r.text.startswith("The shelves at Saltholm are bare today; they restock slowly, so come back in a day or so.")


async def test_browsing_an_invented_yard_is_a_look_around(tmp_path):
    s, st, gm, agent = setup(tmp_path, where="Grimsby Tip")
    rec = IP.accept(st, "Briar", "Grimsby Tip is all scrap heaps.", {"place": "Grimsby Tip", "there": "scrap heaps"},
                    now=time.time())
    IP.design(st, rec, {"kind": "yard", "description": "Heaps.", "loot": [
        {"name": "scrap iron", "kind": "material"}, {"name": "old chain", "kind": "material"}]}, random.Random(1))
    r = await call(agent, "browse")
    assert r.text.startswith("Looking over Grimsby Tip, you can make out: ") and "scrap iron" in r.text


async def test_where_to_knows_what_a_real_invented_place_has(tmp_path):
    s, st, gm, agent = make(tmp_path)
    real_shop(st)
    r = await call(agent, "where_to", what="fish hooks")
    assert "- Saltholm: a harbour village with an ironmonger's; you haven't found any yet, but it's the kind of place" in r.text


async def test_go_to_somewhere_far_warns_when_it_will_be_dark_before_pip_is_back(tmp_path):
    s, st, gm, agent = make(tmp_path, work_speed=1)
    heard(st)
    h = time.localtime().tm_hour
    s.bedtime_hour, s.wake_hour = (h + 1) % 24, (h + 9) % 24                  # night falls within the hour
    st.update_place("Saltholm", hours=None, daylight_only=0, walk_minutes=40)
    r = await call(agent, "go_to", place="Saltholm")
    assert r.text.endswith(" It'll be dark before you could get back.")
    st.end_session()
    s.bedtime_hour, s.wake_hour = (h + 6) % 24, (h + 12) % 24
    r = await call(agent, "go_to", place="Saltholm")
    assert "dark" not in r.text


async def test_go_to_a_shop_that_will_be_shut_says_when_it_opens(tmp_path):
    s, st, gm, agent = make(tmp_path, work_speed=10**6)
    heard(st)
    h = (time.localtime().tm_hour + 2) % 24
    st.update_place("Saltholm", hours=[h, (h + 1) % 24])
    r = await call(agent, "go_to", place="Saltholm")
    assert r.text.endswith(f" It'll be shut when you get there; it opens at {h}:00.")
