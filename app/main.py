import asyncio
import logging
import os
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import creations as cr
from . import projects as proj
from .config import Settings
from .llm import get_backend
from .loop import Agent
from .pacing import get_policy
from .state import SECTIONS, State
from .stream import event_stream

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

    @app.get("/stream")
    async def stream(request: Request, after_id: int | None = None):
        """Live events (SSE). Starts after `after_id`, the Last-Event-ID header (auto-reconnect), or now."""
        state = app.state.agent.state
        if after_id is None:
            after_id = int(request.headers.get("last-event-id") or 0) or \
                       next((e["id"] for e in state.events(limit=1)), 0)
        return StreamingResponse(event_stream(state, after_id, request.is_disconnected),
                                 media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

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

    @app.get("/projects")
    def get_projects(status: str | None = None):
        st = app.state.agent.state
        sess = st.session()
        out = []
        for p in st.projects(status):
            i = proj.current_stage(p)
            out.append({**p, "percent": proj.percent(p), "current_stage": i,
                        "working_until": sess["ends_at"] if sess and sess["project_id"] == p["id"] else None})
        return {"projects": out, "skills": {c: {"xp": xp, "level": proj.level(xp)} for c, xp in st.skills().items()}}

    @app.get("/creations")
    def get_creations():
        st = app.state.agent.state
        now = time.time()
        chars = {ch["creation_id"]: ch["name"] for ch in st.characters() if ch["kind"] == "creation"}
        out = []
        for c in st.creations():
            extra = {"running": cr.running(c, now), "summary": cr.describe(c, now)[2:], "character": chars.get(c["id"])}
            if "timekeeper" in c["spec"]["capabilities"]:
                shown, off = cr.clock_reading(c, now)
                extra["clock"] = {"reads": shown, "minutes_off": round(off, 1)}
            out.append({**c, **extra})
        return out

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
        wishes = agent.state.matching_wishes(item["name"])
        if wishes:
            ids = ", ".join(f"#{m['id']}" for m in wishes)
            text += (f" (This may be something you wished for: {ids}. Cross it off with resolve_note if it is "
                     "fully met, or use edit_note to trim the wish down to what's still missing.)")
        inbox_id = agent.state.add_inbox(text)
        agent.state.log("gift", sender=g.sender, item=item["name"], qty=g.qty, item_kind=item["kind"])
        agent.state.log("inbox", id=inbox_id, text=text, gift=True)
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

    web_dir = Path(os.environ.get("WEB_DIR") or Path(__file__).resolve().parent.parent / "web")
    if web_dir.is_dir():
        app.mount("/ui", StaticFiles(directory=web_dir, html=True), name="ui")

        @app.get("/", include_in_schema=False)
        def root():
            return RedirectResponse("/ui/")

    return app


app = create_app()
