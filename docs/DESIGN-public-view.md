# The public, read-only view

Set `PUBLIC_HOSTS` (comma-separated hostnames) and any request whose `Host` header is listed is **public**. Requests on any other host
are the full, owner dashboard, unchanged. One process serves both, so a deployment is two Traefik/nginx routes to the same container.

## Rules
- **Default deny, in the app.** A public request is answered only if it is a `GET`/`HEAD` of a path in `PUBLIC_PATHS` / `PUBLIC_PATTERNS`
  (`app/public_view.py`); everything else is a 404 (not a 403, so it does not say what exists). A new endpoint is owner-only until
  someone adds it to that list.
- **Viewers never cost anything or change anything.** No public route calls the model, wakes Pip or writes. The cacheable routes carry
  `Cache-Control: public, max-age=5`; `/stream` is capped at `MAX_PUBLIC_STREAMS` (50) concurrent viewers (503 beyond that). Rate
  limiting belongs in the reverse proxy.
- **Events are allowlisted by kind and by field.** `EVENT_FIELDS` lists the public kinds and, for each, the fields that survive. A tool
  event shows its result only for the tools in `TOOLS_WITH_RESULT`; every other tool shows just its name, never its arguments.
- **Known names are hidden.** Everyone who has ever written to Pip (`inbox` senders), everyone in Pip's people notes, and everything in
  `PUBLIC_REDACT` is replaced by "someone", as a whole word in any case, in every string of every public JSON response and event.

## What is public (tabs of the dashboard)
| Tab | Public? | Notes |
|---|---|---|
| Now | yes | state (agent, ticks only), the filtered feed, emotions, focus. No chat, no usage/model/pacing/tools/inbox count |
| Journal | yes | Pip's own notes (diary, todo, wishlist, ambitions, learned) |
| World | yes | map, belongings, garden, places. No letters, no "give Pip something" |
| Work | yes | projects, creations, works |
| Mind | yes, except people | self-portrait, beliefs, days, night-pass decisions, capabilities. The `people` list is dropped |

## Endpoints
Public: `/ui/*`, `/` (redirect), `/mode`, `/healthz`, `/state` (trimmed), `/events` (filtered), `/stream` (filtered), `/notes`, `/items`,
`/emotions`, `/standing` (what modules show the agent; it was `/garden` before 0.35.0), `/projects`, `/creations`, `/works` (+ `/works/{id}`, `.svg`, `.png`), `/map`, `/places`, `/memory` (no `people`).

Owner-only: `POST /inbox`, `/items`, `/tick`, `/reflect`; `PATCH`/`DELETE /places/{key}`; `/letters`, `/outreach`, `/recall`,
`/library/*`, the API docs.

Event kinds dropped from the public feed: `say`, `inbox`, `inbox_read`, `gift`, `outreach`, `letter_sent`, `letter_read`, `companion`
(they can quote a visitor or a real person), `start`, `error`, `tool_error`, `gm_error`, `reflection_error`, `budget_exceeded`,
`night_undo`.

## What this does not do
Name redaction only knows names the engine has seen. Something a visitor said that Pip then writes into its diary in a paraphrase, or a
third party's name Pip learned from a message, can still appear in a note. Read the Journal and Mind tabs before pointing a public
hostname at it, and add anything you want hidden to `PUBLIC_REDACT`. Because the public view is a mode of the app, a bug in the
allowlist is a bug in the app: the proxy should still rate-limit and must not add `forwardAuth` for the public host.

## Deployment
`PUBLIC_HOSTS=pip.example.org`, then route that hostname to the same container as the owner hostname (which must stay private,
e.g. IP-restricted). The public route needs no authentication; the owner route must keep its restriction, because the owner `Host` can
write.
