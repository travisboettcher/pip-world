"""The conversation scene (docs/DESIGN-conversation.md, part 2): a talk in person runs as its own short scene, then the world turn picks up."""
import time

import pytest

from tests.test_garden import planted

from app import talk
from app import tools as T
from app.config import Settings
from app.llm.base import LLMResponse, ToolCall, Usage
from app.llm.fake import FakeBackend
from tests.test_neighbor import neighbor
from tests.test_projects import FixedRng, call, crafting, make, report

import app.neighbors as nb


def says(text, goodbye=None, feel=None):
    calls = [ToolCall("s", "say", {"text": text, **({"goodbye": goodbye} if goodbye is not None else {})})]
    if feel:
        calls.append(ToolCall("f", "feel", {"emotion": feel}))
    return LLMResponse("", calls, Usage(10, 5))


async def visiting(tmp_path, her_lines, pip_turns, **kw):
    """Pip walks to Marigold's, she greets it, and the scene's script is set: her answers (GM) and Pip's turns."""
    kw.setdefault("talk_scenes", "on")
    s, st, gm, agent = make(tmp_path, [report(text="A low cottage humming with bees."), report(text="Pip! Come in.")] + her_lines, work_speed=1e6, **kw)
    agent.tools.update({n: T.REGISTRY[n] for n in ("say", "feel", "go_to")})
    neighbor(st, s)
    await call(agent, "go_to", place="Marigold")
    time.sleep(0.01)
    await agent.finish_work()
    await nb.step(st, s, agent.gm, FixedRng(), time.time())                       # the greeting
    agent.backend = FakeBackend(pip_turns)
    return s, st, gm, agent


def lines(st):
    out = []
    for e in reversed(st.events(100)):
        if e["kind"] == "companion":
            out.append(("Marigold", e["data"]["text"]))
        elif e["kind"] == "say":
            out.append(("Pip", e["data"]["text"]))
    return out


@pytest.mark.asyncio
async def test_a_visit_becomes_a_talk_until_pip_says_goodbye(tmp_path):
    s, st, gm, agent = await visiting(tmp_path, [report(text="The hives are cross today. How is your garden?"), report(text="Go well, Pip.", goodbye=True)],
                                      [says("Hello! How are the bees?"), says("Growing well, thank you. I must get home.", goodbye=True)])
    await agent.tick("event")
    assert lines(st) == [("Marigold", "Pip! Come in."), ("Pip", "Hello! How are the bees?"), ("Marigold", "The hives are cross today. How is your garden?"),
                         ("Pip", "Growing well, thank you. I must get home."), ("Marigold", "Go well, Pip.")]
    ev = [e["data"] for e in st.events(30) if e["kind"] == "talk"][0]
    assert ev == {"name": "Marigold", "turns": 2, "ended": "pip"}
    assert st.meta("talk_done") == st.meta("arrived_at") and st.meta("talk_scene") == "" and agent._wake.is_set()
    assert [e["data"]["reason"] for e in st.events(30) if e["kind"] == "tick"] == ["talk", "talk"]
    assert st.characters("neighbor")[0]["heard"] == []                           # all answered in the scene


@pytest.mark.asyncio
async def test_pips_turn_has_a_small_prompt_with_the_talk_so_far_and_only_talking_tools(tmp_path):
    s, st, gm, agent = await visiting(tmp_path, [report(text="Cross today.")], [says("Hello! How are the bees?"), LLMResponse("", [], Usage(1, 1))])
    st.add_memory("Bring Marigold a jar of tomato seed.", "todo")
    st.upsert_person("Marigold", "A badger who keeps bees; kind but blunt.", time.time())
    await agent.tick("event")
    first = agent.backend.calls[0]
    p = first["messages"][0]["content"]
    assert "face to face with Marigold" in first["system"] and "How things work" not in first["system"]
    assert p.startswith("It is ") and "talking with Marigold." in p and "What you think of Marigold: A badger who keeps bees; kind but blunt." in p
    assert "What you meant to do about them:\n- Bring Marigold a jar of tomato seed." in p
    assert "Talking with Marigold (this visit, oldest first):\n  Marigold: Pip! Come in." in p and p.endswith("You may also feel something.")
    assert first["tools"] == ["say", "feel"] and len(p) < 2500
    second = agent.backend.calls[1]["messages"][0]["content"]
    assert "  You: Hello! How are the bees?\n  Marigold: Cross today." in second
    assert [e["data"] for e in st.events(30) if e["kind"] == "talk"][0]["ended"] == "silence"


@pytest.mark.asyncio
async def test_she_may_end_it_and_she_is_asked_whether_she_does(tmp_path):
    s, st, gm, agent = await visiting(tmp_path, [report(text="I must see to the hives now. Come again, Pip.", goodbye=True)], [says("Hello!")])
    await agent.tick("event")
    assert [e["data"] for e in st.events(30) if e["kind"] == "talk"][0] == {"name": "Marigold", "turns": 1, "ended": "Marigold"}
    task = gm.calls[-1]["messages"][0]["content"]
    assert "- `goodbye`: true only if this line closes the talk" in task
    said = [e["data"] for e in st.events(10) if e["kind"] == "companion"][0]
    assert said["goodbye"] is True


@pytest.mark.asyncio
async def test_a_talk_stops_after_six_of_pips_lines(tmp_path):
    hers = [report(text=t) for t in ["The bees swarmed twice.", "Rain is due by dusk.", "Salt is dear this week.", "My wool came in grey.",
                                     "I spilled the ink again.", "The oak dropped a limb.", "Ash makes the best handles."]]
    mine = [says(t) for t in ["Did you catch them?", "Then I'll cover my beds.", "I'll skip the salt.", "Grey suits a scarf.",
                              "Blot it with bread!", "Did it miss the roof?", "I'll keep an eye out for ash."]]
    s, st, gm, agent = await visiting(tmp_path, hers, mine)
    await agent.tick("event")
    assert [e["data"] for e in st.events(60) if e["kind"] == "talk"][0] == {"name": "Marigold", "turns": talk.SCENE_TURNS, "ended": "turns"}
    assert sum(1 for p, _ in lines(st) if p == "Pip") == talk.SCENE_TURNS


@pytest.mark.asyncio
async def test_after_the_talk_the_world_turn_takes_over(tmp_path):
    s, st, gm, agent = await visiting(tmp_path, [report(text="Go well.", goodbye=True)], [says("Bye for now!", goodbye=True),
                                                                                         LLMResponse("Back to my day.", [], Usage(1, 1))])
    await agent.tick("event")
    await agent.tick("timer")
    world = agent.backend.calls[1]
    assert "face to face" not in world["system"] and "Talking with Marigold (this visit, oldest first):" in world["messages"][0]["content"]
    assert "- you talked with Marigold (1 of your lines; you said goodbye)" in world["messages"][0]["content"]


@pytest.mark.asyncio
async def test_no_scene_when_it_is_off_or_a_visitor_is_waiting_or_she_has_not_spoken(tmp_path):
    s, st, gm, agent = await visiting(tmp_path, [], [LLMResponse("", [], Usage(1, 1))], talk_scenes="off")
    await agent.tick("event")
    assert not [e for e in st.events(30) if e["kind"] == "talk"] and "face to face" not in agent.backend.calls[0]["system"]
    (tmp_path / "b").mkdir()
    s, st, gm, agent = await visiting(tmp_path / "b", [], [LLMResponse("", [], Usage(1, 1))])
    agent.receive("Hello Pip, how's the visit?", "Travis")
    await agent.tick("event")
    assert not [e for e in st.events(30) if e["kind"] == "talk"]
    assert talk.waiting(st) is not None                                            # the talk waits until the visitor is answered


@pytest.mark.asyncio
async def test_who_pip_is_with_and_whether_a_talk_is_due(tmp_path):
    s, st, gm, agent = make(tmp_path, [report(text="A low cottage."), report(text="Pip! Come in.")], work_speed=1e6)
    agent.tools.update({n: T.REGISTRY[n] for n in ("say", "go_to")})
    ch = neighbor(st, s)
    assert talk.partner(st) is None and talk.waiting(st) is None
    await call(agent, "go_to", place="Marigold")
    assert talk.partner(st) is None                                                 # on the way, not there
    time.sleep(0.01)
    await agent.finish_work()
    assert talk.partner(st)["name"] == "Marigold" and talk.waiting(st) is None      # there, but she has not spoken yet
    await nb.step(st, s, agent.gm, FixedRng(), time.time())
    assert talk.waiting(st)["name"] == "Marigold"
    st.set_meta(talk_done=st.meta("arrived_at"))
    assert talk.waiting(st) is None


@pytest.mark.asyncio
async def test_a_goodbye_in_the_world_turn_ends_this_visits_talk(tmp_path):
    s, st, gm, agent = await visiting(tmp_path, [], [])
    r = await call(agent, "say", text="I have to go, Marigold. Goodbye!", to="Marigold", goodbye=True)
    assert r.text.startswith("said it to Marigold")
    assert st.meta("talk_done") == st.meta("arrived_at") and talk.waiting(st) is None
    assert [e["data"] for e in st.events(5) if e["kind"] == "say"][0]["goodbye"] is True


@pytest.mark.asyncio
async def test_the_monitor_leaves_answers_to_the_scene(tmp_path):
    s, st, gm, agent = await visiting(tmp_path, [report(text="Should not be said.")], [])
    await call(agent, "say", text="How are the bees?", to="Marigold")
    st.set_meta(talk_scene=st.meta("arrived_at"))
    before = len(gm.calls)
    await nb.step(st, s, agent.gm, FixedRng(), time.time())
    assert len(gm.calls) == before and st.characters("neighbor")[0]["heard"]
    st.set_meta(talk_scene="")
    await nb.step(st, s, agent.gm, FixedRng(), time.time())
    assert len(gm.calls) == before + 1


@pytest.mark.asyncio
async def test_a_talk_stops_when_the_days_tokens_are_spent_or_she_has_nothing_to_say(tmp_path):
    s, st, gm, agent = await visiting(tmp_path, [], [says("Hello there!")])
    st.add_usage(10 ** 9, 0)
    await agent.tick("event")
    assert [e["data"] for e in st.events(30) if e["kind"] == "talk"][0]["ended"] == "budget" and agent.backend.calls == []
    (tmp_path / "b").mkdir()
    s2, st2, gm2, agent2 = await visiting(tmp_path / "b", [report(text="")], [says("Hello there!")])
    await agent2.tick("event")
    assert [e["data"] for e in st2.events(30) if e["kind"] == "talk"][0]["ended"] == "no answer"


@pytest.mark.asyncio
async def test_feel_works_in_a_talk(tmp_path):
    s, st, gm, agent = await visiting(tmp_path, [report(text="Go well.", goodbye=True)], [says("That is lovely to hear!", feel="joy")])
    await agent.tick("event")
    assert [e["data"]["tool"] for e in st.events(30) if e["kind"] == "tool"][:2] == ["feel", "say"]


def test_the_setting():
    import os
    assert Settings().talk_scenes == "off"
    old = os.environ.pop("TALK_SCENES", None)
    try:
        assert Settings.from_env().talk_scenes == "on"
        os.environ["TALK_SCENES"] = "OFF"
        assert Settings.from_env().talk_scenes == "off"
        os.environ["TALK_SCENES"] = "maybe"
        assert Settings.from_env().talk_scenes == "on"
    finally:
        os.environ.pop("TALK_SCENES", None)
        if old is not None:
            os.environ["TALK_SCENES"] = old


# --- free time ---------------------------------------------------------------------------------------------------------------------
def test_free_time_is_said_with_what_pip_wants_to_do(tmp_path):
    s, st, gm, agent = make(tmp_path)
    st.add_memory("Build a self-winding clock.", "ambitions")
    st.add_memory("To run my own stall.", "wishlist", "activity")
    st.add_memory("A spool of wire.", "wishlist", "thing")
    planted(st, s, 1, "tomatoes", 600)
    crafting(st)
    got = agent._free_time(time.time())
    assert got[0] == "Nothing needs you for about 10 hours."
    assert got[1].startswith("Your ambitions: #") and "Build a self-winding clock." in got[1]
    assert got[2].startswith("Things you wish you could do: #") and "To run my own stall." in got[2] and "spool" not in got[2]
    assert got[3] == "start_project begins something new."
    assert "Nothing needs you for about 10 hours." in agent._perception("timer", [])


def test_no_free_time_when_something_is_due_soon_or_pip_is_out_or_busy(tmp_path):
    s, st, gm, agent = make(tmp_path)
    planted(st, s, 1, "tomatoes", 60)
    assert agent._free_time(time.time()) == []                                   # ripe within the hour
    (tmp_path / "b").mkdir()
    s2, st2, gm2, agent2 = make(tmp_path / "b")
    assert agent2._free_time(time.time()) == ["Nothing needs you for now."]
    st2.update_agent(location="woods")
    assert agent2._free_time(time.time()) == []
    st2.update_agent(location="workshop", activity="sleeping")
    assert agent2._free_time(time.time()) == []
    st2.update_agent(activity="idle")
    st2.start_session(0, 0, 10, time.time() + 600, kind="walk", target="woods")
    assert agent2._free_time(time.time()) == []
    st2.end_session()
    agent2.receive("hi", "Travis")
    assert agent2._free_time(time.time()) == []                                   # a visitor is waiting


def test_a_clock_that_needs_winding_soon_is_not_free_time(tmp_path):
    from tests.test_happenings import clock
    s, st, gm, agent = make(tmp_path)
    c = clock(st)
    st.set_runtime(c["id"], {**c["runtime"], "tended_until": time.time() + 30 * 60})
    assert agent._free_time(time.time()) == []
    st.set_runtime(c["id"], {**c["runtime"], "tended_until": time.time() + 5 * 3600})
    assert agent._free_time(time.time())[0] == "Nothing needs you for about 5 hours."
    st.add_memory("Build a self-winding clock.", "ambitions")
    assert "start_project begins something new." not in agent._free_time(time.time())   # no crafting module, no start_project


# --- letters --------------------------------------------------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_a_letter_that_repeats_an_earlier_one_is_written_again(tmp_path):
    s, st, gm, agent = make(tmp_path, [report(text="I laid my palm on the step this morning and it was still cool, so my own bed waits.", gist="g"),
                                       report(text="The heron came back to the flats today and stood for an hour.", gist="g2")])
    ch = neighbor(st, s)
    st.add_letter("Marigold", "pip", "Dear Pip, I laid my palm on the step this morning and it was still cool, so my bed waits.", time.time() - 10)
    assert await nb._write(st, s, agent.gm, FixedRng(), st.characters("neighbor")[0], time.time(), None) is True
    sent = [lt for lt in st.letters(between="Marigold", limit=5) if lt["sender"] == "Marigold"]
    assert any("heron" in lt["text"] for lt in sent) and len(gm.calls) == 2
    assert "Your first try repeated an earlier letter; write it afresh." in gm.calls[1]["messages"][0]["content"]
    assert "Don't reuse a sentence, image or daily ritual from your earlier letters" in gm.calls[0]["messages"][0]["content"]


class Watching(FakeBackend):
    """Pip's side of a talk, noting what the world looked like at each of its turns."""
    def __init__(self, script, state):
        super().__init__(script)
        self.state, self.seen = state, []

    async def complete(self, system, messages, tools, max_tokens):
        self.seen.append({"scene": self.state.meta("talk_scene"), "max_tokens": max_tokens, "role": messages[0]["role"]})
        return await super().complete(system, messages, tools, max_tokens)


@pytest.mark.asyncio
async def test_while_the_scene_runs_it_is_marked_and_each_turn_is_a_logged_tick(tmp_path):
    s, st, gm, agent = await visiting(tmp_path, [report(text="Come again soon.", goodbye=True)], [], llm_max_tokens=321)
    (tmp_path / "persona.md").write_text("You are Pip, a small tinkering robot.")
    agent.s.persona_path = str(tmp_path / "persona.md")
    agent.backend = Watching([LLMResponse("hm", [ToolCall("s", "say", {"text": "Hello, Marigold!"})], Usage(7, 4))], st)
    await agent.tick("event")
    visit = st.meta("arrived_at")
    assert agent.backend.seen == [{"scene": visit, "max_tokens": 321, "role": "user"}]
    assert agent.backend.calls[0]["system"].startswith("You are Pip, a small tinkering robot.")
    tick = [e["data"] for e in st.events(30) if e["kind"] == "tick"][0]
    tick.pop("firsts", None)
    assert tick == {"reason": "talk", "step": 0, "text": "hm", "tokens": 11, "tools": ["say"]}
    assert [e["data"] for e in st.events(30) if e["kind"] == "talk"][0]["ended"] == "Marigold"
    assert st.meta("talk_done") == visit and talk.waiting(st) is None             # she ended it: no second talk this visit


@pytest.mark.asyncio
async def test_feeling_without_saying_anything_ends_the_talk(tmp_path):
    s, st, gm, agent = await visiting(tmp_path, [report(text="Should not be needed.")], [LLMResponse("", [ToolCall("f", "feel", {"emotion": "joy"})], Usage(1, 1))])
    await agent.tick("event")
    assert [e["data"] for e in st.events(30) if e["kind"] == "talk"][0] == {"name": "Marigold", "turns": 1, "ended": "silence"}
    assert st.meta("talk_scene") == "" and st.meta("talk_done") == st.meta("arrived_at")


# --- the scene's pieces, exactly --------------------------------------------------------------------------------------------------
def test_pips_turn_prompt_in_full(tmp_path):
    s, st, gm, agent = make(tmp_path)
    ch = neighbor(st, s)
    st.update_agent(location="Marigold", activity="visiting", description="sitting on the step", mood="content")
    st.set_meta(arrived_at=str(time.time() - 60))
    for t in ["Ask Marigold about the swarm.", "Bring Marigold seed.", "Return Marigold's basket.", "Tell Marigold about the heron.", "Oil the hinge."]:
        st.add_memory(t, "todo")
    done = st.add_memory("Thank Marigold for the honey.", "todo")
    st.set_memory_status(done, "done")
    for i in st.items():
        st.take_item(i["id"], i["qty"])
    for i in range(9):
        st.add_item(f"thing{i}", 1)
    st.log("companion", name="Marigold", text="Pip! Come in.", visit=True)
    got = talk.prompt(st, {**ch, "about": "A beekeeping badger."}, "It is noon.", time.time())
    assert got.split("\n") == [
        "It is noon.", f"You are at {talk.places.label('Marigold')}, talking with Marigold.",
        "What you think of Marigold: A beekeeping badger.",
        "What you meant to do about them:", "- Tell Marigold about the heron.", "- Return Marigold's basket.", "- Bring Marigold seed.",
        "You were visiting (sitting on the step), feeling content.",
        "You have with you: " + ", ".join(f"thing{i} x1" for i in range(8)) + f"; {st.coins()} coins.",
        "Talking with Marigold (this visit, oldest first):", "  Marigold: Pip! Come in.",
        "Your turn: answer what was just said, with say. Don't open with thanks or say back what you were told; ask something, or tell "
        "something of your own. When the talk has run its course, say goodbye (say with goodbye true). You may also feel something."]


def test_a_bare_prompt_says_so(tmp_path):
    s, st, gm, agent = make(tmp_path)
    ch = neighbor(st, s)
    st.update_agent(location="Marigold", activity="idle", description="", mood="calm")
    for i in st.items():
        st.take_item(i["id"], i["qty"])
    st.add_memory("x" * 170 + " Marigold.", "todo")
    st.log("companion", name="Marigold", text="Before this visit.", visit=True)
    got = talk.prompt(st, {k: v for k, v in ch.items() if k != "about"}, "It is noon.", time.time())
    assert "What you think of" not in got and "You were idle, feeling calm." in got and "You have with you: nothing much;" in got
    assert f"- {'x' * 157}..." in got or f"- {'x' * 160}" in got
    assert "  Marigold: Before this visit." in got                               # with no arrival on record, all of it counts
    st.set_meta(arrived_at=str(time.time() + 10))
    assert "Before this visit." not in talk.prompt(st, ch, "c", time.time())


def test_the_scene_system_prompt_and_tools():
    assert talk.system("I am Pip.", {"name": "Marigold"}) == ("I am Pip.\n\nRight now you are face to face with Marigold, in the middle of a conversation. "
                                                            "Talk as yourself. Answer only by calling a tool.")
    assert talk.specs({}) == [talk.SAY]
    assert talk.specs({"feel": (T.REGISTRY["feel"][0],)})[1].name == "feel"


@pytest.mark.asyncio
async def test_only_her_own_words_this_visit_count_as_her_having_spoken(tmp_path):
    s, st, gm, agent = make(tmp_path, [report(text="A low cottage.")], work_speed=1e6)
    agent.tools.update({n: T.REGISTRY[n] for n in ("say", "go_to")})
    neighbor(st, s)
    st.set_meta(arrived_at=str(time.time() - 5))
    st.log("companion", name="Marigold", text="A letter's line, read at home.", visit=False)
    assert talk.waiting(st) is None                                              # at home, with no one
    await call(agent, "go_to", place="Marigold")
    time.sleep(0.01)
    await agent.finish_work()
    st.log("companion", name="Someone Else", text="Hello.", visit=True)
    st.log("say", name="Marigold", text="Hello.")
    assert talk.waiting(st) is None
    st.log("companion", name="Marigold", text="Hello, Pip.", visit=True)
    e = st.events(1)[0]
    st.set_meta(arrived_at=str(e["ts"]))
    assert talk.waiting(st)["name"] == "Marigold"                                # at the very moment Pip arrived counts


def test_free_time_at_exactly_two_hours_and_just_over(tmp_path):
    from tests.test_happenings import clock
    s, st, gm, agent = make(tmp_path)
    c = clock(st)
    now = time.time()
    st.set_runtime(c["id"], {**c["runtime"], "tended_until": now + 120 * 60})
    assert agent._free_time(now) == ["Nothing needs you for about 2 hours."]
    st.set_runtime(c["id"], {**c["runtime"], "tended_until": now + 121 * 60})
    assert agent._free_time(now) == ["Nothing needs you for about 2 hours."]


def test_free_time_ignores_what_needs_no_tending(tmp_path):
    from tests.test_happenings import UPKEEP, clock
    s, st, gm, agent = make(tmp_path)
    spec = {**UPKEEP, "capabilities": {k: v for k, v in UPKEEP["capabilities"].items() if k != "upkeep"}}
    c = clock(st, spec=spec)
    st.set_runtime(c["id"], {**c["runtime"], "tended_until": time.time() + 10 * 60})
    assert agent._free_time(time.time()) == ["Nothing needs you for now."]


def test_free_time_lists_open_ambitions_and_wishes_to_do(tmp_path):
    s, st, gm, agent = make(tmp_path)
    old = st.add_memory("An old finished aim.", "ambitions")
    st.set_memory_status(old, "done")
    a1 = st.add_memory("Build a clock.", "ambitions")
    a2 = st.add_memory("Map the coast. " + "y" * 120, "ambitions")
    st.add_memory("A third aim.", "ambitions")
    gone = st.add_memory("To sing.", "wishlist", "activity")
    st.set_memory_status(gone, "done")
    w1 = st.add_memory("To be able to swim.", "wishlist", "ability")
    w2 = st.add_memory("A boat that rows itself.", "wishlist", "idea")
    st.add_todo = None
    crafting(st)
    got = agent._free_time(time.time())
    aims = st.memories("ambitions", status="open", limit=2)
    assert got[1] == "Your ambitions: " + "; ".join(f"#{m['id']} {talk.clip(m['text'], 100)}" for m in aims) and len(aims) == 2
    assert "An old finished aim." not in got[1] and len(got[1].split("; ")[-1]) <= len(f"#{a2} ") + 100 or a2 not in [m["id"] for m in aims]
    assert got[2] == f"Things you wish you could do: #{w1} To be able to swim.; #{w2} A boat that rows itself."
    assert got[3] == "start_project begins something new."


def test_free_time_offers_a_project_for_wishes_alone(tmp_path):
    s, st, gm, agent = make(tmp_path)
    st.add_memory("To be able to swim.", "wishlist", "ability")
    crafting(st)
    assert agent._free_time(time.time())[-1] == "start_project begins something new."


@pytest.mark.asyncio
async def test_the_second_try_at_a_letter_has_the_same_context(tmp_path):
    s, st, gm, agent = make(tmp_path, [report(text="I laid my palm on the step this morning and it was still cool, so my own bed waits.", gist="g"),
                                       report(text="The heron came back to the flats today and stood for an hour.", gist="g2")])
    neighbor(st, s)
    st.add_letter("Marigold", "pip", "Dear Pip, I laid my palm on the step this morning and it was still cool, so my bed waits.", time.time() - 10)
    now = time.time()
    await nb._write(st, s, agent.gm, FixedRng(), st.characters("neighbor")[0], now, None)
    first, second = (c["messages"][0]["content"] for c in gm.calls)
    assert second.replace(" Your first try repeated an earlier letter; write it afresh.", "") == first
    assert st.characters("neighbor")[0]["next_chatter_at"] > now


@pytest.mark.asyncio
async def test_only_her_last_few_letters_are_checked_for_repeats(tmp_path):
    s, st, gm, agent = make(tmp_path, [report(text="I laid my palm on the step this morning and it was still cool, so my own bed waits.", gist="g")])
    neighbor(st, s)
    st.add_letter("Marigold", "pip", "Dear Pip, I laid my palm on the step this morning and it was still cool, so my bed waits.", time.time() - 100)
    for i in range(nb.LETTERS_CHECKED):
        st.add_letter("Marigold", "pip", f"Letter number {i}: the weather turned and the {['bees', 'hens', 'goats', 'cats', 'owls', 'moths'][i % 6]} hid.", time.time() - 50 + i)
    await nb._write(st, s, agent.gm, FixedRng(), st.characters("neighbor")[0], time.time(), None)
    assert len(gm.calls) == 1


def test_no_free_time_with_a_crop_ready_to_pick(tmp_path):
    s, st, gm, agent = make(tmp_path)
    planted(st, s, 2, "carrots", 900)
    planted(st, s, 1, "tomatoes", -1)
    assert agent._free_time(time.time()) == []


def test_free_time_shows_only_open_aims_and_wishes_in_full_up_to_a_hundred_characters(tmp_path):
    s, st, gm, agent = make(tmp_path)
    a = st.add_memory("A" * 100, "ambitions")
    st.set_memory_status(st.add_memory("A finished aim.", "ambitions"), "done")
    w = st.add_memory("To " + "w" * 97, "wishlist", "activity")
    st.set_memory_status(st.add_memory("To sing in a choir.", "wishlist", "activity"), "done")
    assert agent._free_time(time.time())[1:3] == [f"Your ambitions: #{a} {'A' * 100}", f"Things you wish you could do: #{w} To {'w' * 97}"]


@pytest.mark.asyncio
async def test_outside_a_scene_her_goodbye_is_not_recorded(tmp_path):
    s, st, gm, agent = make(tmp_path, [report(text="A low cottage."), report(text="Pip! Come in.", goodbye=True)], work_speed=1e6)
    agent.tools.update({n: T.REGISTRY[n] for n in ("go_to",)})
    neighbor(st, s)
    await call(agent, "go_to", place="Marigold")
    time.sleep(0.01)
    await agent.finish_work()
    await nb.step(st, s, agent.gm, FixedRng(), time.time())
    said = [e["data"] for e in st.events(10) if e["kind"] == "companion"][0]
    assert said["text"] == "Pip! Come in." and "goodbye" not in said
