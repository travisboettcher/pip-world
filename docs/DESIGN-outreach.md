# Design: reaching out (a two-way, pluggable channel; Matrix first)

Status: **steps 1 (the channel-agnostic core) and 2 (the Matrix channel, `matrix.py`) built 2026-10-30; the homeserver service is next.** Built: `channels.py` (the `Channel`
interface, `ChannelStore`, registry, `FakeChannel`), `outreach.py` (policy, `send_postcard`, reply routing, typing), a shared `Agent.receive`
(also used by `POST /inbox`), `inbox` source/conversation/external id, `GET /outreach`, `pipchat outreach`, events, firsts, day counts, and the
contract test suite (`tests/channel_contract.py`). With no `OUTREACH_CHANNELS` configured the tool is not offered and nothing changes. Event field
note: outreach events use `what` ('postcard' | 'reply') because `kind` is the event kind. Roadmap item "Pip can reach out" (Social). Revised 2026-10-30 after the owner asked to look at
self-hosted Matrix and wants the channel pluggable. Telegram stays a documented alternative; the same interface fits both.

## Why
Pip can only talk when someone talks to it, or in letters to a neighbor it invented. It has things it would like to tell a real
person: a project finished, a specific thing it is missing, something it found out. And the owner wants to answer from a phone, in a
native app, as an extension of the chat. So: a real two-way channel, owned by the owner, that Pip can start a conversation on.

Principles: **rare and meaningful** unprompted messages; **the owner stays in control** (a kill switch, hard caps, everything logged);
**no secrets in the model's reach**; the model chooses only **short plain words** (and, later, a picture), never a destination.

## The shape: a conversation is a thread
The owner's model is: Pip may start **2 new threads a day**, and within a thread it may reply to what the human says (but doesn't have to).
- **Unprompted** = a new thread (a top-level message). Capped: 2 a day, a minimum gap, none in quiet hours (the night window).
- **A reply** = Pip's normal `say` answer to a message the human sent, delivered inside that thread. Not capped (the human started or
  continued it). Pip can't post follow-ups into a thread nobody has replied to, so a thread ends when the human stops.
- A human message that is **not** in a thread starts a new one (Pip's answer goes in a thread under it).
Matrix has real threads; Telegram has reply chains; a webhook has none (every message is its own thread). The core only uses the abstract
idea (`conversation`).

## Pluggable channels
The core talks to a small **`Channel`** interface (the same plug-in style as the LLM backend and pacing policy: a registry, chosen by env,
one file per channel). Matrix is the first real channel; Telegram, Signal, Slack or a webhook can sit beside or replace it later with the same
send/receive semantics and no change to Pip, the tool, the policy or the UI.

```python
@dataclass
class Inbound:   sender_id: str; sender_name: str; text: str; conversation: str; ts: float; message_id: str  # conversation: opaque thread ref
@dataclass
class Outbound:  text: str; kind: str; images: list[Image] = ()        # kind: 'reply' | 'postcard'; images only if the channel declares 'images'
@dataclass
class SendResult: delivered: bool; error: str = ""; conversation: str = ""     # the thread the message landed in (a new postcard's root)

class Channel(Protocol):
    name: str
    capabilities: frozenset[str]                     # {'receive', 'threads', 'typing', 'images'}: the core uses only what is declared
    async def start(self, on_message) -> None         # begin receiving (sync/poll/socket); a no-op if send-only
    async def stop(self) -> None
    async def send(self, out: Outbound, conversation: str | None = None) -> SendResult   # None -> a new thread to the primary recipient
    async def typing(self, conversation: str) -> None # optional
```
- **Authorization lives in the channel.** It only calls `on_message` for senders it allows and fills `sender_name` from its own config; the core
  treats the result like any visitor message (same function as `POST /inbox`).
- **Routing is generic.** The `inbox` row and event record `source` (channel name) and `conversation` (opaque). A `say` reply to that message
  goes back through the same channel into the same conversation; a postcard goes to the **primary** channel (the first in
  `OUTREACH_CHANNELS`, several can run at once).
- **The core owns policy**: limits, quiet hours, repeat/URL/length checks, events, firsts, day counts. Every channel gets the same safety.
- **Contract tests:** a `FakeChannel` (in-memory, scriptable, like `FakeBackend`) ships with the code, and one reusable contract suite runs against any
  implementation with a fake transport: inbound delivered once and in order; unauthorised senders dropped; `send` reports failure honestly; replies stay in
  their conversation; no replay after a restart; `typing` only if declared; secrets never in `repr` or events. A channel is done when it passes.
- **Photos:** the interface carries `images` and a capability flag, and the Matrix channel implements it (upload + `m.image`) so Pip's drawings
  can arrive later. Nothing in the core needs changing when the art tools exist. (Inbound photos are ignored for now.)

## Matrix, self-hosted
### What the research says (sources are community posts and docs, partly unverified; confirm at build time)
- **Homeserver.** Synapse is the full-featured reference but sits at roughly 1-2 GB RAM. The lightweight Rust line (Conduit, now continued as
  **Tuwunel** and **Continuwuity**) is a single small container with an embedded database and a few hundred MB at most; the landscape moved
  quickly in 2025-26 (Conduwuit was discontinued), so pick whichever has a current release and Docker image when we build.
  Dendrite is in maintenance mode. For one bot and one human, a lightweight homeserver is plenty.
- **Bot library.** The Python options are awkward right now: `matrix-nio`'s upstream is quiet, its E2EE depends on libolm (deprecated by
  Matrix) and wheels lag Python versions; the nio-based bot framework `nio-bot` is archived. Rather than depend on that, speak the **Client-Server API
  directly over `httpx`** (login, `/sync` long-poll, send event, threads, typing, read receipts, media upload). That is a few hundred lines, no native
  dependency, and fits the plug-in interface.
- **End-to-end encryption.** The simplest robust choice is an **unencrypted room on your own server** (TLS in transit; messages at rest only on
  your homeserver). E2EE would pull in olm/vodozemac and device verification for a bot, which is real maintenance for little gain on a private
  homelab. It can be revisited. (This is the main trade against Telegram, where Telegram sees everything.)
- **Phone and push.** Element X (Android) syncs from your homeserver and gets push through a push gateway; the homeserver makes *outbound* calls to the
  gateway, so no inbound port for push. Unverified here, and worth confirming: Element X fetches the message body from the homeserver on notification,
  so the **phone must be able to reach the homeserver**. UnifiedPush (ntfy as distributor) is an FCM-free alternative.

### Reachability: the one real decision
The phone needs the homeserver whenever it is away from home, but everything else here is internal-only (an IP allowlist, a VPN for remote access).
| Option | For | Against |
|---|---|---|
| **Public hostname** (`matrix.example.org` via a reverse proxy with Let's Encrypt), federation off, registration off | works from anywhere with the native app | a login surface on the internet (mitigate: no federation, no registration, strong passwords, rate limits, keep it updated) |
| **Internal only + an always-on VPN on the phone** | nothing exposed | VPN must be on to chat; any lapse = no messages |

The recommendation is a public hostname with federation and registration disabled and the accounts created once by script, because "chat from the phone
anywhere" is the point; the internal-only route stays available (same code).

### Deployment (new `matrix/` service, hll-defined like the others)
A lightweight homeserver container on the same Docker network as the reverse proxy, one volume (included in the backups), env for `server_name`, `allow_federation=false`,
registration closed (a one-time registration token to create the two accounts, then removed). Traefik routes `/_matrix` (and `/.well-known/matrix/client`
if the server name differs from the host). Optional: Element Web at its own internal hostname for chatting from a desktop browser. A `matrix/bootstrap`
script creates `@pip` (the bot) and your account and an invite-only, unencrypted room; Pip's `.env` gets the bot's access token.

### The Matrix channel
- **Identity and room:** the bot `@pip:...` and the owner in one private, invite-only, unencrypted room. The channel listens to that room only and
  declines every other invite; `on_message` fires only for events from allowed user ids.
- **Threads:** `conversation` = the thread root's event id. A postcard is a top-level message (its event id becomes the conversation); a reply is sent
  with `m.relates_to: {rel_type: m.thread, event_id: root}` (plus the in-reply-to fallback for clients that don't render threads). A human message in a thread
  keeps that conversation; a top-level human message starts one.
- **Receiving:** `/sync` long-poll with a stored `since` token (restart-safe, no replay), a filter limited to the room and to message events, backoff on errors.
- **Typing and receipts:** `PUT /rooms/{id}/typing/{user}` while Pip is thinking (the same cue as the web UI) and a read receipt when a message reaches Pip.
- **Images:** `POST /_matrix/media/v3/upload` then an `m.image` event, when Pip has something to show.

## Web UI
The web chat stays what it is: Pip's own interface, backed by the same inbox. It is conceptually just another channel, so both can run side by side, with the
event log as the one history. Matrix is deliberately **not** embedded in our page (a Matrix client in the browser means login, tokens and a heavy SDK). If a
browser Matrix view is wanted, host **Element Web** next to it. A reply to something typed in the web UI is not sent to Matrix (they stay separate); messages that arrive
through Matrix do appear in the web chat as yours, labelled with their source.

## The tool: `send_postcard(text)` (anywhere, awake only)
- **What Pip sees:** "Start a conversation with a friend outside (a short postcard). Rarely; for something worth telling: a thing you finished, a specific thing you
  need, something you found out. Plain text, at most 240 characters."
- **Fixed recipient, no `to`.** Text only: no URLs (refused), control characters stripped, sent as plain text so words can't format themselves. A picture is a later
  `images` argument, subject to the same limits.
- **Limits (engine, not prompt), for unprompted postcards only:** `OUTREACH_PER_DAY` = 2 new threads (local day), `OUTREACH_MIN_GAP_HOURS` = 3, none in quiet hours,
  nothing too like one of the last five. Replies are not limited; they can only answer a message that exists, are length-capped, and Pip may stay silent.
- **Pip sees its allowance** only when it can send: "You can start 1 more conversation today (next after 2:30 pm)." Otherwise the tool isn't offered.
- **Honest delivery:** a failure is reported to Pip and not retried; failures are capped per day so a dead server isn't hammered.
- **Modes:** `OUTREACH=off | on` (live by default, as decided); `log` remains available for a dry run. `off` removes the tool and stops the channel.

## Records and visibility
Events `outreach` `{id, text, delivered, error?, channel, conversation, kind}` and `inbox` events with `source`. They appear in the feed and chat ("via Matrix"),
`recall`, the nightly reflection, the day counts (conversations started, messages received), and firsts ("the first time you sent something out into the world",
"the first time someone answered from outside"). `GET /outreach`, `pipchat outreach`, `pipchat channels` (status and, for setup, unknown senders seen).

## Safety
- The destination is fixed in `.env`; allowed ids are an allow-list; strangers and other rooms are ignored. Inbound text is untrusted like any visitor's, capped at 2000 characters.
- Tokens are never shown to the model, never logged, never in events. A prompt-injected page or visitor message can at most make Pip say something short to the owner,
  within the daily cap, in a logged event.
- The homeserver is a new internet-facing service if public: federation and registration off, rate limits on, backed up, monitored in uptime Kuma, and updated (watchtower is already here).

## Persona
One short paragraph: you have a way to message a friend outside, in a thread; start a conversation rarely, for what is worth telling; you may answer replies or not. Not for status updates.

## Build order
1. **Core, channel-agnostic:** extract `deliver_visitor_message` from `POST /inbox`; `inbox` gains `source` and `conversation`; the `Channel` interface and registry; `FakeChannel` and the
   contract suite; the policy (limits, quiet hours, checks), `send_postcard`, reply routing, events, `GET /outreach`, `pipchat outreach`, firsts, day counts, persona line.
2. **Matrix channel** (httpx over the Client-Server API) passing the contract against a fake homeserver, with `typing`, threads, receipts and image upload.
3. **The service:** `matrix/matrix.hll` (homeserver, reverse-proxy route, backup entry, bootstrap script), accounts and room, Element X on the phone.
4. Later: Element Web, E2EE, a Telegram or webhook channel, inbound photos.

## Decisions
- Made: pluggable; the web UI chat stays separate; the name `send_postcard`; 2 new threads a day with replies free inside a thread; live from the start; photos supported by the interface.
- Made (2026-10-30): **public hostname** for the homeserver (federation and registration off), **unencrypted room** for the first version.
- Still to settle at build time: the homeserver (Tuwunel/Continuwuity vs Synapse, whichever is current and healthy) and whether to host Element Web too.

## Matrix channel: as built
`matrix.py` talks to the Client-Server API over httpx (`MATRIX_HOMESERVER`, `MATRIX_USER_ID`, `MATRIX_ACCESS_TOKEN`, `MATRIX_ROOM_ID`, `MATRIX_ALLOWED`). It takes
the room's current position on first start (no history replay), long-polls `/sync` with a persisted `since` token, delivers text from allowed users in the one room
(a thread keeps its root; a plain reply to one of Pip's postcards maps to it; a top-level message opens a conversation), ignores its own events, notices, images and other
rooms, leaves every other invite and joins its own, backs off on errors, and keeps a persisted list of delivered event ids so a re-offered event is never delivered twice.
It sends text into a thread (with the in-reply-to fallback pointing at the thread's latest message), starts a thread with a top-level message, shows typing, sends read
receipts, and uploads and sends images in the thread (a failed upload still delivers the words and says so). It passes the shared contract suite against an in-process fake
homeserver. An unconfigured channel never breaks Pip: it reports "not configured" and the error shows in `pipchat outreach`.

## Slash commands (built 2026-10-31)
A message from an allowed sender that is exactly `/word [argument]` is not a visitor message: `commands.answer` builds the reply from state and the channel handler
sends it back into the same thread (kind `reply`), then returns. Nothing reaches Pip's inbox, no tick is requested, no event is logged, and no LLM is called.
Commands (read-only): `/help`, `/status`, `/items`, `/garden`, `/projects`, `/creations`, `/notes [diary|todo|wishlist|ambitions|learned]`, `/emotions`, `/usage`. An unknown word
is answered with a pointer to `/help`. A `/word` later in a sentence is an ordinary message to Pip. In `OUTREACH=log` mode the reply is built but not sent.
