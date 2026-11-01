"""Outreach: Pip's way to the world outside, over a pluggable channel (see DESIGN-outreach.md).

The core owns policy; a channel (channels.py) owns transport. Pip may *start* a conversation (a postcard) a couple of
times a day, never at night, never twice alike, with short plain text and no links. It may *answer* what a person sends
back through the channel the message came in on, inside the same conversation, as often as it likes (but never
unprompted). Everything is recorded; the recipient is fixed by the channel, never chosen by the model.
"""
import asyncio
import difflib
import logging
import re
import time
from datetime import datetime

from . import commands
from . import matrix  # noqa: F401  (registers the 'matrix' channel)
from . import sleep as sleepmod
from .channels import Inbound, Outbound, build_channels
from .text import clip

log = logging.getLogger("outreach")

URL = re.compile(r"(https?://|www\.|\b[a-z0-9-]+\.(com|org|net|io|dev|app|xyz|co|me|info)\b)", re.I)
CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")
SEND_TIMEOUT = 15.0
SIMILAR = 0.6
RECENT_CHECKED = 5


def clean(text: str) -> str:
    return " ".join(CONTROL.sub("", str(text or "")).split())


def when(ts: float) -> str:
    return datetime.fromtimestamp(ts).strftime("%-I:%M %p").lower()


class Outreach:
    def __init__(self, settings, state, channels=None, receive=None):
        self.s, self.state = settings, state
        self.channels = channels if channels is not None else (build_channels(settings, state) if settings.outreach != "off" else [])
        self.receive = receive          # callable(text, sender, source, conversation, external_id) -> inbox id | None
        self.errors: dict[str, str] = {}

    # --- lifecycle --------------------------------------------------------
    @property
    def enabled(self) -> bool:
        return self.s.outreach != "off" and bool(self.channels)

    @property
    def primary(self):
        return self.channels[0] if self.channels else None

    def channel(self, name: str):
        return next((c for c in self.channels if c.name == name), None)

    async def start(self) -> None:
        if not self.enabled:
            return
        for ch in self.channels:
            if "receive" in ch.capabilities:
                try:
                    await ch.start(self._handler(ch))
                except Exception as e:  # a broken channel must not stop Pip
                    self.errors[ch.name] = f"{type(e).__name__}: {e}"
                    log.exception("channel %s failed to start", ch.name)

    async def stop(self) -> None:
        for ch in self.channels:
            try:
                await ch.stop()
            except Exception:
                log.exception("channel %s failed to stop", ch.name)

    def _handler(self, ch):
        async def on_message(m: Inbound) -> None:
            if self.s.outreach == "off" or not self.receive:
                return
            sender = clip(m.sender_name or m.sender_id, 40)
            reply = commands.answer(self.state, self.s, m.text)
            if reply is not None:       # a slash command: answered from state, never Pip's inbox
                await self._deliver(ch, Outbound(reply[:2000], "reply"), m.conversation)
                return
            iid = self.receive(str(m.text)[:2000], sender, ch.name, m.conversation, m.message_id)
            if iid and "receipts" in ch.capabilities:
                try:
                    await ch.read(m.conversation, m.message_id)
                except Exception:
                    pass
        return on_message

    # --- policy -----------------------------------------------------------
    def _day_start(self, now: float) -> float:
        return datetime.fromtimestamp(now).replace(hour=0, minute=0, second=0, microsecond=0).timestamp()

    def allowance(self, now: float | None = None) -> dict:
        """What Pip may do right now: {'now', 'remaining', 'next', 'reason'}. `next` is when it could next start a conversation."""
        now = now or time.time()
        if not self.enabled:
            return {"now": False, "remaining": 0, "next": None, "reason": "no channel"}
        day0 = self._day_start(now)
        sent = self.state.outreach_rows(50, kind="postcard", since=day0, statuses=("sent", "logged"))   # newest first
        failed = self.state.outreach_rows(50, kind="postcard", since=day0, statuses=("failed",))
        remaining = max(0, self.s.outreach_per_day - len(sent))
        tomorrow = day0 + 86400
        if len(failed) >= self.s.outreach_failures_per_day:
            return {"now": False, "remaining": remaining, "next": tomorrow, "reason": "the channel isn't working right now"}
        if not remaining:
            return {"now": False, "remaining": 0, "next": tomorrow, "reason": "you've started as many conversations as you can today"}
        if sleepmod.is_night(self.s, now):
            return {"now": False, "remaining": remaining, "next": sleepmod.next_wake(self.s, now), "reason": "it's night"}
        gap_until = sent[0]["ts"] + self.s.outreach_min_gap_hours * 3600 if sent else 0
        if now < gap_until:
            nxt = sleepmod.next_wake(self.s, gap_until) if sleepmod.is_night(self.s, gap_until) else gap_until
            return {"now": False, "remaining": remaining, "next": nxt, "reason": "it's too soon after your last one"}
        return {"now": True, "remaining": remaining, "next": None, "reason": ""}

    def can_send(self, now: float | None = None) -> bool:
        return self.allowance(now).get("now", False)

    def perception(self, now: float | None = None) -> list[str]:
        a = self.allowance(now)
        if not a.get("now"):
            return []
        n = a["remaining"]
        return [f"You can start {n} more conversation{'s' if n != 1 else ''} with a friend outside today (send_postcard); "
                "answer when they write back."]

    def check_text(self, text: str) -> tuple[str, str]:
        """(cleaned text, why it can't be sent or '')."""
        t = clean(text)
        if len(t) < 3:
            return t, "say something first"
        if len(t) > self.s.outreach_max_chars:
            return t, f"that's too long for a postcard ({len(t)} characters; at most {self.s.outreach_max_chars}) - say it shorter"
        if URL.search(t):
            return t, "postcards are plain words only: no links or web addresses"
        return t, ""

    def _too_like_recent(self, text: str) -> bool:
        from .tools import overlapping  # tools imports nothing from here; avoid a cycle at import time
        for r in self.state.outreach_rows(RECENT_CHECKED, kind="postcard", statuses=("sent", "logged")):
            if difflib.SequenceMatcher(None, text.lower(), r["text"].lower()).ratio() >= SIMILAR or overlapping(text, r["text"]):
                return True
        return False

    # --- sending ------------------------------------------------------------
    async def _deliver(self, ch, out: Outbound, conversation: str | None):
        if self.s.outreach == "log":
            return True, "", conversation or "", "logged"
        try:
            res = await asyncio.wait_for(ch.send(out, conversation), timeout=SEND_TIMEOUT)
        except Exception as e:
            return False, f"{type(e).__name__}: {e}"[:200], "", "failed"
        if not res.delivered:
            return False, res.error or "not delivered", "", "failed"
        return True, "", res.conversation or conversation or "", "sent"

    def _record(self, kind: str, ch, conversation: str, text: str, status: str, error: str = "") -> dict:
        rid = self.state.add_outreach(kind, ch.name, conversation, text, status, error)
        data = {"id": rid, "what": kind, "channel": ch.name, "conversation": conversation, "text": text, "status": status,
                "delivered": status in ("sent", "logged"), "mode": self.s.outreach}
        if error:
            data["error"] = error
        self.state.log("outreach", **data)
        return data

    async def send_postcard(self, text: str, now: float | None = None, images=()) -> tuple[bool, str]:
        """Start a conversation. Returns (ok, what Pip is told)."""
        now = now or time.time()
        if not self.enabled:
            return False, "you have no way to reach anyone outside right now"
        a = self.allowance(now)
        if not a.get("now"):
            nxt = f" Next possible after {when(a['next'])}." if a.get("next") else ""
            return False, f"not now: {a['reason']}.{nxt}"
        t, why = self.check_text(text)
        if why:
            return False, why
        if self._too_like_recent(t):
            return False, "you've already told them something like this"
        ch = self.primary
        pictures = list(images) if "images" in ch.capabilities else []
        ok, error, conv, status = await self._deliver(ch, Outbound(t, "postcard", images=pictures), None)
        self._record("postcard", ch, conv, t + (f" [with a picture: {pictures[0].caption}]" if pictures else ""), status, error)
        if not ok:
            return False, "it couldn't be sent just now, so nothing went out"
        extra = " (the picture can't travel this way, so only your words went)" if images and not pictures else ""
        if error and pictures:
            extra = f" ({error})"
        return True, "your postcard is on its way; if they write back you'll hear it in the same thread" + extra

    async def route_reply(self, text: str, inbox_ids: list[int]) -> int:
        """Pip's `say` answered these visitor messages; send it back through any channel they came in on, into the same
        conversation. Returns how many conversations it went to. Never unprompted: it needs a real message to answer."""
        if not self.enabled or not inbox_ids:
            return 0
        t = clean(text)[: self.s.outreach_reply_max_chars]
        if not t:
            return 0
        seen, sent = set(), 0
        for row in self.state.inbox_rows(list(inbox_ids)):
            ch = self.channel(row["source"])
            key = (row["source"], row["conversation"])
            if not ch or key in seen:
                continue
            seen.add(key)
            ok, error, conv, status = await self._deliver(ch, Outbound(t, "reply"), row["conversation"] or None)
            self._record("reply", ch, row["conversation"], t, status, error)
            sent += ok
        return sent

    async def typing(self, inbox_ids: list[int]) -> None:
        """Show 'typing' wherever Pip is about to answer. Best effort."""
        if not self.enabled or self.s.outreach == "log":
            return
        for row in self.state.inbox_rows(list(inbox_ids)):
            ch = self.channel(row["source"])
            if ch and "typing" in ch.capabilities and row["conversation"]:
                try:
                    await asyncio.wait_for(ch.typing(row["conversation"]), timeout=5)
                except Exception:
                    pass

    def status(self) -> list[dict]:
        return [{"name": c.name, "capabilities": sorted(c.capabilities), "primary": c is self.primary,
                 "error": self.errors.get(c.name, "")} for c in self.channels]
