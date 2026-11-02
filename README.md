# agent_world

A small world with an autonomous creature in it.

The creature, **Pip**, wakes on its own, looks after itself, tends a garden, makes things, walks to places, exchanges slow letters
with a neighbor, forms memories and reflects on them every night. You can watch it, talk to it and give it things. Nothing is scripted:
**the engine owns the rules, a language model writes the content.** Pip decides what to do; the engine keeps time, rolls the dice,
tracks hunger and energy, enforces limits and remembers; a separate "game master" model only narrates what the engine already decided.

It is an experiment in long-running agents, built to be watched for weeks rather than days.

## What is in the world

- **A life**: hunger, energy, mood, emotions, day and night, sleep. It goes to bed and wakes up.
- **Memory and a sense of self**: a journal, nightly reflections that cite their evidence, a self-portrait that changes, and a "night pass" in which it can
  tidy its own goals (and take it back).
- **Making things**: projects whose progress the world decides, experiments against facts Pip can't see, skills that grow with practice, and finished things
  that live on (a clock that has to be wound, a bird that talks).
- **Places**: a garden, woods and a junkyard to forage in, a library of real books, a neighbor's house, and places other characters mention. A map that grows.
- **People**: a neighbor invented on first start who writes back, visitors, and optionally a real chat channel (Matrix) so it can write to you.
- **The outside world, optionally**: real weather from Home Assistant, web search, your own books.

## Quick start

```sh
git clone https://github.com/travisboettcher/agent-world && cd agent-world
cp .env.example .env          # set ANTHROPIC_API_KEY
docker compose up -d --build
```

Open <http://localhost:8000/ui/> for the dashboard. Talk to Pip from a terminal with the stdlib-only CLI:

```sh
./pipchat "hello there"       # say something and print the reply
./pipchat status              # what it is doing, how it feels
./pipchat give "a tiny needle file"
./pipchat --help
```

Pip wakes by itself, so give it a few minutes. The dashboard shows what it is doing, its belongings and garden, the map, its projects and journal.

### What it costs

It makes about 125 model calls a day. Measured over a real day on the default small model: about 1.3 million input and 40 thousand output tokens, which at the
dashboard's price table (0.10 and 0.50 USD per million tokens) is roughly 15 cents. A larger model costs proportionally more. `DAILY_TOKEN_BUDGET` is a hard
cap: ticks pause when it is reached. Start with the default and watch the dashboard's usage figure before changing models.

### Security

The dashboard and API have **no login** and include write endpoints (messages, gifts, waking it). The compose file publishes the port on `127.0.0.1` only. Keep it
that way unless something in front of it handles access (a VPN, or a reverse proxy with authentication). Anyone who can reach it can talk to Pip and send it
text that ends up in its prompt.

## Configuration

Everything is an environment variable, listed with comments in [`.env.example`](.env.example). Changing one needs a restart, not a rebuild
(`docker compose up -d`). The ones you are most likely to touch:

| Variable | What it does |
|---|---|
| `LLM_BACKEND`, `LLM_MODEL`, `LLM_BASE_URL`, `LLM_API_KEY` | the model: `anthropic`, or `openai_compat` (OpenAI, Ollama, vLLM...) |
| `PACING` | `heartbeat_events` (wake on events and a slow heartbeat), `fixed_tick`, or `manual` |
| `DAILY_TOKEN_BUDGET` | the daily cap on tokens |
| `TOOLS` | which tools Pip has (the parts of the world that need a tool, like the garden, only appear when it is enabled) |
| `GROW_SPEED`, `WORK_SPEED` | make crops and work sessions pass faster than real time (handy for testing) |
| `OUTREACH_CHANNELS`, `MATRIX_*` | let Pip write to a chat room |

## Pluggable parts

Where something comes from is a provider chosen by a setting, so the engine never depends on one service:

| Part | Setting | Providers |
|---|---|---|
| The model | `LLM_BACKEND` | `anthropic`, `openai_compat` |
| Chat channel | `OUTREACH_CHANNELS` | `matrix` |
| Real weather | `WEATHER_PROVIDER` (with `WEATHER=1`) | `homeassistant` (read-only: the weather entity and `sun.sun`, nothing else) |
| Books | `LIBRARY_PROVIDER` | `calibre`, `folder` (a plain folder of EPUB, PDF, text and Markdown; `auto` picks) |
| Web search | `SEARCH_PROVIDER` | `tavily` |

Adding one is a small class registered by name; see `app/weather.py`, `app/library.py` and `app/search.py` for the pattern.

## Pip's instructions

Pip is given a text file at every wake: `persona.md` in the image, or your own mounted at `/srv/persona.md` (see the commented volume in `docker-compose.yml`). It is
re-read every tick, so editing it changes Pip on its next wake. At the moment that one file both explains how the world works and sets Pip's character; to give
Pip a different character, replace it with your own version of that file.

## Deploying with hll (alternative)

[`agent-world.hll`](agent-world.hll) describes the same service for [hll](https://github.com/travisboettcher/hl-lang), a small language that generates Compose files.
If you already manage your services that way: `hllc build agent-world.hll --out docker-compose.yml`. `docker-compose.yml` is what the project ships and
tests; the `.hll` is an alternative, not a requirement.

## Development

```sh
python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
.venv/bin/pytest -q                      # about 1,300 tests, no network, about half a minute
```

Changes are test-driven, and engine code is checked with mutation testing (a 95% cutoff on what you change): the rules, and the one hard-won one about running
mutation tests, are in [`CLAUDE.md`](CLAUDE.md). The design of each area is in [`docs/`](docs/): start with
[`docs/reference.md`](docs/reference.md) (everything Pip can do, tool by tool) and [`docs/ROADMAP.md`](docs/ROADMAP.md) (what is done and what is next).

## License

[MIT](LICENSE).
