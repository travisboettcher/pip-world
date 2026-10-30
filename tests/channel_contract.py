"""The contract every Channel implementation must satisfy (DESIGN-outreach.md).

A channel's test module subclasses ChannelContract and provides a `harness` fixture: an adapter over that channel's
(fake) transport. A channel is finished when it passes this suite.

Harness interface:
  channel                      the current Channel instance
  sender: (id, name)           an allowed sender;  stranger: id of one that is not allowed
  async start(on_message) / stop()
  async inbound(sender_id, text, conversation=None, message_id=None) -> bool   the transport delivers a message; False if the channel dropped it
  sent() -> [(text, conversation it was sent to, conversation it landed in)]
  fail_sends(on)               make the transport fail
  async restart()              a new instance over the same persisted store (a process restart)
  secrets() -> [str]           strings that must never show up in repr(channel)
"""
import pytest

from app.channels import Outbound


class ChannelContract:
    @pytest.fixture
    def got(self):
        return []

    @pytest.fixture
    def collect(self, got):
        async def on_message(m):
            got.append(m)
        return on_message

    @pytest.mark.asyncio
    async def test_inbound_arrives_once_in_order_with_the_senders_name(self, harness, collect, got):
        await harness.start(collect)
        sid, name = harness.sender
        assert await harness.inbound(sid, "first") and await harness.inbound(sid, "second")
        assert [m.text for m in got] == ["first", "second"]
        assert got[0].sender_name == name and got[0].conversation and got[0].message_id
        assert len({m.message_id for m in got}) == 2

    @pytest.mark.asyncio
    async def test_unauthorised_senders_are_dropped(self, harness, collect, got):
        await harness.start(collect)
        assert await harness.inbound(harness.stranger, "let me in") is False
        assert got == []

    @pytest.mark.asyncio
    async def test_a_conversation_is_kept_and_a_new_message_can_open_one(self, harness, collect, got):
        await harness.start(collect)
        sid, _ = harness.sender
        res = await harness.channel.send(Outbound("hello there", "postcard"), None)
        assert res.delivered and (res.conversation or "threads" not in harness.channel.capabilities)
        if "threads" in harness.channel.capabilities:
            await harness.inbound(sid, "hi back", conversation=res.conversation)
            assert got[-1].conversation == res.conversation                      # an answer in the thread stays in it
            reply = await harness.channel.send(Outbound("glad you wrote", "reply"), got[-1].conversation)
            assert reply.delivered and harness.sent()[-1][1] == res.conversation  # and Pip's reply goes into that thread
            await harness.inbound(sid, "something new")                           # a fresh top-level message...
            assert got[-1].conversation and got[-1].conversation != res.conversation   # ...opens its own conversation

    @pytest.mark.asyncio
    async def test_send_reports_failure_honestly(self, harness, collect):
        await harness.start(collect)
        harness.fail_sends(True)
        res = await harness.channel.send(Outbound("anyone?", "postcard"), None)
        assert res.delivered is False and res.error
        harness.fail_sends(False)
        assert (await harness.channel.send(Outbound("again", "postcard"), None)).delivered

    @pytest.mark.asyncio
    async def test_a_restart_does_not_replay_old_messages(self, harness, collect, got):
        await harness.start(collect)
        sid, _ = harness.sender
        assert await harness.inbound(sid, "once", message_id="dup-1")
        await harness.stop()
        await harness.restart()
        await harness.start(collect)
        assert await harness.inbound(sid, "once", message_id="dup-1") is False        # the transport re-offers it; the channel doesn't
        assert [m.text for m in got] == ["once"]

    @pytest.mark.asyncio
    async def test_start_and_stop_are_safe_to_repeat(self, harness, collect):
        await harness.start(collect)
        await harness.stop()
        await harness.stop()
        await harness.start(collect)
        await harness.stop()

    @pytest.mark.asyncio
    async def test_optional_features_exist_only_if_declared(self, harness, collect):
        caps = harness.channel.capabilities
        assert caps <= {"receive", "threads", "typing", "images", "receipts"}
        await harness.start(collect)
        if "typing" in caps:
            await harness.channel.typing("any-conversation")                          # must not raise
        if "receipts" in caps:
            await harness.channel.read("any-conversation", "m1")

    def test_secrets_never_appear_in_repr(self, harness):
        text = repr(harness.channel) + str(harness.channel)
        assert not any(s in text for s in harness.secrets())
