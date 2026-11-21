"""Talk between agents as a scene (docs/DESIGN-multi-agent.md, "Talk between agents"): found on Ashfall (2026-11-18), every line one
agent said to another woke the listener for a whole world turn (about 11,500 tokens), so two neighbours chatting spent a day's budget by
morning, a line every fifteen seconds. Now the listener's turn, finding words from an agent who is here, runs the talk as one scene: each
speaks in turn from a small prompt of its own (its persona, its own notes on the other, the talk so far), heard at once, until a goodbye, a
silence or enough lines; then each has its world turn. For a while after, their words are heard without waking each other."""
import asyncio
import os
import time

import pytest

from app import loop, others, talk, world_pack as W
from app.config import Settings
from app.llm.base import LLMResponse, ToolCall, Usage
from app.llm.fake import FakeBackend
from tests.test_agents import two


def says(text, goodbye=None):
    return LLMResponse("", [ToolCall("s", "say", {"text": text, **({"goodbye": goodbye} if goodbye is not None else {})})], Usage(10, 5))


QUIET = LLMResponse("", [], Usage(1, 1))


@pytest.fixture
def world(tmp_path):
    os.makedirs(tmp_path / "data")
    s = Settings(world_pack=str(two(tmp_path)), db_path=str(tmp_path / "data" / "agent.db"), persona_path="/x", pacing="manual",
                 tools=["say", "write_letter", "go_to"], talk_scenes="on", reflect_hour=99, min_tick_interval=0)
    w = loop.build(s, FakeBackend())
    wren, ivo = w.agents
    for a in w.agents:
        a.state.update_agent(location="ruins")
    with wren.acting():
        others.seen(wren.state)                                             # they have met
    yield w
    W.set_active(W.load(Settings()))


def opens(speaker, listener, text):
    """A line said in a world turn (the say tool), as the speaker."""
    with speaker.acting():
        return others.say(speaker.state, listener, text)


def lines(agent, kind):
    return [(e["data"].get("to_name") or e["data"].get("sender"), e["data"]["text"]) for e in reversed(agent.state.events(50)) if e["kind"] == kind]


@pytest.mark.asyncio
async def test_a_line_from_an_agent_here_becomes_a_scene_with_each_speaking_for_itself(world):
    wren, ivo = world.agents
    backend = wren.backend
    backend.script = [says("Some, by the river."), says("Trade you a tin for it?"), says("Done. Safe roads.", goodbye=True)]
    opens(ivo, wren, "Found any wire?")
    with wren.acting():
        await wren.tick("event")
    assert len(backend.calls) == 3                                                            # three small calls, no world turn
    systems = [c["system"] for c in backend.calls]
    assert systems[0].startswith("You are Wren") and "face to face with Ivo" in systems[0]
    assert systems[1].startswith("You are Ivo, who trades salvage") and "face to face with Wren" in systems[1]
    ivos_turn = backend.calls[1]["messages"][0]["content"]
    assert "  You: Found any wire?\n  Wren: Some, by the river." in ivos_turn                  # his own view of the talk so far
    assert lines(wren, "say") == [("Ivo", "Some, by the river."), ("Ivo", "Done. Safe roads.")]
    assert lines(wren, "inbox") == [("Ivo", "Found any wire?"), ("Ivo", "Trade you a tin for it?")]
    assert lines(ivo, "say") == [("Wren", "Found any wire?"), ("Wren", "Trade you a tin for it?")]
    assert lines(ivo, "inbox") == [("Wren", "Some, by the river."), ("Wren", "Done. Safe roads.")]
    assert wren.state.pending_inbox() == [] == ivo.state.pending_inbox()
    talks = {a.identity.name: next(e["data"] for e in a.state.events(10) if e["kind"] == "talk") for a in world.agents}
    assert talks == {"Wren": {"name": "Ivo", "turns": 3, "ended": "Wren", "agent": True}, "Ivo": {"name": "Wren", "turns": 3, "ended": "Wren", "agent": True}}
    assert wren.state.meta("talked:ivo") and ivo.state.meta("talked:wren")
    assert wren._wake.is_set() and ivo._wake.is_set()                                          # each world turn takes it from here
    assert not wren.talking.locked() and not ivo.talking.locked()


@pytest.mark.asyncio
async def test_a_talk_ends_on_silence_on_enough_lines_or_when_someone_runs_out(world, monkeypatch):
    wren, ivo = world.agents
    backend = wren.backend
    backend.script = [says("Hello."), QUIET]
    opens(ivo, wren, "Morning.")
    with wren.acting():
        await wren.tick("event")
    assert [e["data"]["ended"] for e in wren.state.events(5) if e["kind"] == "talk"] == ["silence"]
    for a in world.agents:
        a.state.set_meta(**{f"talked:{o.identity.key}": "" for o in world.agents})
    monkeypatch.setattr(talk, "AGENT_LINES", 3)
    backend.script = [says("One."), says("Two."), says("Three."), says("Four.")]
    opens(ivo, wren, "Again.")
    with wren.acting():
        await wren.tick("event")
    assert [e["data"]["ended"] for e in wren.state.events(5) if e["kind"] == "talk"][0] == "turns" and backend.script == [says("Four.")]
    for a in world.agents:
        a.state.set_meta(**{f"talked:{o.identity.key}": "" for o in world.agents})
    monkeypatch.setattr(ivo.s, "daily_token_budget", 1)
    backend.script = [says("Still here?")]
    opens(ivo, wren, "Once more.")
    with wren.acting():
        await wren.tick("event")
    assert [e["data"]["ended"] for e in wren.state.events(5) if e["kind"] == "talk"][0] == "budget"


@pytest.mark.asyncio
async def test_after_a_talk_their_words_wait_without_waking_and_resume_the_talk_as_a_scene(world):
    """Found on Ashfall (2026-11-20): every talk ran to its line limit, then went on a line per world turn (about 15,000 tokens a line):
    140 such lines in a day. The owner: let the talk continue rather than the world turns carry it. Words left after a talk still don't
    wake the other for a while, but when the other's turn comes, they pick the talk up again as a scene."""
    wren, ivo = world.agents
    wren.backend.script = [says("Bye.", goodbye=True)]
    opens(ivo, wren, "Hello.")
    with wren.acting():
        await wren.tick("event")
    wren._wake.clear()
    assert opens(ivo, wren, "One more thing.") == "said it to Wren; she heard you"
    assert not wren._wake.is_set() and [m["text"] for m in wren.state.pending_inbox()] == ["One more thing."]
    calls = len(wren.backend.calls)
    wren.backend.script = [says("Go on."), says("Later, then.", goodbye=True)]
    with wren.acting():
        await wren.tick("timer")                                                              # her turn: the talk again, not a world turn
    assert all("Woke because" not in c["messages"][0]["content"] for c in wren.backend.calls[calls:])
    assert [e["data"]["ended"] for e in wren.state.events(30) if e["kind"] == "talk"] == ["Ivo", "Wren"]
    assert wren.state.pending_inbox() == []
    assert talk.agent_waiting(wren.state, [{"source": "agent", "sender": "Ivo"}]) is ivo           # lately or not, words here are a talk


@pytest.mark.asyncio
async def test_a_long_talk_runs_to_its_goodbye(world):
    """Found on Ashfall (2026-11-20): no talk between agents ended on a goodbye; all stopped at eight lines, mid-task."""
    wren, ivo = world.agents
    wren.backend.script = [says(f"Line {i}.") for i in range(14)] + [says("That's all.", goodbye=True)]
    opens(ivo, wren, "Got a minute?")
    with wren.acting():
        await wren.tick("event")
    assert [e["data"] for e in wren.state.events(80) if e["kind"] == "talk"][0] == {"name": "Ivo", "turns": 15, "ended": "Wren", "agent": True}
    assert talk.AGENT_LINES == 20


@pytest.mark.asyncio
async def test_a_scene_needs_the_other_here_and_free(world, monkeypatch):
    wren, ivo = world.agents
    monkeypatch.setattr(talk, "LOCK_WAIT", 0.01)
    opens(ivo, wren, "Hello?")
    await ivo.talking.acquire()                                                              # Ivo is busy with a turn of his own
    try:
        wren.backend.script = [QUIET]
        with wren.acting():
            await wren.tick("event")
        assert "Woke because" in wren.backend.calls[-1]["messages"][0]["content"]               # the old way: a world turn
        assert not [e for e in wren.state.events(10) if e["kind"] == "talk"]
    finally:
        ivo.talking.release()
    for inbox, who in (([{"source": "agent", "sender": "Ivo"}], ivo), ([{"source": "web", "sender": "Ivo"}], None),
                       ([{"source": "agent", "sender": "Nobody"}], None), ([], None)):
        assert talk.agent_waiting(wren.state, inbox) is who
    ivo.state.update_agent(location="lockup")
    assert talk.agent_waiting(wren.state, [{"source": "agent", "sender": "Ivo"}]) is None          # he's gone: no scene
    monkeypatch.setattr(wren.s, "talk_scenes", "off")
    ivo.state.update_agent(location="ruins")
    wren.backend.script = [QUIET]
    opens(ivo, wren, "Hello again?")
    with wren.acting():
        await wren.tick("event")
    assert not [e for e in wren.state.events(10) if e["kind"] == "talk"]


@pytest.mark.asyncio
async def test_a_scene_at_its_edges(world):
    wren, ivo = world.agents
    backend = wren.backend
    visitor = wren.receive("Anyone home?", "Morgan")
    wren._wake.clear()
    feel = ToolCall("f", "feel", {"emotion": "joy"})
    backend.script = [LLMResponse("thinking", [ToolCall("e", "say", {"text": "  "}), ToolCall("s", "say", {"text": "Hello, Ivo."}),
                                               ToolCall("t", "say", {"text": "And again."}), feel], Usage(7, 3)),
                      LLMResponse("", [ToolCall("s", "say", {"text": "Off I go."})], Usage(5, 2))]
    wren.tools["feel"] = __import__("app.tools", fromlist=["REGISTRY"]).REGISTRY["feel"]
    opens(ivo, wren, "Hi.")

    async def walks_off(*a, **k):                                                            # Ivo leaves as he speaks
        ivo.state.update_agent(location="lockup")
        return await real(*a, **k)
    real = ivo._scene_line
    ivo._scene_line = walks_off
    with wren.acting():
        await wren.tick("event")
    assert [m["id"] for m in wren.state.pending_inbox()] == [visitor]                          # a visitor's words wait for a world turn
    assert lines(wren, "say") == [("Ivo", "Hello, Ivo.")]                                        # one line a turn, never an empty one
    assert [e["data"]["ended"] for e in wren.state.events(5) if e["kind"] == "talk"] == ["parted"]
    ticks = [{k: v for k, v in e["data"].items() if k != "firsts"} for e in reversed(wren.state.events(30))
             if e["kind"] == "tick" and e["data"]["reason"] == "talk"]
    assert ticks == [{"reason": "talk", "step": 0, "text": "thinking", "tokens": 10, "tools": ["say", "say", "say", "feel"]}]
    assert wren.state.usage_today()["total_tokens"] == 10 and ivo.state.usage_today()["total_tokens"] == 7
    assert any(e["kind"] == "tool" and e["data"]["tool"] == "feel" for e in wren.state.events(30))
    assert "What you think of Ivo: a scavenger" in backend.calls[0]["messages"][0]["content"]


def test_how_long_a_talk_keeps_them_from_waking_each_other(world):
    wren, ivo = world.agents
    with wren.acting():
        assert not talk.lately(wren.state, ivo)                                                  # never talked
        wren.state.set_meta(**{"talked:ivo": "1000.0"})
        quiet = talk.AGENT_QUIET_MINUTES * 60
        assert talk.lately(wren.state, ivo, now=1000.0 + 10) and talk.lately(wren.state, ivo, now=1000.0 + quiet - 1)
        assert not talk.lately(wren.state, ivo, now=1000.0 + quiet)
    with ivo.acting():
        wren._wake.clear()
        others.say(ivo.state, wren, "Never talked, so this wakes her.")
    assert wren._wake.is_set()


@pytest.mark.asyncio
async def test_a_talk_can_close_a_deal_and_the_world_turn_after_sees_it_all(world):
    """Found on Ashfall (2026-11-18): Ivo and Hester struck a deal in a talk; then each world turn, not shown the talk, asked again."""
    from app import tools as T
    wren, ivo = world.agents
    for a in world.agents:
        a.tools["give"] = T.REGISTRY["give"]
    ivo.state.add_item("copper wire", 11, "material", "clean")
    backend = wren.backend
    backend.script = [says("Four coins for the lot."),
                      LLMResponse("", [ToolCall("g", "give", {"to": "Wren", "item": "copper wire", "quantity": 11}),
                                       ToolCall("s", "say", {"text": "Done. There it is."})], Usage(10, 5)),
                      LLMResponse("", [ToolCall("g", "give", {"to": "Ivo", "coins": 4}), ToolCall("s", "say", {"text": "And your coins.", "goodbye": True})], Usage(10, 5)),
                      QUIET]
    opens(ivo, wren, "Copper wire, eleven lengths. Interested?")
    with wren.acting():
        await wren.tick("event")
    assert "give" in backend.calls[1]["tools"]                                                      # offered in a talk
    assert wren.state.find_item("copper wire")[0]["qty"] == 11 and ivo.state.coins() == 14 and wren.state.coins() == 6
    hers = backend.calls[2]["messages"][0]["content"]
    assert "  Ivo: (hands you 11 x copper wire)\n  Ivo: Done. There it is." in hers                 # in the talk, as it happened
    with wren.acting():
        await wren.tick("event")                                                                    # her world turn: the whole talk in view
    p = backend.calls[-1]["messages"][0]["content"]
    assert "Talking with Ivo (this visit, oldest first):" in p and "  You: (hand Ivo 4 coins)" in p and "  You: And your coins." in p
    assert "Your conversation with Ivo so far" not in p                                             # the talk, once: not as a visitor's chat too


@pytest.mark.asyncio
async def test_a_talk_lifts_each_once_not_every_line(world, monkeypatch):
    """Found on Ashfall (2026-11-18): each line heard from another agent was appraised as a visitor writing (joy +5, trust +4,
    sadness -6), so a chatty day put everyone's joy and trust at 100, grumpy Hester's too. The owner: a talk counts once, as company;
    how it felt beyond that is the agent's own `feel`. A visitor's message still lifts as before."""
    from app import emotions as emo
    wren, ivo = world.agents
    before = {a.identity.key: emo.levels(a.state) for a in world.agents}
    wren.backend.script = [says(f"Line {i}.") for i in range(7)] + [says("Bye.", goodbye=True)]
    opens(ivo, wren, "Hello.")
    with wren.acting():
        await wren.tick("event")
    for a in world.agents:
        with a.acting():
            now = emo.levels(a.state)
        moved = {n: round(now[n] - before[a.identity.key][n]) for n in ("joy", "trust", "sadness")}
        assert moved == {"joy": 4, "trust": 2, "sadness": -3}, (a.identity.name, moved)
    causes = [r for r in wren.state.db.execute("SELECT emotion, delta, cause FROM emotion_log WHERE emotion = 'joy'").fetchall()]
    assert [(r["delta"], r["cause"]) for r in causes] == [(4.0, "talked with Ivo")]
    with wren.acting():
        wren.receive("A visitor's hello.", "Morgan")                                           # a visitor still lifts, as before
    assert [r["cause"] for r in wren.state.db.execute("SELECT cause FROM emotion_log WHERE emotion = 'joy' ORDER BY rowid")][-1] == "Morgan wrote"


@pytest.mark.asyncio
async def test_talking_with_someone_lifts_once_a_day_not_every_talk(world):
    """Found on Ashfall (2026-11-20): with a talk every half hour, each lifting joy and trust, grumpy Hester ended the days at joy 39,
    71, 68 (her baseline 30) and trust 29, 48, 64. A day's company with someone lifts once; how a talk felt is the agent's own `feel`."""
    def joys(agent):
        return [r["delta"] for r in agent.state.db.execute("SELECT delta FROM emotion_log WHERE emotion = 'joy' AND cause = 'talked with Ivo'")]

    wren, ivo = world.agents
    for _ in range(2):
        wren.backend.script = [says("Morning."), says("Bye.", goodbye=True)]
        opens(ivo, wren, "Hello.")
        with wren.acting():
            await wren.tick("event")
    assert joys(wren) == [4.0] and wren.state.meta("company:ivo") == time.strftime("%Y-%m-%d")
    talks = [e["data"] for e in wren.state.events(40) if e["kind"] == "talk"]
    assert [t.get("again", False) for t in talks] == [True, False]                       # newest first
    wren.state.set_meta(**{"company:ivo": "2000-01-01"})                                      # a new day
    wren.backend.script = [says("Morning."), says("Bye.", goodbye=True)]
    opens(ivo, wren, "Hello.")
    with wren.acting():
        await wren.tick("event")
    assert joys(wren) == [4.0, 4.0]


def test_how_a_talk_is_appraised():
    from app import emotions as emo
    assert emo._appraisal("talk", {"agent": True, "name": "Ivo"}) == (emo.TALKED, "talked with Ivo")
    assert emo._appraisal("talk", {"agent": True}) == (emo.TALKED, "talked with someone")
    assert emo._appraisal("talk", {"agent": True, "again": True, "name": "Ivo"}) == ({}, "")              # already counted today
    assert emo._appraisal("talk", {"name": "Marta", "turns": 3, "ended": "agent"}) == ({}, "")          # with a character: no lift
