import pytest

from app.channels import CHANNELS, ChannelStore, FakeChannel, build_channels
from app.config import Settings
from tests.channel_contract import ChannelContract
from tests.test_projects import make


class FakeHarness:
    sender = ("u1", "Morgan")
    stranger = "x9"

    def __init__(self, st):
        self.st = st
        self.channel = self._new()

    def _new(self):
        return FakeChannel(store=ChannelStore(self.st, "fake"), allowed={"u1": "Morgan"})

    async def start(self, on_message):
        await self.channel.start(on_message)

    async def stop(self):
        await self.channel.stop()

    async def inbound(self, sender_id, text, conversation=None, message_id=None):
        return await self.channel.inject(sender_id, text, conversation, message_id)

    def sent(self):
        return [(o.text, c, landed) for o, c, landed in self.channel.sent]

    def fail_sends(self, on):
        self.channel.fail = on

    async def restart(self):
        self.channel = self._new()

    def secrets(self):
        return ["tok-123"]


class TestFakeChannel(ChannelContract):
    @pytest.fixture
    def harness(self, tmp_path):
        s, st, *_ = make(tmp_path)
        return FakeHarness(st)


def test_the_registry_builds_channels_by_name_and_rejects_unknown_ones(tmp_path):
    s, st, *_ = make(tmp_path)
    s.outreach_channels = ["fake"]
    (ch,) = build_channels(s, st)
    assert ch.name == "fake" and "fake" in CHANNELS
    s.outreach_channels = ["carrier-pigeon"]
    with pytest.raises(ValueError, match="unknown channel 'carrier-pigeon'"):
        build_channels(s, st)


def test_the_channel_store_persists_per_channel(tmp_path):
    s, st, *_ = make(tmp_path)
    a, b = ChannelStore(st, "matrix"), ChannelStore(st, "telegram")
    a.set("since", "s123")
    assert a.get("since") == "s123" and b.get("since") is None and b.get("since", "x") == "x"
