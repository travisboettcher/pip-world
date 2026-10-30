import pytest

from app import places
from app import tools as T
from app.llm.base import LLMResponse, ToolCall, Usage
from tests.test_projects import call, make

HOME_ONLY = {"work_on", "experiment", "plant", "harvest", "tend", "sleep"}
LIBRARY_ONLY = {"browse_library", "read"}


def names(specs):
    return {s.name for s in specs}


def test_every_tool_has_a_scope_and_the_table_matches_the_design():
    assert set(T.SCOPES) == set(T.REGISTRY)
    assert {n for n, sc in T.SCOPES.items() if sc == ("home",)} == HOME_ONLY
    assert {n for n, sc in T.SCOPES.items() if sc == ("library",)} == LIBRARY_ONLY
    assert all(T.SCOPES[n] == ("anywhere",) for n in ("say", "eat", "rest", "recall", "go_to", "start_project", "write_letter"))


def test_the_tool_list_depends_on_where_pip_is():
    everything = {n: T.REGISTRY[n] for n in T.REGISTRY}
    home, library = names(T.specs_for(everything, places.HOME)), names(T.specs_for(everything, "library"))
    marigold = names(T.specs_for(everything, "Marigold's home"))
    assert HOME_ONLY <= home and not LIBRARY_ONLY & home
    assert LIBRARY_ONLY <= library and not HOME_ONLY & library
    assert not HOME_ONLY & marigold and not LIBRARY_ONLY & marigold
    assert {"say", "go_to", "note_to_self", "recall"} <= home & library & marigold      # always there
    assert places.scope_of("Marigold's home") == "neighbor" and places.scope_of(places.HOME) == "home"


@pytest.mark.asyncio
async def test_using_a_tool_from_the_wrong_place_is_refused_the_same_way_everywhere(tmp_path):
    s, st, gm, agent = make(tmp_path)
    st.update_agent(location="library")
    for tool, args in (("plant", {"seed": "tomato"}), ("tend", {"creation": "x"}), ("sleep", {}),
                       ("work_on", {"project": "x"}), ("experiment", {"project": "x", "hypothesis": "something"})):
        r = await call(agent, tool, **args)
        assert r.text == "you're at the library; go_to home first" and r.followup, tool
    st.update_agent(location=places.HOME)
    r = await call(agent, "read", book="x")
    assert r.text == "you're not at the library; go_to library first" and r.followup
    st.update_agent(location="Marigold's home")
    assert (await call(agent, "plant", seed="tomato")).text == "you're at Marigold's home; go_to home first"


@pytest.mark.asyncio
async def test_a_tick_offers_only_what_belongs_where_pip_is(tmp_path):
    s, st, gm, agent = make(tmp_path)
    agent.tools.update({n: T.REGISTRY[n] for n in HOME_ONLY})
    agent.backend.script[:] = [LLMResponse("", [], Usage(1, 1)), LLMResponse("", [], Usage(1, 1))]
    st.update_agent(location="library")
    await agent.tick("test")
    at_library = agent.backend.calls[-1]["tools"]
    assert not HOME_ONLY & set(at_library) and "note_to_self" in at_library
    st.update_agent(location=places.HOME)
    await agent.tick("test")
    assert HOME_ONLY & set(agent.backend.calls[-1]["tools"]) >= {"plant", "work_on"}


@pytest.mark.asyncio
async def test_away_from_home_pip_is_told_what_the_place_offers(tmp_path):
    s, st, gm, agent = make(tmp_path)
    agent.tools["browse_library"], agent.tools["read"] = T.REGISTRY["browse_library"], T.REGISTRY["read"]
    assert "Here you can also" not in agent._perception("timer", [])
    st.update_agent(location="library")
    assert "Here you can also: browse_library, read." in agent._perception("timer", [])
    st.update_agent(location="Marigold's home")
    assert "Here you can also" not in agent._perception("timer", [])


@pytest.mark.asyncio
async def test_a_stale_tool_call_gets_a_helpful_result_not_an_error(tmp_path):
    s, st, gm, agent = make(tmp_path)
    agent.tools["plant"] = T.REGISTRY["plant"]
    st.update_agent(location="library")
    out = await agent._run_tool(ToolCall("1", "plant", {"seed": "tomato"}), 0)
    assert out["content"] == "you're at the library; go_to home first" and out["followup"] and not out["is_error"]
