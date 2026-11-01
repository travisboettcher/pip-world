import asyncio
import json
import time

import httpx
import pytest

from app import matrix as M
from app.channels import ChannelStore, Image, Outbound
from app.config import Settings, _parse_people
from app.matrix import MatrixChannel
from app.outreach import Outreach
from tests.channel_contract import ChannelContract
from tests.test_projects import call, make
from tests.test_outreach import daytime

BOT, ROOM, HUMAN, TOKEN = "@pip:test", "!room:test", "@morgan:test", "secret-token"


class FakeHomeserver:
    """Just enough of the Client-Server API for one room, served in-process through httpx's MockTransport."""

    def __init__(self):
        self.events, self.sent, self.typing, self.receipts, self.uploads = [], [], [], [], []
        self.invites, self.left, self.joined, self.requests = [], [], [], []
        self.fail_sends = self.fail_uploads = False
        self.fail_syncs = 0
        self.n = 0

    def add(self, sender, text, thread=None, reply_to=None, event_id=None, msgtype="m.text", room=ROOM):
        self.n += 1
        content = {"msgtype": msgtype, "body": text}
        if thread:
            content["m.relates_to"] = {"rel_type": "m.thread", "event_id": thread}
        elif reply_to:
            content["m.relates_to"] = {"m.in_reply_to": {"event_id": reply_to}}
        ev = {"type": "m.room.message", "sender": sender, "event_id": event_id or f"$e{self.n}", "content": content,
              "origin_server_ts": int(time.time() * 1000), "room": room}
        self.events.append(ev)
        return ev["event_id"]

    def client(self):
        return httpx.AsyncClient(transport=httpx.MockTransport(self.handler), base_url="https://hs.test", timeout=5)

    async def handler(self, request: httpx.Request) -> httpx.Response:
        path, params = request.url.path, dict(request.url.params)
        self.requests.append((request.method, path))
        if request.headers.get("authorization") != f"Bearer {TOKEN}":
            return httpx.Response(401, json={"errcode": "M_UNKNOWN_TOKEN", "error": "bad token"})
        if path.endswith("/sync"):
            if self.fail_syncs:
                self.fail_syncs -= 1
                return httpx.Response(500, json={"errcode": "M_UNKNOWN", "error": "boom"})
            since = int(params["since"][1:]) if params.get("since") else len(self.events)
            if params.get("since") and not self.invites and not [e for e in self.events[since:] if e["room"] == ROOM]:
                await asyncio.sleep(0.02)                           # a short long-poll; events added meanwhile are returned
            upto = len(self.events)
            new = [e for e in self.events[since:upto] if e["room"] == ROOM] if params.get("since") else []
            rooms: dict = {}
            if new:
                rooms["join"] = {ROOM: {"timeline": {"events": [{k: v for k, v in e.items() if k != "room"} for e in new]}}}
            if self.invites:
                rooms["invite"] = {r: {} for r in self.invites}
                self.invites = []
            return httpx.Response(200, json={"next_batch": f"s{upto}", "rooms": rooms})
        if "/send/m.room.message/" in path:
            if self.fail_sends:
                return httpx.Response(500, json={"errcode": "M_UNKNOWN", "error": "server on fire"})
            body = json.loads(request.content)
            eid = self.add(BOT, body["body"], event_id=f"$s{len(self.sent) + 1}")
            self.events[-1]["content"] = body
            rel = body.get("m.relates_to") or {}
            self.sent.append({"id": eid, "body": body, "thread": rel.get("event_id", "")})
            return httpx.Response(200, json={"event_id": eid})
        if "/typing/" in path:
            self.typing.append(json.loads(request.content))
            return httpx.Response(200, json={})
        if "/receipt/" in path:
            self.receipts.append((path, json.loads(request.content)))
            return httpx.Response(200, json={})
        if path.endswith("/upload"):
            if self.fail_uploads:
                return httpx.Response(413, json={"errcode": "M_TOO_LARGE", "error": "too big"})
            self.uploads.append((params.get("filename"), request.headers.get("content-type"), len(request.content)))
            return httpx.Response(200, json={"content_uri": f"mxc://test/{len(self.uploads)}"})
        if path.endswith("/leave"):
            self.left.append(path)
            return httpx.Response(200, json={})
        if path.endswith("/join"):
            self.joined.append(path)
            return httpx.Response(200, json={})
        return httpx.Response(404, json={"errcode": "M_UNRECOGNIZED", "error": path})


def settings(**kw):
    return Settings(matrix_homeserver="https://hs.test", matrix_user_id=BOT, matrix_access_token=TOKEN, matrix_room_id=ROOM,
                    matrix_allowed={HUMAN: "Morgan"}, **kw)


class MatrixHarness:
    sender = (HUMAN, "Morgan")
    stranger = "@mallory:test"

    def __init__(self, st):
        self.server, self.st, self.delivered, self._cb = FakeHomeserver(), st, [], None
        self.channel = self._new()

    def _new(self):
        return MatrixChannel(settings(), ChannelStore(self.st, "matrix"), client=self.server.client())

    async def start(self, on_message):
        async def tee(m):
            self.delivered.append(m.message_id)
            await on_message(m)
        await self.channel.start(tee)

    async def stop(self):
        await self.channel.stop()

    async def inbound(self, sender_id, text, conversation=None, message_id=None):
        eid = self.server.add(sender_id, text, thread=conversation, event_id=message_id)
        for _ in range(40):
            await asyncio.sleep(0.01)
            if eid in self.delivered:
                self.delivered.remove(eid)
                return True
        return False

    def sent(self):
        return [(s["body"]["body"], s["thread"], s["thread"] or s["id"]) for s in self.server.sent]

    def fail_sends(self, on):
        self.server.fail_sends = on

    async def restart(self):
        self.channel = self._new()

    def secrets(self):
        return [TOKEN]


class TestMatrixChannel(ChannelContract):
    @pytest.fixture
    def harness(self, tmp_path):
        s, st, *_ = make(tmp_path)
        return MatrixHarness(st)


@pytest.fixture
def hx(tmp_path):
    s, st, *_ = make(tmp_path)
    return MatrixHarness(st)


async def started(hx, got=None):
    got = got if got is not None else []

    async def cb(m):
        got.append(m)
    await hx.start(cb)
    return got


@pytest.mark.asyncio
async def test_history_before_the_first_start_is_not_replayed(hx):
    hx.server.add(HUMAN, "an old message from before Pip joined")
    got = await started(hx)
    assert got == []
    assert await hx.inbound(HUMAN, "a new one")
    assert [m.text for m in got] == ["a new one"]
    await hx.stop()


@pytest.mark.asyncio
async def test_a_postcard_is_a_top_level_message_and_a_reply_is_a_threaded_one(hx):
    await started(hx)
    res = await hx.channel.send(Outbound("The clock ticks!", "postcard"), None)
    first = hx.server.sent[0]
    assert res.delivered and res.conversation == first["id"] and "m.relates_to" not in first["body"]
    assert first["body"]["msgtype"] == "m.text" and first["body"]["body"] == "The clock ticks!"
    assert await hx.inbound(HUMAN, "On my way", conversation=res.conversation)
    await hx.channel.send(Outbound("Wonderful", "reply"), res.conversation)
    rel = hx.server.sent[1]["body"]["m.relates_to"]
    assert rel["rel_type"] == "m.thread" and rel["event_id"] == res.conversation
    assert rel["m.in_reply_to"]["event_id"] == hx.server.events[1]["event_id"]      # answers the latest message in the thread
    await hx.stop()


@pytest.mark.asyncio
async def test_a_plain_reply_to_a_postcard_and_a_top_level_message_are_conversations(hx):
    got = await started(hx)
    res = await hx.channel.send(Outbound("hello", "postcard"), None)
    hx.server.add(HUMAN, "plain reply", reply_to=res.conversation)
    hx.server.add(HUMAN, "unrelated top-level")
    await asyncio.sleep(0.15)
    assert got[0].conversation == res.conversation                                  # a client that replies without threads
    assert got[1].conversation == got[1].message_id != res.conversation              # a new conversation of its own
    await hx.stop()


@pytest.mark.asyncio
async def test_own_events_images_notices_and_other_rooms_are_ignored(hx):
    got = await started(hx)
    await hx.channel.send(Outbound("my own words", "postcard"), None)                # comes back through sync as the bot's event
    hx.server.add(HUMAN, "a notice", msgtype="m.notice")
    hx.server.add(HUMAN, "photo.png", msgtype="m.image")
    hx.server.add(HUMAN, "elsewhere", room="!other:test")
    await asyncio.sleep(0.15)
    assert got == []
    await hx.stop()


@pytest.mark.asyncio
async def test_other_invites_are_declined_and_this_rooms_is_joined(hx):
    await started(hx)
    hx.server.invites = ["!stranger-room:test", ROOM]
    hx.server.add(HUMAN, "poke the sync")
    await asyncio.sleep(0.2)
    assert any("!stranger-room:test/leave" in p for p in hx.server.left)
    assert any("!room:test/join" in p for p in hx.server.joined) and not any("!room:test/leave" in p for p in hx.server.left)
    await hx.stop()


@pytest.mark.asyncio
async def test_sync_errors_back_off_and_recover_without_losing_messages(hx, monkeypatch):
    monkeypatch.setattr(M, "BACKOFF_START", 0.01)
    got = await started(hx)
    hx.server.fail_syncs = 2
    assert await hx.inbound(HUMAN, "after the outage")
    assert [m.text for m in got] == ["after the outage"]
    await hx.stop()


@pytest.mark.asyncio
async def test_typing_and_receipts_use_the_right_endpoints(hx):
    await started(hx)
    await hx.channel.typing("$root")
    await hx.channel.read("$root", "$msg1")
    assert hx.server.typing == [{"typing": True, "timeout": 20000}]
    path, body = hx.server.receipts[0]
    assert path.endswith("/receipt/m.read/$msg1") and body == {"thread_id": "$root"}
    assert any(p.endswith("/typing/@pip:test") for _, p in hx.server.requests)
    await hx.stop()


@pytest.mark.asyncio
async def test_images_are_uploaded_and_sent_in_the_thread_and_a_failed_upload_keeps_the_words(hx):
    await started(hx)
    res = await hx.channel.send(Outbound("Look what I made", "postcard", images=[Image(b"\x89PNGdata", "image/png", "clock.png", "the clock")]), None)
    assert res.delivered and not res.error and hx.server.uploads == [("clock.png", "image/png", 8)]
    img = hx.server.sent[1]["body"]
    assert img["msgtype"] == "m.image" and img["url"] == "mxc://test/1" and img["body"] == "the clock"
    assert img["m.relates_to"]["event_id"] == res.conversation and img["info"] == {"mimetype": "image/png", "size": 8}
    hx.server.fail_uploads = True
    res2 = await hx.channel.send(Outbound("And another", "reply", images=[Image(b"x")]), res.conversation)
    assert res2.delivered and "picture not sent" in res2.error                        # the text still went
    await hx.stop()


@pytest.mark.asyncio
async def test_a_wrong_token_is_reported_not_raised(tmp_path):
    s, st, *_ = make(tmp_path)
    server = FakeHomeserver()
    ch = MatrixChannel(Settings(matrix_homeserver="https://hs.test", matrix_user_id=BOT, matrix_access_token="nope",
                                matrix_room_id=ROOM, matrix_allowed={HUMAN: "Morgan"}), ChannelStore(st, "matrix"), client=server.client())
    res = await ch.send(Outbound("hi", "postcard"), None)
    assert res.delivered is False and "401" in res.error and "M_UNKNOWN_TOKEN" in res.error


@pytest.mark.asyncio
async def test_an_unconfigured_channel_fails_clearly_and_does_not_break_pip(tmp_path):
    s, st, *_ = make(tmp_path)
    ch = MatrixChannel(Settings(), ChannelStore(st, "matrix"))
    assert ch.configured is False and "token" not in repr(ch).lower().replace("access", "")
    res = await ch.send(Outbound("hi", "postcard"), None)
    assert res.delivered is False and "not configured" in res.error
    with pytest.raises(ValueError, match="needs MATRIX_HOMESERVER"):
        await ch.start(lambda m: None)


def test_matrix_people_are_parsed_from_the_environment_string():
    assert _parse_people("@morgan:ex.org=Morgan, @jade:ex.org") == {"@morgan:ex.org": "Morgan", "@jade:ex.org": "Jade"}
    assert _parse_people("") == {}


@pytest.mark.asyncio
async def test_end_to_end_through_the_core(tmp_path):
    s, st, gm, agent = make(tmp_path)
    daytime(s)  # postcards are never sent at night
    s.outreach = "on"
    hs = FakeHomeserver()
    ch = MatrixChannel(settings(), ChannelStore(st, "matrix"), client=hs.client())
    agent.outreach = Outreach(s, st, [ch], receive=agent.receive)
    agent.ctx.outreach = agent.outreach
    from app import tools as T
    agent.tools.update({n: T.REGISTRY[n] for n in ("say", "send_postcard")})
    await agent.outreach.start()
    root = hs.add(HUMAN, "how is the clock?")
    await asyncio.sleep(0.15)
    (m,) = st.pending_inbox()
    assert (m["source"], m["conversation"], m["external_id"], m["sender"]) == ("matrix", root, root, "Morgan")
    assert hs.receipts and hs.receipts[0][1] == {"thread_id": root}
    agent.ctx.visitor_ids = [m["id"]]
    await call(agent, "say", text="It ticks now!")
    assert hs.sent[-1]["thread"] == root and hs.sent[-1]["body"]["body"] == "It ticks now!"
    ok = await call(agent, "send_postcard", text="I finished the escapement.")
    assert "on its way" in ok.text and "m.relates_to" not in hs.sent[-1]["body"]
    await agent.outreach.stop()
