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
- `TOOLS`: comma list of registered tools. `DAILY_TOKEN_BUDGET` caps spend; ticks pause when hit.

Add a backend in `brain/app/llm/` and register it in `llm/__init__.py`; add a pacing policy in `pacing.py`.
`brain/persona.md` is re-read every tick.

## Tests
`cd brain && pip install -r requirements-dev.txt && pytest`
