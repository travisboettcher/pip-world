from fastapi.testclient import TestClient

from app.config import Settings
from app.llm.base import LLMResponse, ToolCall, Usage
from app.llm.fake import FakeBackend
from app.main import create_app


def test_api_roundtrip(tmp_path):
    s = Settings(db_path=str(tmp_path / "t.db"), persona_path="/x", persona_default_path="/x",
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
    s = Settings(db_path=str(tmp_path / "t.db"), persona_path="/x", persona_default_path="/x", pacing="manual")
    with TestClient(create_app(s, FakeBackend())) as c:
        c.post("/inbox", json={"text": "a"})
        c.post("/inbox", json={"text": "b"})
        ids = [e["id"] for e in c.get("/events?after_id=0").json()]
        assert ids == sorted(ids) and len(ids) >= 3
        assert [e["id"] for e in c.get("/events?after_id=%d" % ids[-2]).json()] == [ids[-1]]


def test_notes_endpoint(tmp_path):
    s = Settings(db_path=str(tmp_path / "t.db"), persona_path="/x", persona_default_path="/x", pacing="manual")
    with TestClient(create_app(s, FakeBackend())) as c:
        c.app.state.agent.state.add_memory("a wish", "wishlist")
        notes = c.get("/notes").json()
        assert set(notes) == {"diary", "todo", "wishlist", "ambitions", "learned"}
        assert notes["wishlist"][0]["text"] == "a wish"
