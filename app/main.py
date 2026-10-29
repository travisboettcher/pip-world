import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from .config import Settings
from .llm import get_backend
from .loop import Agent
from .pacing import get_policy
from .state import SECTIONS, State

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")


class InboxItem(BaseModel):
    text: str


class Gift(BaseModel):
    name: str
    qty: int = Field(1, ge=1, le=999)
    kind: str = "tool"
    description: str = ""
    attrs: dict = {}
    sender: str = "A visitor"
    message: str = ""


def create_app(settings: Settings | None = None, backend=None) -> FastAPI:
    settings = settings or Settings.from_env()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        state = State(settings)
        agent = Agent(settings, state, backend or get_backend(settings), get_policy(settings))
        app.state.agent = agent
        state.log("start", backend=agent.backend.name, model=settings.llm_model,
                  pacing=agent.pacing.name, tools=list(agent.tools))
        task = asyncio.create_task(agent.run())
        yield
        task.cancel()

    app = FastAPI(title="agent-world", lifespan=lifespan)

    @app.get("/healthz")
    def healthz():
        return {"ok": True}

    @app.get("/state")
    def get_state():
        agent: Agent = app.state.agent
        return {
            "agent": agent.state.agent(),
            "usage": agent.state.usage_today(),
            "pending_inbox": len(agent.state.pending_inbox()),
            "ticks": agent.ticks,
            "backend": agent.backend.name,
            "model": settings.llm_model,
            "pacing": agent.pacing.name,
            "tools": list(agent.tools),
        }

    @app.get("/events")
    def get_events(limit: int = 50, before_id: int | None = None, after_id: int | None = None):
        return app.state.agent.state.events(min(limit, 500), before_id, after_id)

    @app.get("/notes")
    def get_notes(limit: int = 50, status: str | None = None):
        """status=archived shows archived entries; otherwise they're hidden."""
        st = app.state.agent.state
        return {sec: st.memories(sec, status=status, limit=min(limit, 500)) for sec in SECTIONS}

    @app.get("/items")
    def get_items():
        return app.state.agent.state.items()

    @app.get("/garden")
    def get_garden():
        return app.state.agent.state.garden()

    @app.post("/items")
    def give_item(g: Gift):
        """A visitor gives Pip something: it joins the inventory and Pip is told (so it can react)."""
        agent: Agent = app.state.agent
        try:
            item = agent.state.add_item(g.name, g.qty, g.kind, g.description, g.attrs)
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e))
        text = f"{g.sender} gave you {g.qty} x {item['name']} ({item['kind']})" \
               + (f": {item['description']}" if item["description"] else "") + "." + (f" {g.message}" if g.message else "")
        inbox_id = agent.state.add_inbox(text)
        agent.state.log("gift", sender=g.sender, item=item["name"], qty=g.qty, item_kind=item["kind"])
        agent.state.log("inbox", id=inbox_id, text=text)
        agent.request_wake()
        return {"queued": True, "id": inbox_id, "item": item}

    @app.post("/inbox")
    def post_inbox(item: InboxItem):
        agent: Agent = app.state.agent
        inbox_id = agent.state.add_inbox(item.text)
        agent.state.log("inbox", id=inbox_id, text=item.text)
        agent.request_wake()
        return {"queued": True, "id": inbox_id}

    @app.post("/tick")
    def post_tick():
        app.state.agent.request_wake(force=True)
        return {"requested": True}

    return app


app = create_app()
