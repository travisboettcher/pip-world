from fastapi.testclient import TestClient

from app.config import Settings
from app.llm.base import LLMResponse, ToolCall, Usage
from app.llm.fake import FakeBackend
from app.main import create_app


def test_api_roundtrip(tmp_path):
    s = Settings(db_path=str(tmp_path / "t.db"), persona_path="/x", persona_default_path="/x",
                 pacing="manual", tools=["set_activity"])
    backend = FakeBackend([LLMResponse("hi", [ToolCall("1", "set_activity", {"activity": "Painting"})], Usage(5, 5))])
    with TestClient(create_app(s, backend)) as c:
        assert c.get("/healthz").json() == {"ok": True}
        assert c.post("/inbox", json={"text": "yo"}).json() == {"queued": True}
        c.post("/tick")
        for _ in range(50):
            import time; time.sleep(0.05)
            if c.get("/state").json()["ticks"]:
                break
        st = c.get("/state").json()
        assert st["agent"]["activity"] == "painting"
        assert st["usage"]["total_tokens"] == 10
        kinds = [e["kind"] for e in c.get("/events").json()]
        assert "start" in kinds and "tool" in kinds
