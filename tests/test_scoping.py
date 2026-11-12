import pytest

from app import places
from app import tools as T
from app.llm.base import LLMResponse, ToolCall, Usage
from tests.test_projects import call, make

HOME_ONLY = {"program", "work_on", "experiment", "tend", "sleep"}
LIBRARY_ONLY = {"browse", "read"}


def names(specs):
    return {s.name for s in specs}


def test_every_tool_has_a_scope_and_the_table_matches_the_design():
    assert set(T.SCOPES) == set(T.REGISTRY)
    assert {n for n, sc in T.SCOPES.items() if sc == ("home",)} == HOME_ONLY
    assert {n for n, sc in T.SCOPES.items() if sc == ("library",)} == {"read"}
    assert T.SCOPES["browse"] == ("library", "junkyard", "neighbor") and "gather" not in T.SCOPES      # the gathering module's
    assert T.SCOPES["where_to"] == ("anywhere",)
    assert all(T.SCOPES[n] == ("anywhere",) for n in ("say", "eat", "rest", "recall", "go_to", "start_project", "write_letter"))


def test_the_tool_list_depends_on_where_pip_is():
    everything = {n: T.REGISTRY[n] for n in T.REGISTRY}
    home, library = names(T.specs_for(everything, places.HOME)), names(T.specs_for(everything, "library"))
    marigold = names(T.specs_for(everything, "Marigold's home"))
    assert HOME_ONLY <= home and not LIBRARY_ONLY & home
    assert LIBRARY_ONLY <= library and not HOME_ONLY & library
    assert not HOME_ONLY & marigold and "read" not in marigold and {"browse", "buy", "sell"} <= marigold   # a neighbor may have wares
    assert {"say", "go_to", "note_to_self", "recall"} <= home & library & marigold      # always there
    assert places.scope_of("Marigold's home") == "neighbor" and places.scope_of(places.HOME) == "home"


@pytest.mark.asyncio
async def test_using_a_tool_from_the_wrong_place_is_refused_the_same_way_everywhere(tmp_path):
    s, st, gm, agent = make(tmp_path)
    st.update_agent(location="library")
    for tool, args in (("tend", {"creation": "x"}), ("sleep", {}),
                       ("work_on", {"project": "x"}), ("experiment", {"project": "x", "hypothesis": "something"})):
        r = await call(agent, tool, **args)
        assert r.text == "you're at the library; go_to home first" and r.followup, tool
    st.update_agent(location=places.HOME)
    r = await call(agent, "read", book="x")
    assert r.text == "you're not at the library; go_to library first" and r.followup
    st.update_agent(location="Marigold's home")
    assert (await call(agent, "tend", creation="x")).text == "you're at Marigold's home; go_to home first"


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
    assert HOME_ONLY & set(agent.backend.calls[-1]["tools"]) >= {"tend", "work_on"}


class FakeLibrary:
    def available(self):
        return True


@pytest.mark.asyncio
async def test_away_from_home_pip_is_told_what_the_place_offers(tmp_path):
    s, st, gm, agent = make(tmp_path)
    agent.library = FakeLibrary()
    assert "Here you can:" not in agent._perception("timer", [])
    st.update_agent(location="library")
    p = agent._perception("timer", [])
    assert "Here you can: browse (look for books, by subject, title or author, or wander the shelves), " \
           "read (settle in and read a book for a while)." in p
    st.update_agent(location="Marigold's home")
    assert "Here you can:" not in agent._perception("timer", [])


@pytest.mark.asyncio
async def test_a_stale_tool_call_gets_a_helpful_result_not_an_error(tmp_path):
    s, st, gm, agent = make(tmp_path)
    agent.tools["tend"] = T.REGISTRY["tend"]
    st.update_agent(location="library")
    out = await agent._run_tool(ToolCall("1", "tend", {"creation": "x"}), 0)
    assert out["content"] == "you're at the library; go_to home first" and out["followup"] and not out["is_error"]
