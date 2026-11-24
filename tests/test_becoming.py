"""A character who becomes an agent (docs/DESIGN-multi-agent.md, "A character becomes an agent"): the owner, 2026-11-22, wanted Oriel,
Pip's neighbour, to become an agent of her own, tried first on Ashfall with Marta at the gate. A world.json agent may name the character
it was (`was`); the first time it starts, it takes over what the character carried (her life, what she told, every exchange the agents
had with her, letters still in the post), everyone who dealt with her has met her, and the character steps aside."""
import json
import os
import time

import pytest

from app import loop, others, world_pack as W
from app.config import Settings
from app.llm.fake import FakeBackend
from tests.test_agents import WREN
from tests.test_world_pack import pack_dir

MARTA = {"key": "marta", "name": "Marta", "pronoun": "she", "kind": "the gatekeeper", "was": "Marta", "role": "villager",
         "home": {"key": "gatehouse", "description": "your home: the gatehouse by the village gate", "called": "gatehouse"}}


def world_with(tmp_path, agents, **kw):
    d = tmp_path / "ashfall" if (tmp_path / "ashfall").exists() else pack_dir(tmp_path, agents=[WREN, MARTA])
    (d / "places.json").write_text(json.dumps({"home": {"key": "shelter", "description": "your home: a shelter", "called": "shelter"},
                                              "start": [{"key": "village", "kind": "yard", "about": "a walled village", "description": "a walled village"}]}))
    os.makedirs(tmp_path / "data", exist_ok=True)
    s = Settings(world_pack=str(d), db_path=str(tmp_path / "data" / "agent.db"), persona_path="/x", pacing="manual", agents=agents, **kw)
    return loop.build(s, FakeBackend())


def kinds(agent):
    return [(e["kind"], {k: v for k, v in e["data"].items() if k in ("to", "to_name", "sender", "source", "text")}, round(e["ts"]))
            for e in reversed(agent.state.events(1000)) if e["kind"] in ("letter_sent", "inbox", "say")]


@pytest.fixture
def before(tmp_path):
    """Wren's world with Marta as a character at the village: they have written and talked, and a letter is on its way each way."""
    w = world_with(tmp_path, ["wren"])
    wren = w.agents[0]
    st = wren.state
    st.add_character("Marta", "villager", None, "Marta keeps the gate.", 60, 0, about="keeps the village gate", place="village", writes=True)
    marta = st.find_character("Marta")
    st.update_character(marta["id"], life=["The pumps failed on Tuesday."], told=["the east blocks have dogs"])
    sent = st.add_letter("Wren", "Marta", "Do you need wire?", 1000.0)
    st.update_letter(sent["id"], delivered_at=1000.0)
    got = st.add_letter("Marta", "Wren", "Wire, yes. Bring it Thursday.", 2000.0)
    st.update_letter(got["id"], delivered_at=2000.0)
    st.db.execute("UPDATE letters SET ts = deliver_at")
    st.add_letter("Wren", "Marta", "On my way with the wire.", time.time() + 3600)
    st.add_letter("Marta", "Wren", "The gate shuts at dusk.", time.time() + 7200)
    for ts, kind, data in ((3000.0, "say", {"text": "Morning, Marta.", "to": [], "to_name": "Marta"}),
                           (3001.0, "companion", {"name": "Marta", "text": "You're late, Wren.", "reply": True, "visit": True})):
        st.db.execute("INSERT INTO events (ts, kind, data) VALUES (?, ?, ?)", (ts, kind, json.dumps(data)))
    st.db.commit()
    yield tmp_path
    W.set_active(W.load(Settings()))


def test_a_pack_agent_may_name_the_character_it_was(tmp_path):
    d = pack_dir(tmp_path, agents=[WREN, MARTA])
    assert W.load(Settings(world_pack=str(d))).agent_named("marta").was == "Marta"
    assert W.load(Settings(world_pack=str(d))).agent_named("wren").was == ""
    (tmp_path / "ashfall" / "world.json").write_text(json.dumps({"name": "A", "api": 1, "agents": [WREN, {**MARTA, "was": ["Marta"]}]}))
    with pytest.raises(W.PackError, match="an agent's `was` is the name of a character it was$"):
        W.load(Settings(world_pack=str(tmp_path / "ashfall")))


def test_the_character_becomes_the_agent_with_what_she_carried(before):
    w = world_with(before, None)
    wren, marta = w.agents
    assert marta.state.meta("became") == "Marta" and wren.state.find_character("Marta") is None     # one Marta, now an agent
    learned = [m["text"] for m in marta.state.memories("learned", limit=20)]
    assert sorted(learned) == ["Something you have told others: the east blocks have dogs", "The pumps failed on Tuesday."]
    assert kinds(marta) == [("inbox", {"sender": "Wren", "source": "letter", "text": "Do you need wire?"}, 1000),
                            ("letter_sent", {"to": "Wren", "text": "Wire, yes. Bring it Thursday."}, 2000),
                            ("inbox", {"sender": "Wren", "source": "agent", "text": "Morning, Marta."}, 3000),
                            ("say", {"to": [], "to_name": "Wren", "text": "You're late, Wren."}, 3001)]      # her side of it, when it happened
    assert marta.state.pending_inbox() == [] and marta.state.db.execute("SELECT COUNT(*) FROM emotion_log").fetchone()[0] == 0
    assert [e["data"]["enclosed"] for e in marta.state.events(50) if e["kind"] == "letter_sent"] == [""]     # shaped as her own letters are
    with marta.acting():
        assert others.met(marta.state, wren)
    with wren.acting():
        assert others.met(wren.state, marta)
    became = [e["data"] for e in marta.state.events(50) if e["kind"] == "became"]
    assert became == [{"was": "Marta", "about": "keeps the village gate", "from": ["Wren"]}]


def test_letters_in_the_post_go_on_between_the_agents(before):
    w = world_with(before, None)
    wren, marta = w.agents
    post = wren.state.db.execute("SELECT sender, recipient, text, deliver_at FROM agent_post ORDER BY id").fetchall()
    assert [tuple(r)[:3] for r in post] == [("wren", "marta", "On my way with the wire."), ("marta", "wren", "The gate shuts at dusk.")]
    assert all(r["deliver_at"] > time.time() for r in post)                                  # when they were due, not now
    assert wren.state.letters(undelivered=True) == []                                         # none goes to the character any more


def test_it_happens_once_and_not_at_all_without_the_character(before, tmp_path):
    world_with(before, None)
    w = world_with(before, None)                                                              # started again
    marta = w.agents[1]
    assert len(kinds(marta)) == 4 and len([e for e in marta.state.events(50) if e["kind"] == "became"]) == 1
    fresh = world_with(tmp_path / "fresh", None)                                              # a world that never had her
    assert fresh.agents[1].state.meta("became") == "Marta" and kinds(fresh.agents[1]) == []
    assert not [e for e in fresh.agents[1].state.events(20) if e["kind"] == "became"]


def test_only_what_was_said_with_her_is_hers_however_long_it_ran(tmp_path):
    """Tobin said 73 lines to Marta in a few days: all of them are hers; what was said to anyone else stays where it was."""
    from app import memory
    w = world_with(tmp_path, ["wren"])
    st = w.agents[0].state
    st.add_character("Marta", "villager", None, "Marta keeps the gate.", 60, 0, about="keeps the gate", place="village")
    st.add_character("Ezra", "villager", None, "Ezra keeps the pumps.", 60, 0, about="keeps the pumps", place="village")
    rows = []
    for i in range(60):
        rows += [(1000.0 + 4 * i, "companion", {"name": "Ezra", "text": f"Pumps, {i}.", "reply": True}),
                 (1001.0 + 4 * i, "say", {"text": f"To Ezra, {i}.", "to": [], "to_name": "Ezra"}),
                 (1002.0 + 4 * i, "say", {"text": f"Gate question {i}.", "to": [], "to_name": "Marta"}),
                 (1003.0 + 4 * i, "companion", {"name": "Marta", "text": f"Gate answer {i}.", "reply": True})]
    st.db.executemany("INSERT INTO events (ts, kind, data) VALUES (?, ?, ?)", [(t, k, json.dumps(d)) for t, k, d in rows])
    for i in range(120):
        st.add_letter("Wren", "Marta" if i % 2 else "Ezra", f"Letter {i}.", 400.0 + i)
    st.db.execute("UPDATE letters SET delivered_at = deliver_at, ts = deliver_at")
    st.db.commit()
    W.set_active(W.load(Settings()))
    w = world_with(tmp_path, None)
    marta = w.agents[1]
    carried = kinds(marta)
    assert len(carried) == 180 and {c[1]["text"] for c in carried} >= {"Gate question 0.", "Gate answer 59.", "Letter 1.", "Letter 119."}
    assert not {c[1]["text"] for c in carried} & {"Pumps, 0.", "To Ezra, 0.", "Letter 0."}           # Ezra's, not hers
    assert carried[0] == ("inbox", {"sender": "Wren", "source": "letter", "text": "Letter 1."}, 401)
    row = marta.state.db.execute("SELECT id, data, importance FROM events WHERE kind = 'say' ORDER BY ts LIMIT 1").fetchone()
    assert row["importance"] == memory.event_importance("say", json.loads(row["data"]))
    assert marta.state.recall_text_of("event:say", row["id"]) == "You said to Wren: Gate answer 0."          # she can recall it
    ctx = marta.state.db.execute("SELECT people, importance FROM memory_context WHERE source = 'event:say' AND ref = ?", (str(row["id"]),)).fetchone()
    assert json.loads(ctx["people"]) == ["Wren"] and ctx["importance"] == row["importance"]               # and is reminded of it by Wren
    assert w.agents[0].state.find_character("Ezra") is not None
    W.set_active(W.load(Settings()))


def test_one_who_never_dealt_with_her_hasnt_met_her_and_she_comes_back_as_no_one(before):
    w = world_with(before, ["wren"])
    st = w.agents[0].state
    st.db.execute("DELETE FROM letters")
    st.db.execute("DELETE FROM events WHERE kind IN ('say', 'companion')")
    st.db.commit()
    W.set_active(W.load(Settings()))
    w = world_with(before, None)
    wren, marta = w.agents
    with marta.acting():
        assert not others.met(marta.state, wren)
    assert [e["data"]["from"] for e in marta.state.events(20) if e["kind"] == "became"] == [[]]
    wren.state.add_character("Marta", "villager", None, "A second Marta.", 60, 0, about="?", place="village")   # brought back by a module
    W.set_active(W.load(Settings()))
    w = world_with(before, None)
    assert len([e for e in w.agents[1].state.events(50) if e["kind"] == "became"]) == 1 and w.agents[0].state.find_character("Marta")


def test_letters_alone_are_dealings_enough_to_have_met(before):
    w = world_with(before, ["wren"])
    st = w.agents[0].state
    st.db.execute("DELETE FROM events WHERE kind IN ('say', 'companion')")
    st.db.commit()
    W.set_active(W.load(Settings()))
    w = world_with(before, None)
    wren, marta = w.agents
    with marta.acting():
        assert others.met(marta.state, wren)
    assert [e["data"]["from"] for e in marta.state.events(20) if e["kind"] == "became"] == [["Wren"]]
