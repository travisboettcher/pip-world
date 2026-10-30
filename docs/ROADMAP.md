# agent_world roadmap

Autonomous AI agent ("Pip") in a small virtual world, running as a homelab service. Origin: the Obsidian project
note `1-Projects/Autonomous AI Agent Virtual World.md` (exploration, started 2026-10-29). Day-to-day usage is in
[README.md](README.md); this file tracks what's done, what's next, and the decisions behind it.

## Status at a glance
| | Milestone | Status |
|---|---|---|
| M1 | Headless brain | Done |
| M1.5 | Local LLM backend experiment | Not started (optional) |
| M2a | Web dashboard + chat (same info as `pipchat`) | Done |
| M1.6 | Projects, living creations, companions ([design](DESIGN-creations.md)) | Deployed |
| M2b | Visual world (2D) | Not started |
| M3 | Long-term memory ([design](DESIGN-memory.md)) | Steps 1-2 deployed; 3-4 open |
| M3.5 | A neighbor and slow letters ([design](DESIGN-neighbor.md)) | Deployed |
| M3.6 | Places + the library (Calibre) ([design](DESIGN-library.md)) | Deployed |
| M3.7 | Day/night and sleep ([design](DESIGN-sleep.md)) | Deployed |
| M3.8 | Sense of self: firsts, cited reflections, portraits, expectations, turning points, capabilities, night pass | Deployed (first night pending) |
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

## M2a - Web dashboard + chat (done)
Browser equivalent of `pipchat`, served by the existing service at `https://agent-world.internal.example.io/ui/`
(plain HTML/JS in `brain/web/`, bind-mounted so edits show on refresh; live updates over SSE at `/stream`).
- [x] Live status (activity, mood, hunger/energy, model/pacing/tools, token usage and cost)
- [x] Event feed with group filters, live updates
- [x] Chat with Pip (send message, typing indicator, reply)
- [x] Journal browser (sections, open/done/archived)
- [x] Belongings and garden views; give-item form; wake button
- [x] Verified in a real browser (in daily use)
- [ ] Decide whether Authentik is wanted in front of it (currently internal-only, IP whitelisted)
- [x] **Rework the layout** (built 2026-10-30; the owner should check it in a browser, esp. phone width and dark mode):
  chat is a hideable bubble (bottom-right, unread badge, remembers open/closed; a bottom sheet on phones); usage moved to a
  header pill with a hover/tap popover; hunger/energy are small header meters; the old 12-card column is five tabs
  (*Now*: activity and Pip right now; *Journal*; *World*: belongings, garden, letters, give; *Work*: projects and creations;
  *Mind*: self-portrait, beliefs and hunches, how Pip has changed, days that mattered, people, night decisions, capabilities).
  The feed marks firsts with a star and shows experiments, gathers, sleeping, and night decisions. The tab is in the URL hash.
  Checked in an embedded V8 with a stub DOM against the live API's real data (boot, tabs, chat toggle/unread, usage popover); not yet seen in a real browser.

## M2b - Visual world
- [ ] Decide 2D (pixel canvas: a room, a sprite, activity -> animation) vs 3D; default 2D
- [ ] Map `set_activity` labels and garden state to visuals; live push from the backend
- [ ] Optional: evaluate a16z AI Town on the side (Convex-based, probably too heavy)

## M3 - Long-term memory (see DESIGN-memory.md)
- [x] Deploy: add `recall` to `TOOLS` in `.env`, rebuild; the first reflection runs right away
- [x] Visitor identity: inbox `sender`, shown in perception, moments and the feed
- [x] Nightly reflection in Pip's voice: day summaries, insights with importance, people notes, self-portrait
- [x] `recall(query)` over journal, events, reflections and people (SQLite FTS5)
- [ ] Step 3: "this reminds you of..." - situation-based retrieval into the prompt (recency x importance x relevance)
- [ ] Step 4: forgetting - stop indexing raw events covered by summaries; unused insights lose rank
- [ ] Embeddings (sqlite-vec) if FTS relevance proves too noisy; add Chroma only if retrieval quality demands it
- [ ] Revisit LangGraph if the loop needs checkpointing or branching
- [ ] Keep prompts well under 100k tokens (Haiku 5.5 pricing steps up 5x past that); prompts are ~3-5k today

## M4 - Richer tools and exposure
- [ ] Image generation (canvas/drawing)
- [ ] Sandboxed code execution (network-less container, resource limits)
- [ ] Model escalation (Haiku -> bigger) for hard decisions
- [ ] If ever public: Authentik, rate limiting, prompt-injection hardening

## Ideas (not yet scheduled)
Collected 2026-10-29 after watching Pip's first ~60 ticks. The main gap: Pip's projects exist only in its head.
Nothing in the world reports results, so it repeats activities ("filing pallets" x6), accumulates near-duplicate
todos (#19/#34/#38/#43/#50), and only moves on by deciding it's "close enough". Diary #26 says it itself: "the loop
is in my notes, not in the gears".

### Projects and creations (M1.6: phases 1-3 built, see DESIGN-creations.md)
- [x] Deployed (tools are in `.env`)
- [x] **Projects with world-decided progress**: `start_project(name, goal, needs, effort)` and `work_on(project, minutes)`.
      The engine owns progress, cost (energy, materials) and outcome rolls; Pip only chooses what to do. Work takes
      real time like crops do, so Pip can sleep until it's done instead of re-stating its activity every minute
- [x] **Referee pattern**: the engine rolls success / partial / setback (from skill, tools, materials); an LLM call
      only *narrates* that result ("the third tooth chipped"). The engine decides what happened, the LLM describes it
- [x] **Living creations without scripting each one**: on completion, a one-time "world" LLM call turns the project
      into a stored spec built from a small fixed set of **capabilities** the engine knows how to run, plus a quirk or
      two. Capabilities compose (timekeeper + chime = cuckoo clock), so adding one capability benefits every future
      creation. Candidates:
  - `timekeeper(drift)`: Pip's perception shows the time by its clock ("reads 3:14, runs 2 min fast")
  - `upkeep(verb, hours)`: stops working until Pip tends it, however that thing is tended (upkeep = attachment)
  - `periodic(event, every)`: chirps, plays a tune, ticks; shows in the event feed
  - `sensor(condition)`: wakes Pip when something happens (crop ripe, visitor, dusk)
  - `helper(effect, every)`: hurries the garden, finds things (GM-chosen), or comforts Pip, on a schedule
  - `companion(persona)`: becomes a small agent of its own (see social: same multi-agent seam as a neighbor)
- [x] **Generic `use` fallback**: actively using a creation calls the world LLM with its spec and context and returns
      narration plus effects from a small, capped vocabulary (adjust stat, add/remove item, change crop timer, schedule
      an event, write an event). Specs are persisted so items behave consistently instead of being re-improvised
- [x] A shelf of finished creations: perception, `GET /creations`, `pipchat creations`, "Made by Pip" UI panel

### World mechanics
- [x] (built; DESIGN-sleep.md; deploy: add `sleep` to `TOOLS`) **Day/night and real sleep**: Pip goes to bed at night and the loop pauses for hours (cost saving). The nightly
      reflection (M3) already exists; tie it to Pip actually going to bed
- [x] **Places and place-scoped tools** (DESIGN-places.md): tool scoping, place records, `browse`, the directory, `gather` at the woods and
      junkyard (loot tables, depletion, daylight hours), `where_to`, the missing-material hint
- [ ] Places, remaining: a user-editable `places.json` (places, hours, loot) and a place or two more (e.g. a market, once there are coins)
- [ ] **Small economy**: sell surplus produce and creations at the market for coins, buy materials there
- [x] **Skills that grow with practice**: per-craft xp from work minutes; feeds the referee's odds
- [ ] **LLM-free surprises**: a cheap random-event generator (storm flattens a plot, a mouse gets the tomatoes, a
      creation breaks) so the diary has things happen *to* Pip, not just things Pip decides
- [ ] Scarcity: gifts currently grant wishes within minutes; consider delivery delays or partial gifts so wants persist
- [x] **Pip changes its world** (built 2026-10-30): a finished project can carry a `world` capability, decided by the GM only for work that plainly was
      about making room to grow things, and applied once by the engine: a new garden plot, up to `GARDEN_PLOTS_MAX` (8). The engine gates it (a
      land-related project of at least difficulty 2; the cap) so the GM can't hand out plots. Foraging gives wild seeds (sunflower, carrot, pea,
      radish, bean) and food (berries, hazelnuts, mushrooms, apples). The capability list is the extension point for other lasting changes
      (a pond, a path that shortens a walk).

### Social
- [x] **Pip can reach out** (DESIGN-outreach.md): a pluggable two-way `Channel` (contract-tested), `send_postcard` (2 new threads a day, replies free
      in the thread, never at night), the Matrix channel, and the `matrix/` homeserver on `matrix.example.io` with `bootstrap.py` and a restic backup.
      Live since 2026-10-30. A message Pip reads but doesn't answer is put back once.
- [ ] Outreach, remaining: Element Web for a desktop view; inbound photos; a Telegram or webhook channel if ever wanted; end-to-end encryption (later);
      add the homeserver to Uptime Kuma
- [x] Companion creations talk (chatter + answers to `say(to=...)`), on a `characters` table meant to be reused
- [x] **A neighbor** (built; DESIGN-neighbor.md; deploy: add `write_letter` to `TOOLS`): a second creature with its own persona exchanging letters with delivery delays, so Pip has
      relationships beyond Morgan. Build multi-agent support once and reuse it for `companion` creations
- [x] Visitor identity: remember who visited and what they talked about, per person (M3 people notes)

### Homelab tie-ins
- [ ] Real weather / daylight from Home Assistant (harmless sensors only): cloudy days slow the garden, sunset means bed
- [x] A bookshelf: the Calibre library is a place Pip walks to and reads in (M3.6, DESIGN-library.md)

## Ideas to design (2026-10-30)
Not scheduled unless marked built; each needs a DESIGN doc first. Prior art is noted in the design docs and RESEARCH-self.md.

### Discovery in projects and transferable skills (built; DESIGN-discovery.md)
- [x] The plan is Pip's (`start_project(name, goal, steps)`); the GM reviews and arbitrates, never rewrites; Pip edits freely
      with `revise_plan`; `work_on(..., approach)` is judged within one step of the die (blowups possible)
- [x] `experiment(project, hypothesis)` against hidden facts, with a pity timer; research (`web_search`, library, visitors)
      feeds the plan through `revise_plan(..., because)`
- [x] Five transferable abilities (precision, patience, ingenuity, knowledge, handiness) plus craft familiarity, narrated to Pip
      in words and numeric only in the API and `pipchat`

### Extract to a public repo
- [ ] Split `agent_world/` with history (`git subtree split` / `filter-repo`); audit history for secrets first
- [ ] Remove homelab specifics: hostnames, Calibre mount, Morgan-specific persona text; ship a plain
      `docker-compose.yml` + `.env.example`, README, license, token-budget warning
- [ ] Consume it here as a **published artifact** (container image from the new repo's CI) rather than a copy or
      submodule: this repo keeps only `agent_world.hll` pointing at the image, plus `.env`, persona and mounts

### Day, night and sleep (built; DESIGN-sleep.md)
- [x] Time of day and "day N of your life here"; the `sleep` tool; no ticks while asleep; the reflection runs as Pip sleeps

### Introspection and a sense of self (RESEARCH-self.md; DESIGN-self.md, DESIGN-expectations.md, DESIGN-nightpass.md)
- [x] Survey of the prior work (LLM agents, classic AI and cognitive architectures, psychology and philosophy of self),
      with a verification status per source
- [x] Firsts computed from the log and shown as facts
- [x] Cited reflections: evidence ids, validation, nightly support check, hunches, `recall` shows the evidence, event importance
- [x] Versioned self-portrait (all versions kept), cited `changed` claims, daily counts as evidence
- [x] Expectations and surprise: optional `expect`, step-duration guesses, calibration, learning progress
- [x] Turning-point detector; capabilities table
- [x] Night pass: archive/merge/resolve notes, pause/resume projects, adopt a goal, set a focus; cited, reversible
      (`undo_decision`), `NIGHT_PASS=off|log|apply`
- [ ] Life periods / chapters: group days by place, people and goals
- [ ] Recall frame: show Pip's state at the time of a recalled memory (Tulving)
- [ ] Delayed-self recognition test: show Pip an old undated entry or portrait and see whether it recognizes its voice
- [ ] Rare open-question prompts, not scripted performances
- [ ] Watch the first nights (2026-10-30 onward): reflection prompt size and cost, the live shape of `changed`/`turning_points`,
      the support check's verdicts, and what the night pass decides

### Typed-decision model (idea, 2026-10-30)
- [ ] A fast "System One" model that returns typed decisions instead of text (TypeSafe's Jev is one; claims of 100x+ faster
      and cheaper are the company's own and unverified). Candidate fits: the GM's enum judgments (`verify_insights`
      verdicts, experiment `relevant`, `accepted`), and a pre-tick gate ("is there anything new worth a full call?").
      Not the narration or Pip itself. Cost today is tiny (~$0.0003/call), so revisit only if cost or latency starts to
      matter; the seam would be a `DecisionBackend` beside `LLMBackend`.

### Writing and drawing (built 2026-10-30; DESIGN-art.md)
- [x] `draw` (sanitised SVG on a fixed canvas) and `write_piece`; a gallery (API, Work tab, `pipchat gallery`); drawings travel with postcards as PNGs
- [ ] Let Pip see its own picture (image blocks in the LLM message format) so it can draw, look and revise; drawing as a timed session; inbound pictures

## Backlog / known issues
- [x] Let Pip edit its own notes: `edit_note` for todo/wishlist/ambitions/learned (not the diary), and wishes are flagged
      when Pip has since received a related item
- [x] `set_activity` restating the same activity/description is a no-op (hidden from feeds and Pip's recent events)
- [ ] Diary moments: any diary entry clears all offered moments, so a visit and a garden event may share one entry.
      Consider per-moment coverage
- [ ] Dollar-based budget cap (`DAILY_BUDGET_USD` + per-model prices) instead of tokens only; output tokens cost 5x input
- [ ] Healthcheck delays Traefik registration by ~30 s after a recreate (404s meanwhile); tighten interval/start period
- [x] Verified `restic/backup-agent-world.sh` against the live container and restored a snapshot (2026-10-30: integrity ok, 1013 events)
- [ ] `pipchat` interactive terminal mode (spinner, line editing, `/watch`) has only been exercised via pipes
- [ ] Pip's diary entries still drift toward status logs sometimes; keep an eye on it after prompt changes
- [ ] Pip reuses identical activity text across ticks while waiting on slow things (crops); consider an explicit "waiting" state
- [x] `rest(minutes)`: timed rest; the heartbeat sleeps through it (Pip was resting every 60 s tick)
- [x] Todos pile up as near-duplicate restatements: new open to-dos/wishes/ambitions that cover the same ground as an
      open one (3+ shared content words, 60% of the shorter) are refused with a pointer to `edit_note`

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
