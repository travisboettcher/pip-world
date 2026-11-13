import random
import time

from fastapi.testclient import TestClient

from app import creations as cr

from app.config import Settings
from app.llm.base import LLMResponse, ToolCall, Usage
from app.llm.fake import FakeBackend
from app.main import create_app
from tests.test_projects import given


def test_api_roundtrip(tmp_path):
    s = Settings(db_path=str(tmp_path / "t.db"), persona_path="/x",
                 pacing="manual", tools=["set_activity"])
    backend = FakeBackend([LLMResponse("hi", [ToolCall("1", "set_activity", {"activity": "Painting", "description": "mixing blues"})], Usage(5, 5))])
    with TestClient(create_app(s, backend)) as c:
        assert c.get("/healthz").json() == {"ok": True}
        assert c.post("/inbox", json={"text": "yo"}).json() == {"queued": True, "id": 1}
        c.post("/tick")
        for _ in range(50):
            import time; time.sleep(0.05)
            if c.get("/state").json()["ticks"]:
                break
        st = c.get("/state").json()
        assert st["agent"]["activity"] == "painting" and st["agent"]["description"] == "mixing blues"
        assert st["usage"]["total_tokens"] == 10
        kinds = [e["kind"] for e in c.get("/events").json()]
        assert "start" in kinds and "tool" in kinds


def test_events_after_id_is_ascending(tmp_path):
    s = Settings(db_path=str(tmp_path / "t.db"), persona_path="/x", pacing="manual")
    with TestClient(create_app(s, FakeBackend())) as c:
        c.post("/inbox", json={"text": "a"})
        c.post("/inbox", json={"text": "b"})
        ids = [e["id"] for e in c.get("/events?after_id=0").json()]
        assert ids == sorted(ids) and len(ids) >= 3
        assert [e["id"] for e in c.get("/events?after_id=%d" % ids[-2]).json()] == [ids[-1]]


def test_notes_endpoint(tmp_path):
    s = Settings(db_path=str(tmp_path / "t.db"), persona_path="/x", pacing="manual")
    with TestClient(create_app(s, FakeBackend())) as c:
        c.app.state.agent.state.add_memory("a wish", "wishlist")
        notes = c.get("/notes").json()
        assert set(notes) == {"diary", "todo", "wishlist", "ambitions", "learned"}
        assert notes["wishlist"][0]["text"] == "a wish"


def test_gift_endpoint_and_inventory(tmp_path):
    s = Settings(db_path=str(tmp_path / "t.db"), persona_path="/x", pacing="manual")
    with TestClient(create_app(s, FakeBackend())) as c:
        r = c.post("/items", json={"name": "tiny needle file", "kind": "tool", "sender": "Morgan",
                                   "message": "For the clock!"}).json()
        assert r["queued"] and r["item"]["qty"] == 1
        names = [i["name"] for i in c.get("/items").json()]
        assert "tiny needle file" in names and "tomato seeds" in names
        ev = c.get("/events?limit=20").json()
        assert any(e["kind"] == "gift" and e["data"]["item"] == "tiny needle file" for e in ev)
        assert any(e["kind"] == "inbox" and "Morgan gave you 1 x tiny needle file" in e["data"]["text"] for e in ev)
        assert c.post("/items", json={"name": "x", "kind": "weapon"}).status_code == 422
        assert c.get("/standing").json() == [] and c.get("/garden").status_code == 404


def test_ui_is_served_and_root_redirects(tmp_path):
    s = Settings(db_path=str(tmp_path / "t.db"), persona_path="/x", pacing="manual")
    with TestClient(create_app(s, FakeBackend())) as c:
        r = c.get("/", follow_redirects=False)
        assert r.status_code in (302, 307) and r.headers["location"] == "/ui/"
        page = c.get("/ui/")
        assert page.status_code == 200 and "<title>Pip</title>" in page.text
        assert c.get("/ui/app.js").status_code == 200 and c.get("/ui/style.css").status_code == 200
        # the JSON API is unaffected by the static mount
        assert c.get("/healthz").json() == {"ok": True}


def test_gift_inbox_event_is_flagged(tmp_path):
    s = Settings(db_path=str(tmp_path / "t.db"), persona_path="/x", pacing="manual")
    with TestClient(create_app(s, FakeBackend())) as c:
        c.post("/items", json={"name": "file"})
        c.post("/inbox", json={"text": "hello"})
        inbox = [e["data"] for e in c.get("/events?after_id=0").json() if e["kind"] == "inbox"]
        assert [d.get("gift", False) for d in inbox] == [True, False]  # the UI hides gift messages from chat


import asyncio  # noqa: E402

from app.state import State  # noqa: E402
from app.stream import event_stream  # noqa: E402


def test_event_stream_frames_and_resume(tmp_path):
    st = State(Settings(db_path=str(tmp_path / "t.db")))
    first = st.log("a", n=1)
    st.log("b", n=2)

    async def collect(cur, polls=2):
        async def never(): return False
        return [f async for f in event_stream(st, cur, never, interval=0, max_polls=polls)]

    frames = asyncio.run(collect(first))
    assert frames[0].startswith("retry:")
    data = [f for f in frames if f.startswith("id:")]
    assert len(data) == 1 and f"id: {first + 1}\n" in data[0] and '"kind": "b"' in data[0]  # only events after `first`
    assert asyncio.run(collect(first + 1)) == ["retry: 3000\n\n"]  # nothing new -> only the retry hint


def test_event_stream_stops_on_disconnect(tmp_path):
    st = State(Settings(db_path=str(tmp_path / "t.db")))

    async def run():
        async def gone(): return True
        return [f async for f in event_stream(st, 0, gone, interval=0)]

    assert asyncio.run(run()) == ["retry: 3000\n\n"]


def test_gift_points_at_matching_wish(tmp_path):
    s = Settings(db_path=str(tmp_path / "t.db"), persona_path="/x", pacing="manual")
    with TestClient(create_app(s, FakeBackend())) as c:
        st = c.app.state.agent.state
        wish = st.add_memory("A small brass set of fine gears and a tiny file", "wishlist")
        c.post("/items", json={"name": "tiny needle file", "sender": "Morgan"})
        c.post("/items", json={"name": "watering can", "sender": "Morgan"})
        texts = [i["text"] for i in st.pending_inbox()]
        assert f"#{wish}" in texts[0] and "edit_note" in texts[0] and "resolve_note" in texts[0]
        assert "wished for" not in texts[1]


def test_projects_and_creations_endpoints(tmp_path):
    s = Settings(db_path=str(tmp_path / "t.db"), persona_path="/x", pacing="manual")
    with TestClient(create_app(s, FakeBackend())) as c:
        st = c.app.state.agent.state
        asyncio.run(given(st, {"name": "kite", "goal": "fly", "craft": "sewing", "stages": [{"name": "cut", "minutes": 30, "progress": 15.0,
                                                                                            "started": True}]}, skills={"sewing": 120}))
        st.start_session(0, 0, 30, 9e9, kind="module", target="crafting", about="kite")
        _, _, spec = cr.sanitize_spec({"description": "a clock", "capabilities": [{"type": "timekeeper"}]},
                                      {"name": "clock", "difficulty": 1}, "fine", [], random.Random(1))
        st.add_creation("clock", "a clock", None, "fine", spec, cr.initial_runtime(spec, time.time()))
        r = c.get("/projects").json()
        assert r["projects"][0]["percent"] == 50 and r["projects"][0]["working_until"] == 9e9
        assert r["skills"] == {"sewing": {"xp": 120, "level": 1}}
        (made,) = c.get("/creations").json()
        assert made["running"] and made["clock"]["minutes_off"] == 0 and made["summary"].startswith("clock (fine)")


def test_ui_files_are_revalidated_not_cached_blindly(tmp_path, monkeypatch):
    web = tmp_path / "web"
    web.mkdir()
    (web / "index.html").write_text("<p>hi</p>")
    (web / "style.css").write_text("p{}")
    monkeypatch.setenv("WEB_DIR", str(web))
    s = Settings(db_path=str(tmp_path / "t.db"), persona_path="/x", pacing="manual")
    with TestClient(create_app(s, FakeBackend())) as c:
        for path in ("/ui/", "/ui/style.css"):
            r = c.get(path)
            assert r.status_code == 200 and r.headers["cache-control"] == "no-cache" and r.headers["etag"], path
        again = c.get("/ui/style.css", headers={"if-none-match": r.headers["etag"]})
        assert again.status_code == 304


def test_the_app_is_named_serves_drawings_locked_down_and_mounts_the_web_dir(tmp_path, monkeypatch):
    from app import art
    from tests.test_art import GOOD
    web = tmp_path / "web"
    web.mkdir()
    (web / "index.html").write_text("<p>hello</p>")
    monkeypatch.setenv("WEB_DIR", str(web))
    s = Settings(db_path=str(tmp_path / "t.db"), persona_path="/x", pacing="manual")
    with TestClient(create_app(s, FakeBackend())) as c:
        assert c.app.title == "pip-world" and c.app.url_path_for("ui", path="/index.html") == "/ui/index.html"
        assert "hello" in c.get("/ui/index.html").text
        d = c.app.state.agent.state.add_work("drawing", "A circle", art.sanitize_svg(GOOD), "round")
        h = c.get(f"/works/{d}.svg").headers
        assert h["content-security-policy"] == "default-src 'none'; style-src 'unsafe-inline'; sandbox"
        assert h["cache-control"] == "no-cache" and h["x-content-type-options"] == "nosniff"
