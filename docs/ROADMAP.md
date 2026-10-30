# agent_world roadmap

Autonomous AI agent ("Pip") in a small virtual world, running as a homelab service. Origin: the Obsidian project
note `1-Projects/Autonomous AI Agent Virtual World.md` (exploration, started 2026-10-29). Day-to-day usage is in
[README.md](README.md); this file tracks what's done, what's next, and the decisions behind it.

## Status at a glance
| | Milestone | Status |
|---|---|---|
| M1 | Headless brain | Done |
| M1.5 | Local LLM backend experiment | Not started (optional) |
| M2a | Web dashboard + chat (same info as `pipchat`) | **Built, needs a browser check** |
| M2b | Visual world (2D) | Not started |
| M3 | Long-term memory | Not started |
| M4 | Richer tools, optional exposure | Not started |

## M1 - Headless brain (done)
- [x] Python/FastAPI service, plain asyncio loop, SQLite state in a named volume, generated from `agent_world.hll`
- [x] Pluggable LLM backend (`anthropic`, `openai_compat`, `fake`) and pacing policy (`heartbeat_events`, `fixed_tick`, `manual`)
- [x] Stats that decay by time (hunger, energy); alerts wake the agent
- [x] Tools: `say`, `set_activity`, `eat`, `rest`, `note_to_self`, `resolve_note`, `use_item`, `plant`, `harvest`, `web_search`
- [x] Multi-call ticks (`MAX_CALLS_PER_TICK`) so tool results can be used immediately
- [x] Journal with sections (diary, todo, wishlist, ambitions, learned), archive, duplicate/stat-number guards,
      "diary moments" prompt for visits/gifts/garden events
- [x] Belongings and garden (real-time growth, starter seeds); visitors give items via `POST /items`
- [x] Daily token budget (5M ~ $0.70/day on Haiku 5.5); `pipchat usage` shows cost
- [x] `pipchat` CLI: chat, status, usage, health, notes, log, watch, tick, give, items, garden, `--json`
- [x] Restic backup script (`restic/backup-agent-world.sh`, registered in `backup-all.sh`)
- [x] Internal-only Traefik route (`agent-world.internal.example.io`)

## M1.5 - Local LLM experiment (optional)
- [ ] Separate `llm_local/` stack serving an OpenAI-compatible endpoint on `traefik-net`; point `LLM_BACKEND=openai_compat` at it
- [ ] Try a 3-4B model on the Arc A310 (4 GB VRAM, shared with Jellyfin) via an Intel-capable runtime; measure tool-calling
      reliability and tokens/sec
- [ ] If a dedicated NVIDIA GPU is added (12-16+ GB): stock Ollama with passthrough and a larger model
- [ ] Compare against the Claude default through the same loop (cost vs quality)

## M2a - Web dashboard + chat (built; open `/ui/` and check it)
Browser equivalent of `pipchat`, served by the existing service at `https://agent-world.internal.example.io/ui/`
(plain HTML/JS in `brain/web/`, bind-mounted so edits show on refresh; live updates over SSE at `/stream`).
- [x] Live status (activity, mood, hunger/energy, model/pacing/tools, token usage and cost)
- [x] Event feed with group filters, live updates
- [x] Chat with Pip (send message, typing indicator, reply)
- [x] Journal browser (sections, open/done/archived)
- [x] Belongings and garden views; give-item form; wake button
- [ ] **Verify in a real browser** (layout on phone width, dark mode, SSE reconnect, chat/gift flow). Only the API,
      static serving, SSE framing and JS syntax have been checked so far
- [ ] Decide whether Authentik is wanted in front of it (currently internal-only, IP whitelisted)

## M2b - Visual world
- [ ] Decide 2D (pixel canvas: a room, a sprite, activity -> animation) vs 3D; default 2D
- [ ] Map `set_activity` labels and garden state to visuals; live push from the backend
- [ ] Optional: evaluate a16z AI Town on the side (Convex-based, probably too heavy)

## M3 - Long-term memory
- [ ] Summarize old events/diary into compact memories; retrieve relevant ones into the prompt
- [ ] Start with SQLite FTS or sqlite-vec; add Chroma only if retrieval quality demands it
- [ ] Revisit LangGraph if the loop needs checkpointing or branching
- [ ] Keep prompts well under 100k tokens (Haiku 5.5 pricing steps up 5x past that); prompts are ~3-5k today

## M4 - Richer tools and exposure
- [ ] Image generation (canvas/drawing)
- [ ] Sandboxed code execution (network-less container, resource limits)
- [ ] Model escalation (Haiku -> bigger) for hard decisions
- [ ] If ever public: Authentik, rate limiting, prompt-injection hardening

## Backlog / known issues
- [x] Let Pip edit its own notes: `edit_note` for todo/wishlist/ambitions/learned (not the diary), and wishes are flagged
      when Pip has since received a related item
- [ ] `set_activity` with an unchanged activity should be a no-op (Pip restates it every tick, adding noise and tokens)
- [ ] Diary moments: any diary entry clears all offered moments, so a visit and a garden event may share one entry.
      Consider per-moment coverage
- [ ] Dollar-based budget cap (`DAILY_BUDGET_USD` + per-model prices) instead of tokens only; output tokens cost 5x input
- [ ] Healthcheck delays Traefik registration by ~30 s after a recreate (404s meanwhile); tighten interval/start period
- [ ] Verify `restic/backup-agent-world.sh` against the live container and restore a snapshot once
- [ ] `pipchat` interactive terminal mode (spinner, line editing, `/watch`) has only been exercised via pipes
- [ ] Pip's diary entries still drift toward status logs sometimes; keep an eye on it after prompt changes
- [ ] Pip reuses identical activity text across ticks while waiting on slow things (crops); consider an explicit "waiting" state

## Key decisions
- **Internal only**, safe tools only in v1; no code execution until M4.
- **Plain asyncio loop** over LangGraph for M1 (a deviation from the original note); revisit in M3.
- **Pluggable seams**: `LLMBackend` and `PacingPolicy` chosen by env, tools by name via `TOOLS`.
- **Default model** `claude-haiku-5-5` at low effort; pricing $0.10 / $0.50 per M tokens (flat under 100k prompt tokens).
- **Speech via a `say` tool**, not free text: Haiku 5.5 can return text as hidden thinking, and a tool works on any backend.
- **Eating stays unlimited**; food is a bonus. Food can be grown in the garden.
- **Guard rails over prompt tuning** where possible (stat-number and duplicate note refusal, event-driven diary moments);
  deliberately no diary rate limit.
- **Hardware:** Arc A310 (4 GB) is shared with Jellyfin; a good local LLM likely needs a dedicated NVIDIA GPU.
