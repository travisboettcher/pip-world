import asyncio
import logging
import os
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
import json

from fastapi.responses import JSONResponse, RedirectResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import art
from . import creations as cr
from . import emotions as emo
from . import invented_places as invented
from . import happenings
from . import modules
from . import places
from . import public_view as pv
from . import projects as proj
from . import worldmap
from . import world_view
from .config import Settings
from .llm import get_backend
from .loop import Agent
from .pacing import get_policy
from .state import SECTIONS, State, clean_sender
from .stream import event_stream

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")


class InboxItem(BaseModel):
    text: str
    sender: str = "A visitor"


class Gift(BaseModel):
    name: str
    qty: int = Field(1, ge=1, le=999)
    kind: str = "tool"
    description: str = ""
    attrs: dict = {}
    sender: str = "A visitor"
    message: str = ""


class NoCacheStaticFiles(StaticFiles):
    """The UI is three small files that change together; make browsers revalidate (cheap, ETag) instead of
    pairing a stale stylesheet with new markup."""

    def file_response(self, *args, **kwargs):
        response = super().file_response(*args, **kwargs)
        response.headers["Cache-Control"] = "no-cache"
        return response


logging.getLogger("httpx").setLevel(logging.WARNING)  # one INFO line per request (every 30 s for Matrix sync) is just noise


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

    app = FastAPI(title="pip-world", lifespan=lifespan)
    app.state.settings = settings
    app.state.public_streams = 0

    @app.middleware("http")
    async def public_view(request: Request, call_next):
        """Requests on a PUBLIC_HOSTS host: default-deny, read-only, names hidden, cacheable (see public_view.py)."""
        request.state.public = pv.is_public(request, settings)
        if not request.state.public:
            return await call_next(request)
        if not pv.allowed(request.method, request.url.path):
            return JSONResponse({"detail": "Not Found"}, status_code=404)
        response = await call_next(request)
        if response.headers.get("content-type", "").startswith("application/json") and response.status_code == 200:
            body = b"".join([chunk async for chunk in response.body_iterator])
            data = pv.redact(json.loads(body), pv.names_to_hide(app.state.agent.state, settings))
            response = JSONResponse(data, status_code=200)
        if response.status_code == 200 and request.url.path != "/stream":
            response.headers["Cache-Control"] = f"public, max-age={pv.CACHE_SECONDS}"
        return response

    @app.get("/mode")
    def mode(request: Request):
        return {"public": request.state.public, "version": settings.version, "revision": settings.revision}

    @app.get("/stream")
    async def stream(request: Request, after_id: int | None = None):
        """Live events (SSE). Starts after `after_id`, the Last-Event-ID header (auto-reconnect), or now."""
        state = app.state.agent.state
        transform = None
        if request.state.public:
            if app.state.public_streams >= pv.MAX_PUBLIC_STREAMS:
                return JSONResponse({"detail": "Too many viewers right now"}, status_code=503)
            transform = pv.public_events(state, settings)
        if after_id is None:
            after_id = int(request.headers.get("last-event-id") or 0) or \
                       next((e["id"] for e in state.events(limit=1)), 0)
        async def frames():
            counted = request.state.public
            app.state.public_streams += counted
            try:
                async for frame in event_stream(state, after_id, request.is_disconnected, transform=transform):
                    yield frame
            finally:
                app.state.public_streams -= counted
        return StreamingResponse(frames(),
                                 media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    @app.get("/healthz")
    def healthz():
        return {"ok": True}

    @app.get("/state")
    def get_state(request: Request):
        agent: Agent = app.state.agent
        full = {
            "agent": agent.state.agent(),
            "usage": agent.state.usage_today(),
            "pending_inbox": len(agent.state.pending_inbox()),
            "coins": agent.state.coins(),
            "ticks": agent.ticks,
            "backend": agent.backend.name,
            "model": settings.llm_model,
            "pacing": agent.pacing.name,
            "tools": list(agent.tools),
        }
        return pv.public_state(full) if request.state.public else full

    @app.get("/events")
    def get_events(request: Request, limit: int = 50, before_id: int | None = None, after_id: int | None = None):
        events = app.state.agent.state.events(min(limit, 500), before_id, after_id)
        if request.state.public:
            shown = pv.public_events(app.state.agent.state, settings)
            return [e for e in map(shown, events) if e]
        return events

    @app.get("/notes")
    def get_notes(limit: int = 50, status: str | None = None):
        """status=archived shows archived entries; otherwise they're hidden."""
        st = app.state.agent.state
        return {sec: st.memories(sec, status=status, limit=min(limit, 500)) for sec in SECTIONS}

    @app.get("/items")
    def get_items():
        return app.state.agent.state.items()

    @app.get("/emotions")
    def get_emotions(limit: int = 50):
        st = app.state.agent.state
        return {"mode": settings.emotions, **emo.snapshot(st), "log": st.emotion_log(min(limit, 500))}

    @app.get("/happenings")
    def get_happenings(request: Request, limit: int = 20):
        rows = app.state.agent.state.happenings(min(limit, 100))
        return [happenings.public_row(h) for h in rows] if request.state.public else rows

    @app.get("/happenings/{happening_id}/replay")
    def replay_happening(happening_id: int):
        """Owner only (not in the public allowlist): the dice for one happening, rolled again from its stored seed."""
        st = app.state.agent.state
        h = st.happening(happening_id)
        if not h:
            raise HTTPException(status_code=404, detail=f"no happening #{happening_id}")
        return happenings.replay(st, settings, h)

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
                        "working_until": sess["ends_at"] if sess and sess["kind"] in ("work", "experiment")
                        and sess["project_id"] == p["id"] else None})
        return {"projects": out, "skills": {c: {"xp": xp, "level": proj.level(xp)} for c, xp in st.skills().items()},
                "abilities": {a: {"xp": xp, "level": proj.level(xp)} for a, xp in st.abilities().items()}}

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
        sender = clean_sender(g.sender)
        inbox_id = agent.state.add_inbox(text, sender, gift=True)
        agent.state.log("gift", sender=sender, item=item["name"], qty=g.qty, item_kind=item["kind"])
        agent.state.log("inbox", id=inbox_id, text=text, gift=True, sender=sender)
        agent.request_wake(urgent=True)
        return {"queued": True, "id": inbox_id, "item": item}

    @app.get("/works")
    def get_works(kind: str | None = None, limit: int = 50):
        return app.state.agent.state.works(kind if kind in ("drawing", "writing") else None, min(limit, 200))

    # A drawing is served only as the sanitised SVG stored at creation, with a policy that lets it paint and nothing else.
    SVG_HEADERS = {"Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; sandbox",
                   "X-Content-Type-Options": "nosniff", "Cache-Control": "no-cache"}

    @app.get("/works/{work_id}.svg")
    def get_work_svg(work_id: int):
        w = app.state.agent.state.work(work_id)
        if not w or w["kind"] != "drawing":
            raise HTTPException(status_code=404, detail="no such drawing")
        return Response(w["body"], media_type="image/svg+xml", headers=SVG_HEADERS)

    @app.get("/works/{work_id}.png")
    def get_work_png(work_id: int, width: int = 800):
        w = app.state.agent.state.work(work_id)
        if not w or w["kind"] != "drawing":
            raise HTTPException(status_code=404, detail="no such drawing")
        try:
            return Response(art.render_png(w["body"], max(100, min(width, 1600))), media_type="image/png", headers=SVG_HEADERS)
        except Exception:
            raise HTTPException(status_code=422, detail="that drawing can't be rendered") from None

    @app.get("/works/{work_id}")
    def get_work(work_id: int):
        w = app.state.agent.state.work(work_id)
        if not w:
            raise HTTPException(status_code=404, detail="no such work")
        return w

    @app.post("/inbox")
    def post_inbox(item: InboxItem):
        agent: Agent = app.state.agent
        inbox_id = agent.receive(item.text, item.sender)
        return {"queued": True, "id": inbox_id}

    @app.get("/outreach")
    def get_outreach(limit: int = 50):
        o = app.state.agent.outreach
        return {"mode": settings.outreach, "channels": o.status(), "allowance": o.allowance(),
                "items": o.state.outreach_rows(min(limit, 200))}

    @app.get("/memory")
    def get_memory(request: Request):
        st = app.state.agent.state
        full = {"self": st.meta("self_portrait"), "people": st.people(),
                "days": st.reflections("day", limit=30), "insights": st.reflections("insight", limit=50, by_importance=True),
                "portraits": st.reflections("portrait", limit=20), "changes": st.reflections("change", limit=20),
                "stats": [{"day": d, **v} for d, v in st.day_stats(14)],
                "expectations": st.expectations(limit=50),
                "capabilities": (st.capability_snapshots(1) or [(None, None)])[0][1],
                "night_decisions": st.decisions(20), "focus": st.focus(None, 20),
                "turning": st.reflections("turning", limit=20), "turning_candidates": st.turning_points(20),
                "on_mind": next((e["data"] for e in st.events(200) if e["kind"] == "reminded"), None),
                "last_reflection_ts": float(st.meta("last_reflection_ts") or 0) or None}
        return {k: v for k, v in full.items() if k not in ("people", "on_mind")} if request.state.public else full

    @app.get("/recall")
    def get_recall(q: str, limit: int = 5):
        return app.state.agent.state.recall(q, min(limit, 20))

    @app.post("/reflect")
    async def post_reflect():
        """Reflect now instead of waiting for the night (covers everything since the last reflection)."""
        return {"reflection": await app.state.agent.reflect()}

    @app.get("/letters")
    def get_letters(limit: int = 50):
        st = app.state.agent.state
        return {"neighbors": [{k: c[k] for k in ("name", "about", "life", "next_chatter_at")}
                              for c in st.characters("neighbor")],
                "letters": st.letters(limit=min(limit, 500))}

    @app.get("/map")
    def get_map():
        """Pip's map: every place with its spot, and where Pip is (see worldmap.py)."""
        agent: Agent = app.state.agent
        return worldmap.snapshot(agent.state, settings, agent.library)

    @app.get("/world/map")
    def get_world_map():
        """Everything the parchment map draws from (see world_view.py and DESIGN-world-view.md)."""
        agent: Agent = app.state.agent
        return world_view.map_view(agent.state, settings, agent.library)

    @app.get("/world/scene")
    def get_world_scene(place: str | None = None):
        """Everything a place's scene draws from (where Pip is, unless `place` says otherwise)."""
        agent: Agent = app.state.agent
        got = world_view.scene_view(agent.state, settings, agent.library, place)
        if got is None:
            raise HTTPException(status_code=404, detail=f"no place called {place!r}")
        return got

    @app.get("/places")
    def get_places():
        """Places characters told Pip about (heard-of, real, removed), with who mentioned them and who lives there;
        and the built-ins."""
        agent: Agent = app.state.agent
        st = agent.state
        built = [k for k, p in places.registry(st, settings, agent.library).items() if not p.invented]
        residents = st.characters("resident")
        return {"places": [{**r, "residents": [{k: c[k] for k in ("name", "about", "life")} for c in residents
                                               if c["place"] == r["key"]]} for r in st.place_rows()],
                "built_in": built}

    @app.patch("/places/{key}")
    def patch_place(key: str, changes: dict):
        try:
            rec = invented.patch(app.state.agent.state, key, changes)
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e))
        if not rec:
            raise HTTPException(status_code=404, detail=f"no place called {key!r}")
        return rec

    @app.delete("/places/{key}")
    def delete_place(key: str):
        rec = invented.remove(app.state.agent.state, key)
        if not rec:
            raise HTTPException(status_code=404, detail=f"no place called {key!r}")
        return rec

    @app.get("/library/search")
    def library_search(q: str = "", limit: int = 10):
        agent: Agent = app.state.agent
        if not agent.library:
            raise HTTPException(status_code=404, detail="no library mounted")
        return [{k: b[k] for k in ("id", "title", "authors", "tags", "series", "description", "formats", "format")}
                for b in agent.library.search(q, min(limit, 50))]

    @app.get("/library/bookmarks")
    def library_bookmarks():
        return app.state.agent.state.bookmarks()

    # --- modules (docs/DESIGN-modules.md): anyone sees what's live; only the owner sees proposals and decides ---------------------
    @app.get("/modules")
    def get_modules(request: Request):
        rows = app.state.agent.state.modules()
        if request.state.public:
            return [modules.public_row(m) for m in rows if m["status"] in ("live", "disabled")]
        return [modules.public_row(m, full=True) for m in rows]

    @app.get("/modules/{module_id}")
    def get_module(module_id: int, request: Request, calls: int = 30):
        st = app.state.agent.state
        m = st.module(module_id)
        if not m or (request.state.public and m["status"] not in ("live", "disabled")):
            raise HTTPException(status_code=404, detail=f"no module #{module_id}")
        return {**modules.public_row(m, full=not request.state.public), "calls": st.module_calls(module_id, min(calls, 200))}

    class Decision(BaseModel):
        note: str = Field("", max_length=500)

    async def _decide(module_id: int, what: str, note: str):
        agent = app.state.agent
        if what == "approve":
            r = await modules.approve(agent.state, settings, agent.runner, module_id, note)
        elif what == "reject":
            r = modules.reject(agent.state, module_id, note)
        else:
            r = modules.disable(agent.state, module_id, note or "switched off by the owner")
        if "error" in r:
            raise HTTPException(status_code=409, detail=r["error"])
        agent.request_wake()
        return r

    @app.post("/modules/{module_id}/approve")
    async def approve_module(module_id: int, body: Decision | None = None):
        return await _decide(module_id, "approve", body.note if body else "")

    @app.post("/modules/{module_id}/reject")
    async def reject_module(module_id: int, body: Decision | None = None):
        return await _decide(module_id, "reject", body.note if body else "")

    @app.post("/modules/{module_id}/disable")
    async def disable_module(module_id: int, body: Decision | None = None):
        return await _decide(module_id, "disable", body.note if body else "")

    @app.post("/tick")
    def post_tick():
        app.state.agent.request_wake(force=True)
        return {"requested": True}

    web_dir = Path(os.environ.get("WEB_DIR") or Path(__file__).resolve().parent.parent / "web")
    if web_dir.is_dir():
        app.mount("/ui", NoCacheStaticFiles(directory=web_dir, html=True), name="ui")

        @app.get("/", include_in_schema=False)
        def root():
            return RedirectResponse("/ui/")

    return app


app = create_app()
