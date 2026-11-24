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
def world(tmp_path, monkeypatch):
    os.makedirs(tmp_path / "data")
    s = Settings(world_pack=str(two(tmp_path)), db_path=str(tmp_path / "data" / "agent.db"), persona_path="/x", pacing="manual",
                 tools=["say", "write_letter", "go_to"], talk_scenes="on", reflect_hour=99, min_tick_interval=0)
    w = loop.build(s, FakeBackend())
    wren, ivo = w.agents
    for a in w.agents:
        a.state.update_agent(location="ruins")
    with wren.acting():
        others.seen(wren.state)                                             # they have met
    w.waits = []

    async def wait(seconds):                                                # a talk's pauses, noted and not waited out
        w.waits.append(seconds)
    monkeypatch.setattr(talk, "wait", wait)
    yield w
    W.set_active(W.load(Settings()))


def opens(speaker, listener, text):
    """A line said in a world turn (the say tool), as the speaker."""
    with speaker.acting():
        return others.say(speaker.state, listener, text)


async def turn(agent, reason="event"):
    """The agent's turn, and any talk it starts, to its end."""
    with agent.acting():
        await agent.tick(reason)
    await asyncio.gather(*agent.world.talks.values())


def lines(agent, kind):
    return [(e["data"].get("to_name") or e["data"].get("sender"), e["data"]["text"]) for e in reversed(agent.state.events(50)) if e["kind"] == kind]


@pytest.mark.asyncio
async def test_a_line_from_an_agent_here_becomes_a_scene_with_each_speaking_for_itself(world):
    wren, ivo = world.agents
    backend = wren.backend
    backend.script = [says("Some, by the river."), says("Trade you a tin for it?"), says("Done. Safe roads.", goodbye=True)]
    opens(ivo, wren, "Found any wire?")
    await turn(wren, "event")
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
async def test_a_talk_ends_on_silence_after_a_while_or_when_someone_runs_out(world, monkeypatch):
    wren, ivo = world.agents
    backend = wren.backend
    backend.script = [says("Hello."), QUIET]
    opens(ivo, wren, "Morning.")
    await turn(wren, "event")
    assert [e["data"]["ended"] for e in wren.state.events(5) if e["kind"] == "talk"] == ["silence"]
    for a in world.agents:
        a.state.set_meta(**{f"talked:{o.identity.key}": "" for o in world.agents})
    monkeypatch.setattr(talk, "STRETCH_MINUTES", 1)                                          # three lines of 20.4 s pass a minute
    backend.script = [says("One."), says("Two."), says("Three."), says("Four.")]
    opens(ivo, wren, "Again.")
    wren._wake.clear()
    ivo._wake.clear()
    await turn(wren, "event")
    assert [e["data"]["ended"] for e in wren.state.events(5) if e["kind"] == "talk"][0] == "a while" and backend.script == [says("Four.")]
    assert wren._wake.is_set() and ivo._wake.is_set()                                              # each has a world turn, then on
    for a in world.agents:
        a.state.set_meta(**{f"talked:{o.identity.key}": "" for o in world.agents})
    monkeypatch.setattr(talk, "STRETCH_MINUTES", 20)
    monkeypatch.setattr(ivo.s, "daily_token_budget", ivo.state.usage_today()["total_tokens"] + 1)    # one line left in him
    backend.script = [says("Still here?"), says("Just."), says("Good."), says("Never said.")]
    opens(ivo, wren, "Once more.")
    await turn(wren, "event")
    assert [e["data"]["ended"] for e in wren.state.events(5) if e["kind"] == "talk"][0] == "budget" and backend.script == [says("Never said.")]


@pytest.mark.asyncio
async def test_after_a_talk_their_words_wait_without_waking_and_resume_the_talk_as_a_scene(world):
    """Found on Ashfall (2026-11-20): every talk ran to its line limit, then went on a line per world turn (about 15,000 tokens a line):
    140 such lines in a day. The owner: let the talk continue rather than the world turns carry it. Words left after a talk still don't
    wake the other for a while, but when the other's turn comes, they pick the talk up again as a scene."""
    wren, ivo = world.agents
    wren.backend.script = [says("Bye.", goodbye=True)]
    opens(ivo, wren, "Hello.")
    await turn(wren, "event")
    wren._wake.clear()
    assert opens(ivo, wren, "One more thing.") == "said it to Wren; she heard you"
    assert not wren._wake.is_set() and [m["text"] for m in wren.state.pending_inbox()] == ["One more thing."]
    calls = len(wren.backend.calls)
    wren.backend.script = [says("Go on."), says("Later, then.", goodbye=True)]
    await turn(wren, "timer")                                                                 # her turn: the talk again, not a world turn
    assert all("Woke because" not in c["messages"][0]["content"] for c in wren.backend.calls[calls:])
    assert [e["data"]["ended"] for e in wren.state.events(30) if e["kind"] == "talk"] == ["Ivo", "Wren"]
    assert wren.state.pending_inbox() == []
    assert talk.agent_waiting(wren.state, [{"source": "agent", "sender": "Ivo"}]) is ivo           # lately or not, words here are a talk


@pytest.mark.asyncio
async def test_a_long_talk_runs_to_its_goodbye(world):
    """Found on Ashfall (2026-11-20): no talk between agents ended on a goodbye; all stopped at eight lines, mid-task. A talk has no
    limit on lines (2026-11-21): it takes time instead."""
    wren, ivo = world.agents
    wren.backend.script = [says(f"Line {i}.") for i in range(14)] + [says("That's all.", goodbye=True)]
    opens(ivo, wren, "Got a minute?")
    await turn(wren, "event")
    assert [e["data"] for e in wren.state.events(80) if e["kind"] == "talk"][0] == {"name": "Ivo", "turns": 15, "ended": "Wren", "agent": True}
    assert len(world.waits) == 14                                                                # no limit on lines: only time


@pytest.mark.asyncio
async def test_a_scene_needs_the_other_here_and_free(world, monkeypatch):
    wren, ivo = world.agents
    monkeypatch.setattr(talk, "LOCK_WAIT", 0.01)
    opens(ivo, wren, "Hello?")
    await ivo.talking.acquire()                                                              # Ivo is busy with a turn of his own
    try:
        wren.backend.script = [QUIET]
        await turn(wren, "event")
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
    await turn(wren, "event")
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
    await turn(wren, "event")
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
    await turn(wren, "event")
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
    await turn(wren, "event")
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
        await turn(wren, "event")
    assert joys(wren) == [4.0] and wren.state.meta("company:ivo") == time.strftime("%Y-%m-%d")
    talks = [e["data"] for e in wren.state.events(40) if e["kind"] == "talk"]
    assert [t.get("again", False) for t in talks] == [True, False]                       # newest first
    wren.state.set_meta(**{"company:ivo": "2000-01-01"})                                      # a new day
    wren.backend.script = [says("Morning."), says("Bye.", goodbye=True)]
    opens(ivo, wren, "Hello.")
    await turn(wren, "event")
    assert joys(wren) == [4.0, 4.0]


def test_how_a_talk_is_appraised():
    from app import emotions as emo
    assert emo._appraisal("talk", {"agent": True, "name": "Ivo"}) == (emo.TALKED, "talked with Ivo")
    assert emo._appraisal("talk", {"agent": True}) == (emo.TALKED, "talked with someone")
    assert emo._appraisal("talk", {"agent": True, "again": True, "name": "Ivo"}) == ({}, "")              # already counted today
    assert emo._appraisal("talk", {"name": "Marta", "turns": 3, "ended": "agent"}) == ({}, "")          # with a character: no lift


@pytest.mark.asyncio
async def test_each_line_of_a_talk_takes_its_speaking_time_and_a_pause(world):
    """Found on Ashfall (2026-11-21): with no brake between talks, Wren and Sela said a line a second for an hour and a half, about
    seventy talks back to back, and both spent their day's tokens by noon. The owner: the talk takes time, not a limit on lines; how
    long they stay together is the limit. A line takes as long as it takes to say (2.5 words a second) and a pause after it."""
    wren, ivo = world.agents
    assert talk.line_seconds("one two three four five") == 22.0 and talk.line_seconds("") == talk.LINE_PAUSE_SECONDS == 20
    wren.backend.script = [says("Some, by the river."), says("Trade you a tin for it?"), says("Done.", goodbye=True)]
    opens(ivo, wren, "Found any wire?")
    await turn(wren)
    assert world.waits == [talk.line_seconds("Some, by the river."), talk.line_seconds("Trade you a tin for it?")]   # none after a goodbye
    assert world.talks == {}


@pytest.mark.asyncio
async def test_between_lines_the_two_are_free_and_what_they_say_is_the_talk(world, monkeypatch):
    """A talk that takes time mustn't hold the agents: between lines each can have a world turn for what comes (a visitor, a letter),
    and what one says to the other in it is part of the talk they are having, not the start of another."""
    wren, ivo = world.agents
    backend = wren.backend
    seen = {}

    async def meanwhile(seconds):
        if seen:
            return
        seen["talking"] = (world.talking_with(wren), world.talking_with(ivo), wren.talking.locked(), ivo.talking.locked())
        wren._wake.clear()
        opens(ivo, wren, "By the way, the gate's shut.")                                      # his world turn, between lines
        seen["woken"] = wren._wake.is_set()                                                  # heard in the talk: no turn of hers for it
        visitor = wren.receive("Anyone home?", "Morgan")
        backend.script.insert(0, QUIET)                                                      # her world turn, for the visitor
        with wren.acting():
            await wren.tick("event")
        seen["turn"] = backend.calls[-1]["messages"][0]["content"]
        seen["pending"] = [m["sender"] for m in wren.state.pending_inbox()]
        seen["talks"] = len(world.talks)
        seen["visitor"] = visitor
    monkeypatch.setattr(talk, "wait", meanwhile)
    backend.script = [says("Morning."), says("Gate's shut, then. Bye.", goodbye=True)]
    opens(ivo, wren, "Morning, Wren.")
    await turn(wren)
    assert seen["talking"] == (ivo, wren, False, False)
    assert "Anyone home?" in seen["turn"] and "Ivo" not in seen["pending"] and seen["talks"] == 1
    assert [l for l in lines(wren, "inbox") if l[0] == "Ivo"] == [("Ivo", "Morning, Wren."), ("Ivo", "By the way, the gate's shut."),
                                                                  ("Ivo", "Gate's shut, then. Bye.")]
    assert seen["woken"] is False
    assert [e["data"]["turns"] for e in wren.state.events(40) if e["kind"] == "talk"] == [2]
    assert world.talking_with(wren) is None and world.talks == {}


@pytest.mark.asyncio
async def test_no_heartbeat_while_a_talk_goes_on(world, monkeypatch):
    """Talking, an agent is busy: its heartbeat waits (an event still wakes it), and wakes it once the talk is over."""
    from types import SimpleNamespace
    wren, ivo = world.agents
    wren.pacing = SimpleNamespace(next_delay=lambda now, last: 0.01, wakes_on_events=True)
    go_on = asyncio.Event()

    async def held(seconds):
        await go_on.wait()
    monkeypatch.setattr(talk, "wait", held)
    wren.backend.script = [says("Morning."), says("Bye.", goodbye=True)]
    opens(ivo, wren, "Morning, Wren.")
    with wren.acting():
        await wren.tick("event")
    wren._wake.clear()
    await asyncio.sleep(0.05)                                                                  # the first line, then the pause
    assert world.talking_with(wren) is ivo
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(wren._sleep(), 0.2)
    go_on.set()
    await asyncio.gather(*world.talks.values())
    assert await asyncio.wait_for(wren._sleep(), 1) == "event"                               # the talk over, her world turn
    wren._wake.clear()
    assert await asyncio.wait_for(wren._sleep(), 1) == "timer"                               # and her heartbeat again


def test_why_a_talk_cant_go_on_to_its_next_line(world, monkeypatch):
    """Between lines, one may have left or gone to bed in a turn of their own, or the one to speak may have run out."""
    wren, ivo = world.agents
    assert talk.cut_short(wren.state, ivo.state) is None
    ivo.state.update_agent(location="lockup")
    assert talk.cut_short(wren.state, ivo.state) == "parted"
    ivo.state.update_agent(location="ruins")
    for asleep in (ivo, wren):
        asleep.state.update_agent(activity="sleeping")
        assert talk.cut_short(wren.state, ivo.state) == "asleep"
        asleep.state.update_agent(activity="idle")
    monkeypatch.setattr(ivo.s, "daily_token_budget", 1)
    ivo.state.add_usage(5, 5)
    assert talk.cut_short(wren.state, ivo.state) is None and talk.cut_short(ivo.state, wren.state) == "budget"   # the speaker's own


@pytest.mark.asyncio
async def test_who_is_in_a_talk_is_only_whoever_is_in_one_still_going(world):
    wren, ivo = world.agents
    done, going = asyncio.Future(), asyncio.Future()
    done.set_result(None)
    world.talks = {frozenset(("wren", "ivo")): done, frozenset(("hester", "tobin")): going}
    assert world.talking_with(wren) is None and world.talking_with(ivo) is None              # theirs is over; someone else's isn't
    world.talks = {frozenset(("wren", "ivo")): going}
    assert world.talking_with(wren) is ivo and world.talking_with(ivo) is wren
    going.cancel()


@pytest.mark.asyncio
async def test_a_talk_runs_until_its_stretch_is_spent_to_the_second(world, monkeypatch):
    """Each line here takes 22 s (five words and the pause): a stretch of 44 s is two lines, and the last has no pause after it."""
    wren, ivo = world.agents
    five = "One two three four five."
    for stretch, lines_said, waits in ((44, 2, 1), (44.5, 3, 2)):
        monkeypatch.setattr(talk, "STRETCH_MINUTES", stretch / 60)
        world.waits.clear()
        wren.backend.script = [says(five) for _ in range(4)]
        opens(ivo, wren, "Morning.")
        await turn(wren)
        talked = [e["data"] for e in wren.state.events(30) if e["kind"] == "talk"][0]
        assert (talked["turns"], talked["ended"], len(world.waits)) == (lines_said, "a while", waits), stretch
        wren.backend.script = []


@pytest.mark.asyncio
async def test_a_talk_waits_for_one_busy_with_a_turn_of_their_own_but_not_for_ever(world, monkeypatch):
    """Between lines either may be in a turn of their own; the next line waits for it, and if it never comes, the talk ends."""
    wren, ivo = world.agents
    monkeypatch.setattr(talk, "LOCK_WAIT", 0.05)
    for busy in (ivo, wren):                                                                 # the first lock taken, and the second
        async def held(seconds):
            await busy.talking.acquire()                                                      # a long turn of theirs, between lines
        monkeypatch.setattr(talk, "wait", held)
        wren.backend.script = [says("Morning."), says("Never said.")]
        opens(ivo, wren, "Morning, Wren.")
        await asyncio.wait_for(turn(wren), 2)
        busy.talking.release()
        assert [e["data"]["ended"] for e in wren.state.events(30) if e["kind"] == "talk"][0] == "busy"
        assert wren.backend.script == [says("Never said.")] and world.talks == {}
        wren.backend.script = []


@pytest.mark.asyncio
async def test_a_talk_takes_in_only_the_other_ones_words(world, monkeypatch):
    """What the other said meanwhile is the talk's; a visitor's words, or another agent's, wait for a world turn."""
    wren, ivo = world.agents

    async def meanwhile(seconds):
        if not world.waits:
            opens(ivo, wren, "By the way, the gate's shut.")                                  # his world turn; she has none for it
        world.waits.append(seconds)
    monkeypatch.setattr(talk, "wait", meanwhile)
    wren.receive("A note from the gate.", "Ivo", source="web")
    wren.receive("Wren? It's Hester.", "Hester", source="agent")
    wren.backend.script = [says("Morning."), says("Shut, is it."), says("Bye.", goodbye=True)]
    opens(ivo, wren, "Morning, Wren.")
    await turn(wren)
    assert sorted((m["sender"], m["source"]) for m in wren.state.pending_inbox()) == [("Hester", "agent"), ("Ivo", "web")]
    assert "By the way, the gate's shut." in wren.backend.calls[2]["messages"][0]["content"]       # heard, in the talk, by her next line


@pytest.mark.asyncio
async def test_one_who_has_spent_the_days_tokens_is_too_worn_out_to_talk(world, monkeypatch):
    """Found live on Pip's world (2026-11-24): Oriel spent her day's tokens at 14:21; Pip, beside her, opened ten talks in four minutes,
    each over before a word (`budget`), and each followed by a world turn of Pip's. One who has run out doesn't talk, and isn't woken
    by being spoken to; the one speaking is told so, in the world's terms."""
    wren, ivo = world.agents
    monkeypatch.setattr(ivo.s, "daily_token_budget", 100)
    ivo.state.add_usage(90, 20)                                                                # spent
    ivo._wake.clear()
    with wren.acting():
        said = others.say(wren.state, ivo, "Still up for a talk?")
    assert said == "Ivo is too worn out to talk today; he heard you" and not ivo._wake.is_set()
    wren.backend.script = [QUIET]
    opens(ivo, wren, "Morning.")                                                               # words of his from before he ran out
    await turn(wren)
    assert not [e for e in wren.state.events(20) if e["kind"] == "talk"] and world.talks == {}
    assert "Woke because" in wren.backend.calls[-1]["messages"][0]["content"]                  # a turn of her own instead
