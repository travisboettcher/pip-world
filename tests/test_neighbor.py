import time

import pytest

from app import memory as mem
from app import neighbors as nb
from app.llm.base import LLMResponse, Usage
from tests.test_creations import build
from tests.test_projects import FixedRng, call, make, report

HOUR = 3600
INVENTED = dict(name="Marigold", persona="A badger who keeps bees and writes long, warm letters.",
                about="Lives past the hedge; keeps bees.", letter="Hello neighbor! I'm Marigold, the beekeeper.")


def neighbor(st, s, rng=None, now=None):
    return st.add_character("Marigold", "neighbor", None, INVENTED["persona"], s.neighbor_writes_every_hours * 60,
                            (now or time.time()) + 99 * HOUR, about=INVENTED["about"])


@pytest.mark.asyncio
async def test_neighbor_is_invented_once_and_writes_first(tmp_path):
    s, st, gm, agent = make(tmp_path, [report(**INVENTED)], neighbor=True)
    now = time.time()
    ch = await nb.ensure_neighbor(st, s, agent.gm, FixedRng(), now)
    assert ch["name"] == "Marigold" and ch["about"] == "Lives past the hedge; keeps bees."
    (first,) = st.letters()
    assert first["sender"] == "Marigold" and first["recipient"] == "Pip"
    assert now + 0.25 * 0.7 * 120 * 60 <= first["deliver_at"] <= now + 0.25 * 1.3 * 120 * 60  # soon-ish
    await nb.ensure_neighbor(st, s, agent.gm, FixedRng(), now)
    assert len(gm.calls) == 1 and len(st.characters("neighbor")) == 1


@pytest.mark.asyncio
async def test_failed_invention_retries_in_an_hour_and_pip_is_not_a_name(tmp_path):
    s, st, gm, agent = make(tmp_path, [LLMResponse("no", [], Usage(1, 1)), report(**{**INVENTED, "name": "pip"})],
                            neighbor=True)
    now = time.time()
    assert await nb.ensure_neighbor(st, s, agent.gm, FixedRng(), now) is None
    assert await nb.ensure_neighbor(st, s, agent.gm, FixedRng(), now + 60) is None and len(gm.calls) == 1
    assert await nb.ensure_neighbor(st, s, agent.gm, FixedRng(), now + HOUR + 1) is None  # "Pip" is rejected
    assert st.characters() == []


@pytest.mark.asyncio
async def test_letter_with_parcel_lands_in_the_inbox_and_wakes_pip(tmp_path):
    s, st, gm, agent = make(tmp_path)
    neighbor(st, s)
    now = time.time()
    st.add_letter("Marigold", "Pip", "Some seeds for your plots!", now - 1,
                  parcel={"name": "sunflower seeds", "kind": "seed", "qty": 2, "description": "big ones"})
    assert await nb.step(st, s, None, FixedRng(), now) is True
    (m,) = st.pending_inbox()
    assert m["sender"] == "Marigold" and m["text"] == ("A letter from Marigold: Some seeds for your plots! "
                                                       "(Enclosed: 2 x sunflower seeds (seed).)")
    seeds = st.find_item("sunflower seeds")[0]
    assert seeds["kind"] == "seed" and seeds["attrs"]["crop"] == "sunflower"  # plantable
    assert st.letters()[0]["delivered_at"] == now
    p = agent._perception("event", st.pending_inbox())
    assert "- A letter from Marigold: Some seeds" in p and "A letter came from Marigold" in p
    assert "Marigold" in mem.material(st, 0, now + 1, 12000)[1]  # the reflection will write a note on them


@pytest.mark.asyncio
async def test_pip_writes_and_the_neighbor_answers_with_their_life_moving_on(tmp_path):
    reply = report(text="Thank you for the lovely hourglass!", life_update="The bees swarmed this week.",
                   life_update_new=True)
    s, st, gm, agent = make(tmp_path, [reply], neighbor=True)
    neighbor(st, s)
    hourglass = build(st, {"name": "Sandy", "description": "a small hourglass", "capabilities": []})
    r = await call(agent, "write_letter", to="marigold", text="I made you something.", enclose="Sandy")
    assert r.text == ("your letter to Marigold is on its way, with Sandy tucked inside; it'll take a few hours "
                      "to arrive")
    assert st.creations() == [] and st.creation(hourglass["id"])["given_to"] == "Marigold"
    assert "your letter to Marigold (sent just now) is on its way" in agent._perception("timer", [])
    (sent,) = st.letters()
    assert await nb.step(st, s, agent.gm, FixedRng(), sent["deliver_at"] + 1) is False  # neighbor reads; no wake
    task = gm.calls[0]["messages"][0]["content"]
    assert "Pip's letter just arrived:\nI made you something." in task and "Sandy, something Pip made" in task
    letters = st.letters()
    assert letters[0]["delivered_at"] and letters[1]["sender"] == "Marigold" and letters[1]["reply_to"] == sent["id"]
    assert st.characters("neighbor")[0]["life"] == ["The bees swarmed this week."]
    assert [h["text"] for h in st.recall("hourglass")][0].startswith("You wrote to Marigold: I made you something.")


@pytest.mark.asyncio
async def test_write_letter_guards(tmp_path):
    s, st, gm, agent = make(tmp_path, letters_per_day=1)
    assert "you don't have a neighbor called 'Bob' (you know: nobody yet)" in (
        await call(agent, "write_letter", to="Bob", text="hi")).text
    neighbor(st, s)
    assert "empty" in (await call(agent, "write_letter", to="Marigold", text=" ")).text
    assert "nothing was sent" in (await call(agent, "write_letter", to="Marigold", text="hi", enclose="anvil")).text
    st.add_item("twine", 3, "material")
    await call(agent, "write_letter", to="Marigold", text="hi", enclose="twine")
    assert st.find_item("twine")[0]["qty"] == 2 and st.letters()[0]["enclosed"] == "1 x twine"
    assert "plenty of letters today" in (await call(agent, "write_letter", to="Marigold", text="again")).text
    assert "write_letter, or go_to their home to visit" in (await call(agent, "say", text="hello!", to="Marigold")).text


@pytest.mark.asyncio
async def test_unanswerable_letters_retry_then_drop(tmp_path):
    s, st, gm, agent = make(tmp_path, [LLMResponse("", [], Usage(1, 1))] * 3)
    neighbor(st, s)
    now = time.time()
    lt = st.add_letter("Pip", "Marigold", "hello?", now - 1)
    for i in range(3):
        await nb.step(st, s, agent.gm, FixedRng(), now + i * (HOUR + 1))
    got = st.letters()[0]
    assert got["attempts"] == 3 and got["delivered_at"] and len(st.letters()) == 1  # dropped quietly, no reply
    assert st.events(1)[0]["data"] == {"id": lt["id"], "by": "Marigold", "answered": False}


@pytest.mark.asyncio
async def test_neighbor_writes_first_when_due_and_parcels_are_capped(tmp_path):
    parcel = {"name": "honey", "kind": "food", "qty": 9, "description": "a jar"}
    s, st, gm, agent = make(tmp_path, [report(text="Thinking of you.", parcel=parcel),
                                       report(text="Me again.", parcel=parcel)])
    ch = neighbor(st, s)
    now = time.time()
    due = lambda: st.update_character(ch["id"], next_chatter_at=now)  # noqa: E731
    await nb.step(st, s, agent.gm, FixedRng(), now)
    assert gm.calls == []  # not due yet
    due()
    await nb.step(st, s, agent.gm, FixedRng(), now + 1)
    first = st.letters()[-1]
    assert first["text"] == "Thinking of you." and first["parcel"]["qty"] == 3  # clamped
    due()
    await nb.step(st, s, agent.gm, FixedRng(), now + 2)
    assert len(gm.calls) == 1  # their letter is still on the way: no second one yet
    st.update_letter(first["id"], delivered_at=now)
    due()
    await nb.step(st, s, agent.gm, FixedRng(), now + 3)
    assert st.letters()[-1]["text"] == "Me again." and st.letters()[-1]["parcel"] is None  # one parcel a day
    assert "parcel" not in gm.calls[1]["messages"][0]["content"].split("Optional:")[1]


def test_clean_parcel():
    assert nb.clean_parcel({"name": "x", "kind": "weapon"}) is None and nb.clean_parcel("junk") is None
    assert nb.clean_parcel({"name": "  wax.", "kind": "material", "qty": "lots"}) == {
        "name": "wax", "kind": "material", "qty": 1, "description": ""}


@pytest.mark.asyncio
async def test_visiting_the_neighbor_in_person(tmp_path):
    s, st, gm, agent = make(tmp_path, [report(text="A low cottage humming with bees."),
                                       report(text="*wipes honey off her paws* Pip! Come in, come in."),
                                       report(text="Oh, the hives are cross today.")], work_speed=1e6)
    neighbor(st, s)
    r = await call(agent, "go_to", place="Marigold")
    assert r.text.startswith("you set off for Marigold's home") and st.agent()["description"] == "on the way to Marigold's home"
    time.sleep(0.01)
    await agent.finish_work()
    assert st.agent()["location"] == "Marigold's home"
    assert "A badger who keeps bees" in gm.calls[0]["messages"][0]["content"]  # her home is described from who she is
    assert await nb.step(st, s, agent.gm, FixedRng(), time.time()) is True  # she greets Pip at the door
    assert "Pip has just arrived at the door" in gm.calls[1]["messages"][0]["content"]
    assert {k: v for k, v in st.events(1)[0]["data"].items() if k != "firsts"} == {"name": "Marigold", "text": "*wipes honey off her paws* Pip! Come in, come in.",
                                       "reply": True, "visit": True}
    assert await nb.step(st, s, agent.gm, FixedRng(), time.time()) is False  # once per visit
    assert "said it to Marigold" in (await call(agent, "say", text="How are the bees?", to="marigold")).text
    await nb.step(st, s, agent.gm, FixedRng(), time.time())
    task = gm.calls[2]["messages"][0]["content"]
    assert 'Pip just said: "How are the bees?"' in task and "Pip: How are the bees?" not in task.split("Right now")[1]
    p = agent._perception("event", [])
    assert "You are at: Marigold's home - A low cottage" in p and "You're visiting Marigold." in p
    assert 'Marigold said: "Oh, the hives are cross today." (answering you)' in p
    assert "go_to home first" in (await call(agent, "plant", seed="tomato")).text
    await call(agent, "say", text="bye!", to="Marigold")
    await call(agent, "go_to", place="home")
    time.sleep(0.01)
    await agent.finish_work()
    await nb.step(st, s, agent.gm, FixedRng(), time.time())
    assert st.characters("neighbor")[0]["heard"] == [] and len(gm.calls) == 3  # left before she answered


async def _visit(agent, st, s):
    await call(agent, "go_to", place="Marigold")
    time.sleep(0.01)
    await agent.finish_work()
    await nb.step(st, s, agent.gm, FixedRng(), time.time())  # greeting


@pytest.mark.asyncio
async def test_setting_off_from_her_home_ends_the_conversation(tmp_path):
    s, st, gm, agent = make(tmp_path, [report(text="A low cottage."), report(text="Pip! Come in.")], work_speed=1e6)
    neighbor(st, s)
    await _visit(agent, st, s)
    await call(agent, "say", text="bye!", to="Marigold")
    await call(agent, "go_to", place="home")  # still walking: the cottage is behind Pip
    assert await nb.step(st, s, agent.gm, FixedRng(), time.time()) is False
    assert st.characters("neighbor")[0]["heard"] == [] and len(gm.calls) == 2  # she doesn't call after Pip down the path
    r = await call(agent, "say", text="thanks again!", to="Marigold")
    assert "Marigold can't hear you from here" in r.text and st.characters("neighbor")[0]["heard"] == []
    assert "You're visiting Marigold" not in agent._perception("timer", [])


@pytest.mark.asyncio
async def test_pip_is_told_she_hasnt_answered_yet(tmp_path):
    s, st, gm, agent = make(tmp_path, [report(text="A low cottage."), report(text="Pip! Come in.")], work_speed=1e6)
    neighbor(st, s)
    await _visit(agent, st, s)
    hint = "Marigold hasn't answered yet: give them a moment, no need to say it again."
    assert hint not in agent._perception("timer", [])
    await call(agent, "say", text="How are the bees?", to="Marigold")
    assert hint in agent._perception("timer", [])


@pytest.mark.asyncio
async def test_a_visit_is_remembered_against_open_todos(tmp_path):
    s, st, gm, agent = make(tmp_path, [report(text="A low cottage."), report(text="Pip! Come in.")], work_speed=1e6)
    neighbor(st, s)
    st.add_memory("Walk over to Marigold for some beeswax", section="todo")
    st.add_memory("Plant the sunflower seeds", section="todo")
    assert "you've since visited" not in agent._perception("timer", [])
    await _visit(agent, st, s)
    await call(agent, "go_to", place="home")
    time.sleep(0.01)
    await agent.finish_work()
    p = agent._perception("timer", [])
    assert ("Walk over to Marigold for some beeswax  [you've since visited Marigold - is this done? "
            "resolve_note it, or edit_note it down to what's left]") in p
    assert "Plant the sunflower seeds  [" not in p
    assert "- Marigold: Lives past the hedge; keeps bees. (you last visited just now)" in p


def _arrived(st, place, ts):
    st.log("arrived", place=place, label=place, first_time=False, description="")
    st.db.execute("UPDATE facets SET last_ts = ? WHERE key = ?", (ts, f"place:{place}"))


def test_the_neighbor_line_says_how_long_since_the_last_visit(tmp_path):
    s, st, gm, agent = make(tmp_path)
    neighbor(st, s)
    st.add_character("Bramble", "neighbor", None, "A hedgehog.", 60, time.time() + 99 * HOUR, about="Bakes.")
    now = time.time()
    _arrived(st, "Marigold's home", now - 2 * HOUR)
    lines = nb.perception(st, now + 3 * HOUR)
    assert "- Marigold: Lives past the hedge; keeps bees. (you last visited 5 hours ago)" in lines
    assert "- Bramble: Bakes." in lines  # never visited: nothing added


def test_a_todo_is_flagged_only_for_visits_after_it_was_written(tmp_path):
    s, st, gm, agent = make(tmp_path)
    neighbor(st, s)
    st.add_character("Bramble", "neighbor", None, "A hedgehog.", 60, time.time() + 99 * HOUR, about="Bakes.")
    both = st.add_memory("Take honey from Marigold over to Bramble", section="todo")
    ts = st.memories("todo")[0]["ts"]
    _arrived(st, "Marigold's home", ts)  # the same moment: not since
    _arrived(st, "Bramble's home", ts + 1)
    p = agent._perception("timer", [])
    assert f"- #{both} Take honey from Marigold over to Bramble  [you've since visited Bramble - is this done?" in p
    _arrived(st, "Marigold's home", ts + 2)
    p = agent._perception("timer", [])
    assert "[you've since visited Marigold, Bramble - is this done?" in p
    st.add_memory("Plant the sunflower seeds", section="todo")
    assert "Plant the sunflower seeds\nYour wishlist (open):" in agent._perception("timer", [])


# --- memory: what she's said (DESIGN-neighbor-memory.md) ---------------------------------------------------------
KNOWN = "Things Pip already knows about Marigold (refer back to them if it's natural, but don't introduce them again as news):"


def _due_to_write(st, ch, now):
    st.update_character(ch["id"], next_chatter_at=now)


@pytest.mark.asyncio
async def test_her_letters_are_shown_to_her_as_gists_and_pips_verbatim(tmp_path):
    s, st, gm, agent = make(tmp_path, [report(text="Hello again! The bees are calm.", gist="Said hello and that the bees are calm.",
                                              told=["their hives sit by the hedge"])])
    ch = neighbor(st, s)
    now = time.time()
    st.add_letter("Marigold", "Pip", "My blue door rattles. Come by!", now - 9, gist="Told Pip about the rattling door.")
    st.add_letter("Marigold", "Pip", "The hive hums at dusk. More soon!", now - 8)  # written before gists existed
    st.add_letter("Pip", "Marigold", "How are the bees? I love the door.", now - 7)
    for lt in st.letters():
        st.update_letter(lt["id"], delivered_at=now - 1)
    _due_to_write(st, ch, now)
    await nb.step(st, s, agent.gm, FixedRng(), now)
    task = gm.calls[0]["messages"][0]["content"]
    assert ("Your letters with Pip so far (oldest first; Pip's in full, yours in brief):\n"
            "Marigold (in brief): Told Pip about the rattling door.\nMarigold (in brief): The hive hums at dusk.\n"
            "Pip: How are the bees? I love the door.\n") in task
    assert "blue door rattles" not in task and "More soon" not in task
    mine = st.letters()[-1]
    assert mine["text"] == "Hello again! The bees are calm." and mine["gist"] == "Said hello and that the bees are calm."
    assert st.characters("neighbor")[0]["told"] == ["their hives sit by the hedge"]


def test_a_letter_without_a_gist_falls_back_to_its_first_sentence_clipped(tmp_path):
    s, st, gm, agent = make(tmp_path)
    neighbor(st, s)
    st.add_letter("Marigold", "Pip", "Well! " + "word " * 80, time.time() - 1)
    st.add_letter("Marigold", "Pip", "no stop at all " * 20, time.time() - 1)
    st.add_letter("Marigold", "Pip", "Is it? Yes.", time.time() - 1, gist="  ")
    for lt in st.letters():
        st.update_letter(lt["id"], delivered_at=time.time())
    first, long, q = nb.correspondence(st, "Marigold")
    assert first == "Marigold (in brief): Well!"
    assert long.startswith("Marigold (in brief): no stop at all") and len(long) <= len("Marigold (in brief): ") + 200
    assert q == "Marigold (in brief): Is it?"


@pytest.mark.asyncio
async def test_told_grows_three_at_a_time_is_clipped_and_capped_and_shown_as_already_known(tmp_path):
    s, st, gm, agent = make(tmp_path, [report(text="Hi.", told=["", "word " * 30, "a new thing", "b", "c"]),
                                       report(text="Hi again.", told="not a list")])
    ch = neighbor(st, s)
    st.update_character(ch["id"], told=[f"fact {i}" for i in range(29)])
    now = time.time()
    _due_to_write(st, ch, now)
    await nb.step(st, s, agent.gm, FixedRng(), now)
    told = st.characters("neighbor")[0]["told"]
    assert len(told) == 30 and told[:2] == ["fact 2", "fact 3"]  # oldest dropped
    assert told[-3:] == ["word " * 15 + "word...", "a new thing", "b"]  # at most 3 per letter, empty ones skipped
    assert KNOWN + "\n- fact 0\n- fact 1\n" in gm.calls[0]["messages"][0]["content"]
    assert "`told`" in gm.calls[0]["messages"][0]["content"] and "`gist`" in gm.calls[0]["messages"][0]["content"]
    for lt in st.letters():
        st.update_letter(lt["id"], delivered_at=now)
    _due_to_write(st, ch, now)
    await nb.step(st, s, agent.gm, FixedRng(), now + 1)
    assert st.characters("neighbor")[0]["told"] == told
    assert st.letters()[-1]["gist"] == ""


@pytest.mark.asyncio
async def test_in_person_her_lines_from_this_visit_are_verbatim_and_earlier_ones_brief(tmp_path):
    s, st, gm, agent = make(tmp_path, [
        report(text="Pip! Mind the blue door, it rattles. Come in.", gist="Greeted Pip at the door.",
               told=["their blue door rattles"]),
        report(text="Back so soon? Sit by the hives.", told=["their blue door rattles in the wind"]),
        report(text="The bees are cross today. Shh.")])
    ch = neighbor(st, s)
    st.update_character(ch["id"], told=["they keep bees"])
    st.update_agent(location="Marigold's home")
    st.set_meta(arrived_at=str(time.time()))
    assert await nb.step(st, s, agent.gm, FixedRng(), time.time()) is True
    assert KNOWN + "\n- they keep bees\n" in gm.calls[0]["messages"][0]["content"]
    assert "`gist`" in gm.calls[0]["messages"][0]["content"]
    first = st.events(1)[0]["data"]
    assert first["text"] == "Pip! Mind the blue door, it rattles. Come in." and first["gist"] == "Greeted Pip at the door."
    assert st.characters("neighbor")[0]["told"] == ["they keep bees", "their blue door rattles"]
    time.sleep(0.01)
    st.set_meta(arrived_at=str(time.time()))  # Pip went away and came back: a new visit
    await nb.step(st, s, agent.gm, FixedRng(), time.time())
    task = gm.calls[1]["messages"][0]["content"]
    assert "Marigold (in brief): Greeted Pip at the door.\n" in task 
    assert "rattles" not in task.split("What's passed between them")[1]
    assert "gist" not in st.events(1)[0]["data"]  # none given: nothing stored
    await call(agent, "say", text="Are the bees well?", to="Marigold")
    await nb.step(st, s, agent.gm, FixedRng(), time.time())
    task = gm.calls[2]["messages"][0]["content"]
    assert "Marigold: Back so soon? Sit by the hives.\nPip: Are the bees well?\n" in task  # this visit: word for word
    assert "Marigold (in brief): Greeted Pip at the door.\n" in task
    assert st.characters("neighbor")[0]["told"][-1] == "their blue door rattles in the wind"


@pytest.mark.asyncio
async def test_an_empty_line_in_person_is_not_said(tmp_path):
    s, st, gm, agent = make(tmp_path, [report(text="  ", told=["they hum"])])
    neighbor(st, s)
    st.update_agent(location="Marigold's home")
    st.set_meta(arrived_at=str(time.time()))
    assert await nb.step(st, s, agent.gm, FixedRng(), time.time()) is False
    assert [e for e in st.events(20) if e["kind"] == "companion"] == [] and st.characters()[0]["told"] == []


@pytest.mark.asyncio
async def test_what_she_has_told_pip_is_recalled_once_from_the_letters_so_far(tmp_path):
    s, st, gm, agent = make(tmp_path, [report(told=["their blue door rattles", 7, "", "word " * 30] + ["more"] * 40)])
    ch = neighbor(st, s)
    st.add_character("Bramble", "neighbor", None, "A hedgehog.", 60, time.time() + 99 * HOUR, about="Bakes.")
    st.update_character(ch["id"] + 1, told=["they bake"])  # already knows some: not asked
    first = st.add_letter("Marigold", "Pip", "My blue door rattles. Come by!", 0, gist="Told Pip about the door.")
    st.update_letter(first["id"], delivered_at=1)
    st.add_letter("Pip", "Marigold", "I will!", time.time() + 99 * HOUR)
    st.add_letter("Marigold", "Pip", "Still on its way.", time.time() + 99 * HOUR)
    st.log("companion", name="Marigold", text="Mind the step, it wobbles.", reply=True, visit=True, gist="Greeted Pip.")
    await agent.resolve_world()
    (c,) = gm.calls
    task = c["messages"][0]["content"]
    assert "Marigold: My blue door rattles. Come by!\nPip: I will!\nMarigold: Mind the step, it wobbles." in task  # word for word
    assert "A badger who keeps bees" in task and "A hedgehog" not in task and "Still on its way" not in task
    told = st.characters("neighbor")[0]["told"]
    assert told[0] == "their blue door rattles" and told[1] == "word " * 15 + "word..." and len(told) == 30
    st.update_character(ch["id"], told=[])
    await agent.resolve_world()
    await nb.recall_told(st, agent.gm, {})  # a new start: still done for good
    assert len(gm.calls) == 1


@pytest.mark.asyncio
async def test_recalling_what_she_told_gives_up_after_two_failures_until_the_next_start(tmp_path):
    s, st, gm, agent = make(tmp_path, [report(told="not a list")] + [LLMResponse("no", [], Usage(1, 1))] * 2
                            + [report(told=["they keep bees"])])
    neighbor(st, s)
    st.update_letter(st.add_letter("Marigold", "Pip", "Hello!", 0)["id"], delivered_at=1)
    tries = {}
    for _ in range(3):
        await nb.recall_told(st, agent.gm, tries)
    assert len(gm.calls) == 2 and st.characters()[0]["told"] == []
    await nb.recall_told(st, agent.gm, {})  # the next start
    await nb.recall_told(st, agent.gm, {})
    assert len(gm.calls) == 4 and st.characters()[0]["told"] == ["they keep bees"]
    assert await nb.recall_told(st, None, {}) is None  # no GM: nothing to do


# --- something new to say ---------------------------------------------------------------------------------------
async def _letters(st, s, agent, ch, *nows):
    for now in nows:
        for lt in st.letters(undelivered=True):
            st.update_letter(lt["id"], delivered_at=now)
        st.update_character(ch["id"], next_chatter_at=now)
        await nb.step(st, s, agent.gm, FixedRng(), now)


@pytest.mark.asyncio
async def test_a_life_update_is_kept_only_when_she_says_it_is_new_and_five_are_kept(tmp_path):
    s, st, gm, agent = make(tmp_path, [report(text="Hi.", life_update="The bees swarmed.", life_update_new=True),
                                       report(text="Hi.", life_update="The bees swarmed again.", life_update_new=False),
                                       report(text="Hi.", life_update="The bees, as I said, swarmed.")])
    ch = neighbor(st, s)
    st.update_character(ch["id"], life=[f"Old news {i}." for i in range(5)])
    now = time.time()
    await _letters(st, s, agent, ch, now)
    life = st.characters()[0]["life"]
    assert life == [f"Old news {i}." for i in range(1, 5)] + ["The bees swarmed."]
    task = gm.calls[0]["messages"][0]["content"]
    assert "What's already happening in Marigold's life (not news any more): Old news 0. Old news 1." in task
    assert "`life_update_new`" in task
    await _letters(st, s, agent, ch, now + 1, now + 2)
    assert st.characters()[0]["life"] == life  # a restatement, or not said to be new: not kept
    assert nb.LIFE_KEPT == 5


@pytest.mark.asyncio
async def test_her_plans_are_clamped_capped_and_happen_when_due(tmp_path):
    day = nb.DAY
    s, st, gm, agent = make(tmp_path, [report(text="Hi.", upcoming={"what": "the spring tide.", "in_days": 30}),
                                       report(text="Hi.", upcoming={"what": "a bird count", "in_days": 0}),
                                       report(text="Hi.", upcoming={"what": "nothing", "in_days": "soon"}),
                                       report(text="Hi.", upcoming={"what": " ", "in_days": 2}),
                                       report(text="Hi.", upcoming={"what": "no day given"}),
                                       report(text="Hi.", upcoming={"what": "jam day", "in_days": 2}),
                                       report(text="Hi.", upcoming={"what": "one too many", "in_days": 2}),
                                       report(text="Hi. The count was fun!", upcoming={"what": "honey fair", "in_days": 3})])
    ch = neighbor(st, s)
    now = time.time()
    await _letters(st, s, agent, ch, now, now + 1, now + 2, now + 3, now + 4, now + 5, now + 6)
    up = st.characters()[0]["upcoming"]
    assert [u["what"] for u in up] == ["the spring tide", "a bird count", "jam day"]  # at most 3 pending
    assert [u["due_at"] for u in up] == [now + 14 * day, now + 1 + day, now + 5 + 2 * day]  # 1-14 days
    task = gm.calls[6]["messages"][0]["content"]
    assert ("Coming up for Marigold:\n- in 14 days: the spring tide\n- in 1 day: a bird count\n"
            "- in 2 days: jam day\n") in task and "`upcoming`" in task
    await _letters(st, s, agent, ch, now + 1 + day)
    task = gm.calls[7]["messages"][0]["content"]
    assert "- today or this week: a bird count\n" in task
    ch = st.characters()[0]
    assert ch["life"] == ["Recently: a bird count."]  # it happened: part of their life now
    assert [u["what"] for u in ch["upcoming"]] == ["the spring tide", "jam day", "honey fair"]


@pytest.mark.asyncio
async def test_a_plan_long_overdue_moves_into_her_life_quietly(tmp_path):
    s, st, gm, agent = make(tmp_path)
    ch = neighbor(st, s)
    now = time.time()
    st.update_character(ch["id"], upcoming=[{"what": "jam day", "due_at": now - 3 * nb.DAY},
                                            {"what": "the fair", "due_at": now - 3 * nb.DAY + 1}])
    await nb.step(st, s, agent.gm, FixedRng(), now)
    ch = st.characters()[0]
    assert ch["life"] == ["Recently: jam day."] and [u["what"] for u in ch["upcoming"]] == ["the fair"]
    assert gm.calls == []


@pytest.mark.asyncio
async def test_a_due_plan_comes_up_in_person_and_then_has_happened(tmp_path):
    s, st, gm, agent = make(tmp_path, [report(text="Pip! The fair is today!")])
    ch = neighbor(st, s)
    now = time.time()
    st.update_character(ch["id"], upcoming=[{"what": "the honey fair", "due_at": now - 60}])
    st.update_agent(location="Marigold's home")
    st.set_meta(arrived_at=str(now))
    await nb.step(st, s, agent.gm, FixedRng(), now)
    assert "Coming up for Marigold:\n- today or this week: the honey fair\n" in gm.calls[0]["messages"][0]["content"]
    ch = st.characters()[0]
    assert ch["life"] == ["Recently: the honey fair."] and ch["upcoming"] == []


@pytest.mark.asyncio
async def test_nothing_is_recalled_before_anything_has_been_said(tmp_path):
    s, st, gm, agent = make(tmp_path, [report(told=["they keep bees"])])
    neighbor(st, s)
    st.add_letter("Marigold", "Pip", "Hello! I keep bees.", time.time() + HOUR)  # her first letter, still on its way
    await nb.recall_told(st, agent.gm, {})
    assert gm.calls == []
    st.update_letter(st.letters()[0]["id"], delivered_at=time.time())
    await nb.recall_told(st, agent.gm, {})
    assert "Marigold: Hello! I keep bees." in gm.calls[0]["messages"][0]["content"]
    assert st.characters()[0]["told"] == ["they keep bees"]
