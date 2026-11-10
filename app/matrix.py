"""The Matrix channel: Pip and its owner in one private room on a homeserver they run (see DESIGN-outreach.md).

It speaks the Client-Server API directly over httpx (login is done once by the bootstrap script; Pip is given an access
token), so there is no native dependency and no end-to-end encryption machinery: the room is unencrypted, on the owner's own
server. A *conversation* is a thread: the id of its root event. A postcard is a top-level message (its event id is the thread
root); a reply is sent inside that thread; a human message in a thread keeps it, and a human top-level message opens one.
"""
import asyncio
import json
import logging
import uuid
from urllib.parse import quote

import httpx

from .channels import Inbound, Outbound, SendResult, register

log = logging.getLogger("matrix")

API = "/_matrix/client/v3"
SYNC_TIMEOUT_MS = 30_000
BACKOFF_START = 1.0
BACKOFF_MAX = 60.0
KEEP_SEEN = 200
KEEP_ROOTS = 200
SYNC_FILTER = json.dumps({
    "presence": {"types": []}, "account_data": {"types": []},
    "room": {"timeline": {"types": ["m.room.message"], "limit": 50}, "state": {"types": []},
             "ephemeral": {"types": []}, "account_data": {"types": []}},
})


class MatrixChannel:
    name = "matrix"
    capabilities = frozenset({"receive", "threads", "typing", "images", "receipts"})

    def __init__(self, settings, store, client: httpx.AsyncClient | None = None):
        self.homeserver = (settings.matrix_homeserver or "").rstrip("/")
        self.user_id = settings.matrix_user_id
        self.room_id = settings.matrix_room_id
        self.allowed = dict(settings.matrix_allowed)
        self._token = settings.matrix_access_token
        self.store = store
        self._client = client
        self._own_client = client is None
        self._task: asyncio.Task | None = None
        self._on_message = None
        self.last_error = ""

    def __repr__(self) -> str:  # never shows the token
        return f"MatrixChannel(room={self.room_id!r}, user={self.user_id!r})"

    @property
    def configured(self) -> bool:
        return all((self.homeserver, self.user_id, self._token, self.room_id, self.allowed))

    def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(base_url=self.homeserver, timeout=SYNC_TIMEOUT_MS / 1000 + 10)
        return self._client

    async def _call(self, method: str, url: str, **kw) -> httpx.Response:
        """Every request carries the token itself, so an injected client (tests, a proxy) needs no special set-up."""
        kw["headers"] = {**(kw.get("headers") or {}), "Authorization": f"Bearer {self._token}"}
        return await self._http().request(method, url, **kw)

    # --- small persisted sets ------------------------------------------------------
    def _list(self, key: str) -> list[str]:
        return [x for x in (self.store.get(key, "") or "").split(",") if x]

    def _remember(self, key: str, value: str, keep: int) -> None:
        items = [x for x in self._list(key) if x != value] + [value]
        self.store.set(key, ",".join(items[-keep:]))

    # --- receiving ----------------------------------------------------------------
    async def start(self, on_message) -> None:
        if not self.configured:
            raise ValueError("the Matrix channel needs MATRIX_HOMESERVER, MATRIX_USER_ID, MATRIX_ACCESS_TOKEN, MATRIX_ROOM_ID "
                             "and MATRIX_ALLOWED")
        self._on_message = on_message
        if self._task and not self._task.done():
            return
        if not self.store.get("since"):  # first run: take today's position, not the room's history
            data = await self._sync(None, 0)
            self.store.set("since", data["next_batch"])
        self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass
            self._task = None
        if self._client is not None and self._own_client:
            await self._client.aclose()
            self._client = None
        self._on_message = None

    async def _sync(self, since: str | None, timeout_ms: int) -> dict:
        params = {"timeout": str(timeout_ms), "filter": SYNC_FILTER}
        if since:
            params["since"] = since
        r = await self._call("GET", f"{API}/sync", params=params)
        r.raise_for_status()
        return r.json()

    async def _loop(self) -> None:
        delay = BACKOFF_START
        while True:
            try:
                data = await self._sync(self.store.get("since"), SYNC_TIMEOUT_MS)
                await self._handle(data)
                self.store.set("since", data["next_batch"])  # after delivery: at-least-once (the core drops duplicates)
                self.last_error, delay = "", BACKOFF_START
            except asyncio.CancelledError:
                raise
            except Exception as e:
                self.last_error = f"{type(e).__name__}: {e}"[:200]
                log.warning("matrix sync failed: %s", self.last_error)
                await asyncio.sleep(delay)
                delay = min(BACKOFF_MAX, delay * 2)

    async def _handle(self, data: dict) -> None:
        rooms = data.get("rooms", {})
        for room_id in rooms.get("invite", {}):
            await self._answer_invite(room_id)
        for ev in rooms.get("join", {}).get(self.room_id, {}).get("timeline", {}).get("events", []):
            await self._deliver(ev)

    async def _answer_invite(self, room_id: str) -> None:
        action = "join" if room_id == self.room_id else "leave"  # this room only; decline every other invite
        try:
            await self._call("POST", f"{API}/rooms/{quote(room_id, safe='')}/{action}", json={})
        except Exception as e:
            log.warning("matrix %s %s failed: %s", action, room_id, e)

    def _conversation(self, ev: dict) -> str:
        rel = (ev.get("content") or {}).get("m.relates_to") or {}
        if rel.get("rel_type") == "m.thread" and rel.get("event_id"):
            return rel["event_id"]
        replied = (rel.get("m.in_reply_to") or {}).get("event_id")
        if replied and replied in self._list("roots"):  # a plain reply to one of Pip's postcards
            return replied
        return ev["event_id"]                            # a top-level message opens its own conversation

    async def _deliver(self, ev: dict) -> None:
        sender, content = ev.get("sender"), ev.get("content") or {}
        if (ev.get("type") != "m.room.message" or sender == self.user_id or sender not in self.allowed
                or content.get("msgtype") not in ("m.text", "m.emote") or not content.get("body")):
            return
        eid = ev["event_id"]
        if eid in self._list("seen"):
            return
        self._remember("seen", eid, KEEP_SEEN)
        conversation = self._conversation(ev)
        self.store.set(f"last:{conversation}", eid)  # Pip's next reply answers the latest message in the thread
        if self._on_message:
            await self._on_message(Inbound(sender, self.allowed[sender], str(content["body"]), conversation,
                                           (ev.get("origin_server_ts") or 0) / 1000, eid))

    # --- sending ------------------------------------------------------------------
    def _relation(self, conversation: str | None) -> dict:
        if not conversation:
            return {}
        last = self.store.get(f"last:{conversation}") or conversation
        return {"m.relates_to": {"rel_type": "m.thread", "event_id": conversation, "is_falling_back": True,
                                 "m.in_reply_to": {"event_id": last}}}

    async def _put_event(self, content: dict, room: str | None = None) -> str:
        r = await self._call("PUT", f"{API}/rooms/{quote(room or self.room_id, safe='')}/send/m.room.message/{uuid.uuid4().hex}",
                             json=content)
        r.raise_for_status()
        return r.json()["event_id"]

    async def send(self, out: Outbound, conversation: str | None = None) -> SendResult:
        if not self.configured:
            return SendResult(False, error="the Matrix channel is not configured")
        try:
            content = {"msgtype": "m.text", "body": out.text, **self._relation(conversation)}
            eid = await self._put_event(content)
            root = conversation or eid
            if not conversation:
                self._remember("roots", eid, KEEP_ROOTS)
            self.store.set(f"last:{root}", eid)
        except httpx.HTTPStatusError as e:
            return SendResult(False, error=_describe(e))
        except Exception as e:
            return SendResult(False, error=f"{type(e).__name__}: {e}"[:200])
        problems = []
        for img in out.images:
            try:
                await self._send_image(img, root)
            except Exception as e:  # the words went; say the picture didn't
                problems.append(f"picture not sent: {type(e).__name__}")
        return SendResult(True, error="; ".join(problems), conversation=root)

    async def notice(self, text: str, room: str | None = None) -> SendResult:
        """A notice from the engine to the owner (not Pip speaking): an m.notice, in Pip's room or another it has joined. Pip never sees it:
        the sync skips messages from its own account."""
        if not self.configured:
            return SendResult(False, error="the Matrix channel is not configured")
        try:
            await self._put_event({"msgtype": "m.notice", "body": text}, room)
        except httpx.HTTPStatusError as e:
            return SendResult(False, error=_describe(e))
        except Exception as e:
            return SendResult(False, error=f"{type(e).__name__}: {e}"[:200])
        return SendResult(True)

    async def _send_image(self, img, conversation: str) -> None:
        up = await self._call("POST", "/_matrix/media/v3/upload", params={"filename": img.name}, content=img.data,
                              headers={"Content-Type": img.mime})
        up.raise_for_status()
        content = {"msgtype": "m.image", "body": img.caption or img.name, "url": up.json()["content_uri"],
                   "info": {"mimetype": img.mime, "size": len(img.data)}, **self._relation(conversation)}
        self.store.set(f"last:{conversation}", await self._put_event(content))

    async def typing(self, conversation: str) -> None:
        if not self.configured:
            return
        await self._call("PUT", f"{API}/rooms/{quote(self.room_id, safe='')}/typing/{quote(self.user_id, safe='')}",
                         json={"typing": True, "timeout": 20_000})

    async def read(self, conversation: str, message_id: str) -> None:
        if not self.configured:
            return
        await self._call("POST", f"{API}/rooms/{quote(self.room_id, safe='')}/receipt/m.read/{quote(message_id, safe='')}",
                         json={"thread_id": conversation or "main"})


def _describe(e: httpx.HTTPStatusError) -> str:
    try:
        body = e.response.json()
        return f"{e.response.status_code} {body.get('errcode', '')} {body.get('error', '')}".strip()[:200]
    except Exception:
        return f"{e.response.status_code}"


@register("matrix")
def _make_matrix(settings, store):
    return MatrixChannel(settings, store)
