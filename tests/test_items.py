"""Quantities: what stacks together, what a work stage uses up, and what it leaves alone."""
import pytest

from app import tools as tools_mod
from app.state import name_key
from tests.test_projects import call, make, report


def stock(st):
    """What Pip owns, minus the starter seed packets every new world begins with."""
    return {i["name"]: i["qty"] for i in st.items() if i["kind"] != "seed"}


def test_name_key_ignores_case_and_plurals():
    keys = [name_key(n) for n in ("Tomatoes", "tomato", "  carrots ", "carrot", "fine brass gears", "berries", "brass", "glass")]
    assert keys == ["tomato", "tomato", "carrot", "carrot", "fine brass gear", "berry", "brass", "glass"]


def test_plural_and_singular_stack_together(tmp_path):
    s, st, *_ = make(tmp_path)
    st.add_item("tomato", 3, "food")
    item = st.add_item("Tomatoes", 2, "food")
    assert item["name"] == "tomato" and item["qty"] == 5       # one stack, under the name Pip already had
    assert stock(st) == {"tomato": 5}
    assert st.find_item("tomatoes")[0]["qty"] == 5 and st.find_item("TOMATO")[0]["qty"] == 5


def test_different_things_do_not_stack(tmp_path):
    s, st, *_ = make(tmp_path)
    st.add_item("brass wire", 1, "material")
    st.add_item("brass gear", 1, "material")
    st.add_item("brass", 1, "material")
    assert stock(st) == {"brass": 1, "brass gear": 1, "brass wire": 1}


def test_existing_duplicate_stacks_are_merged_once(tmp_path):
    s, st, *_ = make(tmp_path)
    with st.lock:   # how the live database looks: the old exact-name rule left both
        for name, qty in (("tomato", 9), ("tomatoes", 6), ("carrots", 2)):
            st.db.execute("INSERT INTO items (name, description, kind, qty, attrs, ts) VALUES (?, '', 'food', ?, '{}', 1)", (name, qty))
        st.db.commit()
    assert st.merge_duplicate_items() == 1
    assert stock(st) == {"tomato": 15, "carrots": 2}
    assert st.merge_duplicate_items() == 0


@pytest.mark.asyncio
async def test_eating_one_leaves_the_rest(tmp_path):
    s, st, gm, agent = make(tmp_path)
    st.add_item("tomatoes", 3, "food")
    await tools_mod.REGISTRY["eat"][1](agent.ctx, {"item": "tomato"})
    assert st.find_item("tomato")[0]["qty"] == 2


def stage(**kw):
    return {"name": "build the escapement and pendulum", "minutes": 60, "materials": {}, "started": False, **kw}


@pytest.mark.asyncio
async def test_starting_a_stage_uses_up_listed_and_mentioned_materials_but_not_tools(tmp_path):
    s, st, gm, agent = make(tmp_path, [report(craft="clockmaking", difficulty=2)])
    st.add_item("brass wire", 3, "material")
    st.add_item("pendulum", 1, "material")
    st.add_item("tweezers", 1, "tool")
    steps = [{"name": "build the escapement and pendulum", "minutes": 60, "materials": {"brass wire": 2, "tweezers": 1}}]
    await call(agent, "start_project", name="gear clock", steps=steps)
    r = await call(agent, "work_on", project="gear clock", minutes=30)
    have = stock(st)
    assert have == {"brass wire": 1, "tweezers": 1}               # wire spent, pendulum built in, tweezers kept
    assert "pendulum" in r.text and "used up" in r.text


@pytest.mark.asyncio
async def test_a_second_session_on_the_same_stage_uses_nothing_more(tmp_path):
    s, st, gm, agent = make(tmp_path, [report(craft="clockmaking", difficulty=2)])
    st.add_item("brass wire", 4, "material")
    st.add_item("pendulum", 2, "material")
    steps = [{"name": "hang the pendulum", "minutes": 120, "materials": {"brass wire": 2}}]
    await call(agent, "start_project", name="gear clock", steps=steps)
    await call(agent, "work_on", project="gear clock", minutes=30)
    st.end_session()
    await call(agent, "work_on", project="gear clock", minutes=30)      # same stage again
    assert stock(st) == {"brass wire": 2, "pendulum": 1}
