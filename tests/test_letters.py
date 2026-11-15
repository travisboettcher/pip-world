"""People, part two (docs/DESIGN-engine-audit.md, C1): letters go between the agent and anyone a module brings as writing, of any role;
what modules note about someone is theirs to bring up; a parcel is any kind of thing the world has."""
import time
from pathlib import Path

import pytest

from app import modules as M, neighbors as nb, world_pack as W
from app.config import Settings
from tests.test_modules import live, rule
from tests.test_projects import FixedRng, call, make, report

ROOT = Path(__file__).resolve().parent.parent


def bring(st, s, **v):
    return nb.arrive(st, s, M._character(st, {"persona": "a scavenger", "about": "trades salvage", **v}))


@pytest.mark.asyncio
async def test_anyone_who_writes_gets_letters_whatever_their_role(tmp_path):
    s, st, gm, agent = make(tmp_path, [report(text="Got your note. The dogs are out east again.")], work_speed=1e6)
    jun = bring(st, s, name="Jun", kind="villager", home="woods", writes=True)
    r = await call(agent, "write_letter", to="Jun", text="Any salvage this week?")
    assert r.text == "your letter to Jun is on its way; it'll take a few hours to arrive"
    (lt,) = st.letters()
    st.update_letter(lt["id"], deliver_at=time.time() - 1)
    await nb.step(st, s, agent.gm, FixedRng(), time.time())
    task = gm.calls[0]["messages"][0]["content"]
    assert task.startswith("Write as Jun (villager), who writes letters with Pip. Who Jun is: a scavenger\n")
    assert "Pip can walk over to visit Jun at the woods (you can invite it)" in task
    assert [l["sender"] for l in st.letters()] == ["Pip", "Jun"] and st.correspondents() == [st.find_character("Jun")]
    assert "People you write to (write_letter; go_to where they live to visit):" in nb.perception(st)
    assert "- Jun (at the woods): trades salvage" in nb.perception(st)
    assert jun["writes"] == 1


@pytest.mark.asyncio
async def test_someone_met_only_in_person_is_not_written_to(tmp_path):
    s, st, gm, agent = make(tmp_path)
    bring(st, s, name="Marta", kind="villager", home="woods")
    assert (await call(agent, "write_letter", to="Marta", text="Hello?")).text == "error: you don't write to anyone called 'Marta' (you write to: nobody yet)"
    assert (await call(agent, "say", text="Hello?", to="Marta")).text == "Marta can't hear you from here; go_to woods to talk with them"
    bring(st, s, name="Jun", kind="villager", home="woods", writes=True)
    assert (await call(agent, "say", text="Hello?", to="Jun")).text == "Jun can't hear you from here; write_letter, or go_to woods to visit"
    assert nb.perception(st) == ["People you write to (write_letter; go_to where they live to visit):", "- Jun (at the woods): trades salvage"]


def test_the_old_neighbours_write(tmp_path):
    s, st, *_ = make(tmp_path)
    old = st.add_character("Oriel", "neighbor", None, "p", 60, 0)
    met = st.add_character("Bran", "resident", None, "p", 0, 0, place="Saltholm")
    assert not old["writes"] and not met["writes"]
    st.set_meta(letters_named="")
    st._letters_named()
    assert [c["name"] for c in st.correspondents()] == ["Oriel"] and st.meta("letters_named") == "1"
    st.add_character("Ash", "neighbor", None, "p", 60, 0)
    st._letters_named()                                                              # once
    assert [c["name"] for c in st.correspondents()] == ["Oriel"]


def test_a_module_may_read_what_the_agent_wishes_for(tmp_path):
    s, st, *_ = make(tmp_path)
    for i in range(M.WISHES_READ + 2):
        st.add_memory(f"a wish {i}", "wishlist")
    done = st.add_memory("a met wish", "wishlist")
    st.resolve_memory(done, "got it")
    ctx = M.context(st, s, live(st, rule(reads=["wishes"]), "x"), time.time())
    assert len(ctx["wishes"]) == M.WISHES_READ and set(ctx["wishes"][0]) == {"id", "text"} and "a met wish" not in [w["text"] for w in ctx["wishes"]]
    assert "wishes" in M.READS and "wishes" not in M.context(st, s, live(st, rule(name="other"), "x"), time.time())


def test_a_parcel_is_any_kind_of_thing_the_world_has(tmp_path):
    good = {"name": "seed packet", "kind": "seed", "qty": 2}
    assert nb.clean_parcel(good)["kind"] == "seed"
    W.set_active(W.load(Settings(world_pack=str(ROOT / "worlds" / "ashfall"))))
    try:
        assert nb.clean_parcel(good) is None and nb.clean_parcel({**good, "kind": "food"})["kind"] == "food"   # Ashfall has no seeds
    finally:
        W.set_active(W.load(Settings()))


@pytest.mark.asyncio
async def test_a_letter_brings_up_what_modules_note_and_is_written_afresh_if_it_repeats(tmp_path):
    s, st, gm, agent = make(tmp_path, [report(text="The dogs are out east."), report(text="The dogs are out east."),
                                       report(text="A new crate of jars came in.")])
    jun = bring(st, s, name="Jun", kind="villager", home="woods", writes=True)
    st.update_module(live(st, rule(name="aaa"), "x")["id"], notes={"Jun": "trades salvage at the gate"})
    assert await nb._write(st, s, agent.gm, FixedRng(), st.find_character("Jun"), time.time(), None) is True
    assert "(you can invite it), and Jun trades salvage at the gate Also report:" in gm.calls[0]["messages"][0]["content"]
    assert await nb._write(st, s, agent.gm, FixedRng(), st.find_character("Jun"), time.time(), None) is True    # the same again: once more
    again = gm.calls[2]["messages"][0]["content"]
    assert "tell something new. Your first try repeated an earlier letter; write it afresh. Pip can walk over to visit Jun at the woods" in again
    assert again.startswith("Write as Jun (villager), who writes letters with Pip.") and "and Jun trades salvage at the gate Also report:" in again
    assert [l["text"] for l in st.letters()] == ["The dogs are out east.", "A new crate of jars came in."] and jun["writes"]


def test_the_kinds_a_parcel_may_be_are_said_plainly(monkeypatch):
    from app import gm as G, world as world_content
    for kinds, said in ((("tool", "food", "seed"), "tool, food or seed"), (("tool", "food"), "tool or food"), (("food",), "food"), ((), "a thing")):
        monkeypatch.setattr(world_content, "kinds", lambda kinds=kinds: kinds)
        assert G.GameMaster._kinds() == said


def test_a_module_reads_who_writes_and_only_the_wishes(tmp_path):
    s, st, *_ = make(tmp_path)
    bring(st, s, name="Jun", kind="villager", home="woods", writes=True)
    bring(st, s, name="Marta", kind="villager", home="woods")
    st.add_memory("fix the door", "todo")
    st.add_memory("a spare fuse", "wishlist")
    ctx = M.context(st, s, live(st, rule(reads=["wishes", "people"]), "x"), time.time())
    assert [(p["name"], p["writes"]) for p in ctx["people"]] == [("Jun", True), ("Marta", False)]
    assert [w["text"] for w in ctx["wishes"]] == ["a spare fuse"]
