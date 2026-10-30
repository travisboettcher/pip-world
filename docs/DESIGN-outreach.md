# Design: reaching out (postcards to the outside world)

Status: **design only, not built.** Roadmap item "Pip can reach out" (Social).

## Why
Pip can only talk when someone talks to it, or by writing letters to a neighbor it invented. It has things it would
like to say to a real person: a project finished, a specific thing it is missing, something it found out. A push message
to the owner's phone is the smallest real-world channel, and the one most likely to matter.

Principles: **rare and meaningful** (a postcard, not a notification stream), **the owner stays in control** (a kill
switch, hard caps, everything logged), **no new secrets in Pip's reach**, and the model gets **no way to choose a
destination or send anything but short plain text**.

## What exists on this homelab
- **Home Assistant** already pushes to the owner's Android phones (`notify.mobile_app_pixel_11_pro`, `..._pixel_6a`) from
  automations. A HA webhook-triggered automation is the lowest-effort route to a phone push with no new service.
- **n8n** can do the same, or email/Slack/Telegram, and could also hold the credentials.
- No ntfy/gotify/pushover is deployed, and host mail is unverified (see the restic notification todo), so email is not a
  good first channel.

## Shape
```
Pip (agent-world)  --POST JSON-->  webhook  --> Home Assistant automation --> notify.mobile_app_*  (phone)
                                         \--> or an n8n workflow --> anything n8n can reach
```
Pip knows one thing: a webhook URL (and an optional bearer token), set in `.env`. Where the message goes after that is
configured on the receiving side, so changing channels never touches Pip.

### The tool: `send_postcard(text)` (anywhere, awake only)
- **What Pip sees:** "Send a short postcard to a friend outside (Morgan). Rarely; for something worth telling: a thing you
  finished, a specific thing you need, something you found out. Plain text, at most 240 characters."
- **The recipient is fixed.** No `to` argument. Text only: no URLs (a message containing one is refused), no attachments, control
  characters stripped.
- **Rate limits** (engine, not prompt): `OUTREACH_PER_DAY` (default 2, local day), `OUTREACH_MIN_GAP_HOURS` (default 3), no sending
  during quiet hours (the night window, same clock as sleep), and no postcard that is too like one of the last five
  (similarity or overlapping content words, as for notes). A refusal says why and when it can next send.
- **Pip is told the budget** in its prompt, only when the tool is usable: "You can send 1 more postcard today (next after 2:30 pm)."
  When it can't, the tool isn't offered, so it can't keep trying.
- **Delivery:** one POST (5 s timeout) with `{id, text, from: "Pip", ts, context: {activity, location}}`. 2xx = delivered. A failure
  is reported honestly ("it couldn't be sent") and not retried; failures don't use the daily allowance but are capped (3/day) so a
  dead webhook isn't hammered.
- **Modes:** `OUTREACH=off | log | on`. `log` records what Pip would send (visible in the feed, `pipchat outreach` and
  `GET /outreach`) and tells Pip it is on its way, but delivers nothing: a dry run before the phone is involved. `off` removes the tool.

### Records and visibility
- Event `outreach` `{id, text, delivered, error?, mode}` in the feed ("Pip sent a postcard: ..."), `recall`, the nightly reflection
  and the day counts (`postcards sent`); a firsts facet ("the first time you sent something out into the world").
- `GET /outreach` and `pipchat outreach` list them with delivery status; the web UI shows them in the activity feed.

### Replies (phase 2, optional)
A phone reply can come back through the existing `POST /inbox` (sender "Morgan (phone)"): a Home Assistant notification action or an
n8n workflow calls it from the LAN, where the Traefik whitelist already allows it. The engine can then mark an inbox message that
arrives within a few hours of a postcard as `reply_to` that postcard, as a fact in the log. No new endpoint is needed.

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
1. Backend interface (`webhook`, `log`), the tool, limits and quiet hours, events, tests with a fake receiver.
2. `GET /outreach`, `pipchat outreach`, feed line, firsts, day counts, README with the Home Assistant YAML.
3. Persona paragraph and the prompt budget line.
4. (Later) replies marked `reply_to`; other backends if wanted.

## Open questions
1. Channel: a Home Assistant webhook automation to your phone (recommended: already in use), or n8n, or something else?
2. The name and framing: `send_postcard` (matches Pip's world), or something plainer like `message_owner`?
3. Limits: 2 a day, 3 hours apart, none at night. Too tight, or too loose?
4. Start in `log` mode for a day to read what Pip would send before it reaches your phone (recommended), or `on` from the start?
5. Replies (phase 2): do you want to answer Pip from the notification, or is the web UI enough for now?
