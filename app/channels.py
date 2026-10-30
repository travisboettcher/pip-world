"""Channels: how Pip talks to the world outside (see DESIGN-outreach.md).

A channel is a plug-in with a small, fixed set of semantics - receive messages from allowed people, send into a
conversation (a thread) or start a new one, optionally show typing and images - so Matrix, Telegram, a webhook or anything
else can be swapped in without touching Pip, the tool, the limits or the UI. The core (outreach.py) owns policy; a channel
owns transport and authorization (it only reports messages from senders it allows).
"""
import asyncio
from dataclasses import dataclass, field
from typing import Awaitable, Callable, Protocol

MESSAGE_KINDS = ("reply", "postcard")


@dataclass
class Inbound:
    sender_id: str
    sender_name: str
    text: str
    conversation: str      # opaque thread reference; the channel gives it back on send
    ts: float
    message_id: str        # unique within the channel (used to ignore replays)


@dataclass
class Image:
    data: bytes
    mime: str = "image/png"
    name: str = "picture.png"
    caption: str = ""


@dataclass
class Outbound:
    text: str
    kind: str = "postcard"             # 'reply' (to a message) or 'postcard' (unprompted)
    images: list = field(default_factory=list)   # only used if the channel declares 'images'


@dataclass
class SendResult:
    delivered: bool
    error: str = ""
    conversation: str = ""             # the thread the message landed in (a new postcard's root)


OnMessage = Callable[[Inbound], Awaitable[None]]


class ChannelStore:
    """A little persistent key-value space per channel (a sync token, an offset), kept in the state database."""

    def __init__(self, state, name: str):
        self._state, self._prefix = state, f"channel:{name}:"

    def get(self, key: str, default: str | None = None) -> str | None:
        v = self._state.meta(self._prefix + key)
        return default if v is None else v

    def set(self, key: str, value) -> None:
        self._state.set_meta(**{self._prefix + key: value})


class Channel(Protocol):
    name: str
    capabilities: frozenset            # {'receive', 'threads', 'typing', 'images', 'receipts'}: the core uses only what is declared

    async def start(self, on_message: OnMessage) -> None: ...   # begin receiving; a no-op if send-only
    async def stop(self) -> None: ...
    async def send(self, out: Outbound, conversation: str | None = None) -> SendResult: ...
    async def typing(self, conversation: str) -> None: ...      # optional ('typing')
    async def read(self, conversation: str, message_id: str) -> None: ...  # optional ('receipts')


# --- registry: channels are chosen by name in OUTREACH_CHANNELS ----------------------------------
Factory = Callable[..., "Channel"]
CHANNELS: dict[str, Factory] = {}


def register(name: str):
    def deco(factory: Factory) -> Factory:
        CHANNELS[name] = factory
        return factory
    return deco


def build_channels(settings, state) -> list:
    out = []
    for name in settings.outreach_channels:
        if name not in CHANNELS:
            raise ValueError(f"unknown channel {name!r}; options: {sorted(CHANNELS)}")
        out.append(CHANNELS[name](settings, ChannelStore(state, name)))
    return out


# --- a scriptable in-memory channel for tests and dry runs ------------------------------------------
class FakeChannel:
    """Everything stays in memory: `inject` plays an incoming message, `sent` is what Pip sent. Like FakeBackend,
    it exists so the whole outreach path can be tested with no network."""

    name = "fake"

    def __init__(self, allowed: dict[str, str] | None = None, store: ChannelStore | None = None,
                 capabilities=("receive", "threads", "typing", "receipts")):
        self.allowed = allowed if allowed is not None else {"u1": "Morgan"}
        self.store = store
        self.capabilities = frozenset(capabilities)
        self.sent: list[tuple[Outbound, str, str]] = []     # (message, conversation it went to, result conversation)
        self.typing_calls: list[str] = []
        self.read_calls: list[tuple[str, str]] = []
        self.fail = False
        self._on_message: OnMessage | None = None
        self._n = 0
        self._memory: list[str] = []
        self.started = False

    async def start(self, on_message: OnMessage) -> None:
        self._on_message, self.started = on_message, True

    async def stop(self) -> None:
        self._on_message, self.started = None, False

    def _recent(self) -> list[str]:
        return (self.store.get("recent", "") or "").split(",") if self.store else self._memory

    def _remember(self, mid: str) -> None:
        recent = (self._recent() + [mid])[-30:]
        if self.store:
            self.store.set("recent", ",".join(recent))
        else:
            self._memory = recent

    async def inject(self, sender_id: str, text: str, conversation: str | None = None, message_id: str | None = None) -> bool:
        """Play an incoming message. Returns whether it reached the core: unauthorised senders are dropped, and a message id
        this channel has already delivered (even before a restart) is not delivered again, as a real transport's offset would ensure."""
        if sender_id not in self.allowed or not self._on_message:
            return False
        self._n += 1
        mid = message_id or f"{id(self)}-{self._n}"
        if mid in self._recent():
            return False
        self._remember(mid)
        await self._on_message(Inbound(sender_id, self.allowed[sender_id], text, conversation or f"t-{mid}", 0.0, mid))
        return True

    async def send(self, out: Outbound, conversation: str | None = None) -> SendResult:
        if self.fail:
            return SendResult(False, error="fake channel is set to fail")
        landed = conversation or f"t-out{len(self.sent) + 1}"
        self.sent.append((out, conversation or "", landed))
        return SendResult(True, conversation=landed)

    async def typing(self, conversation: str) -> None:
        self.typing_calls.append(conversation)

    async def read(self, conversation: str, message_id: str) -> None:
        self.read_calls.append((conversation, message_id))

    def __repr__(self) -> str:
        return f"FakeChannel(allowed={sorted(self.allowed)})"


@register("fake")
def _make_fake(settings, store):
    return FakeChannel(store=store)


def with_timeout(coro, seconds: float):
    return asyncio.wait_for(coro, timeout=seconds)
