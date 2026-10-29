# agent_world

Autonomous AI agent ("Pip") that wakes on its own, looks at its state, and acts via tools.
M1 is headless: a Python/FastAPI brain with an HTTP API. `agent_world.hll` is the source of
truth; `docker-compose.yml` is generated (`hllc build agent_world/agent_world.hll`).

## Run
```sh
cp .env.tpl .env   # add ANTHROPIC_API_KEY (and TAVILY_API_KEY for web_search)
docker compose up -d --build
```
Internal only: `https://agent-world.internal.example.io` (`/state`, `/events`, `POST /inbox`, `POST /tick`).

## Swapping parts (env + restart, no rebuild)
- `LLM_BACKEND`: `anthropic` (default) | `openai_compat` (set `LLM_BASE_URL`, e.g. `http://ollama:11434/v1`) | `fake`
- `PACING`: `heartbeat_events` (default) | `fixed_tick` | `manual` (only `POST /tick`)
- `MAX_CALLS_PER_TICK` (default 3): extra LLM calls in one wake happen only when a tool result needs a response (currently `web_search` and tool errors). `1` restores one-call-per-tick.
- `TOOLS`: comma list of registered tools. `DAILY_TOKEN_BUDGET` (default 5M, ~$0.70/day on Haiku 5.5) caps spend; ticks pause when hit.

Add a backend in `brain/app/llm/` and register it in `llm/__init__.py`; add a pacing policy in `pacing.py`.
`brain/persona.md` is re-read every tick.

## Tests
`cd brain && pip install -r requirements-dev.txt && pytest`

## Talking to Pip: `pipchat`
Stdlib-only CLI (`./pipchat`, or symlink it onto your PATH). Defaults to the Traefik URL; override with `PIP_URL` or `--url`.
```sh
./pipchat                       # interactive chat; /status /usage /notes /log /watch /tick work inside it
./pipchat "hello Pip"           # say one thing, print the reply
./pipchat status | usage | health
./pipchat notes [diary|todo|wishlist|ambitions|learned] [--status open|done]
./pipchat log 30 --kind tool --kind say
./pipchat watch --kind tick     # live stream
./pipchat --json notes          # JSON for scripting (watch emits JSON lines)
```

## Pip's journal
`note_to_self` writes to one of five sections (`diary`, `todo`, `wishlist`, `ambitions`, `learned`); `resolve_note`
crosses off a todo/wishlist/ambition item. Open items and the latest diary entries are shown to Pip every tick, and the
persona (`brain/persona.md`, re-read live) encourages it to keep them. HTTP: `GET /notes`.
