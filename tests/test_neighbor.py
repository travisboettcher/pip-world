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
    reply = report(text="Thank you for the lovely hourglass!", life_update="The bees swarmed this week.")
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
