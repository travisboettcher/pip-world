"""The public, read-only view (docs/DESIGN-public-view.md): default deny, scrubbed events, nothing a viewer does costs or changes anything."""
import asyncio

import pytest
from fastapi.testclient import TestClient

from app import public_view as pv
from app.config import Settings
from app.llm.fake import FakeBackend
from app.main import create_app
from app.stream import event_stream

PUBLIC = {"host": "pip.example.org"}


@pytest.fixture
def client(tmp_path):
    s = Settings(db_path=str(tmp_path / "t.db"), persona_path="/x", pacing="manual",
                 public_hosts=["pip.example.org"], public_redact=["Dana"])
    with TestClient(create_app(s, FakeBackend())) as c:
        yield c


def test_public_hosts_come_from_the_environment(monkeypatch):
    monkeypatch.setenv("PUBLIC_HOSTS", "Pip.Example.org, other.example.org:443 ,")
    monkeypatch.setenv("PUBLIC_REDACT", "Dana, Lee")
    s = Settings.from_env()
    assert s.public_hosts == ["pip.example.org", "other.example.org"] and s.public_redact == ["Dana", "Lee"]
    monkeypatch.delenv("PUBLIC_HOSTS")
    assert Settings.from_env().public_hosts == []


def test_the_owner_host_is_unchanged(client):
    assert client.post("/inbox", json={"text": "hi"}).json()["queued"] is True
    assert "pending_inbox" in client.get("/state").json()
    assert client.get("/mode").json() == {"public": False, "version": "dev", "revision": ""}


def test_mode_reports_public(client):
    assert client.get("/mode", headers=PUBLIC).json() == {"public": True, "version": "dev", "revision": ""}


@pytest.mark.parametrize("method,path", [
    ("post", "/inbox"), ("post", "/items"), ("post", "/tick"), ("post", "/reflect"),
    ("patch", "/places/x"), ("delete", "/places/x"), ("put", "/state"),
    ("get", "/letters"), ("get", "/outreach"), ("get", "/recall?q=a"), ("get", "/library/search"),
    ("get", "/library/bookmarks"), ("get", "/openapi.json"), ("get", "/docs"), ("get", "/anything-new"),
])
def test_everything_not_listed_is_refused(client, method, path):
    r = client.request(method.upper(), path, headers=PUBLIC)
    assert r.status_code == 404
    assert client.get("/state").json()["pending_inbox"] == 0


def test_a_public_write_changes_nothing(client):
    client.post("/inbox", json={"text": "x"}, headers=PUBLIC)
    client.post("/tick", headers=PUBLIC)
    assert client.get("/state").json()["pending_inbox"] == 0


def test_the_host_port_and_case_do_not_matter(client):
    assert client.get("/mode", headers={"host": "PIP.example.org:443"}).json()["public"] is True


@pytest.mark.parametrize("path", ["/state", "/events", "/notes", "/items", "/emotions", "/standing", "/projects",
                                  "/creations", "/works", "/map", "/places", "/memory", "/healthz", "/ui/"])
def test_the_listed_reads_answer_and_are_cacheable(client, path):
    r = client.get(path, headers=PUBLIC)
    assert r.status_code == 200
    assert "max-age" in r.headers["cache-control"]


def test_public_state_leaves_out_operations(client):
    st = client.get("/state", headers=PUBLIC).json()
    assert set(st) == {"agent", "ticks", "coins", "condition"}


def test_memory_leaves_out_people(client):
    client.app.state.agent.state.upsert_person("Dana", "likes tea", 1.0)
    assert client.get("/memory", headers=PUBLIC).json().get("people") is None
    assert client.get("/memory").json()["people"]


def test_events_keep_only_listed_kinds_and_fields(client):
    st = client.app.state.agent.state
    st.log("inbox", id=1, text="secret", sender="Dana")
    st.log("say", text="hello Dana", to=[1])
    st.log("letter_sent", id=1, to="Mina", text="dear", enclosed="")
    st.log("error", error="Traceback: /data/agent.db")
    st.log("garden", plot=1, crop="beans", surprise_field="x")
    kinds = {e["kind"] for e in client.get("/events?limit=100", headers=PUBLIC).json()}
    assert {"inbox", "say", "letter_sent", "error"}.isdisjoint(kinds)
    garden = next(e for e in client.get("/events?limit=100", headers=PUBLIC).json() if e["kind"] == "garden")
    assert set(garden["data"]) <= {"plot", "crop", "firsts", "returns"} and garden["data"]["crop"] == "beans"


def test_tool_events_drop_their_arguments(client):
    client.app.state.agent.state.log("tool", tool="write_letter", args={"text": "private"}, result="sent to Mina: private")
    e = next(e for e in client.get("/events", headers=PUBLIC).json() if e["kind"] == "tool")
    assert e["data"] == {"tool": "write_letter"}
    client.app.state.agent.state.log("tool", tool="tend", args={"plot": 1}, result="watered plot 1")
    e = client.get("/events?limit=1", headers=PUBLIC).json()[0]
    assert e["data"] == {"tool": "tend", "result": "watered plot 1"}


def test_known_names_are_redacted_everywhere(client):
    st = client.app.state.agent.state
    st.add_inbox("hi", "Morgan")                     # a visitor's name, learned from the inbox
    st.upsert_person("Riley", "friend", 1.0)         # a person Pip has notes on
    st.log("tick", reason="x", step=1, text="Dana, Morgan and riley visited")  # Dana is configured
    st.add_memory("Talked with Morgan about Dana.")
    ev = client.get("/events?limit=100", headers=PUBLIC).json()
    text = next(e for e in ev if e["kind"] == "tick")["data"]["text"]
    assert text == "someone, someone and someone visited"
    assert "Morgan" not in client.get("/notes", headers=PUBLIC).text


def test_generic_sender_names_are_not_redacted(client):
    st = client.app.state.agent.state
    st.add_inbox("hi", "A visitor")
    st.add_inbox("hi", "Al")
    assert pv.names_to_hide(st, client.app.state.settings) == ["Dana"]


def test_redaction_matches_whole_words_only():
    assert pv.redact(["Danahan met dana."], ["Dana"]) == ["Danahan met someone."]


def test_public_stream_is_filtered(client):
    st = client.app.state.agent.state
    st.log("inbox", id=1, text="secret", sender="Dana")
    st.log("garden", plot=2, crop="kale")
    async def never():
        return False

    async def run():
        return "".join([f async for f in event_stream(st, 0, never, interval=0, max_polls=1,
                                                       transform=pv.public_events(st, client.app.state.settings))])
    body = asyncio.run(run())
    assert "kale" in body and "secret" not in body and "Dana" not in body


def test_public_streams_are_capped(client, monkeypatch):
    monkeypatch.setattr(pv, "MAX_PUBLIC_STREAMS", 0)
    assert client.get("/stream", headers=PUBLIC).status_code == 503


def test_events_and_notes_limits_are_clamped_for_the_public(client):
    assert client.get("/events?limit=100000", headers=PUBLIC).status_code == 200


class _Req:
    def __init__(self, headers):
        self.headers = headers


class _State:
    def senders(self):
        return ["Ann", "Ann Lee", "Al", "A Visitor"]

    def people(self):
        return [{"name": "Bob"}, {"name": "  Cy "}]


def test_a_request_without_a_host_is_not_public():
    assert pv.host_of(_Req({})) == ""
    assert pv.host_of(_Req({"host": "Pip.Example.org:8080"})) == "pip.example.org"


def test_head_is_allowed_other_methods_are_not():
    assert pv.allowed("HEAD", "/state") and pv.allowed("GET", "/state")
    assert not pv.allowed("OPTIONS", "/state") and not pv.allowed("POST", "/state")
    assert not pv.allowed("GET", "/works/abc") and pv.allowed("GET", "/works/12.png")


def test_names_to_hide_are_long_enough_not_generic_and_longest_first():
    s = Settings(public_redact=["Dana"])
    names = pv.names_to_hide(_State(), s)
    assert names.index("Ann Lee") < names.index("Ann")
    assert set(names) == {"Ann", "Ann Lee", "Bob", "Dana"}
    assert [len(n) for n in names] == sorted((len(n) for n in names), reverse=True)
    assert pv.redact("Ann Lee and Ann", names) == "someone and someone"


def test_a_three_letter_name_is_hidden_and_a_two_letter_one_is_not():
    names = pv.names_to_hide(_State(), Settings())
    assert "Bob" in names and "Al" not in names


def test_a_public_event_keeps_its_envelope():
    out = pv.public_event({"id": 7, "ts": 1.5, "kind": "garden", "importance": 3, "data": {"plot": 1, "crop": "kale", "x": 1}})
    assert out == {"id": 7, "ts": 1.5, "kind": "garden", "importance": 3, "data": {"plot": 1, "crop": "kale"}}


def test_the_event_transform_drops_private_events_and_hides_names(client):
    st = client.app.state.agent.state
    st.add_inbox("hi", "Morgan")
    shown = pv.public_events(st, client.app.state.settings)
    assert shown({"id": 1, "ts": 1.0, "kind": "inbox", "data": {"text": "x"}}) is None
    assert shown({"id": 2, "ts": 1.0, "kind": "tick", "data": {"text": "Morgan came"}})["data"]["text"] == "someone came"


def test_the_running_version_is_reported_on_both_hosts(tmp_path, monkeypatch):
    monkeypatch.setenv("PIP_VERSION", "v1.2.3")
    monkeypatch.setenv("PIP_REVISION", "0123456789abcdef0123456789abcdef01234567")
    s = Settings.from_env()
    s.db_path, s.persona_path, s.pacing, s.public_hosts = str(tmp_path / "t.db"), "/x", "manual", ["pip.example.org"]
    with TestClient(create_app(s, FakeBackend())) as c:
        for headers in ({}, PUBLIC):
            got = c.get("/mode", headers=headers).json()
            assert got["version"] == "v1.2.3" and got["revision"] == "0123456"                 # the short revision


def test_a_build_without_a_version_says_dev(monkeypatch):
    monkeypatch.delenv("PIP_VERSION", raising=False)
    monkeypatch.delenv("PIP_REVISION", raising=False)
    s = Settings.from_env()
    assert s.version == "dev" and s.revision == ""
