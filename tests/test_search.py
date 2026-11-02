"""Web search is a provider: Tavily is one source of answers (DESIGN-extract.md)."""
import pytest

from app import search as S
from app import search_tavily as TV
from app import tools as T
from app.config import Settings
from tests.test_projects import call, make


def answers(summary="An answer.", *hits):
    return S.Answers(summary, [S.Found(t, c) for t, c in hits])


# --- the core ---------------------------------------------------------------------------------------------------------
def test_tavily_is_the_default_provider_and_the_settings_name_can_come_from_the_environment(monkeypatch):
    assert Settings().search_provider == "tavily" and S.PROVIDERS["tavily"] is TV.Tavily
    monkeypatch.setenv("SEARCH_PROVIDER", " Other ")
    assert Settings.from_env().search_provider == "other"


def test_a_provider_is_built_from_the_settings_and_is_ready_only_when_set_up():
    ok = S.provider(Settings(tavily_api_key="k"))
    assert isinstance(ok, TV.Tavily) and ok.ready is True and S.ready(Settings(tavily_api_key="k")) is True
    assert S.provider(Settings(tavily_api_key="")).ready is False and S.ready(Settings(tavily_api_key="")) is False
    assert S.provider(Settings(search_provider="no-such")) is None and S.ready(Settings(search_provider="no-such")) is False


def test_the_registry_stores_the_class_and_hands_it_back(monkeypatch):
    monkeypatch.setattr(S, "PROVIDERS", {})
    assert S.register("x")(TV.Tavily) is TV.Tavily and S.PROVIDERS == {"x": TV.Tavily}


def test_what_pip_reads_is_the_answer_then_a_line_per_result_clipped():
    a = answers("The answer.", ("One", "c" * 300), ("Two", "short body"))
    assert S.format(a) == "The answer.\n- One: " + "c" * 200 + "\n- Two: short body"
    assert S.format(answers("", ("Only", "hit"))) == "- Only: hit"                       # no summary: just the results
    assert S.format(answers("Just this.")) == "Just this."
    assert S.format(answers("", )) == ""
    long = S.format(answers("a" * 1500))
    assert long == "a" * 1200
    many = S.format(answers("", *[(f"T{i}", "x" * 200) for i in range(10)]))
    assert len(many) == 1200


class FakeProvider:
    ready, built, queries, answer = True, 0, [], None

    def __init__(self, settings):
        FakeProvider.built += 1

    async def fetch(self, query, http=None):
        FakeProvider.queries.append((query, http))
        return FakeProvider.answer


@pytest.fixture
def fake(monkeypatch):
    for name, value in dict(ready=True, built=0, queries=[], answer=answers("Hello.", ("A", "body"))).items():
        monkeypatch.setattr(FakeProvider, name, value)
    monkeypatch.setitem(S.PROVIDERS, "fake", FakeProvider)
    return FakeProvider


@pytest.mark.asyncio
async def test_run_asks_the_provider_and_formats_what_comes_back(fake):
    http = object()
    assert await S.run(Settings(search_provider="fake"), "bees", http) == "Hello.\n- A: body"
    assert fake.queries == [("bees", http)]
    fake.answer = None
    assert await S.run(Settings(search_provider="fake"), "bees") == ""                    # nothing usable: nothing to show


@pytest.mark.asyncio
async def test_run_does_nothing_when_there_is_no_ready_provider(fake):
    fake.ready = False
    assert await S.run(Settings(search_provider="fake"), "bees") is None and fake.queries == []
    assert await S.run(Settings(search_provider="no-such"), "bees") is None


# --- the Tavily provider ----------------------------------------------------------------------------------------------
class FakeHTTP:
    def __init__(self, body, fail=False):
        self.body, self.fail, self.posts, self.checked = body, fail, [], 0

    async def post(self, url, json=None, timeout=None):
        self.posts.append((url, json, timeout))
        outer = self

        class R:
            def raise_for_status(self):
                outer.checked += 1
                if outer.fail:
                    raise RuntimeError("HTTP 500")

            def json(self):
                return outer.body
        return R()


@pytest.mark.asyncio
async def test_tavily_posts_the_query_with_the_key_and_reads_the_answer_and_results():
    http = FakeHTTP({"answer": "Bees make honey.", "results": [{"title": "Honey", "content": "From nectar."}, {"title": "Wax", "content": "Cells."}]})
    got = await TV.Tavily(Settings(tavily_api_key="secret")).fetch("how do bees make honey", http)
    assert got == S.Answers("Bees make honey.", [S.Found("Honey", "From nectar."), S.Found("Wax", "Cells.")])
    assert http.posts == [("https://api.tavily.com/search",
                           {"api_key": "secret", "query": "how do bees make honey", "max_results": 3, "include_answer": True}, 30)]
    assert http.checked == 1


@pytest.mark.asyncio
async def test_tavily_copes_with_missing_pieces_and_reports_failures():
    got = await TV.Tavily(Settings(tavily_api_key="k")).fetch("q", FakeHTTP({}))
    assert got == S.Answers("", [])
    odd = await TV.Tavily(Settings(tavily_api_key="k")).fetch("q", FakeHTTP({"answer": None, "results": [{"title": "T"}, {"content": "C"}]}))
    assert odd == S.Answers("", [S.Found("T", ""), S.Found("", "C")])
    with pytest.raises(RuntimeError):
        await TV.Tavily(Settings(tavily_api_key="k")).fetch("q", FakeHTTP({}, fail=True))


# --- the tool ----------------------------------------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_the_web_search_tool_returns_what_the_provider_found(tmp_path, fake):
    s, st, gm, agent = make(tmp_path, search_provider="fake")
    r = await call(agent, "web_search", query="bees")
    assert r.text == "Hello.\n- A: body" and r.followup is True and fake.queries[0][0] == "bees"
    fake.answer = None
    assert (await call(agent, "web_search", query="bees")).text == "nothing came back for that search"
    fake.ready = False
    r = await call(agent, "web_search", query="bees")
    assert r.text == "error: web search isn't set up" and r.followup is True


def test_the_tool_is_offered_only_when_a_provider_is_ready(fake):
    def offered(**kw):
        return "web_search" in T.enabled_tools(Settings(tools=["web_search", "say"], **kw))
    assert offered(tavily_api_key="k") is True and offered(tavily_api_key="") is False
    assert offered(search_provider="fake") is True
    fake.ready = False
    assert offered(search_provider="fake") is False and offered(search_provider="no-such") is False
