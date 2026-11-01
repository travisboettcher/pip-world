"""Places that characters mention become real (DESIGN-invented-places.md)."""
import time

from app.config import Settings
from app.state import State
from app.text import clip


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


# --- residents: someone who lives or works at a real place (owner decision 5) -----------------------------
TEAGUE = {"name": "Mr Teague", "persona": "The Saltholm ironmonger: slow-spoken, proud of his drawer of odds and ends.",
          "about": "keeps the ironmonger's in Saltholm"}


def test_a_design_with_a_resident_makes_them_a_character_of_the_place(tmp_path):
    s, st = fresh(tmp_path)
    IP.design(st, known_shop(st), {**DESIGN, "resident": {**TEAGUE, "name": "  Mr Teague. "}}, random.Random(2),
              now=5000.0)
    (ch,) = st.characters()
    assert ch["kind"] == "resident" and ch["place"] == "Saltholm" and ch["name"] == "Mr Teague"
    assert ch["persona"] == TEAGUE["persona"] and ch["about"] == TEAGUE["about"]
    ev = st.events(limit=1)[0]
    assert ev["kind"] == "resident" and ev["data"] == {"name": "Mr Teague", "place": "Saltholm",
                                                      "about": TEAGUE["about"]}


def test_a_residents_words_are_clipped_like_a_neighbors(tmp_path):
    s, st = fresh(tmp_path)
    IP.design(st, known_shop(st), {**DESIGN, "resident": {"name": "N" * 41, "persona": "p" * 801, "about": "a" * 161}},
              random.Random(2))
    (ch,) = st.characters()
    assert ch["name"] == "N" * 40 + "..." and ch["persona"] == "p" * 800 + "..." and ch["about"] == "a" * 160 + "..."


@pytest.mark.parametrize("resident", [None, "Mr Teague", {}, {"name": "  ", "persona": "x"}, {"name": "Mr Teague"},
                                      {"name": "Mr Teague", "persona": " "}, {"name": "pip", "persona": "x"},
                                      {"name": "briar", "persona": "x"}, {"name": 7, "persona": "x"},
                                      {"name": "Mr Teague", "persona": ["x"]}])
def test_a_resident_needs_a_new_name_and_a_persona(tmp_path, resident):
    s, st = fresh(tmp_path)
    st.add_character("Briar", "neighbor", None, "A shore warden.", 60, 0)
    rec = IP.design(st, known_shop(st), {**DESIGN, "resident": resident}, random.Random(2))
    assert rec["status"] == "real" and [c["name"] for c in st.characters()] == ["Briar"]


def test_an_unusable_design_makes_no_resident(tmp_path):
    s, st = fresh(tmp_path)
    assert IP.design(st, known_shop(st), {"kind": "shop", "resident": TEAGUE}, random.Random(2)) is None
    assert st.characters() == []


DESIGN_PROMPT = (
    "Pip has just arrived at Saltholm for the first time. Nobody has described it before; this is what others told "
    "Pip about it (the place must agree with all of it):\n"
    "- Briar says: an ironmonger\n"
    "\n"
    "Decide what Saltholm is. `kind`, one of: {kinds}. Use the kind what was said suggests; a shop only if someone "
    "said there's a shop or a trade there. Give:\n"
    "- `description`: 2-3 sentences of the place as Pip finds it (kept, and shown whenever Pip is here)\n"
    "- `blurb`: one short line for a list of places\n"
    "- `loot`: 4-10 things that can be found or had there, each {{`name`, `kind`: material, food, seed or tool, "
    "`tier`: common, uncommon or rare, `description`}}; include everything the words above say is there. When a "
    "thing is one of these, use its name exactly: brass wire, sticks. \n"
    "- for a shop: `opens` and `closes` (local hours); `gather_help` (a few words: how Pip picks through the "
    "stock), `browse_help` (a few words: how Pip sees what's in), `gerund` (e.g. 'rummaging in the drawer'). For a "
    "wild place or a yard: `gather_help` and `gerund`. A sight needs none of these.\n"
    "- `resident`: someone who lives or works there and will talk with Pip, if the place has one (a shop "
    "normally has its keeper; a wild place or a sight often has nobody): `name`, `persona` (3-5 sentences, "
    "private: who they are, their days, how they talk) and `about` (one short line of what Pip would know of them "
    "once met). If the words above name someone who is there, it's them; never Pip or whoever told Pip about it."
)


async def test_gm_design_place_asks_for_a_resident_exactly(tmp_path):
    from app import place_kinds
    from tests.test_gm_prompts import SchemaBackend
    s, st = fresh(tmp_path)
    fake = SchemaBackend([report(**DESIGN)])
    await GameMaster(fake, st).design_place("Saltholm", ["Briar says: an ironmonger"], ["brass wire", "sticks"])
    assert fake.calls[0]["messages"][0]["content"] == DESIGN_PROMPT.format(kinds=place_kinds.gm_lines())
    assert fake.schemas[0]["properties"]["resident"] == {"type": "object", "properties": {
        "name": {"type": "string"}, "persona": {"type": "string"}, "about": {"type": "string"}},
        "required": ["name", "persona"]}
    assert fake.schemas[0]["required"] == ["kind", "description"]


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


# --- places grow from later mentions (owner decision 3) ------------------------------------------------------
def test_a_later_mention_of_something_new_at_a_real_place_adds_it(tmp_path):
    s, st = fresh(tmp_path)
    rec = real_shop(st)
    before = len(rec["loot"])
    out = IP.add_to(st, "Saltholm", "Briar", "Saltholm's chandler has tarred rope now.",
                    {"place": "Saltholm", "there": "the chandler has tarred rope", "items": ["tarred rope"]})
    loot = {e[0]: e for e in out["loot"]}
    assert len(out["loot"]) == before + 1 and loot["tarred rope"][1] == "material" and 6 <= loot["tarred rope"][2] <= 12
    assert out["grown"] == 1 and out["description"] == DESIGN["description"]
    again = IP.add_to(st, "Saltholm", "Briar", "Saltholm has tarred rope.", {"place": "Saltholm", "items": ["tarred rope"]})
    assert len(again["loot"]) == before + 1 and again["grown"] == 1                  # nothing new: no growth


def test_a_later_mention_with_no_new_thing_adds_a_line_of_description(tmp_path):
    s, st = fresh(tmp_path)
    real_shop(st)
    out = IP.add_to(st, "Saltholm", "Morgan", "Saltholm has a harbour.", {"place": "Saltholm", "there": "a harbour full of boats"})
    assert out["description"] == DESIGN["description"] + " Morgan says: a harbour full of boats."
    assert st.meta("place:Saltholm") == out["description"] and out["grown"] == 1
    same = IP.add_to(st, "Saltholm", "Morgan", "Saltholm has a harbour.", {"place": "Saltholm", "there": "a harbour full of boats"})
    assert same["description"] == out["description"] and same["grown"] == 1          # said already: nothing new


def test_a_sight_can_grow_something_to_gather(tmp_path):
    s, st = fresh(tmp_path)
    rec = IP.accept(st, "Briar", "Lake Ennis has a view.", {"place": "Lake Ennis", "there": "a view"})
    IP.design(st, rec, {"description": "A still lake."}, random.Random(1))
    out = IP.add_to(st, "Lake Ennis", "Briar", "There are wild berries by Lake Ennis.",
                    {"place": "Lake Ennis", "there": "wild berries by the shore"})
    assert [e[0] for e in out["loot"]] == ["wild berries"] and out["loot"][0][1] == "food"
    assert out["verbs"] == {"gather": ["look around for what can be had here", "looking around"]}


def test_growth_is_capped_per_place_but_mentions_are_still_kept(tmp_path):
    s, st = fresh(tmp_path)
    real_shop(st)
    for i, thing in enumerate(("tarred rope", "cork floats", "net needles", "lamp wicks")):
        out = IP.add_to(st, "Saltholm", "Briar", f"Saltholm has {thing}.", {"place": "Saltholm", "items": [thing]})
    names = [e[0] for e in out["loot"]]
    assert "net needles" in names and "lamp wicks" not in names and out["grown"] == IP.GROWTH_MAX == 3
    assert out["mentions"][-1]["items"] == ["lamp wicks"]


def test_a_heard_of_place_keeps_later_mentions_as_promises_without_growing(tmp_path):
    s, st = fresh(tmp_path)
    known_shop(st, now=time.time())
    out = IP.add_to(st, "Saltholm", "Briar", "Saltholm has tarred rope.", {"place": "Saltholm", "items": ["tarred rope"]})
    assert out["grown"] == 0 and out["loot"] == [] and out["mentions"][-1]["items"] == ["tarred rope"]
    designed = IP.design(st, out, DESIGN, random.Random(1))
    assert "tarred rope" in [e[0] for e in designed["loot"]]                         # promised, so it's there


def test_the_directory_blurb_of_a_real_place_shows_what_was_said_since(tmp_path):
    s, st, *_ = make(tmp_path, wild_places=[])
    real_shop(st, now=time.time() - 60)
    st.update_place("Saltholm", real_at=time.time() - 30)
    assert P.registry(st, s, None)["Saltholm"].blurb == DESIGN["blurb"]
    IP.add_to(st, "Saltholm", "Morgan", "Saltholm has a harbour.", {"place": "Saltholm", "there": "a harbour full of boats"})
    assert P.registry(st, s, None)["Saltholm"].blurb == DESIGN["blurb"] + " (Morgan says: a harbour full of boats)"


# --- the seams for the neighbor prompts ------------------------------------------------------------------
def test_the_mention_property_is_a_report_schema_with_the_distance_enum():
    prop = IP.MENTION_PROPERTY
    assert prop["type"] == "object" and prop["required"] == ["place"]
    assert set(prop["properties"]) == {"place", "there", "distance", "items"}
    assert prop["properties"]["distance"]["enum"] == ["near", "far", "very far"]
    assert prop["properties"]["items"] == {"type": "array", "items": {"type": "string"}}


def test_the_mention_instruction_lists_the_places_that_already_exist(tmp_path):
    s, st, *_ = make(tmp_path)
    st.add_character("Briar Fennick", "neighbor", None, "a mender of nets", 60, 0)
    heard(st)
    heard(st, "Brightwater", "very far", "where Briar's sister lives")
    line = IP.mention_instruction(st, s)
    assert line.startswith("Only if your words point Pip to a place it could go that isn't one of these: ")
    assert "the woods, the junkyard, Briar Fennick's home, Saltholm, Brightwater" in line and "home (" not in line
    assert "`mentions_place`" in line and "very far" in line and "Not your own home" in line


async def test_a_gm_reply_with_a_mention_records_the_place_and_one_without_does_nothing(tmp_path):
    s, st, *_ = make(tmp_path)
    reply = {"text": TIP, "mentions_place": SALT}
    assert IP.accept(st, "Briar", reply["text"], reply.get("mentions_place"))["key"] == "Saltholm"
    assert IP.accept(st, "Briar", "Hello again.", {"text": "Hello again."}.get("mentions_place")) is None
    again = IP.accept(st, "Briar", "Saltholm's quay is busy.", {"place": "Saltholm's quay", "there": "a busy quay"})
    assert again["key"] == "Saltholm" and len(again["mentions"]) == 2 and "saltholm quay" in again["aliases"]


def places_world(tmp_path):
    s, st, *_ = make(tmp_path)
    st.add_character("Briar Fennick", "neighbor", None, "a mender of nets", 60, 0)
    st.add_character("Marigold", "neighbor", None, "a beekeeper", 60, 0)
    s.invented_places_per_day = 3
    now = time.time()
    IP.design(st, IP.accept(st, "Briar Fennick", TIP, SALT, now=now), DESIGN, random.Random(1))
    st.add_find("Saltholm", "brass wire")
    heard(st, "Fallow", "near", "a meadow full of larks", by="Marigold", now=now)
    heard(st, "Brightwater", "very far", "where my sister lives", by="Briar Fennick", now=now + 1)
    return s, st


def test_the_places_line_puts_what_this_character_told_pip_first(tmp_path, monkeypatch):
    s, st = places_world(tmp_path)
    assert IP.places_line(st, "Briar Fennick", s) == (
        f"Places in Pip's world: Saltholm, a long walk (you told Pip: {SALT['there']}; Pip has been and found brass wire "
        "there); Brightwater, too far to walk (you told Pip: where my sister lives); the woods (foraging); the junkyard "
        "(scrap); Marigold's home; Fallow, a short walk")
    assert IP.places_line(st, "Marigold", s).startswith(
        "Places in Pip's world: Fallow, a short walk (you told Pip: a meadow full of larks); the woods (foraging); "
        "the junkyard (scrap); Briar Fennick's home; Saltholm, a long walk (Pip has been and found brass wire there); "
        "Brightwater, too far to walk")
    monkeypatch.setattr(IP, "PLACES_SHOWN", 2)
    short = IP.places_line(st, "Briar Fennick", s)
    assert short.endswith("; Brightwater, too far to walk (you told Pip: where my sister lives)") and "woods" not in short


def test_the_places_line_is_empty_when_there_is_nowhere_to_go(tmp_path):
    s, st, *_ = make(tmp_path, wild_places=[])
    assert IP.places_line(st, "Briar", s) == ""
    st.update_agent(location="library")
    assert IP.places_line(st, "Briar", s) == ""


# --- owner control ---------------------------------------------------------------------------------------
def test_removing_a_place_hides_it_but_pip_can_still_leave(tmp_path):
    s, st, gm, agent = make(tmp_path)
    real_shop(st)
    st.update_agent(location="Saltholm")
    assert IP.remove(st, "saltholm")["status"] == "removed" and IP.remove(st, "Nowhere") is None
    assert "Saltholm" not in P.registry(st, s, None) and P.here(st, s, None).verbs == {}
    assert IP.find_record(st, "Saltholm") is None
    assert IP.accept(st, "Briar", TIP, SALT) is None                       # and nobody brings it back by name
    assert st.place_row("Saltholm")["status"] == "removed"


def test_patch_changes_walk_hours_description_and_loot_through_the_validator(tmp_path):
    s, st = fresh(tmp_path)
    real_shop(st)
    out = IP.patch(st, "Saltholm", {"walk_minutes": 90, "hours": [3, 23], "description": "x " * 300,
                                    "loot": [{"name": "rope", "kind": "material", "tier": "rare"},
                                             {"name": "a saw", "kind": "tool"}, {"name": "a dragon", "kind": "beast"}]},
                   rng=random.Random(1))
    assert out["walk_minutes"] == 50 and out["hours"] == [7, 19] and out["description"] == clip("x " * 300, 500)
    assert st.meta("place:Saltholm") == out["description"]
    assert [e[0] for e in out["loot"]] == ["rope", "a saw"] and out["loot"][0][3] == [1, 1]
    assert IP.patch(st, "Saltholm", {"walk_minutes": 0.2})["walk_minutes"] == 1
    assert IP.patch(st, "Saltholm", {"walk_minutes": None})["walk_minutes"] is None     # too far to walk now
    assert IP.patch(st, "Nowhere", {"walk_minutes": 5}) is None


@pytest.mark.parametrize("changes", [{"description": " "}, {"walk_minutes": "far"}, {"hours": [9]}, {"loot": "rope"},
                                     {"colour": "blue"}])
def test_patch_refuses_what_it_cant_use(tmp_path, changes):
    s, st = fresh(tmp_path)
    real_shop(st)
    with pytest.raises(ValueError):
        IP.patch(st, "Saltholm", changes)


def test_patch_hours_only_apply_to_a_shop_and_loot_only_to_a_real_place(tmp_path):
    s, st = fresh(tmp_path)
    rec = IP.accept(st, "Briar", "Fallow is a meadow.", {"place": "Fallow", "there": "a meadow"}, now=time.time())
    with pytest.raises(ValueError):
        IP.patch(st, "Fallow", {"hours": [9, 17]})
    with pytest.raises(ValueError):
        IP.patch(st, "Fallow", {"loot": [{"name": "rope", "kind": "material"}]})
    assert IP.patch(st, "Fallow", {"walk_minutes": 14})["walk_minutes"] == 14 and rec["kind"] == "wild"


def test_the_places_endpoints_list_patch_and_remove(tmp_path):
    from fastapi.testclient import TestClient
    from app.main import create_app
    s = Settings(db_path=str(tmp_path / "t.db"), persona_path="/x", persona_default_path="/x", pacing="manual",
                 neighbor=False)
    with TestClient(create_app(s, FakeBackend())) as c:
        st = c.app.state.agent.state
        heard(st, now=time.time())
        got = c.get("/places").json()
        assert [p["key"] for p in got["places"]] == ["Saltholm"] and got["places"][0]["mentions"][0]["by"] == "Briar"
        assert "woods" in got["built_in"] and "workshop" in got["built_in"]
        assert c.patch("/places/saltholm", json={"walk_minutes": 18}).json()["walk_minutes"] == 18
        assert c.patch("/places/saltholm", json={"colour": "blue"}).status_code == 422
        assert c.patch("/places/Nowhere", json={"walk_minutes": 18}).status_code == 404
        assert c.delete("/places/Saltholm").json()["status"] == "removed"
        assert c.delete("/places/Saltholm").status_code == 404
        assert c.get("/places").json()["places"][0]["status"] == "removed"


def test_the_places_endpoint_lists_who_lives_at_each_place_even_once_removed(tmp_path):
    from fastapi.testclient import TestClient
    from app.main import create_app
    s = Settings(db_path=str(tmp_path / "t.db"), persona_path="/x", persona_default_path="/x", pacing="manual",
                 neighbor=False)
    with TestClient(create_app(s, FakeBackend())) as c:
        st = c.app.state.agent.state
        IP.design(st, known_shop(st, now=time.time()), {**DESIGN, "resident": TEAGUE}, random.Random(2))
        heard(st, "Fallow", "near", "a meadow", now=time.time())
        st.update_character(st.characters()[0]["id"], life=["A new drawer came."])
        expected = [{"name": "Mr Teague", "about": TEAGUE["about"], "life": ["A new drawer came."]}]
        assert [p["residents"] for p in c.get("/places").json()["places"]] == [expected, []]
        c.delete("/places/Saltholm")
        assert c.get("/places").json()["places"][0]["residents"] == expected


# --- edges pinned by mutation testing ----------------------------------------------------------------------
DAY = 86400.0


def test_a_capitalised_connector_isnt_part_of_the_proper_name():
    assert IP.core("The Mill At Saltholm") == "saltholm" and IP.key_for("The Mill At Saltholm") == "Saltholm"


def test_a_possessive_s_is_not_a_word_the_speaker_said(tmp_path):
    s, st = fresh(tmp_path)
    assert IP.accept(st, "Morgan", "Go to Briar's Bend.", {"place": "S Bend"}) is None


@pytest.mark.parametrize("name, key", [("Ys", "Ys"), ("Xanadu", "Xanadu"), ("Saint Agnes Under The Hill", "Saint Agnes Under Hill")])
def test_short_long_and_x_names_are_kept(tmp_path, name, key):
    s, st = fresh(tmp_path)
    assert IP.accept(st, "Briar", f"Go to {name}.", {"place": name})["key"] == key


def test_a_name_of_forty_letters_is_kept_after_its_punctuation_is_trimmed(tmp_path):
    s, st = fresh(tmp_path)
    name = f"A{'a' * 12} B{'b' * 12} C{'c' * 11}"
    assert len(name) == 40
    assert IP.accept(st, "Briar", f"Go to {name}.", {"place": f"{name}."})["key"] == name
    assert IP.accept(st, "Briar", "Go to Saint Agnes Under The Green Hill.",
                     {"place": "Saint Agnes Under The Green Hill"}) is None          # six words


def test_a_name_said_exactly_is_enough(tmp_path):
    s, st = fresh(tmp_path)
    assert IP.accept(st, "Briar", "Saltholm", {"place": "Saltholm"})["key"] == "Saltholm"


def test_names_of_three_letters_count_as_a_characters_name_but_two_dont(tmp_path):
    s, st = fresh(tmp_path)
    st.add_character("Ann Fenwick", "neighbor", None, "x", 60, 0)
    st.add_character("Ed Marlow", "neighbor", None, "x", 60, 0)
    assert IP.accept(st, "Morgan", "Go to Ann Tor.", {"place": "Ann Tor"}) is None
    assert IP.accept(st, "Morgan", "Go to Ed Tor.", {"place": "Ed Tor"})["key"] == "Ed Tor"


def test_a_place_is_remembered_for_exactly_thirty_days(tmp_path):
    s, st = fresh(tmp_path)
    IP.accept(st, "Briar", "Visit Aldmoor.", {"place": "Aldmoor"}, now=1000.0)
    assert [r["key"] for r in IP.records(st, now=1000.0 + 30 * DAY)] == ["Aldmoor"]


def test_the_day_cap_counts_places_from_less_than_a_day_ago(tmp_path):
    s, st = fresh(tmp_path)
    s.invented_places_per_day = 1
    IP.accept(st, "Briar", "Visit Aldmoor.", {"place": "Aldmoor"}, now=1000.0)
    assert IP.accept(st, "Briar", "Visit Brenfold.", {"place": "Brenfold"}, now=1000.0 + DAY)["key"] == "Brenfold"


def test_a_first_mention_by_a_longer_name_keeps_it_as_an_alias(tmp_path):
    s, st = fresh(tmp_path)
    rec = IP.accept(st, "Briar", "Ask the ironmonger in Saltholm.", {"place": "the ironmonger in Saltholm"}, now=1000.0)
    assert rec["key"] == "Saltholm" and rec["aliases"] == ["ironmonger in saltholm"]
    assert IP.find_record(st, "ironmonger in saltholm", now=1000.0)["key"] == "Saltholm"   # by its alias


def test_a_mention_clips_the_speaker_and_keeps_three_named_things(tmp_path):
    s, st = fresh(tmp_path)
    speaker = "Morgan " + "x" * 34
    rec = IP.accept(st, speaker, "Go to Fallow.", {"place": "Fallow", "items": [7, "rope", "q" * 41, " ", "nets", "floats"]})
    assert rec["mentions"][0]["by"] == clip(speaker, 40) and rec["mentions"][0]["items"] == ["rope", clip("q" * 41, 40), "nets"]


def test_add_to_finds_the_place_at_the_time_given(tmp_path):
    s, st = fresh(tmp_path)
    IP.accept(st, "Briar", TIP, SALT, now=1000.0)
    assert IP.add_to(st, "Saltholm", "Briar", "", None, now=2000.0) is None          # nothing to add
    out = IP.add_to(st, "Saltholm", "Briar", "", {"there": "boats"}, now=2000.0)
    assert out["heard_at"] == 2000.0 and out["aliases"] == [] and out["mentions"][-1]["there"] == "boats"
    out = IP.add_to(st, "Saltholm", "Briar", "", {"place": "Saltholm", "there": "nets"}, now=2000.0)
    assert out["aliases"] == []                                                      # its own name isn't an alias


def test_a_place_that_has_grown_three_times_takes_no_more_description(tmp_path):
    s, st = fresh(tmp_path)
    real_shop(st)
    st.update_place("Saltholm", grown=3)
    out = IP.add_to(st, "Saltholm", "Morgan", "", {"place": "Saltholm", "there": "a harbour full of boats"})
    assert out["description"] == DESIGN["description"] and out["grown"] == 3


def test_a_yard_only_grows_what_a_yard_can_hold(tmp_path):
    s, st = fresh(tmp_path)
    rec = IP.accept(st, "Briar", "Cobbleton has a scrap heap.", {"place": "Cobbleton", "there": "a scrap heap"})
    IP.design(st, rec, {"kind": "yard", "description": "A tip.", "loot": [{"name": "rusty tin", "kind": "material"}]},
              random.Random(1))
    out = IP.add_to(st, "Cobbleton", "Briar", "", {"place": "Cobbleton", "items": ["wild berries"]})
    assert [e[0] for e in out["loot"]] == ["rusty tin"] and out["grown"] == 0


def test_growth_skips_what_is_already_there_and_keeps_the_gather_verb(tmp_path):
    s, st = fresh(tmp_path)
    real_shop(st)
    st.update_place("Saltholm", grown=2)                                             # room for one more
    out = IP.add_to(st, "Saltholm", "Briar", "", {"place": "Saltholm", "items": ["brass wire", "tarred rope"]})
    assert "tarred rope" in [e[0] for e in out["loot"]] and out["grown"] == 3
    assert out["verbs"]["gather"] == ["ask Mr Teague to let you pick through the drawer",
                                      "rummaging in the ironmonger's drawer"]


def test_a_line_of_description_ends_with_one_full_stop(tmp_path):
    s, st = fresh(tmp_path)
    real_shop(st)
    out = IP.add_to(st, "Saltholm", "Morgan", "", {"place": "Saltholm", "there": "tea at the inn of Captain X."})
    assert out["description"] == DESIGN["description"] + " Morgan says: tea at the inn of Captain X."


def test_a_description_grows_up_to_five_hundred_characters(tmp_path):
    s, st = fresh(tmp_path)
    real_shop(st)
    line = " Morgan says: boats."
    st.update_place("Saltholm", description="d" * (501 - len(line)))
    out = IP.add_to(st, "Saltholm", "Morgan", "", {"place": "Saltholm", "there": "boats"})
    assert out["grown"] == 0 and len(out["description"]) == 501 - len(line)
    st.update_place("Saltholm", description="d" * (500 - len(line)))
    out = IP.add_to(st, "Saltholm", "Morgan", "", {"place": "Saltholm", "there": "boats"})
    assert out["grown"] == 1 and len(out["description"]) == 500


def test_the_backstop_hears_a_visitor_and_a_letter_with_a_gift(tmp_path):
    s, st = fresh(tmp_path)
    s.invented_places_per_day = 5
    st.log("inbox", text="You could visit Brenfold.")
    st.log("inbox", text="Dear Pip, do visit Cailey.", sender="Briar", letter=True, gift=True)
    st.log("inbox", text="Here's a gift from Dunmere.", sender="Briar", gift=True)   # an engine-written gift note
    assert IP.recall_mention(st, "Brenfold")["mentions"][0]["by"] == "A visitor"
    assert IP.recall_mention(st, "Cailey")["mentions"][0]["by"] == "Briar"
    assert IP.recall_mention(st, "Dunmere") is None


def test_the_backstop_searches_only_the_latest_voices(tmp_path):
    s, st = fresh(tmp_path)
    st.log("companion", name="Briar", text="Go to Fallow.")
    st.log("companion", name="Briar", text="Hello.")
    assert IP.recall_mention(st, "Fallow", limit=1) is None
    assert IP.recall_mention(st, "Fallow", limit=2, now=1000.0)["created_at"] == 1000.0


def test_the_backstop_keeps_the_full_name_said_and_falls_back_to_its_core(tmp_path):
    s, st = fresh(tmp_path)
    st.log("companion", name="Briar", text="Ask the ironmonger in Saltholm for wire.")
    assert IP.recall_mention(st, "the ironmonger in Saltholm")["aliases"] == ["ironmonger in saltholm"]
    (tmp_path / "b").mkdir()
    s2, st2 = fresh(tmp_path / "b")
    st2.log("companion", name="Briar", text="Saltholm is lovely.")                   # said first in a sentence: fine here
    assert IP.recall_mention(st2, "the Saltholm ironmonger")["key"] == "Saltholm"


@pytest.mark.parametrize("text, there", [
    ("Hi. Lovely day. Go to Fallow.", "Go to Fallow."), ("Mr X says go to Fallow.", "Mr X says go to Fallow."),
    ("Go to Fallow with Mr X now.", "Go to Fallow with Mr X now."), ("go to Fallow", "go to Fallow"),
    ("Go to Fallow. Then rest.", "Go to Fallow."), (":) go to Fallow", ") go to Fallow"),
])
def test_what_is_there_is_the_sentence_the_name_is_in(text, there):
    assert IP.chat_mentions(text)[0]["there"] == there


def test_a_chat_message_names_each_place_once(tmp_path):
    assert [m["place"] for m in IP.chat_mentions("Go to Fen Hollow, a village called Fen Hollow.")] == ["Fen Hollow"]
    assert [m["place"] for m in IP.chat_mentions(
        "Go to Fen Hollow, then go to Fen Hollow again, and visit Brightwater.")] == ["Fen Hollow", "Brightwater"]
    s, st = fresh(tmp_path)
    assert IP.from_chat(st, "Morgan", "Go to Fallow.", now=1000.0)[0]["created_at"] == 1000.0


def test_named_in_matches_a_text_that_is_just_the_name(tmp_path):
    s, st = fresh(tmp_path)
    rec = heard(st)
    assert IP.named_in([rec], "Saltholm") == [rec] and IP.named_in([rec], "nowhere") == []


def test_the_backfill_only_reads_the_newest_two_hundred_open_to_dos(tmp_path):
    s, st = fresh(tmp_path)
    s.invented_places_per_day = 5
    st.log("companion", name="Briar", text="Briar says Fallow and Brenfold are lovely, and Dunmere and Eskdale too.")
    for _ in range(300):
        st.log("noise")                                                              # past the go_to backstop's reach
    st.add_memory("go to Brenfold", "todo")
    st.add_memory("go to Fallow", "todo")
    for i in range(199):
        st.add_memory(f"mend the clock {i}", "todo")
    st.resolve_memory(st.add_memory("go to Dunmere", "todo"))
    st.add_memory("go to Eskdale", "wishlist")
    found = IP.backfill(st, now=1000.0)
    assert [r["key"] for r in found] == ["Fallow"] and [r["key"] for r in st.place_rows()] == ["Fallow"]
    assert found[0]["created_at"] == 1000.0


def test_the_backfill_skips_weekdays_and_runs_once(tmp_path):
    s, st = fresh(tmp_path)
    st.log("companion", name="Briar", text="Briar mends nets on Thursday, then walks to Fallow.")
    st.add_memory("Thursday: Fallow with Briar", "todo")
    assert [r["key"] for r in IP.backfill(st)] == ["Fallow"]
    st.log("companion", name="Briar", text="Briar says Brenfold is lovely.")
    st.add_memory("go to Brenfold", "todo")
    assert IP.backfill(st) == [] and st.place_row("Brenfold") is None


def test_the_backfill_returns_nothing_when_nobody_named_the_place(tmp_path):
    s, st = fresh(tmp_path)
    st.add_memory("go to Fallow", "todo")
    assert IP.backfill(st) == []


def test_what_was_promised_reuses_existing_names_without_repeats(tmp_path):
    s, st = fresh(tmp_path)
    known = IP.known_items(st)
    assert IP.promised({"mentions": [{"there": "wire"}]}, known) == []                # an old mention with no items
    assert IP.promised({"mentions": [{"there": "", "items": ["Wild Berries"]}]}, known) == [
        {"name": "wild berries", "kind": "food", "tier": "uncommon", "description": ""}]
    assert IP.promised({"mentions": [{"there": "", "items": ["brass wire", "thin brass wire"]}]}, known) == [
        {"name": "brass wire", "kind": "material", "tier": "uncommon", "description": ""}]


def test_build_loot_counts_tools_already_there(tmp_path):
    existing = [["pliers", "tool", 3, [1, 1], "p", {}], ["saw", "tool", 3, [1, 1], "s", {}]]
    out = IP.build_loot([{"name": "awl", "kind": "tool"}], "shop", {}, [], random.Random(1), existing=existing)
    assert [e[0] for e in out] == ["pliers", "saw"]


def test_build_loot_cleans_names_and_keeps_descriptions(tmp_path):
    entries = [{"name": "Rope.", "kind": "material", "description": "a coil of rope"}, {"name": "nets", "kind": "material"},
               {"name": "floats", "kind": "material", "description": "d" * 101}, {"name": "q" * 41, "kind": "material"},
               {"name": "Xmas cake", "kind": "food"}]
    out = IP.build_loot(entries, "shop", {}, [], random.Random(1))
    assert [e[0] for e in out] == ["rope", "nets", "floats", "q" * 40, "xmas cake"]
    assert [e[4] for e in out][:3] == ["a coil of rope", "nets", clip("d" * 101, 100)]


def test_build_loot_takes_ten_entries_from_the_first_twenty(tmp_path):
    many = [{"name": f"thing {chr(97 + i)}", "kind": "material"} for i in range(12)]
    assert len(IP.build_loot(many, "wild", {}, [], random.Random(1))) == 10
    late = ["junk"] * 20 + [{"name": "rope", "kind": "material"}]
    assert IP.build_loot(late, "wild", {}, [], random.Random(1)) == []
    assert IP.build_loot(None, "wild", {}, [], random.Random(1)) == []


def test_a_promise_kept_by_a_longer_name_isnt_added_again():
    promise = {"name": "hemp twine", "kind": "material", "tier": "uncommon", "description": ""}
    out = IP.build_loot([{"name": "thick hemp twine", "kind": "material"}], "wild", {}, [promise], random.Random(1))
    assert [e[0] for e in out] == ["thick hemp twine"]


class DesignGM:
    def __init__(self, raw):
        self.raw, self.calls = raw, []

    async def design_place(self, label, said, known):
        self.calls.append((label, said, known))
        return self.raw


async def test_realise_asks_the_gm_with_what_was_said_and_keeps_its_numbers(tmp_path):
    s, st = fresh(tmp_path)
    now = time.time()
    IP.accept(st, "Briar", "Fallow is a meadow.", {"place": "Fallow", "there": "a meadow"}, now=now)
    IP.add_to(st, "Fallow", "Morgan", "", {"place": "Fallow"}, now=now)
    loot = [{"name": f"thing {c}", "kind": "material", "tier": "common"} for c in "abc"]
    gm = DesignGM({"kind": "wild", "description": "A meadow.", "loot": loot})
    assert await IP.realise(st, None, "Fallow", "Fallow") is None
    assert await IP.realise(st, gm, "Nowhere", "Nowhere") is None
    rec = await IP.realise(st, gm, "Fallow", "Fallow", rng=random.Random(5), now=now)
    assert gm.calls == [("Fallow", ["Briar says: a meadow", "Morgan mentioned it"],
                         sorted({n for n, _ in IP.known_items(st).values()} - {"thing a", "thing b", "thing c"}))]
    r = random.Random(5)
    assert [e[2] for e in rec["loot"]] == [r.randint(15, 30) for _ in range(3)] and rec["real_at"] == now
    assert await IP.realise(st, gm, "Fallow", "Fallow", now=now + 2 * DAY) is None and len(gm.calls) == 1   # real now


async def test_a_design_from_exactly_a_day_ago_doesnt_count(tmp_path):
    s, st = fresh(tmp_path)
    now = time.time()
    heard(st, "Fallow", "near", "a meadow", now=now)
    heard(st, "Brenfold", "near", "a meadow", now=now + 1)
    st.update_place("Brenfold", status="real", real_at=now - DAY)
    assert (await IP.realise(st, DesignGM({"description": "A meadow."}), "Fallow", "Fallow", now=now))["status"] == "real"


class Shelves:
    def available(self):
        return True


def test_the_names_and_instruction_follow_the_settings_and_the_library(tmp_path):
    s, st, *_ = make(tmp_path, wild_places=[])
    heard(st)
    assert IP.known_names(st, s, Shelves()) == ["the library", "Saltholm"]
    assert IP.mention_instruction(st, s, Shelves()) == (
        "Only if your words point Pip to a place it could go that isn't one of these: the library, Saltholm, give "
        "`mentions_place` (`place`: the destination as you said it; `there`: what you say is there, under 120 "
        "characters; `distance`: near, far or very far, as you'd put it; `items`: things you say can be had there). "
        "Not your own home, not landscape you just pass through.")
    assert IP.places_line(st, "Marigold", s, Shelves()) == (
        f"Places in Pip's world: the library (books); Saltholm, a long walk")


def test_the_places_line_names_two_finds_or_just_that_pip_has_been(tmp_path):
    s, st, *_ = make(tmp_path, wild_places=[])
    real_shop(st)
    assert IP.places_line(st, "Marigold", s) == "Places in Pip's world: Saltholm, a long walk (Pip has been)"
    for item, ts in (("rope", 1.0), ("nails", 2.0), ("brass wire", 3.0)):
        st.add_find("Saltholm", item, ts=ts)
    assert IP.places_line(st, "Marigold", s) == (
        "Places in Pip's world: Saltholm, a long walk (Pip has been and found brass wire, nails there)")


@pytest.mark.parametrize("walk, distance", [(14, "near"), (20, "near"), (21, "far"), (None, "very far")])
def test_patching_the_walk_sets_the_distance(tmp_path, walk, distance):
    s, st = fresh(tmp_path)
    real_shop(st)
    out = IP.patch(st, "Saltholm", {"walk_minutes": walk})
    assert out["walk_minutes"] == walk and out["distance"] == distance


def test_patch_clips_a_description_and_builds_loot_without_a_given_rng(tmp_path):
    s, st = fresh(tmp_path)
    real_shop(st)
    assert IP.patch(st, "Saltholm", {"description": "y" * 501})["description"] == "y" * 500 + "..."
    assert [e[0] for e in IP.patch(st, "Saltholm", {"loot": [{"name": "rope", "kind": "material"}]})["loot"]] == ["rope"]


@pytest.mark.parametrize("changes, message", [
    ({"walk_minutes": "far"}, "walk_minutes must be a number of minutes (or null: too far to walk)"),
    ({"colour": "blue", "age": 3}, "can't change age, colour (only walk_minutes, hours, description, loot)"),
    ({"hours": [9]}, "hours are [opens, closes], and only a shop keeps hours"),
    ({"description": " "}, "a description can't be empty"),
    ({"loot": "rope"}, "loot is a list of {name, kind, tier, description}, for a place Pip has been to"),
])
def test_patch_says_why_it_refuses(tmp_path, changes, message):
    s, st = fresh(tmp_path)
    real_shop(st)
    with pytest.raises(ValueError) as e:
        IP.patch(st, "Saltholm", changes)
    assert str(e.value) == message


async def test_a_half_stocked_shop_shows_half_as_much_and_lists_each_thing_on_account(tmp_path):
    s, st, gm, agent = setup(tmp_path, where="Saltholm")
    real_shop(st)
    st.update_place("Saltholm", hours=None, on_account={"brass wire": 2, "awl": 1})
    st.set_meta(**{"stock:Saltholm": 10, "stock_at:Saltholm": time.time()})          # half of the 20 for a full haul
    lines = (await call(agent, "browse")).text.split("\n")
    shown = lines[0].removeprefix("In stock at Saltholm today: ").removesuffix(". gather to pick through it.").split(", ")
    assert len(shown) == 2 and all(n in [e[0] for e in st.place_row("Saltholm")["loot"]] for n in shown)
    assert lines[1] == "On account here: 2 brass wire, 1 awl (nothing's owed yet; you can settle up later)."


def test_a_design_keeps_its_own_kind_and_resets_daylight(tmp_path):
    s, st = fresh(tmp_path)
    s.invented_places_per_day = 5
    fallow = heard(st, "Fallow", "near", "a meadow by the shop", now=time.time())
    assert fallow["kind"] == "wild" and fallow["daylight_only"] == 1
    out = IP.design(st, fallow, {"kind": "shop", "description": "A meadow. With larks.", "loot": [
        {"name": "rope", "kind": "material"}]}, random.Random(1))
    assert out["kind"] == "shop" and out["daylight_only"] == 0 and out["blurb"] == "A meadow."
    skerry = heard(st, "Skerry", "near", "a beach", now=time.time())
    assert IP.design(st, skerry, {"kind": "sight", "description": "A beach."}, random.Random(1))["kind"] == "sight"


def test_a_design_with_a_proper_trade_name_is_a_shop(tmp_path):
    s, st = fresh(tmp_path)
    rec = IP.accept(st, "Briar", "Go to the Fishmonger.", {"place": "the Fishmonger", "there": "a quiet place"},
                    now=time.time())
    assert IP.design(st, rec, {"kind": "shop", "description": "Fish."}, random.Random(1))["kind"] == "shop"


def test_a_designs_words_are_clipped_at_their_limits(tmp_path):
    s, st = fresh(tmp_path)
    rec = heard(st, "Skerry", "near", "a beach", now=time.time())
    out = IP.design(st, rec, {"kind": "wild", "description": "y" * 501, "gather_help": "h" * 81, "gerund": "g" * 41,
                              "loot": [{"name": "driftwood", "kind": "material"}]}, random.Random(1))
    assert out["description"] == "y" * 500 + "..." and out["verbs"]["gather"] == ["h" * 80 + "...", "g" * 40 + "..."]
    assert out["blurb"] == "y" * 120 + "..."
    st.update_place("Skerry", status="heard")
    out = IP.design(st, st.place_row("Skerry"), {"kind": "wild", "description": "b" * 121 + ". More.", "blurb": "c" * 121},
                    random.Random(1))
    assert out["blurb"] == "c" * 120 + "..."
    st.update_place("Skerry", status="heard")
    out = IP.design(st, st.place_row("Skerry"), {"kind": "wild", "description": "b" * 121 + ". More."}, random.Random(1))
    assert out["blurb"] == "b" * 120 + "..."


def test_a_resident_is_kept_with_their_name_and_never_chatters_on_their_own(tmp_path):
    s, st = fresh(tmp_path)
    IP.design(st, known_shop(st), {**DESIGN, "resident": {**TEAGUE, "name": "Xavier Teague"}}, random.Random(2))
    (ch,) = st.characters()
    assert ch["name"] == "Xavier Teague" and ch["chatter_minutes"] == 0 and ch["next_chatter_at"] == 0


def test_the_backfill_looks_past_a_name_said_first_in_a_sentence(tmp_path):
    s, st = fresh(tmp_path)
    st.log("companion", name="Briar", text="Saltholm is lovely. Ask the man in Saltholm.")
    st.add_memory("go to Saltholm", "todo")
    assert [r["key"] for r in IP.backfill(st)] == ["Saltholm"]
