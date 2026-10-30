# Design: reaching out (postcards to the outside world)

Status: **design only, not built.** Roadmap item "Pip can reach out" (Social). Revised 2026-10-30: the owner wants it to be an
extension of chat, two-way from a phone in a native app, so the primary channel is a **Telegram bot** (below); the one-way
webhook is kept as a second backend.

## Why
Pip can only talk when someone talks to it, or by writing letters to a neighbor it invented. It has things it would
like to say to a real person: a project finished, a specific thing it is missing, something it found out. A push message
to the owner's phone is the smallest real-world channel, and the one most likely to matter.

Principles: **rare and meaningful** (a postcard, not a notification stream), **the owner stays in control** (a kill
switch, hard caps, everything logged), **no new secrets in Pip's reach**, and the model gets **no way to choose a
destination or send anything but short plain text**.

## Channel: Telegram, two-way (recommended)
A Telegram bot gives a native phone app, two-way chat, notifications, and a simple HTTPS API. It fits this setup because Pip's
UI is internal-only: the bot can be driven by **long polling** (`getUpdates`), where Pip's container makes outbound HTTPS calls to
`api.telegram.org` and nothing is exposed (no webhook, no public endpoint, no port).

| Option | Verdict |
|---|---|
| **Telegram bot** | native apps, trivial API, long polling works behind NAT, typing indicator, free. Bot chats are not end-to-end encrypted (messages pass through Telegram's servers): fine for Pip, not for secrets |
| Signal | private, but needs `signal-cli` and a spare number; fragile for bots |
| Matrix (self-hosted) | fully yours, but means running Synapse/Conduit and a client; much more to maintain |
| Home Assistant / ntfy | good for one-way push; replies are awkward (notification actions only) |
| Slack / Discord | workable, but heavier than a bot chat on a phone |

### How Pip gets your replies
A small bridge runs inside the agent-world container as a background task:
1. **Long-poll** `getUpdates` (30 s timeout) with an offset kept in the database, so a restart never replays old messages.
2. For each message from an **allowed chat** (`TELEGRAM_ALLOWED`, your numeric user id; anyone else is ignored), do exactly what
   `POST /inbox` does today: add an inbox item (sender "Morgan", source `telegram`), log the `inbox` event (so it appears in the web
   chat as one of your bubbles, labelled as Telegram), and wake Pip as a visitor does. One shared function serves both paths.
3. **Pip's answer** is its normal `say` reply to that message. The bridge watches for `say` events addressed to inbox ids that came
   from Telegram and sends that text to the same chat. While Pip is thinking, the bridge shows "typing…" (`sendChatAction`), the same
   cue as the web UI's "Pip is thinking".
So it is one conversation with two clients: whatever you type in the web UI or in Telegram reaches Pip the same way, and a reply goes
back to the place the message came from (and always shows in the web feed).

**Pip starting a conversation** is `send_postcard` (below), delivered to the first allowed chat. Your reply to it arrives as a normal
message, so a postcard can turn into a back-and-forth.

### Setup (once, by the owner)
1. In Telegram, talk to **@BotFather**: `/newbot`, pick a name; it gives a **token**.
2. Put the token in `agent_world/.env` (`TELEGRAM_BOT_TOKEN`, gitignored); start Pip with `OUTREACH=log`.
3. Message the bot from your phone. It ignores you but records the sender, and `pipchat telegram` shows "unknown sender 123456789 (name)".
4. Put that id in `TELEGRAM_ALLOWED=123456789:Morgan` and switch on. (Several `id:Name` pairs are allowed; unprompted postcards go to the first.)

## Channel: webhook (one-way, optional)
For Home Assistant or n8n: a POST of `{id, text, from, ts, context}` to a URL (`OUTREACH_WEBHOOK_URL`, optional bearer token). Same limits,
same tool; no replies except through `/inbox`.

## Pluggable channels
Telegram is the first channel, not a built-in. The core talks to a small **`Channel`** interface (same plug-in style as the LLM backend and the
pacing policy: a registry, chosen by env, one file per channel), so Matrix, Signal, Slack or a webhook can replace or sit beside it later with the
same send/receive semantics and no change to Pip, the tool, the limits or the UI.

```python
@dataclass
class Inbound:    sender_id: str; sender_name: str; text: str; conversation: str; ts: float; message_id: str  # conversation is opaque
@dataclass
class Outbound:   text: str; kind: str            # 'reply' (to a message) or 'postcard' (unprompted)
@dataclass
class SendResult: delivered: bool; error: str = ""

class Channel(Protocol):
    name: str
    capabilities: frozenset[str]                  # e.g. {'receive', 'typing'}; the core only uses what a channel declares
    async def start(self, on_message: Callable[[Inbound], Awaitable[None]]) -> None   # begin receiving (poll/socket/subscribe); no-op if send-only
    async def stop(self) -> None
    async def send(self, out: Outbound, conversation: str | None = None) -> SendResult  # conversation=None -> the channel's primary recipient
    async def typing(self, conversation: str) -> None                                   # optional; only if 'typing' declared
```
- **Authorization lives in the channel.** A channel only calls `on_message` for senders it considers allowed (Telegram: the id allow-list), and
  fills `sender_name` from its own config. The core treats whatever arrives as a visitor message, like `POST /inbox`.
- **Routing is generic.** The inbox row and the `inbox` event record `source` (the channel name) and `conversation` (opaque). Pip's `say` reply to
  that message is sent back through the same channel and conversation; unprompted postcards go to the **primary** channel's primary recipient. Several
  channels can run at once (`OUTREACH_CHANNELS=telegram,webhook`; the first is primary).
- **The core owns policy** (modes, per-day and gap limits, quiet hours, repeat and URL checks, length caps, events, firsts, day counts), so every
  channel gets the same safety for free and none can bypass it.
- **Contract tests, one suite for every channel.** A `FakeChannel` (in-memory, scriptable, like `FakeBackend`) ships with the code and drives the
  core tests with no network. A reusable contract test runs against any implementation using a fake transport: inbound is delivered once and in
  order; unauthorised senders are dropped; `send` reports failure honestly; `typing` only when declared; a restart doesn't replay; secrets never
  appear in `repr` or events. A new channel is done when it passes the contract.
- **Built-ins:** `telegram` (two-way, long polling), `webhook` (send-only), `fake`/`log` (tests and dry runs). Adding another is one file plus a
  registry entry.

## The tool: `send_postcard(text)` (anywhere, awake only)
- **What Pip sees:** "Send a short postcard to a friend outside. Rarely; for something worth telling: a thing you finished, a specific thing you
  need, something you found out. Plain text, at most 240 characters."
- **The recipient is fixed** (the first allowed chat). No `to`. Text only: no URLs (refused), no attachments, control characters stripped,
  sent without Markdown so the words can't format themselves.
- **Rate limits** (engine, not prompt) apply to *unprompted* postcards only: `OUTREACH_PER_DAY` (default 2), `OUTREACH_MIN_GAP_HOURS` (3),
  none during quiet hours (the night window), nothing too like one of the last five. Replies to your messages are not limited (you started
  it), only length-capped, and Pip can't send a reply to a message that doesn't exist.
- **Pip sees its allowance** only when it can send: "You can send 1 more postcard today (next after 2:30 pm)." Otherwise the tool isn't offered.
- **Honest delivery:** a failure is reported to Pip ("it couldn't be sent") and not retried; failures are capped per day.
- **Modes:** `OUTREACH=off | log | on`. `log` records what Pip would send (feed, `pipchat outreach`, `GET /outreach`) and delivers nothing, for a dry
  run; `off` removes the tool and stops the bridge. In `log` the bridge still *receives* nothing, so enable `on` only after you've checked.

## Records and visibility
Events `outreach` `{id, text, delivered, error?, channel, mode}` and `inbox` events labelled `source: telegram`. They appear in the feed and
chat ("via Telegram"), `recall`, the nightly reflection, the day counts (postcards sent, messages received), and a firsts facet ("the first
time you sent something out into the world"; "the first time you heard from outside"). `GET /outreach`, `pipchat outreach`, `pipchat telegram`.

## Safety
- The destination is fixed in `.env` and the allowed ids are an allow-list; strangers who find the bot are ignored.
- The token is never sent to the model, never logged, never in events. Incoming text is untrusted like any visitor's.
- A prompt-injected page or visitor message can at most make Pip say something short to you, within the cap and logged.
- Outbound text is plain, short, link-free; inbound is capped (2000 chars like the web UI).
- Telegram sees the conversation (cloud chat). That is the trade for a native, two-way app with no exposed port.

## Persona
One short paragraph: you have a way to send a short postcard to a friend outside; use it rarely, for what is worth telling. Not for
status updates, not to ask for something you already asked for.

## Safety
- The destination is fixed in `.env`; the model chooses only the words. A prompt-injected page or visitor message can at most make Pip
  say something short to the owner, within the daily cap and logged.
- The secret (webhook URL/token) is never sent to the model, never logged, never in events.
- Failure modes are quiet: caps, `off`, and `log` all stop messages without code changes.

## What the receiving side needs (documented, not code)
A Home Assistant automation: trigger `webhook` (`webhook_id` a long random string, local only), action
`notify.mobile_app_pixel_11_pro` with `message: "{{ trigger.json.text }}"`, `title: "Pip"`, and `data.url` pointing at
`https://agent-world.internal.example.io/ui/` so tapping opens the UI. The same payload works for an n8n Webhook node.

## Build order
1. Shared `deliver_visitor_message` (extracted from `POST /inbox`; `inbox` gains `source` and `conversation`), the `Channel` interface and
   registry, `FakeChannel` and the contract test suite, then the Telegram channel (long poll, allow-list, offset, typing) and the webhook and log
   channels, each passing the contract (Telegram against a fake Telegram API).
2. `send_postcard`, limits and quiet hours, events, `GET /outreach`, `pipchat outreach`/`telegram`, feed and chat labels, firsts, day counts.
3. Persona paragraph, the prompt allowance line, README setup steps.
4. (Later) photos of what Pip makes or draws, once the art tools exist; `reply_to` marking; other backends.

## Open questions
1. Telegram is OK with you (cloud chat, not end-to-end encrypted), or do you want to look at self-hosted Matrix instead?
2. Should Pip's reply to a message you typed in the **web UI** also go to Telegram, or only replies to Telegram messages (recommended)?
3. Name: `send_postcard` or something plainer?
4. Limits: 2 unprompted a day, 3 hours apart, none at night. Too tight, or too loose?
5. Start in `log` mode first (recommended), then `on`?
6. Anything the `Channel` interface above is missing for a channel you'd want later (attachments/photos, groups, message edits)? Photos are the
   likely first extension, once Pip can draw (a `send_image` capability).
