import time

import pytest

from app import memory as mem
from app import neighbors as nb
from app.llm.base import LLMResponse, Usage
from app.text import clip
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


@pytest.mark.asyncio
async def test_what_a_neighbor_hands_over_in_person_lands_in_belongings_once_a_day(tmp_path):
    seeds = {"name": "carrot seeds", "kind": "seed", "qty": 9, "description": "old seeds from a husband's rows"}
    s, st, gm, agent = make(tmp_path, [report(text="A low cottage humming with bees."),
                                       report(text="Pip! Come in."),
                                       report(text="Here, take a pinch.", give=seeds),
                                       report(text="Take more.", give=seeds)], work_speed=1e6)
    neighbor(st, s)
    await call(agent, "go_to", place="Marigold")
    time.sleep(0.01)
    await agent.finish_work()
    await nb.step(st, s, agent.gm, FixedRng(), time.time())      # the greeting
    assert "`give`" in gm.calls[1]["messages"][0]["content"]
    await call(agent, "say", text="Any carrot seeds?", to="marigold")
    await nb.step(st, s, agent.gm, FixedRng(), time.time())
    assert st.find_item("carrot seeds")[0]["qty"] == 6 and st.find_item("carrot seeds")[0]["kind"] == "seed"  # 3 starter + 3 (clamped from 9)
    ev = [e for e in st.events(10) if e["kind"] == "companion"][0]["data"]
    assert ev["text"] == "Here, take a pinch. (Marigold hands you 3 x carrot seeds.)"
    gift = [e for e in st.events(10) if e["kind"] == "gift"][0]["data"]
    assert gift["sender"] == "Marigold" and gift["item"] == "carrot seeds" and gift["qty"] == 3 and gift["in_person"] is True
    await call(agent, "say", text="Any more?", to="marigold")
    st.update_character(st.characters("neighbor")[0]["id"], replies=[])
    await nb.step(st, s, agent.gm, FixedRng(), time.time())
    assert "`give`" not in gm.calls[3]["messages"][0]["content"] and "hands Pip nothing" in gm.calls[3]["messages"][0]["content"]
    assert st.find_item("carrot seeds")[0]["qty"] == 6           # a second handover the same day is not honoured
    assert [e for e in st.events(10) if e["kind"] == "companion"][0]["data"]["text"] == "Take more."


def test_the_daily_cap_counts_letter_parcels_and_hand_overs_but_not_old_ones_or_plain_gifts(tmp_path):
    s, st, gm, agent = make(tmp_path)               # parcels_per_day is 1
    now = time.time()
    assert nb._can_give(st, s, now) is True
    st.log("gift", sender="Marigold", item="honey", qty=1, item_kind="food")              # a delivered letter's gift: not in person
    assert nb._can_give(st, s, now + 1) is True
    st.log("tool", tool="x", args={}, result="y", in_person=True)                           # only gifts count
    assert nb._can_give(st, s, now + 1) is True
    st.log("gift", sender="Marigold", item="honey", qty=1, item_kind="food", in_person=True)
    assert nb._can_give(st, s, now + 1) is False
    assert nb._can_give(st, s, now + nb.DAY + 60) is True                                    # a day later
    (tmp_path / "b").mkdir()
    (tmp_path / "c").mkdir()
    s2, st2, *_ = make(tmp_path / "b")
    st2.add_letter("Marigold", "Pip", "hi", now, parcel={"name": "honey", "kind": "food", "qty": 1, "description": ""})
    assert nb._can_give(st2, s2, now + 1) is False and nb._can_give(st2, s2, now + nb.DAY + 60) is True
    assert nb._can_give(st2, make(tmp_path / "c", parcels_per_day=2)[0], now + 1) is True
    assert nb._can_give(st, make(tmp_path / "c", parcels_per_day=2)[0], now + 1) is True      # one of two given


def test_a_hand_over_adds_the_item_logs_it_and_says_so_only_when_it_is_valid(tmp_path):
    s, st, *_ = make(tmp_path)
    assert nb._hand_over(st, "Marigold", None) == "" and nb._hand_over(st, "Marigold", {"name": "x", "kind": "pet"}) == ""
    gifts = lambda: [e["data"] for e in st.events(20) if e["kind"] == "gift"]  # noqa: E731
    assert gifts() == []
    note = nb._hand_over(st, "Marigold", {"name": "honey", "kind": "food", "qty": 2})
    assert note == " (Marigold hands you 2 x honey.)"
    it = st.find_item("honey")[0]
    assert it["qty"] == 2 and it["kind"] == "food" and it["description"] == "from Marigold"
    nb._hand_over(st, "Marigold", {"name": "needle", "kind": "tool", "description": "a fine one"})
    assert st.find_item("needle")[0]["description"] == "a fine one"
    assert {k: v for k, v in gifts()[0].items() if k != "firsts"} == {"sender": "Marigold", "item": "needle", "qty": 1, "item_kind": "tool", "in_person": True}


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


# --- edges: who is asked, what is kept, exact limits -------------------------------------------------------------
def companion(st, name="Clocky"):
    """A creation companion: a character, but not a neighbor (no letters, no home of its own)."""
    return st.add_character(name, "creation", None, "A chatty clock.", 60, time.time() - 1)


def bramble(st):
    return st.add_character("Bramble", "neighbor", None, "A hedgehog.", 60, time.time() + 99 * HOUR, about="Bakes.")


def test_correspondence_is_hers_only_the_newest_six_with_pips_letters_on_the_way(tmp_path):
    s, st, gm, agent = make(tmp_path)
    neighbor(st, s)
    now = time.time()

    def delivered(sender, recipient, text, **kw):
        st.update_letter(st.add_letter(sender, recipient, text, now, **kw)["id"], delivered_at=now)

    delivered("Marigold", "Pip", "Letter 0.", gist="Gist 0.")  # pushed out: only the newest six are shown
    delivered("Marigold", "Pip", "Letter 1.", gist="Gist 1.")
    st.add_letter("Marigold", "Pip", "Still on its way.", now + HOUR)  # hers, not arrived: not said yet
    delivered("Bramble", "Pip", "From Bramble.")  # someone else's
    delivered("Marigold", "Pip", "Letter 2.", gist="Gist 2.")
    delivered("Pip", "Marigold", "Thanks!")
    delivered("Marigold", "Pip", "Letter 3.", gist="Gist 3.")
    st.add_letter("Pip", "Marigold", "On my way to you.", now + HOUR, enclosed="1 x twine")  # Pip's, on the way
    assert nb.correspondence(st, "Marigold") == [
        "Marigold (in brief): Gist 1.", "Marigold (in brief): Gist 2.", "Pip: Thanks!", "Marigold (in brief): Gist 3.",
        "Pip: On my way to you. [enclosed: 1 x twine]"]


def test_clean_upcoming_keeps_a_few_words():
    assert nb.clean_upcoming({"what": "X" * 101, "in_days": 2}, 0)["what"] == "X" * 100  # clipped, and the "..." trimmed
    assert nb.clean_upcoming({"what": "Xmas fair X.", "in_days": 2}, 0) == {"what": "Xmas fair X", "due_at": 2 * nb.DAY}
    assert nb.clean_upcoming("soon", 0) is None and nb.clean_upcoming(None, 0) is None


@pytest.mark.asyncio
async def test_her_letter_is_clipped_exactly_and_a_due_plan_and_news_both_join_her_life(tmp_path):
    s, st, gm, agent = make(tmp_path, [report(text="x" * 1201, gist="g" * 201, told=["a" * 81], life_update="l" * 201,
                                              life_update_new=True)])
    ch = neighbor(st, s)
    now = time.time()
    st.update_character(ch["id"], upcoming=[{"what": "jam day", "due_at": now - 60}], life=["Old."])
    _due_to_write(st, ch, now)
    await nb.step(st, s, agent.gm, FixedRng(*[1.0] * 9), now)  # every jitter at its top: x1.3
    lt = st.letters()[-1]
    assert lt["text"] == "x" * 1200 + "..." and lt["gist"] == "g" * 200 + "..."
    assert lt["deliver_at"] == pytest.approx(now + s.letter_delay_minutes * 60 * 1.3)
    ch = st.characters()[0]
    assert ch["life"] == ["Old.", "Recently: jam day.", "l" * 200 + "..."] and ch["upcoming"] == []
    assert ch["told"] == ["a" * 80 + "..."]
    assert ch["next_chatter_at"] == pytest.approx(now + ch["chatter_minutes"] * 60 * 1.3)


@pytest.mark.asyncio
async def test_a_letter_with_nothing_new_leaves_what_she_has_alone(tmp_path):
    s, st, gm, agent = make(tmp_path, [report(text="Hi.")])
    ch = neighbor(st, s)
    told, life = [f"thing {i}" for i in range(31)], [f"Event {i}." for i in range(7)]  # more than she'd keep now
    st.update_character(ch["id"], told=told, life=life)
    now = time.time()
    _due_to_write(st, ch, now)
    await nb.step(st, s, agent.gm, FixedRng(), now)
    ch = st.characters()[0]
    assert ch["told"] == told and ch["life"] == life and st.letters()[-1]["text"] == "Hi."


@pytest.mark.asyncio
async def test_her_answer_is_asked_with_who_she_is_and_what_pip_enclosed(tmp_path):
    s, st, gm, agent = make(tmp_path, [report(text="Thanks for the twine!"), report(text="Me again.")])
    ch = neighbor(st, s)
    now = time.time()
    st.add_letter("Pip", "Marigold", "Here you go.", now - 1, enclosed="1 x twine")
    await nb.step(st, s, agent.gm, FixedRng(), now)
    task = gm.calls[0]["messages"][0]["content"]
    assert task.startswith(f"Write as Marigold, Pip's neighbor. Who Marigold is: {INVENTED['persona']}\n")
    assert "Pip enclosed something with it: 1 x twine. React to it honestly.\n" in task
    assert "- `parcel`: only if it's natural" in task  # none sent today: one may go along
    for lt in st.letters(undelivered=True):
        st.update_letter(lt["id"], delivered_at=now)
    _due_to_write(st, ch, now + 1)
    await nb.step(st, s, agent.gm, FixedRng(), now + 1)
    task = gm.calls[1]["messages"][0]["content"]
    assert "No letter is waiting; Marigold decides to write to Pip anyway." in task
    assert "Pip enclosed something" not in task


@pytest.mark.asyncio
async def test_without_a_gm_letters_to_her_wait_an_hour_and_so_does_her_next_letter(tmp_path):
    s, st, gm, agent = make(tmp_path)
    ch = neighbor(st, s)
    now = time.time()
    _due_to_write(st, ch, now)
    assert await nb.step(st, s, None, FixedRng(), now) is False
    assert st.characters()[0]["next_chatter_at"] == now + nb.RETRY_AFTER and st.letters() == []
    st.add_letter("Pip", "Marigold", "hello?", now - 1)
    assert await nb.step(st, s, None, FixedRng(), now) is False
    (got,) = st.letters()
    assert got["attempts"] == 1 and got["delivered_at"] is None and got["deliver_at"] == now + nb.RETRY_AFTER


@pytest.mark.asyncio
async def test_due_letters_to_pip_all_arrive_once_each_and_not_early(tmp_path):
    s, st, gm, agent = make(tmp_path)
    neighbor(st, s)
    now = time.time()
    st.add_letter("Marigold", "Pip", "Later.", now + 1)  # not yet (and older than the ones that are due)
    st.add_letter("Marigold", "Pip", "On the dot.", now)
    st.add_letter("Marigold", "Pip", "Earlier.", now - 5)
    assert await nb.step(st, s, None, FixedRng(), now) is True
    assert [m["text"] for m in st.pending_inbox()] == ["A letter from Marigold: On the dot.",
                                                       "A letter from Marigold: Earlier."]
    assert await nb.step(st, s, None, FixedRng(), now) is False  # delivered once
    assert len(st.pending_inbox()) == 2 and st.letters()[0]["delivered_at"] is None


@pytest.mark.asyncio
async def test_at_most_200_letters_arrive_in_one_step(tmp_path):
    s, st, gm, agent = make(tmp_path)
    neighbor(st, s)
    now = time.time()
    for i in range(201):
        st.add_letter("Marigold", "Pip", f"Letter {i}.", now - 1)
    await nb.step(st, s, None, FixedRng(), now)
    assert [lt["text"] for lt in st.letters(undelivered=True)] == ["Letter 0."]


@pytest.mark.asyncio
async def test_only_neighbors_read_letters_and_write_first(tmp_path):
    s, st, gm, agent = make(tmp_path)
    neighbor(st, s)
    c = companion(st)
    now = time.time()
    lt = st.add_letter("Pip", "Clocky", "tick?", now - 1)
    await nb.step(st, s, agent.gm, FixedRng(), now)
    assert gm.calls == [] and st.letters()[0]["delivered_at"] == now  # nobody to answer: dropped
    e = st.events(1)[0]
    assert e["kind"] == "letter_read" and e["data"] == {"id": lt["id"], "by": "Clocky", "answered": False}
    assert [x for x in st.characters() if x["id"] == c["id"]][0]["next_chatter_at"] == c["next_chatter_at"]


@pytest.mark.asyncio
async def test_a_letter_on_the_way_to_someone_else_doesnt_stop_her_writing(tmp_path):
    s, st, gm, agent = make(tmp_path, [report(text="Hello!")])
    ch = neighbor(st, s)
    bramble(st)
    now = time.time()
    st.add_letter("Pip", "Bramble", "Hi Bramble.", now + HOUR)
    _due_to_write(st, ch, now)
    await nb.step(st, s, agent.gm, FixedRng(), now)
    assert st.letters()[-1]["sender"] == "Marigold" and st.letters()[-1]["text"] == "Hello!"


def _at_home_of(st, name, arrived=None):
    st.update_agent(location=f"{name}'s home")
    if arrived is not None:
        st.set_meta(arrived_at=str(arrived))


@pytest.mark.asyncio
async def test_in_person_the_one_whose_home_it_is_greets_pip(tmp_path):
    s, st, gm, agent = make(tmp_path, [report(text="Come in, come in.", gist="g" * 201)])
    ch = neighbor(st, s)
    b = bramble(st)
    st.update_character(b["id"], life=["The oven is new."])
    st.update_letter(st.add_letter("Bramble", "Pip", "Buns!", 0, gist="Wrote about buns.")["id"], delivered_at=1)
    st.add_letter("Marigold", "Pip", "Bees!", 0, gist="Wrote about bees.")
    assert await nb._visits(st, s, agent.gm, time.time()) is False  # at home: nobody to visit
    _at_home_of(st, "Bramble")  # no arrival recorded (an older database): still one greeting
    assert await nb.step(st, s, agent.gm, FixedRng(), time.time()) is True
    task = gm.calls[0]["messages"][0]["content"]
    assert task.startswith("Voice Bramble, Pip's neighbor. Who Bramble is: A hedgehog.\n"
                           "Lately in Bramble's life: The oven is new.\n")
    assert "Bramble (in brief): Wrote about buns.\n" in task and "bees" not in task
    assert "Right now Pip is visiting Bramble at home. Pip seems curious.\n" in task
    assert st.meta(f"greeted:{b['id']}") == ""
    assert st.events(1)[0]["data"]["gist"] == "g" * 200 + "..."
    assert await nb.step(st, s, agent.gm, FixedRng(), time.time()) is False and len(gm.calls) == 1
    assert st.characters()[0]["id"] == ch["id"] and st.characters()[1]["replies"] == []  # a greeting isn't a reply


@pytest.mark.asyncio
async def test_without_a_gm_a_visit_passes_quietly(tmp_path):
    s, st, gm, agent = make(tmp_path)
    ch = neighbor(st, s)
    _at_home_of(st, "Marigold", 5)
    assert await nb.step(st, s, None, FixedRng(), time.time()) is False
    assert st.meta(f"greeted:{ch['id']}") == "5"


@pytest.mark.asyncio
async def test_she_answers_at_most_four_times_an_hour(tmp_path):
    s, st, gm, agent = make(tmp_path, [report(text="Yes?"), report(text="Oh, hello again!")])
    ch = neighbor(st, s)
    now = time.time()
    _at_home_of(st, "Marigold", now - 100)
    st.set_meta(**{f"greeted:{ch['id']}": str(now - 100)})
    heard = [{"ts": now, "text": "hi"}]
    st.update_character(ch["id"], heard=heard, replies=[now - 10] * 4)
    assert await nb.step(st, s, agent.gm, FixedRng(), now) is False and gm.calls == []  # four in the last hour
    st.update_character(ch["id"], replies=[now - 3600] * 4)  # an hour ago: no longer counted
    assert await nb.step(st, s, agent.gm, FixedRng(), now) is True
    assert 'Pip just said: "hi"\n' in gm.calls[0]["messages"][0]["content"]
    c = st.characters()[0]
    assert c["heard"] == [] and c["replies"] == [now]
    st.update_character(ch["id"], heard=heard, replies=[now - 10] * 4)
    _at_home_of(st, "Marigold", now + 1)  # a new visit, while she's talked out: she greets, nothing more
    assert await nb.step(st, s, agent.gm, FixedRng(), now + 1) is True
    task = gm.calls[1]["messages"][0]["content"]
    assert "Pip has just arrived at the door" in task and "Pip just said" not in task
    c = st.characters()[0]
    assert c["heard"] == heard and c["replies"] == [now - 10] * 4


@pytest.mark.asyncio
async def test_a_visit_leaves_what_pip_said_to_a_companion_alone(tmp_path):
    s, st, gm, agent = make(tmp_path)
    neighbor(st, s)
    c = companion(st)
    heard = [{"ts": 1.0, "text": "tick tock"}]
    st.update_character(c["id"], heard=heard)
    await nb.step(st, s, None, FixedRng(), time.time())
    assert st.characters()[1]["heard"] == heard


def test_perception_lists_neighbors_and_only_pips_letters_still_on_the_way(tmp_path):
    s, st, gm, agent = make(tmp_path)
    neighbor(st, s)
    companion(st)
    now = time.time()
    st.update_letter(st.add_letter("Pip", "Marigold", "Arrived.", now)["id"], delivered_at=now)
    st.add_letter("Marigold", "Pip", "Hers.", now + HOUR)
    for i in range(21):
        st.add_letter("Pip", "Marigold", f"Letter {i}.", now + HOUR)
    st.update_letter(st.add_letter("Pip", "Bramble", "Arrived too.", now)["id"], delivered_at=now)
    lines = nb.perception(st, now + 3 * HOUR)
    assert lines[:2] == ["Your neighbors (they live nearby: visit them with go_to, or write with write_letter):",
                         "- Marigold: Lives past the hedge; keeps bees."]
    assert lines[2:] == ["- your letter to Marigold (sent 3 hours ago) is on its way"] * 20  # the newest twenty


@pytest.mark.asyncio
async def test_recall_goes_neighbor_by_neighbor_past_ones_it_cant_do_yet(tmp_path):
    s, st, gm, agent = make(tmp_path, [LLMResponse("no", [], Usage(1, 1)), report(told=["d" * 81, "they sew"])])
    for name in ("Ash", "Birch", "Cedar", "Dahlia"):
        st.add_character(name, "neighbor", None, f"{name} is a tree.", 60, time.time() + 99 * HOUR)
    a, b, c, d = st.characters()
    companion(st)
    st.log("companion", name="Clocky", text="Tick.", reply=True)  # a companion has talked, but isn't a neighbor
    st.update_character(a["id"], told=["they grow tall"])  # already knows: skipped
    for name in ("Cedar", "Dahlia"):  # Birch has said nothing yet
        st.update_letter(st.add_letter(name, "Pip", f"Hello from {name}.", 0)["id"], delivered_at=1)
    st.add_letter("Pip", "Dahlia", "Hello Dahlia!", 0)
    tries = {}
    await nb.recall_told(st, agent.gm, tries)
    assert len(gm.calls) == 2 and tries == {c["id"]: 1}  # Cedar failed: tried again next time
    task = gm.calls[1]["messages"][0]["content"]
    assert task.startswith("Dahlia is Pip's neighbor. Who Dahlia is: Dahlia is a tree.\n")
    assert "so far (letters and talk, oldest first):\nDahlia: Hello from Dahlia.\nPip: Hello Dahlia!\n\n" in task
    assert st.characters()[3]["told"] == ["d" * 80 + "...", "they sew"]
    assert await nb.recall_told(st, None, {}) is None  # no GM: nothing to do, even for Cedar


@pytest.mark.asyncio
async def test_recall_reads_the_newest_fifty_letters(tmp_path):
    s, st, gm, agent = make(tmp_path, [report(told=["they keep bees"])])
    neighbor(st, s)
    for i in range(51):
        st.update_letter(st.add_letter("Marigold", "Pip", f"Note {i}.", 0)["id"], delivered_at=1)
    await nb.recall_told(st, agent.gm, {})
    task = gm.calls[0]["messages"][0]["content"]
    assert "Marigold: Note 0.\n" not in task and "oldest first):\nMarigold: Note 1.\n" in task


@pytest.mark.asyncio
async def test_the_agent_loop_invents_the_neighbor_and_lets_them_answer(tmp_path):
    s, st, gm, agent = make(tmp_path, [report(**INVENTED), report(told=["keeps bees"]), report(text="Got your note!")],
                            neighbor=True)
    await agent.resolve_world()
    (ch,) = st.characters("neighbor")
    assert ch["name"] == "Marigold" and len(gm.calls) == 1
    for lt in st.letters(undelivered=True):
        st.update_letter(lt["id"], delivered_at=time.time())
    st.add_letter("Pip", "Marigold", "Hello Marigold!", time.time() - 1)
    await agent.resolve_world()
    assert st.letters()[-1]["sender"] == "Marigold" and st.letters()[-1]["text"] == "Got your note!"


# --- places she mentions (DESIGN-invented-places.md) ------------------------------------------------------------
from app import invented_places as IP
from tests.test_scoping import FakeLibrary

SALTHOLM = "You'll want the ironmonger in Saltholm; he keeps thin brass wire."
MENTION = {"place": "Saltholm", "there": "an ironmonger with thin brass wire", "distance": "far"}


@pytest.mark.asyncio
async def test_her_letter_naming_a_place_makes_it_heard_of_and_she_is_told_the_places_there_are(tmp_path):
    s, st, gm, agent = make(tmp_path, [report(text=SALTHOLM, mentions_place=MENTION), report(text="Bees!")])
    ch = neighbor(st, s)
    now = time.time()
    await _letters(st, s, agent, ch, now)
    task = gm.calls[0]["messages"][0]["content"]
    assert "\nPlaces in Pip's world: the woods (foraging); the junkyard (scrap)\n" in task
    assert "\n- Only if your words point Pip to a place it could go that isn't one of these: the woods, the junkyard, " \
           "Marigold's home, give `mentions_place`" in task
    rec = st.place_row("Saltholm")
    assert rec["status"] == "heard" and rec["mentions"][0]["by"] == "Marigold" and rec["mentions"][0]["there"] == \
        MENTION["there"]
    await _letters(st, s, agent, st.characters("neighbor")[0], now + 99 * HOUR)  # a letter without one: nothing new
    assert [r["key"] for r in st.place_rows()] == ["Saltholm"]
    assert "Places in Pip's world: Saltholm, a long walk (you told Pip: an ironmonger with thin brass wire)" in \
        gm.calls[1]["messages"][0]["content"]


@pytest.mark.asyncio
async def test_a_place_she_mentions_only_counts_if_her_words_name_it(tmp_path):
    s, st, gm, agent = make(tmp_path, [report(text="Bees are busy.", mentions_place=MENTION)])
    ch = neighbor(st, s)
    await _letters(st, s, agent, ch, time.time())
    assert st.place_rows() == [] and st.letters()[-1]["text"] == "Bees are busy."


@pytest.mark.asyncio
async def test_she_is_told_about_the_library_when_one_is_mounted(tmp_path):
    s, st, gm, agent = make(tmp_path, [report(text="Bees!")])
    ch = neighbor(st, s)
    st.update_character(ch["id"], next_chatter_at=0)
    await nb.step(st, s, agent.gm, FixedRng(), time.time(), library=FakeLibrary())
    task = gm.calls[0]["messages"][0]["content"]
    assert "Places in Pip's world: the library (books); the woods" in task and "isn't one of these: the library," in task


@pytest.mark.asyncio
async def test_in_person_she_can_point_pip_to_a_place(tmp_path):
    s, st, gm, agent = make(tmp_path, [report(text=SALTHOLM, mentions_place=MENTION)])
    neighbor(st, s)
    _at_home_of(st, "Marigold", 5)
    assert await nb.step(st, s, agent.gm, FixedRng(), time.time()) is True
    task = gm.calls[0]["messages"][0]["content"]
    assert "Places in Pip's world: the woods (foraging); the junkyard (scrap)\n" in task
    assert task.endswith(f"- {IP.mention_instruction(st, s)}\n".replace(", Saltholm", ""))
    assert st.place_row("Saltholm")["mentions"][0]["by"] == "Marigold"


@pytest.mark.asyncio
async def test_a_new_neighbors_first_letter_can_name_a_place(tmp_path):
    s, st, gm, agent = make(tmp_path, [report(**{**INVENTED, "letter": SALTHOLM, "mentions_place": MENTION})],
                            neighbor=True)
    await nb.ensure_neighbor(st, s, agent.gm, FixedRng(), time.time())
    task = gm.calls[0]["messages"][0]["content"]
    assert "garden\n\nSomeone lives near Pip" in task and task.endswith(
        "visiting themselves.\nOnly if your words point Pip to a place it could go that isn't one of these: the woods, "
        "the junkyard, give `mentions_place` (`place`: the destination as you said it; `there`: what you say is "
        "there, under 120 characters; `distance`: near, far or very far, as you'd put it; `items`: things you say can "
        "be had there). Not your own home, not landscape you just pass through.")
    assert st.place_row("Saltholm")["mentions"][0]["by"] == "Marigold"


@pytest.mark.asyncio
async def test_the_agent_loop_tells_her_about_its_library(tmp_path):
    s, st, gm, agent = make(tmp_path, [report(text="Bees!")])
    agent.library = FakeLibrary()
    st.update_character(neighbor(st, s)["id"], next_chatter_at=0)
    await agent.resolve_world()
    assert "Places in Pip's world: the library (books)" in gm.calls[0]["messages"][0]["content"]


# --- residents: someone met at a place Pip was told about (DESIGN-invented-places.md, owner decision 5) -----------
import random

from app import places as P
from tests.test_invented_places import DESIGN, TIP, SALT, TEAGUE

HERE = ("Mr Teague is here (keeps the ironmonger's in Saltholm); talk with them in person using say with to: "
        "Mr Teague.")


def saltholm(st, arrived=None):
    """Saltholm, real, with Mr Teague keeping the ironmonger's; Pip there if `arrived` is given."""
    IP.design(st, IP.accept(st, "Briar", TIP, SALT, now=time.time()), {**DESIGN, "resident": TEAGUE},
              random.Random(2))
    if arrived is not None:
        st.update_agent(location="Saltholm")
        st.set_meta(arrived_at=str(arrived))
    return st.characters("resident")[0]


@pytest.mark.asyncio
async def test_a_resident_greets_pip_once_per_visit_and_only_at_their_place(tmp_path):
    s, st, gm, agent = make(tmp_path, [report(text="*looks up from the drawer* Morning.", gist="Greeted Pip.")])
    ch = saltholm(st)
    assert await nb.step(st, s, agent.gm, FixedRng(), time.time()) is False and gm.calls == []  # Pip is at home
    st.update_agent(location="Saltholm")
    st.set_meta(arrived_at="5")
    assert await nb.step(st, s, agent.gm, FixedRng(), time.time()) is True
    task = gm.calls[0]["messages"][0]["content"]
    assert task.startswith(f"Voice Mr Teague, who Pip meets at Saltholm. Who Mr Teague is: {TEAGUE['persona']}\n")
    assert "Right now Pip is at Saltholm, with Mr Teague. Pip seems curious.\nPip has just arrived; greet it" in task
    assert "Places in Pip's world: the woods (foraging); the junkyard (scrap); Saltholm, a long walk (Pip has been)\n" in task
    assert {k: v for k, v in st.events(1)[0]["data"].items() if k != "firsts"} == {
        "name": "Mr Teague", "text": "*looks up from the drawer* Morning.", "reply": True, "visit": True,
        "gist": "Greeted Pip."}
    assert st.meta(f"greeted:{ch['id']}") == "5"
    assert await nb.step(st, s, agent.gm, FixedRng(), time.time()) is False and len(gm.calls) == 1


@pytest.mark.asyncio
async def test_pip_meets_a_resident_by_name_only_at_their_place(tmp_path):
    s, st, gm, agent = make(tmp_path)
    saltholm(st)
    assert "Mr Teague" not in agent._perception("timer", [])
    st.update_agent(location="Saltholm")
    assert HERE in agent._perception("timer", [])
    await call(agent, "say", text="Any brass wire?", to="mr teague")
    assert "Mr Teague hasn't answered yet: give them a moment, no need to say it again." in \
        agent._perception("timer", [])
    st.update_agent(location="woods")
    assert "Mr Teague" not in agent._perception("timer", [])


@pytest.mark.asyncio
async def test_a_resident_answers_what_pip_says_capped_per_hour(tmp_path):
    s, st, gm, agent = make(tmp_path, [report(text="A spool, aye.", told=["he keeps brass wire on spools"])])
    now = time.time()
    ch = saltholm(st, arrived=now - 100)
    st.set_meta(**{f"greeted:{ch['id']}": str(now - 100)})
    r = await call(agent, "say", text="Any brass wire?", to="Mr Teague")
    assert r.text == "said it to Mr Teague; it will answer in a moment"
    st.update_character(ch["id"], replies=[now - 10] * 4)
    assert await nb.step(st, s, agent.gm, FixedRng(), now) is False and gm.calls == []  # four in the last hour
    st.update_character(ch["id"], replies=[])
    assert await nb.step(st, s, agent.gm, FixedRng(), now) is True
    assert 'Pip just said: "Any brass wire?"\nAnswer Pip as Mr Teague' in gm.calls[0]["messages"][0]["content"]
    c = st.characters("resident")[0]
    assert c["heard"] == [] and c["replies"] == [now] and c["told"] == ["he keeps brass wire on spools"]


@pytest.mark.asyncio
async def test_a_resident_cant_be_heard_from_elsewhere_or_on_the_way(tmp_path):
    s, st, gm, agent = make(tmp_path, work_speed=1e-6)
    ch = saltholm(st)
    r = await call(agent, "say", text="hello?", to="Mr Teague")
    assert r.text == "Mr Teague can't hear you from here; go_to Saltholm to talk with them"
    st.update_agent(location="Saltholm")
    await call(agent, "say", text="thanks!", to="Mr Teague")
    await call(agent, "go_to", place="home")                     # walking: Saltholm is behind Pip
    assert "can't hear you from here" in (await call(agent, "say", text="bye!", to="Mr Teague")).text
    assert await nb.step(st, s, agent.gm, FixedRng(), time.time()) is False and gm.calls == []
    assert st.characters("resident")[0]["heard"] == []          # left before they could answer
    assert HERE not in agent._perception("timer", [])


@pytest.mark.asyncio
async def test_a_residents_words_can_point_pip_to_a_place_and_their_life_moves_on(tmp_path):
    said = "Try the chandler at Corrow Point for rope."
    s, st, gm, agent = make(tmp_path, [
        report(text=said, mentions_place={"place": "Corrow Point", "there": "a chandler with rope", "distance": "near"},
               life_update="A new drawer of hooks came in.", life_update_new=True),
        report(text="Hello again.", life_update="Still the drawer.", life_update_new=False)])
    saltholm(st, arrived=5)
    assert await nb.step(st, s, agent.gm, FixedRng(), time.time()) is True
    task = gm.calls[0]["messages"][0]["content"]
    assert "Only if your words point Pip to a place it could go that isn't one of these: the woods, the junkyard, " \
           "Saltholm, give `mentions_place`" in task
    rec = st.place_row("Corrow Point")
    assert rec["status"] == "heard" and rec["mentions"][0]["by"] == "Mr Teague"
    assert st.characters("resident")[0]["life"] == ["A new drawer of hooks came in."]
    st.set_meta(arrived_at="6")
    await nb.step(st, s, agent.gm, FixedRng(), time.time())
    assert st.characters("resident")[0]["life"] == ["A new drawer of hooks came in."]  # not news: not kept


@pytest.mark.asyncio
async def test_residents_dont_write_letters(tmp_path):
    s, st, gm, agent = make(tmp_path)
    saltholm(st)
    assert await nb.step(st, s, agent.gm, FixedRng(), time.time() + 99 * 24 * HOUR) is False and gm.calls == []
    assert st.letters() == []
    r = await call(agent, "write_letter", to="Mr Teague", text="Dear Mr Teague")
    assert "you don't have a neighbor called 'Mr Teague'" in r.text and st.letters() == []


@pytest.mark.asyncio
async def test_a_removed_place_keeps_its_resident_but_nobody_can_reach_them(tmp_path):
    s, st, gm, agent = make(tmp_path, [report(text="Morning.")])
    saltholm(st, arrived=5)
    IP.remove(st, "Saltholm")
    assert [c["name"] for c in st.characters("resident")] == ["Mr Teague"]
    assert await nb.step(st, s, agent.gm, FixedRng(), time.time()) is False and gm.calls == []
    assert (await call(agent, "say", text="hello?", to="Mr Teague")).text == "Mr Teague can't hear you from here"
    assert "Mr Teague" not in agent._perception("timer", [])


@pytest.mark.asyncio
async def test_a_residents_talk_is_remembered_like_a_neighbors(tmp_path):
    s, st, gm, agent = make(tmp_path, [report(text="Morning.")])
    saltholm(st, arrived=5)
    await nb.step(st, s, agent.gm, FixedRng(), time.time())
    lines, people, _ = mem.material(st, 0, time.time() + 1, 12000)
    assert "Mr Teague" in people and any("] Mr Teague said: Morning." in l for l in lines)


@pytest.mark.asyncio
async def test_arriving_somewhere_new_pip_meets_whoever_the_design_says_is_there(tmp_path):
    s, st, gm, agent = make(tmp_path, [report(**DESIGN, resident=TEAGUE), report(text="Morning.")], work_speed=1e6)
    IP.accept(st, "Briar", TIP, SALT, now=time.time())
    await call(agent, "go_to", place="Saltholm")
    time.sleep(0.01)
    await agent.finish_work()
    assert st.agent()["location"] == "Saltholm" and HERE in agent._perception("timer", [])
    assert await nb.step(st, s, agent.gm, FixedRng(), time.time()) is True
    assert gm.calls[1]["messages"][0]["content"].startswith("Voice Mr Teague, who Pip meets at Saltholm.")


# --- exact edges (pinned by mutation testing) ------------------------------------------------------------------
@pytest.mark.asyncio
async def test_a_new_neighbor_exactly(tmp_path):
    raw = {**INVENTED, "name": "N" * 41, "persona": "p" * 801, "about": "a" * 161, "letter": "l" * 1201,
           "mentions_place": MENTION}
    s, st, gm, agent = make(tmp_path, [report(**raw)], neighbor=True, wild_places=["woods"])
    st.add_character("Tock", "creation", None, "a clockwork bird", 60, 0)               # not a neighbor
    for i in range(6):
        st.add_creation(f"thing {i}", "made", None, "fine", {"capabilities": {}}, {})
    now = time.time()
    st.set_meta(neighbor_retry_at=str(now))                                               # the retry is due now
    ch = await nb.ensure_neighbor(st, s, agent.gm, FixedRng(0.0), now)
    task = gm.calls[0]["messages"][0]["content"]
    assert task.startswith("Pip's world so far: Pip lives alone in a workshop with a garden; it has made "
                           "thing 0, thing 1, thing 2, thing 3, thing 4\n\n")
    assert "isn't one of these: the woods, give `mentions_place`" in task
    every = s.neighbor_writes_every_hours * 60
    assert ch["name"] == "N" * 40 + "..." and ch["persona"] == "p" * 800 + "..." and ch["about"] == "a" * 160 + "..."
    assert ch["chatter_minutes"] == every and ch["next_chatter_at"] == pytest.approx(now + every * 60 * 0.7, abs=1e-3)
    (lt,) = st.letters()
    assert lt["text"] == clip("l" * 1201, 1200) and lt["deliver_at"] == pytest.approx(now + s.letter_delay_minutes * 60 / 4, abs=1e-3)
    assert st.place_row("Saltholm") is None                                              # the letter doesn't name it
    assert st.events(limit=1)[0]["kind"] == "neighbor" and st.events(limit=1)[0]["data"] == {"name": ch["name"],
                                                                                            "about": ch["about"]}
    assert await nb.ensure_neighbor(st, s, agent.gm, FixedRng(), now) == st.characters("neighbor")[0]


@pytest.mark.asyncio
async def test_a_new_neighbors_place_is_heard_of_at_the_time_given(tmp_path):
    s, st, gm, agent = make(tmp_path, [report(**{**INVENTED, "letter": SALTHOLM, "mentions_place": MENTION})],
                            neighbor=True)
    await nb.ensure_neighbor(st, s, agent.gm, FixedRng(), 1000.0)
    assert st.place_row("Saltholm")["created_at"] == 1000.0


@pytest.mark.asyncio
@pytest.mark.parametrize("raw", [{**INVENTED, "letter": ""}, {**INVENTED, "name": ""}])
async def test_a_new_neighbor_needs_a_name_and_a_letter(tmp_path, raw):
    s, st, gm, agent = make(tmp_path, [report(**raw)], neighbor=True)
    assert await nb.ensure_neighbor(st, s, agent.gm, FixedRng(), 1000.0) is None and st.characters() == []
    assert st.meta("neighbor_retry_at") == str(1000.0 + nb.RETRY_AFTER)


@pytest.mark.asyncio
async def test_without_a_gm_no_neighbor_is_invented(tmp_path):
    s, st, gm, agent = make(tmp_path, neighbor=True)
    assert await nb.ensure_neighbor(st, s, None, FixedRng(), 1000.0) is None
    assert st.meta("neighbor_retry_at") == str(1000.0 + nb.RETRY_AFTER)


@pytest.mark.asyncio
async def test_her_letters_and_visits_are_told_the_places_this_world_has(tmp_path):
    s, st, gm, agent = make(tmp_path, [report(text="Bees!"), report(text="Come in.")], wild_places=["woods"])
    ch = neighbor(st, s)
    now = time.time()
    st.add_letter("Pip", "Marigold", "Dear Marigold", now - 1)
    await nb.step(st, s, agent.gm, FixedRng(), now, library=FakeLibrary())
    _at_home_of(st, "Marigold", 5)
    await nb.step(st, s, agent.gm, FixedRng(), now, library=FakeLibrary())
    assert len(gm.calls) == 2 and ch["id"]
    for call_ in gm.calls:
        t = call_["messages"][0]["content"]
        assert "Places in Pip's world: the library (books); the woods (foraging)" in t
        assert "isn't one of these: the library, the woods, Marigold's home, give" in t


@pytest.mark.asyncio
async def test_a_place_named_in_a_letter_or_in_person_is_heard_of_at_the_time_given(tmp_path):
    s, st, gm, agent = make(tmp_path, [report(text=SALTHOLM, mentions_place=MENTION),
                                       report(text="Do visit Fallow.", mentions_place={"place": "Fallow"})])
    s.invented_places_per_day = 5
    ch = neighbor(st, s)
    st.update_character(ch["id"], next_chatter_at=0)
    await nb.step(st, s, agent.gm, FixedRng(), 1000.0)
    assert st.place_row("Saltholm")["created_at"] == 1000.0
    _at_home_of(st, "Marigold", 5)
    await nb.step(st, s, agent.gm, FixedRng(), 2000.0)
    assert st.place_row("Fallow")["created_at"] == 2000.0


@pytest.mark.asyncio
async def test_her_news_is_clipped_to_two_hundred(tmp_path):
    s, st, gm, agent = make(tmp_path, [report(text="Hi.", life_update="u" * 201, life_update_new=True)])
    ch = neighbor(st, s)
    await _letters(st, s, agent, ch, time.time())
    assert st.characters("neighbor")[0]["life"] == ["u" * 200 + "..."]


@pytest.mark.asyncio
async def test_in_person_a_neighbors_news_waits_for_a_letter(tmp_path):
    s, st, gm, agent = make(tmp_path, [report(text="Come in.", life_update="The bees swarmed.", life_update_new=True)])
    st.add_character("Tock", "creation", None, "a clockwork bird", 60, 0)               # listed first, not met in person
    neighbor(st, s)
    _at_home_of(st, "Marigold", 5)
    assert await nb.step(st, s, agent.gm, FixedRng(), time.time()) is True
    assert st.characters("neighbor")[0]["life"] == []


@pytest.mark.asyncio
async def test_a_resident_without_a_gm_passes_quietly(tmp_path):
    s, st, gm, agent = make(tmp_path)
    ch = saltholm(st, arrived=5)
    assert await nb.step(st, s, None, FixedRng(), time.time()) is False
    assert st.meta(f"greeted:{ch['id']}") == "5"


@pytest.mark.asyncio
async def test_a_residents_due_plan_and_news_both_join_their_life(tmp_path):
    s, st, gm, agent = make(tmp_path, [report(text="Morning.", life_update="The drawer is full.", life_update_new=True)])
    ch = saltholm(st, arrived=5)
    now = time.time()
    st.update_character(ch["id"], upcoming=[{"what": "the hook delivery", "due_at": now - 60}])
    await nb.step(st, s, agent.gm, FixedRng(), now)
    assert st.characters("resident")[0]["life"] == ["Recently: the hook delivery.", "The drawer is full."]


@pytest.mark.asyncio
async def test_two_people_at_one_place_each_greet_pip(tmp_path):
    s, st, gm, agent = make(tmp_path, [report(text="Morning."), report(text="Hello there.")])
    ch = saltholm(st, arrived=5)
    st.set_meta(**{f"greeted:{ch['id']}": "5"})                                           # he already has
    st.add_character("Mrs Teague", "resident", None, "His wife.", 0, 0, place="Saltholm")
    assert await nb.step(st, s, agent.gm, FixedRng(), time.time()) is True
    assert len(gm.calls) == 1 and gm.calls[0]["messages"][0]["content"].startswith("Voice Mrs Teague")

