import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from pydantic import BaseModel

from .config import Settings
from .llm import get_backend
from .loop import Agent
from .pacing import get_policy
from .state import State

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")


class InboxItem(BaseModel):
    text: str


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
    def get_events(limit: int = 50, before_id: int | None = None):
        return app.state.agent.state.events(min(limit, 500), before_id)

    @app.post("/inbox")
    def post_inbox(item: InboxItem):
        agent: Agent = app.state.agent
        agent.state.log("inbox", text=item.text)
        agent.state.add_inbox(item.text)
        agent.request_wake()
        return {"queued": True}

    @app.post("/tick")
    def post_tick():
        app.state.agent.request_wake(force=True)
        return {"requested": True}

    return app


app = create_app()
